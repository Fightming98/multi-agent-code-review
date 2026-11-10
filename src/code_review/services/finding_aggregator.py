"""工具结果聚合、合同 Finding 映射与确定性去重。

本模块把 Ruff / Bandit / Radon 的 ``ToolFinding`` 与 Pytest 测试摘要映射为
``code_review.schemas.result.Finding``：

- 所有阶段 1 Finding 的 ``agent_name`` 固定为 ``Stage1Analyzer``；
- 所有 Finding 保持 ``verification_status="unverified"``；
- 只使用真实工具输出构造 ``ToolEvidence``，不伪造路径、行号或证据；
- Radon 的 A 级复杂度不进入 Finding 列表，原始结果仍保留在工具结果中；
- 低可维护性按文件汇总为一个项目级 Finding，避免伪造行号。

去重规则遵循 ``docs/workflow.md`` §8.4：同文件、行号范围重叠且类别相同的
定位发现合并；无文件位置的发现按类别与工具来源合并。合并时保留最高严重
级别，描述采用最高置信度者，并合并工具证据与 ``merged_from``。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from code_review.schemas.result import Finding, ToolEvidence
from code_review.schemas.task import ErrorInfo
from code_review.tools.base import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
)
from code_review.tools.test_runner import TestExecutionResult

from .redaction import redact_sensitive_text

STAGE1_AGENT_NAME = "Stage1Analyzer"

SEVERITY_RANK: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

_MAX_TITLE_CHARS = 200
_MAX_TEXT_CHARS = 4_000
_MAX_REASON_CHARS = 300

_BANDIT_CATEGORY_BY_RULE: dict[str, str] = {
    "B105": "hardcoded_secret",
    "B106": "hardcoded_secret",
    "B107": "hardcoded_secret",
    "B108": "path_traversal",
    "B202": "path_traversal",
    "B301": "insecure_deserialization",
    "B302": "insecure_deserialization",
    "B303": "weak_crypto",
    "B304": "weak_crypto",
    "B305": "weak_crypto",
    "B306": "path_traversal",
    "B307": "insecure_deserialization",
    "B324": "weak_crypto",
    "B505": "weak_crypto",
    "B602": "command_injection",
    "B603": "command_injection",
    "B604": "command_injection",
    "B605": "command_injection",
    "B607": "command_injection",
    "B608": "sql_injection",
    "B610": "command_injection",
}

_RECOMMENDATIONS: dict[str, str] = {
    "sql_injection": (
        "Use parameterized queries or a safe query builder; never concatenate "
        "untrusted input into SQL."
    ),
    "command_injection": (
        "Avoid shell execution of untrusted input. Use an argument list with "
        "shell disabled and validate every command argument."
    ),
    "hardcoded_secret": (
        "Remove the secret from source control, load it from a secure secret "
        "store or environment variable, and rotate the exposed value."
    ),
    "insecure_deserialization": (
        "Do not deserialize untrusted data with unsafe formats. Prefer a safe "
        "format and validate the input schema."
    ),
    "path_traversal": (
        "Resolve and validate paths against an allowed root; reject absolute "
        "and parent-directory segments."
    ),
    "weak_crypto": (
        "Replace weak or obsolete cryptographic primitives with maintained, "
        "approved algorithms."
    ),
    "security_issue": (
        "Review the flagged code and apply the security guidance for this "
        "rule; do not suppress the check without an equivalent control."
    ),
    "high_complexity": (
        "Refactor the flagged block into smaller functions and reduce the "
        "number of independent control-flow paths."
    ),
    "low_maintainability": (
        "Refactor the flagged modules to reduce complexity and improve "
        "maintainability."
    ),
    "test_failure": (
        "Fix the failing tests or the underlying implementation; do not ignore "
        "test failures."
    ),
    "style_violation": (
        "Adjust the code to satisfy the reported style rule."
    ),
    "code_smell": (
        "Review the reported code issue and apply the recommended fix."
    ),
}


@dataclass(frozen=True)
class ToolAggregateSummary:
    """单个工具结果的聚合摘要。"""

    tool_name: str
    tool_version: str | None
    execution_status: ToolExecutionStatus
    finding_count: int
    analyzed_file_count: int
    duration_ms: int
    truncated: bool
    error: ErrorInfo | None = None


@dataclass(frozen=True)
class AggregationStats:
    """聚合过程的计数，用于报告与测试断言。"""

    source_finding_count: int
    mapped_finding_count: int
    final_finding_count: int
    duplicate_count: int
    skipped_finding_count: int
    test_failure_finding_count: int
    tool_failure_count: int
    partial_tool_count: int


@dataclass(frozen=True)
class AggregationResult:
    """一次审查的确定性分析聚合结果。"""

    tool_results: tuple[ToolExecutionResult, ...]
    test_result: TestExecutionResult | None
    tool_summaries: tuple[ToolAggregateSummary, ...]
    findings: tuple[Finding, ...]
    stats: AggregationStats
    raw_output_prefix: str
    warnings: tuple[str, ...] = ()


def aggregate_review_results(
    tool_results: Sequence[ToolExecutionResult],
    test_result: TestExecutionResult | None = None,
    *,
    raw_output_prefix: str = "static_analysis.json",
) -> AggregationResult:
    """把确定性工具结果映射、聚合并去重为合同 Finding。"""

    prefix = _normalize_prefix(raw_output_prefix)
    mapped: list[Finding] = []
    warnings: list[str] = []
    source_count = 0
    skipped_count = 0
    tool_counters: dict[str, int] = {}
    maintainability_items: list[tuple[ToolFinding, str, str | None]] = []
    test_failure_count = 0

    for result in tool_results:
        for finding in result.findings:
            source_count += 1
            index = tool_counters.get(result.tool_name, 0)
            tool_counters[result.tool_name] = index + 1
            raw_ref = (
                f"{prefix}#/tools/{_json_pointer_token(result.tool_name)}"
                f"/findings/{index}"
            )

            if result.tool_name == "radon" and finding.rule_id == "RADON_MI":
                if _radon_rank(finding) not in {"B", "C"}:
                    skipped_count += 1
                    continue
                maintainability_items.append(
                    (finding, raw_ref, result.tool_version)
                )
                continue

            if (
                result.tool_name == "radon"
                and finding.rule_id == "RADON_CC"
                and _radon_rank(finding) == "A"
            ):
                skipped_count += 1
                continue

            try:
                mapped.append(
                    _map_tool_finding(
                        finding,
                        tool_version=result.tool_version,
                        raw_output_ref=raw_ref,
                    )
                )
            except (ValidationError, ValueError) as exc:
                skipped_count += 1
                warnings.append(
                    f"{result.tool_name} finding {raw_ref} was skipped: "
                    f"{_safe_reason(exc)}"
                )

    maintainability = _aggregate_maintainability(maintainability_items)
    if maintainability is not None:
        mapped.append(maintainability)

    test_finding = _test_failure_finding(test_result, prefix)
    if test_finding is not None:
        mapped.append(test_finding)
        test_failure_count = 1

    findings, duplicate_count = deduplicate_findings(mapped)

    summaries = tuple(
        ToolAggregateSummary(
            tool_name=result.tool_name,
            tool_version=result.tool_version,
            execution_status=result.execution_status,
            finding_count=len(result.findings),
            analyzed_file_count=result.analyzed_file_count,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
            error=result.error,
        )
        for result in tool_results
    )
    failed_count = sum(
        1
        for summary in summaries
        if summary.execution_status
        in {
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.TIMEOUT,
            ToolExecutionStatus.NOT_FOUND,
            ToolExecutionStatus.PARSE_ERROR,
        }
    )
    partial_count = sum(
        1
        for summary in summaries
        if summary.execution_status is ToolExecutionStatus.PARTIAL
    )
    stats = AggregationStats(
        source_finding_count=source_count,
        mapped_finding_count=len(mapped),
        final_finding_count=len(findings),
        duplicate_count=duplicate_count,
        skipped_finding_count=skipped_count,
        test_failure_finding_count=test_failure_count,
        tool_failure_count=failed_count,
        partial_tool_count=partial_count,
    )
    return AggregationResult(
        tool_results=tuple(tool_results),
        test_result=test_result,
        tool_summaries=summaries,
        findings=findings,
        stats=stats,
        raw_output_prefix=prefix,
        warnings=tuple(warnings),
    )


def deduplicate_findings(
    findings: Iterable[Finding],
) -> tuple[tuple[Finding, ...], int]:
    """按工作流规则去重并合并 Finding。

    返回 ``(合并后的 Finding 元组, 被合并的数量)``。合并结果按严重级别、
    置信度、路径、行号与 finding_id 稳定排序。
    """

    candidates = [
        finding.model_copy(deep=True) for finding in findings
    ]
    candidates.sort(key=_primary_sort_key)

    groups: list[list[Finding]] = []
    for finding in candidates:
        for group in groups:
            if any(_can_merge(finding, member) for member in group):
                group.append(finding)
                break
        else:
            groups.append([finding])

    merged: list[Finding] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
        else:
            merged.append(_merge_group(group))

    merged.sort(key=_primary_sort_key)
    duplicate_count = len(candidates) - len(merged)
    return tuple(merged), duplicate_count


def _map_tool_finding(
    finding: ToolFinding,
    *,
    tool_version: str | None,
    raw_output_ref: str,
) -> Finding:
    tool = finding.tool_name
    rule_id = finding.rule_id or "unknown"
    severity = _tool_severity(finding)
    category = _tool_category(finding)
    confidence = _tool_confidence(finding)
    line = finding.line
    file_path = finding.file_path if line is not None else None
    start_line = line
    end_line = (
        finding.end_line
        if line is not None and finding.end_line is not None
        else line
    )
    message = _clean_text(finding.message, _MAX_TEXT_CHARS)
    if not message:
        message = f"{tool} reported {rule_id}"

    if tool == "radon" and rule_id == "RADON_CC":
        title = _radon_cc_title(finding)
        description = _radon_cc_description(finding, message)
        recommendation = _RECOMMENDATIONS["high_complexity"]
    elif tool == "bandit":
        title = _clean_text(f"{tool.title()} {rule_id}: {message}", _MAX_TITLE_CHARS)
        description = _bandit_description(finding, message)
        recommendation = _RECOMMENDATIONS.get(
            category, _RECOMMENDATIONS["security_issue"]
        )
    else:
        title = _clean_text(f"{tool.title()} {rule_id}: {message}", _MAX_TITLE_CHARS)
        description = _clean_text(
            f"{tool} reported {rule_id} at {finding.file_path}:{line}. {message}",
            _MAX_TEXT_CHARS,
        )
        recommendation = _RECOMMENDATIONS.get(
            category, _RECOMMENDATIONS["code_smell"]
        )

    if not title:
        title = f"{tool} {rule_id}"
    if not description:
        description = message
    evidence = _clean_text(f"{tool} {rule_id}: {message}", _MAX_TEXT_CHARS)
    if not evidence:
        evidence = message

    return Finding(
        finding_id=_tool_finding_id(tool, raw_output_ref),
        agent_name=STAGE1_AGENT_NAME,
        category=category,
        severity=severity,
        title=title,
        description=description,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        evidence=evidence,
        tool_evidence=[
            ToolEvidence(
                tool_name=tool,
                rule_id=finding.rule_id,
                tool_version=tool_version,
                raw_output_ref=raw_output_ref,
            )
        ],
        recommendation=_clean_text(recommendation, _MAX_TEXT_CHARS)
        or "Review the reported code and apply the recommended fix.",
        confidence=confidence,
        verification_status="unverified",
        merged_from=[],
    )


def _test_failure_finding(
    test_result: TestExecutionResult | None,
    prefix: str,
) -> Finding | None:
    if test_result is None:
        return None
    summary = test_result.summary
    if summary.execution_status != "executed":
        return None
    failed = summary.failed or 0
    if failed <= 0:
        return None

    passed = summary.passed or 0
    skipped = summary.skipped or 0
    evidence = (
        f"pytest: {passed} passed, {failed} failed, {skipped} skipped"
    )
    coverage = (
        f"; coverage {summary.coverage:.1f}%"
        if summary.coverage is not None
        else ""
    )
    return Finding(
        finding_id="PYTEST-0001",
        agent_name=STAGE1_AGENT_NAME,
        category="test_failure",
        severity="medium",
        title=_clean_text(f"pytest reported {failed} failing test(s)", _MAX_TITLE_CHARS),
        description=_clean_text(
            f"Pytest executed the trusted test fixture and reported "
            f"{failed} failing test(s) out of {passed + failed + skipped} "
            f"collected test(s){coverage}.",
            _MAX_TEXT_CHARS,
        ),
        file_path=None,
        start_line=None,
        end_line=None,
        evidence=_clean_text(evidence, _MAX_TEXT_CHARS),
        tool_evidence=[
            ToolEvidence(
                tool_name="pytest",
                rule_id=None,
                tool_version=test_result.pytest_version,
                raw_output_ref=f"{prefix}#/tests/pytest",
            )
        ],
        recommendation=_RECOMMENDATIONS["test_failure"],
        confidence=1.0,
        verification_status="unverified",
        merged_from=[],
    )


def _aggregate_maintainability(
    items: Sequence[tuple[ToolFinding, str, str | None]],
) -> Finding | None:
    if not items:
        return None

    ranked: list[tuple[ToolFinding, str, str | None, str, int]] = []
    for finding, raw_ref, tool_version in items:
        rank = _radon_rank(finding)
        if rank not in {"B", "C"}:
            continue
        ranked.append(
            (finding, raw_ref, tool_version, rank, _mi_severity_rank(rank))
        )
    if not ranked:
        return None

    ranked.sort(key=lambda item: (item[3], item[0].file_path))
    severity = _severity_name(max(item[4] for item in ranked))
    evidence_lines = [
        _maintainability_line(item[0], item[3]) for item in ranked
    ]
    evidence = _join_limited(evidence_lines, _MAX_TEXT_CHARS)
    tool_evidence = [
        ToolEvidence(
            tool_name="radon",
            rule_id="RADON_MI",
            tool_version=item[2],
            raw_output_ref=item[1],
        )
        for item in ranked
    ]
    count = len(ranked)
    title = _clean_text(
        f"Low maintainability in {count} module(s)",
        _MAX_TITLE_CHARS,
    )
    description = _clean_text(
        f"Radon maintainability index flagged {count} module(s) below "
        f"rank A; review the listed modules.",
        _MAX_TEXT_CHARS,
    )
    return Finding(
        finding_id="RADON-MI-0001",
        agent_name=STAGE1_AGENT_NAME,
        category="low_maintainability",
        severity=severity,
        title=title,
        description=description,
        file_path=None,
        start_line=None,
        end_line=None,
        evidence=evidence,
        tool_evidence=tool_evidence,
        recommendation=_RECOMMENDATIONS["low_maintainability"],
        confidence=1.0,
        verification_status="unverified",
        merged_from=[],
    )


def _merge_group(group: Sequence[Finding]) -> Finding:
    primary = group[0]
    description_source = max(
        group,
        key=lambda finding: (
            finding.confidence,
            SEVERITY_RANK[finding.severity],
        ),
    )
    severity = max(group, key=lambda finding: SEVERITY_RANK[finding.severity])
    tool_evidence = _merge_tool_evidence(group)
    merged_from = sorted(
        {
            finding.finding_id
            for finding in group
            if finding.finding_id != primary.finding_id
        }
    )
    return Finding(
        finding_id=primary.finding_id,
        agent_name=STAGE1_AGENT_NAME,
        category=primary.category,
        severity=severity.severity,
        title=primary.title,
        description=description_source.description,
        file_path=primary.file_path,
        start_line=primary.start_line,
        end_line=primary.end_line,
        evidence=description_source.evidence,
        tool_evidence=tool_evidence,
        recommendation=description_source.recommendation,
        confidence=max(finding.confidence for finding in group),
        verification_status="unverified",
        merged_from=merged_from,
    )


def _merge_tool_evidence(group: Sequence[Finding]) -> list[ToolEvidence]:
    seen: set[tuple[str, str, str]] = set()
    merged: list[ToolEvidence] = []
    for finding in group:
        for evidence in finding.tool_evidence:
            key = (
                evidence.tool_name,
                evidence.rule_id or "",
                evidence.raw_output_ref,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(evidence.model_copy(deep=True))
    return merged


def _can_merge(left: Finding, right: Finding) -> bool:
    if _category_group(left.category) != _category_group(right.category):
        return False
    left_located = left.file_path is not None and left.start_line is not None
    right_located = right.file_path is not None and right.start_line is not None
    if left_located != right_located:
        return False
    if left_located:
        if left.file_path != right.file_path:
            return False
        return _ranges_overlap(left, right)
    left_tools = _tool_names(left)
    right_tools = _tool_names(right)
    if left_tools or right_tools:
        return left_tools == right_tools
    return left.title == right.title


def _ranges_overlap(left: Finding, right: Finding) -> bool:
    left_start = left.start_line or 0
    right_start = right.start_line or 0
    left_end = left.end_line or left_start
    right_end = right.end_line or right_start
    return left_start <= right_end and right_start <= left_end


def _tool_names(finding: Finding) -> tuple[str, ...]:
    return tuple(
        sorted({evidence.tool_name for evidence in finding.tool_evidence})
    )


def _category_group(category: str) -> str:
    if category == "hardcoded_password":
        return "hardcoded_secret"
    return category


def _primary_sort_key(finding: Finding) -> tuple[object, ...]:
    return (
        -SEVERITY_RANK[finding.severity],
        -finding.confidence,
        finding.file_path or "",
        finding.start_line or 0,
        finding.finding_id,
    )


def _tool_severity(finding: ToolFinding) -> str:
    if finding.tool_name == "bandit":
        return {
            "HIGH": "high",
            "MEDIUM": "medium",
            "LOW": "low",
        }.get((finding.severity or "").upper(), "medium")
    if finding.tool_name == "radon" and finding.rule_id == "RADON_CC":
        rank = _radon_rank(finding)
        return {
            "B": "low",
            "C": "medium",
            "D": "high",
            "E": "high",
            "F": "high",
        }.get(rank, "medium")
    if finding.tool_name == "ruff":
        rule = (finding.rule_id or "").upper()
        if rule.startswith("E9") or _is_bandit_ruff_rule(rule):
            return "high"
        if rule.startswith(("F", "B", "C90")):
            return "medium"
        return "low"
    return "low"


def _is_bandit_ruff_rule(rule: str) -> bool:
    """Ruff 的 Bandit 规则形如 ``S603``，不能把 ``SIM`` 误判为安全规则。"""

    return len(rule) > 1 and rule[0] == "S" and rule[1:].isdigit()


def _tool_category(finding: ToolFinding) -> str:
    rule = (finding.rule_id or "").upper()
    if finding.tool_name == "bandit":
        return _BANDIT_CATEGORY_BY_RULE.get(rule, "security_issue")
    if finding.tool_name == "radon":
        return "high_complexity"
    if finding.tool_name == "ruff":
        if _is_bandit_ruff_rule(rule):
            bandit_rule = f"B{rule[1:]}"
            if bandit_rule in _BANDIT_CATEGORY_BY_RULE:
                return _BANDIT_CATEGORY_BY_RULE[bandit_rule]
            return "security_issue"
        if rule.startswith("C90"):
            return "high_complexity"
        if rule.startswith(("E", "W", "I", "UP", "RUF", "SIM", "D")):
            return "style_violation"
        return "code_smell"
    return "code_smell"


def _tool_confidence(finding: ToolFinding) -> float:
    if finding.tool_name == "bandit":
        return {
            "HIGH": 0.9,
            "MEDIUM": 0.7,
            "LOW": 0.5,
        }.get((finding.confidence or "").upper(), 0.5)
    if finding.tool_name == "radon":
        return 1.0
    return 0.9


def _radon_rank(finding: ToolFinding) -> str:
    rank = finding.metadata.get("rank")
    return rank.upper() if isinstance(rank, str) else ""


def _radon_cc_title(finding: ToolFinding) -> str:
    name = finding.metadata.get("object_name")
    rank = _radon_rank(finding) or "?"
    label = name if isinstance(name, str) and name else "unknown block"
    return _clean_text(
        f"Cyclomatic complexity {rank} in {label}",
        _MAX_TITLE_CHARS,
    )


def _radon_cc_description(finding: ToolFinding, message: str) -> str:
    complexity = finding.metadata.get("complexity")
    rank = _radon_rank(finding) or "?"
    object_type = finding.metadata.get("object_type")
    label = object_type if isinstance(object_type, str) and object_type else "block"
    return _clean_text(
        f"Radon reported {label} {finding.metadata.get('object_name')} "
        f"at {finding.file_path}:{finding.line} with cyclomatic complexity "
        f"{complexity} (rank {rank}). {message}",
        _MAX_TEXT_CHARS,
    )


def _bandit_description(finding: ToolFinding, message: str) -> str:
    test_name = finding.metadata.get("test_name")
    severity = finding.severity or "unknown"
    confidence = finding.confidence or "unknown"
    return _clean_text(
        f"Bandit reported {finding.rule_id}"
        f"{f' ({test_name})' if isinstance(test_name, str) and test_name else ''} "
        f"at {finding.file_path}:{finding.line} with severity {severity} "
        f"and confidence {confidence}. {message}",
        _MAX_TEXT_CHARS,
    )


def _maintainability_line(finding: ToolFinding, rank: str) -> str:
    mi = finding.metadata.get("mi")
    score = f"{float(mi):.2f}" if isinstance(mi, (int, float)) else "unknown"
    return f"{finding.file_path}: MI {score} (rank {rank})"


def _mi_severity_rank(rank: str) -> int:
    return {"B": SEVERITY_RANK["low"], "C": SEVERITY_RANK["medium"]}.get(
        rank, SEVERITY_RANK["low"]
    )


def _severity_name(rank: int) -> str:
    for name, value in SEVERITY_RANK.items():
        if value == rank:
            return name
    return "low"


def _tool_finding_id(tool_name: str, raw_output_ref: str) -> str:
    prefix = "".join(
        character
        for character in tool_name.upper()
        if character.isalnum()
    ) or "TOOL"
    index = raw_output_ref.rsplit("/", 1)[-1]
    return f"{prefix}-{index.zfill(4)}"


def _normalize_prefix(prefix: str) -> str:
    value = prefix.strip().removesuffix("#")
    return value or "static_analysis.json"


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _clean_text(text: str, limit: int) -> str:
    return redact_sensitive_text(text, max_chars=limit).strip()


def _join_limited(lines: Sequence[str], limit: int) -> str:
    result = ""
    for line in lines:
        candidate = f"{result}\n{line}" if result else line
        if len(candidate) > limit:
            suffix = "\n..."
            return candidate[: max(0, limit - len(suffix))] + suffix
        result = candidate
    return result


def _safe_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if errors:
            message = str(errors[0].get("msg", "invalid finding"))
        else:
            message = "invalid finding"
    else:
        message = str(exc)
    return redact_sensitive_text(message, max_chars=_MAX_REASON_CHARS)
