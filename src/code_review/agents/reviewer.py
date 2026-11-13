"""Stage 2.4 Final Reviewer：合同校验、证据验证、去重、评分与报告。

Final Reviewer 是 LangGraph 的独立节点，但**不是 AgentTask**：它不创建
task_id，也不增加专业 Agent 任务总数（仍为四个）。本模块只读取：

- Manager Aggregate 写入 State 的四个 ``AgentResult``（不修改原对象）；
- Manager Aggregate 构建的只读 ``ArtifactData`` 内存快照；
- 固定 commit 的只读工作区源码（证据验证用）。

它不调用 LLM、不访问网络、不写任何文件、不生成报告文件。``ArtifactData``
的同一份内容由 Stage 2.5 报告生成器写盘，保证 JSON Pointer 在内存与落盘
后解析到同一记录。

失败语义：Final Reviewer 自身无法产出合法 ``ReviewReport`` 时抛出
``FinalReviewError``，整次审查失败；不得伪造 partial 报告。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from code_review.agents.contracts import ArtifactData, UsageSummary
from code_review.agents.evidence import (
    CHECK_IDS,
    STATUS_REJECTED,
    STATUS_UNVERIFIED,
    STATUS_VERIFIED,
    FindingValidation,
    Stage2EvidenceValidator,
)
from code_review.agents.manager import AGENT_SPECS, DIMENSIONS
from code_review.agents.scoring import (
    DimensionScoring,
    build_dimension_score,
    compute_overall_score,
    decide_verdict,
    format_score,
    to_schema_dimension,
)
from code_review.schemas.report import (
    CostSummary,
    ExecutionSummary,
    ReviewReport,
    TestSummary,
)
from code_review.schemas.result import AgentResult, Finding, ToolEvidence
from code_review.services.redaction import redact_sensitive_text
from config.llm_pricing import ModelPricing
from config.review_rules import ReviewRules

__all__ = [
    "FinalReviewError",
    "FinalReviewRequest",
    "FinalReviewer",
    "ReviewOutcome",
]

REVIEW_STATUS_COMPLETED = "completed"

_MAX_REASON = 500
_MAX_SUMMARY = 4000

_SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}
_STATUS_RANK = {
    STATUS_UNVERIFIED: 0,
    STATUS_VERIFIED: 1,
}

_CATEGORY_GROUPS = {
    "hardcoded_password": "hardcoded_secret",
    "style_violation": "style",
}

_AGENT_DIMENSIONS = {
    agent_name: dimension
    for dimension, agent_name, _, _ in AGENT_SPECS
}

_TEST_REPORT_STATUSES = frozenset({"executed", "not_executed", "failed"})
_COMPLETE_TOOL_STATUSES = frozenset({"success", "findings"})


class FinalReviewError(RuntimeError):
    """Final Reviewer 无法产出合法审查报告；整次审查失败。"""


def _clip(text: str, limit: int = _MAX_REASON) -> str:
    cleaned = redact_sensitive_text(text, max_chars=limit)
    return cleaned or "unspecified"


def _severity_rank(severity: str) -> int:
    try:
        return _SEVERITY_RANK[severity]
    except KeyError as exc:
        raise FinalReviewError(
            f"unsupported finding severity: {severity}"
        ) from exc


def _dimension_of(agent_name: str) -> str:
    try:
        return _AGENT_DIMENSIONS[agent_name]
    except KeyError as exc:
        raise FinalReviewError(
            f"finding agent_name is not a core agent: {agent_name}"
        ) from exc


# ----------------------------------------------------------------------
# Request / outcome


@dataclass(frozen=True)
class FinalReviewRequest:
    """Final Reviewer 的全部输入；由 Graph 节点从 ``ReviewState`` 构造。"""

    review_id: str
    commit_sha: str
    repository: str
    repository_url: str
    branch: str
    language: str
    workspace_path: Path
    allowed_files: tuple[str, ...]
    rules: ReviewRules
    agent_results: Mapping[str, AgentResult]
    artifact_data: ArtifactData
    usage_summary: UsageSummary
    model_pricing: ModelPricing | None = None
    execution_summary: ExecutionSummary | None = None
    trace_id: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "review_id",
            "commit_sha",
            "repository",
            "repository_url",
            "branch",
            "language",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise FinalReviewError(
                    f"FinalReviewRequest.{name} must be a non-empty string"
                )
        if isinstance(self.allowed_files, (str, bytes)):
            raise FinalReviewError(
                "FinalReviewRequest.allowed_files must be a sequence"
            )
        object.__setattr__(self, "allowed_files", tuple(self.allowed_files))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "workspace_path", Path(self.workspace_path))

        if self.trace_id is not None and (
            not isinstance(self.trace_id, str) or not self.trace_id.strip()
        ):
            raise FinalReviewError(
                "FinalReviewRequest.trace_id must be non-empty or None"
            )
        if not isinstance(self.rules, ReviewRules):
            raise FinalReviewError(
                "FinalReviewRequest.rules must be a ReviewRules"
            )
        if not isinstance(self.artifact_data, ArtifactData):
            raise FinalReviewError(
                "FinalReviewRequest.artifact_data must be an ArtifactData"
            )
        if not isinstance(self.usage_summary, UsageSummary):
            raise FinalReviewError(
                "FinalReviewRequest.usage_summary must be a UsageSummary"
            )
        if self.model_pricing is not None and not isinstance(
            self.model_pricing, ModelPricing
        ):
            raise FinalReviewError(
                "FinalReviewRequest.model_pricing must be a ModelPricing or None"
            )
        if self.execution_summary is not None and not isinstance(
            self.execution_summary, ExecutionSummary
        ):
            raise FinalReviewError(
                "FinalReviewRequest.execution_summary must be an "
                "ExecutionSummary or None"
            )
        if not isinstance(self.agent_results, Mapping):
            raise FinalReviewError(
                "FinalReviewRequest.agent_results must be a mapping"
            )
        agent_results = dict(self.agent_results)
        if set(agent_results) != set(DIMENSIONS):
            raise FinalReviewError(
                "FinalReviewRequest.agent_results must contain exactly the "
                "four core dimensions"
            )
        for dimension, agent_name, _, _ in AGENT_SPECS:
            result = agent_results[dimension]
            if not isinstance(result, AgentResult):
                raise FinalReviewError(
                    f"agent_results[{dimension}] must be an AgentResult"
                )
            if result.agent_name != agent_name:
                raise FinalReviewError(
                    f"agent_results[{dimension}].agent_name must be "
                    f"{agent_name}"
                )
            if result.review_id != self.review_id:
                raise FinalReviewError(
                    f"agent_results[{dimension}].review_id does not match "
                    "the review"
                )
            if result.commit_sha != self.commit_sha:
                raise FinalReviewError(
                    f"agent_results[{dimension}].commit_sha does not match "
                    "the review commit"
                )
        object.__setattr__(self, "agent_results", agent_results)


@dataclass(frozen=True)
class ReviewOutcome:
    """Final Reviewer 的输出：合法报告、统计与完成状态。"""

    report: ReviewReport
    statistics: dict[str, Any]
    review_status: str = REVIEW_STATUS_COMPLETED


# ----------------------------------------------------------------------
# Final Reviewer


class FinalReviewer:
    """Stage 2.4 的确定性终审器。"""

    def __init__(
        self,
        *,
        validator_factory: type[Stage2EvidenceValidator]
        | None = None,
    ) -> None:
        self._validator_factory = (
            validator_factory or Stage2EvidenceValidator
        )

    def review(self, request: FinalReviewRequest) -> ReviewOutcome:
        if not isinstance(request, FinalReviewRequest):
            raise TypeError("request must be a FinalReviewRequest")

        validator = self._validator_factory(
            workspace_path=request.workspace_path,
            allowed_files=request.allowed_files,
            artifact_data=request.artifact_data,
            rules=request.rules,
        )
        validations = self._validate_all(request, validator)

        rejected_findings = [
            validation.finding
            for group in validations.values()
            for validation in group
            if validation.status == STATUS_REJECTED
        ]
        accepted = [
            validation
            for group in validations.values()
            for validation in group
            if validation.status != STATUS_REJECTED
        ]
        merged_findings, dedup_stats = _deduplicate(accepted)

        scorings = [
            self._score_dimension(
                dimension=dimension,
                findings=[
                    finding
                    for finding in merged_findings
                    if _dimension_of(finding.agent_name) == dimension
                ],
                result=request.agent_results[dimension],
                artifact_data=request.artifact_data,
                rules=request.rules,
            )
            for dimension in DIMENSIONS
        ]
        overall_score = compute_overall_score(scorings)
        report_status = _report_status(scorings, request.agent_results)
        verdict = decide_verdict(
            scorings=scorings,
            findings=merged_findings,
            overall_score=overall_score,
            rules=request.rules,
            report_status=report_status,
        )
        execution_summary = (
            request.execution_summary
            if request.execution_summary is not None
            else _derived_execution_summary(request.agent_results)
        )
        test_summary = _build_test_summary(request.artifact_data)
        cost_summary = _build_cost_summary(
            request.usage_summary,
            request.model_pricing,
        )
        summary = _build_summary(
            request=request,
            verdict=verdict.verdict,
            overall_score=overall_score,
            finding_count=len(merged_findings),
            rejected_count=len(rejected_findings),
        )

        try:
            report = ReviewReport(
                review_id=request.review_id,
                trace_id=request.trace_id,
                repository=request.repository,
                repository_url=request.repository_url,
                branch=request.branch,
                commit_sha=request.commit_sha,
                language=request.language,
                report_status=report_status,
                overall_verdict=verdict.verdict,
                verdict_reasons=[
                    _clip(reason) for reason in verdict.reasons
                ],
                overall_score=overall_score,
                dimension_scores={
                    item.dimension: to_schema_dimension(item)
                    for item in scorings
                },
                summary=summary,
                agent_results=dict(request.agent_results),
                findings=merged_findings,
                rejected_findings=rejected_findings,
                test_summary=test_summary,
                execution_summary=execution_summary,
                cost_summary=cost_summary,
            )
        except (ValidationError, ValueError) as exc:
            raise FinalReviewError(
                "final ReviewReport failed contract validation: "
                f"{type(exc).__name__}"
            ) from exc

        statistics = _build_statistics(
            request=request,
            validations=validations,
            rejected=rejected_findings,
            findings=merged_findings,
            dedup_stats=dedup_stats,
            scorings=scorings,
            overall_score=overall_score,
            verdict=verdict.verdict,
            verdict_reasons=verdict.reasons,
            report_status=report_status,
        )
        return ReviewOutcome(
            report=report,
            statistics=statistics,
            review_status=REVIEW_STATUS_COMPLETED,
        )

    # ------------------------------------------------------------------
    # Validation

    def _validate_all(
        self,
        request: FinalReviewRequest,
        validator: Stage2EvidenceValidator,
    ) -> dict[str, list[FindingValidation]]:
        validations: dict[str, list[FindingValidation]] = {}
        for dimension in DIMENSIONS:
            result = request.agent_results[dimension]
            items: list[FindingValidation] = []
            for finding in result.findings:
                if finding.agent_name != result.agent_name:
                    raise FinalReviewError(
                        f"finding {finding.finding_id} agent_name does not "
                        f"match agent_results[{dimension}]"
                    )
                items.append(validator.validate(finding))
            validations[dimension] = items
        return validations

    # ------------------------------------------------------------------
    # Scoring

    @staticmethod
    def _score_dimension(
        *,
        dimension: str,
        findings: Sequence[Finding],
        result: AgentResult,
        artifact_data: ArtifactData,
        rules: ReviewRules,
    ) -> DimensionScoring:
        unavailable_reason = _dimension_unavailable_reason(
            dimension=dimension,
            result=result,
            artifact_data=artifact_data,
        )
        return build_dimension_score(
            dimension=dimension,
            findings=findings,
            status=result.status,
            rules=rules,
            unavailable_reason=unavailable_reason,
        )


# ----------------------------------------------------------------------
# Dimension availability


def _dimension_unavailable_reason(
    *,
    dimension: str,
    result: AgentResult,
    artifact_data: ArtifactData,
) -> str | None:
    if result.status == "failed":
        error_type = (
            result.error.error_type if result.error is not None else "unknown"
        )
        return f"{result.agent_name} failed ({error_type})"
    if dimension == "testing":
        return _testing_unavailable_reason(artifact_data)
    if result.status == "partial":
        incomplete = _incomplete_tools(artifact_data, dimension)
        if incomplete:
            return "tool execution did not complete: " + ", ".join(
                f"{name}={status}" for name, status in incomplete
            )
    return None


def _testing_unavailable_reason(
    artifact_data: ArtifactData,
) -> str | None:
    report = artifact_data.test_report_dict()
    raw_status = report.get("execution_status")
    status = str(raw_status) if isinstance(raw_status, str) else "not_executed"
    if status == "executed":
        return None
    reason = report.get("reason")
    if isinstance(reason, str) and reason.strip():
        return _clip(reason)
    if status == "not_executed":
        return "tests were not executed"
    if status == "failed":
        return "test execution failed"
    return f"test execution status is {status}"


def _incomplete_tools(
    artifact_data: ArtifactData,
    dimension: str,
) -> list[tuple[str, str]]:
    static = artifact_data.static_analysis_dict()
    agents = static.get("agents")
    if not isinstance(agents, Mapping):
        return []
    block = agents.get(dimension)
    if not isinstance(block, Mapping):
        return []
    tools = block.get("tools")
    if not isinstance(tools, Mapping):
        return []
    incomplete: list[tuple[str, str]] = []
    for name, tool_block in tools.items():
        status = (
            tool_block.get("execution_status")
            if isinstance(tool_block, Mapping)
            else None
        )
        normalized = str(status) if status is not None else "unknown"
        if normalized not in _COMPLETE_TOOL_STATUSES:
            incomplete.append((str(name), normalized))
    return incomplete


# ----------------------------------------------------------------------
# Deduplication


def _category_group(category: str) -> str:
    return _CATEGORY_GROUPS.get(category, category)


def _tool_key(finding: Finding) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                evidence.tool_name.strip().lower()
                for evidence in finding.tool_evidence
                if evidence.tool_name.strip()
            }
        )
    )


def _ranges_overlap(left: Finding, right: Finding) -> bool:
    if (
        left.start_line is None
        or right.start_line is None
    ):
        return False
    left_end = left.end_line or left.start_line
    right_end = right.end_line or right.start_line
    return left.start_line <= right_end and right.start_line <= left_end


def _can_merge(left: Finding, right: Finding) -> bool:
    """去重条件：类别组一致，且位于同一位置 / 同一项目级稳定键。"""

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
    # 项目级 Finding 使用 (category, tool_name) 稳定键；没有工具名不合并。
    left_tools = _tool_key(left)
    right_tools = _tool_key(right)
    return bool(left_tools) and left_tools == right_tools


def _best_member(group: Sequence[FindingValidation]) -> FindingValidation:
    return max(
        group,
        key=lambda validation: (
            validation.finding.confidence,
            _severity_rank(validation.finding.severity),
            -DIMENSIONS.index(_dimension_of(validation.finding.agent_name)),
            validation.finding.finding_id,
        ),
    )


def _merge_group(group: Sequence[FindingValidation]) -> Finding:
    best = _best_member(group)
    base = best.finding
    severity = max(
        (validation.finding.severity for validation in group),
        key=_severity_rank,
    )
    if severity in {"critical", "high"} and (
        base.file_path is None or base.start_line is None
    ):
        raise FinalReviewError(
            "merged critical/high finding must keep a code location"
        )

    ordered: list[FindingValidation] = [best]
    ordered.extend(validation for validation in group if validation is not best)

    tool_evidence: list[ToolEvidence] = []
    seen_refs: set[str] = set()
    for validation in ordered:
        for evidence in validation.finding.tool_evidence:
            if evidence.raw_output_ref in seen_refs:
                continue
            seen_refs.add(evidence.raw_output_ref)
            tool_evidence.append(evidence)

    merged_from: set[str] = set(base.merged_from)
    for validation in group:
        if validation is best:
            continue
        merged_from.update(validation.finding.merged_from)
        merged_from.add(validation.finding.finding_id)

    status = STATUS_UNVERIFIED
    if any(validation.status == STATUS_VERIFIED for validation in group):
        status = STATUS_VERIFIED
    if any(validation.status == STATUS_REJECTED for validation in group):
        raise FinalReviewError("rejected findings must not enter deduplication")

    return base.model_copy(
        update={
            "severity": severity,
            "tool_evidence": tool_evidence,
            "merged_from": sorted(merged_from),
            "verification_status": status,
        }
    )


def _deduplicate(
    validations: Sequence[FindingValidation],
) -> tuple[list[Finding], dict[str, Any]]:
    groups: list[list[FindingValidation]] = []
    for validation in validations:
        for group in groups:
            if any(
                _can_merge(validation.finding, member.finding)
                for member in group
            ):
                group.append(validation)
                break
        else:
            groups.append([validation])

    merged = [_merge_group(group) for group in groups]
    merged = _ensure_unique_ids(merged)
    merged.sort(key=_final_sort_key)
    stats = {
        "input_findings": len(validations),
        "output_findings": len(merged),
        "merged_groups": sum(1 for group in groups if len(group) > 1),
        "merged_away": len(validations) - len(merged),
    }
    return merged, stats


def _ensure_unique_ids(findings: Sequence[Finding]) -> list[Finding]:
    seen: set[str] = set()
    unique: list[Finding] = []
    for finding in findings:
        finding_id = finding.finding_id
        if finding_id in seen:
            suffix = 2
            while f"{finding_id}~{suffix}" in seen:
                suffix += 1
            finding_id = f"{finding_id}~{suffix}"
            finding = finding.model_copy(update={"finding_id": finding_id})
        seen.add(finding_id)
        unique.append(finding)
    return unique


def _final_sort_key(finding: Finding) -> tuple[Any, ...]:
    return (
        -_severity_rank(finding.severity),
        DIMENSIONS.index(_dimension_of(finding.agent_name)),
        finding.file_path or "",
        finding.start_line or 0,
        finding.finding_id,
    )


# ----------------------------------------------------------------------
# Report pieces


def _report_status(
    scorings: Sequence[DimensionScoring],
    agent_results: Mapping[str, AgentResult],
) -> str:
    all_scored = all(item.score is not None for item in scorings)
    all_completed = all(
        result.status == "completed" for result in agent_results.values()
    )
    return "completed" if all_scored and all_completed else "partial"


def _derived_execution_summary(
    agent_results: Mapping[str, AgentResult],
) -> ExecutionSummary:
    results = list(agent_results.values())
    cancelled = sum(
        1
        for result in results
        if result.status == "failed"
        and result.error is not None
        and result.error.error_type == "cancelled"
    )
    failed = sum(1 for result in results if result.status == "failed")
    return ExecutionSummary(
        total_tasks=len(results),
        completed_tasks=sum(
            1 for result in results if result.status == "completed"
        ),
        partial_tasks=sum(
            1 for result in results if result.status == "partial"
        ),
        failed_tasks=failed - cancelled,
        cancelled_tasks=cancelled,
        duration_seconds=max(
            (float(result.execution_time) for result in results),
            default=0.0,
        ),
    )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 100:
        return None
    return number


def _build_test_summary(artifact_data: ArtifactData) -> TestSummary:
    report = artifact_data.test_report_dict()
    raw_status = report.get("execution_status")
    status = str(raw_status) if isinstance(raw_status, str) else "not_executed"
    raw_reason = report.get("reason")
    reason = (
        raw_reason.strip()
        if isinstance(raw_reason, str) and raw_reason.strip()
        else None
    )
    coverage = _optional_float(report.get("coverage"))
    raw_source = report.get("source")
    source = (
        raw_source.strip()
        if isinstance(raw_source, str) and raw_source.strip()
        else None
    )
    if coverage is not None and source is None:
        # 覆盖率必须有真实来源；缺失来源时不得把数值写入报告。
        coverage = None

    if status == "not_executed":
        return TestSummary(
            execution_status="not_executed",
            reason=reason or "tests were not executed",
        )
    if status not in _TEST_REPORT_STATUSES:
        status = "failed"
        reason = reason or (
            f"test execution did not complete (raw status: {raw_status})"
        )

    counts = report.get("counts")
    counts = counts if isinstance(counts, Mapping) else {}
    passed = _optional_int(counts.get("passed"))
    failed = _optional_int(counts.get("failed"))
    skipped = _optional_int(counts.get("skipped"))
    if status == "failed":
        return TestSummary(
            execution_status="failed",
            passed=passed,
            failed=failed,
            skipped=skipped,
            coverage=coverage,
            source=source,
            reason=reason or "test execution failed",
        )
    return TestSummary(
        execution_status="executed",
        passed=passed,
        failed=failed,
        skipped=skipped,
        coverage=coverage,
        source=source,
    )


def _build_cost_summary(
    usage_summary: UsageSummary,
    model_pricing: ModelPricing | None,
) -> CostSummary:
    """O-1：零调用写零成本；真实调用必须用真实 usage 与明确单价计价。

    不得把缺失 usage、缺失价格或未知模型降级为 0。只要有一次调用没有
    返回可拆分的 token usage，成本就无法确定，必须让整次审查显式失败。
    """

    if usage_summary.llm_calls == 0:
        if usage_summary.input_tokens or usage_summary.output_tokens:
            raise FinalReviewError(
                "LLM usage reports tokens without calls; cost cannot be "
                "determined"
            )
        return CostSummary()

    if model_pricing is None:
        raise FinalReviewError(
            "LLM pricing is required to compute the cost of real LLM usage"
        )
    if usage_summary.reported_usage_calls != usage_summary.llm_calls:
        raise FinalReviewError(
            "LLM usage is incomplete: cost cannot be determined when any "
            "call omits prompt/completion token usage"
        )
    if usage_summary.total_tokens == 0:
        raise FinalReviewError(
            "LLM usage reports zero tokens for real calls; cost cannot be "
            "determined"
        )

    try:
        estimated_cost = model_pricing.estimate(
            usage_summary.input_tokens,
            usage_summary.output_tokens,
        )
    except ValueError as exc:
        raise FinalReviewError(
            "LLM cost estimate failed due to invalid pricing or usage"
        ) from exc
    return CostSummary(
        total_input_tokens=usage_summary.input_tokens,
        total_output_tokens=usage_summary.output_tokens,
        estimated_cost=float(estimated_cost),
        currency=model_pricing.currency,
    )


def _build_summary(
    *,
    request: FinalReviewRequest,
    verdict: str,
    overall_score: float | None,
    finding_count: int,
    rejected_count: int,
) -> str:
    text = (
        f"{request.repository}@{request.commit_sha[:7]} "
        f"({request.branch}) 审查完成：结论 {verdict}，"
        f"综合分 {format_score(overall_score)}；"
        f"有效 Finding {finding_count} 条，被拒绝 {rejected_count} 条。"
    )
    return redact_sensitive_text(text, max_chars=_MAX_SUMMARY)


# ----------------------------------------------------------------------
# Statistics


def _verification_counts(
    validations: Sequence[FindingValidation],
) -> dict[str, Any]:
    counts = {
        status: sum(1 for item in validations if item.status == status)
        for status in (STATUS_VERIFIED, STATUS_UNVERIFIED, STATUS_REJECTED)
    }
    checks = {
        check_id: {"passed": 0, "failed": 0} for check_id in CHECK_IDS
    }
    for validation in validations:
        for check in validation.checks:
            bucket = checks.setdefault(
                check.check_id, {"passed": 0, "failed": 0}
            )
            bucket["passed" if check.passed else "failed"] += 1
    return {
        "total": len(validations),
        **counts,
        "checks": checks,
        "false_positive_downgrades": sum(
            1 for item in validations if item.false_positive
        ),
        "line_adjustments": sum(
            1 for item in validations if item.adjusted
        ),
    }


def _build_statistics(
    *,
    request: FinalReviewRequest,
    validations: Mapping[str, Sequence[FindingValidation]],
    rejected: Sequence[Finding],
    findings: Sequence[Finding],
    dedup_stats: Mapping[str, Any],
    scorings: Sequence[DimensionScoring],
    overall_score: float | None,
    verdict: str,
    verdict_reasons: Sequence[str],
    report_status: str,
) -> dict[str, Any]:
    per_dimension = {
        dimension: _verification_counts(validations[dimension])
        for dimension in DIMENSIONS
    }
    status_counts = {
        status: sum(
            per_dimension[dimension][status] for dimension in DIMENSIONS
        )
        for status in (STATUS_VERIFIED, STATUS_UNVERIFIED, STATUS_REJECTED)
    }
    return {
        "final_reviewer": "implemented",
        "stage": "2.4",
        "implemented": True,
        "aggregated_dimensions": sorted(request.agent_results),
        "artifact_data_available": True,
        "agent_task_count": len(DIMENSIONS),
        "finding_counts": {
            "total": len(findings) + len(rejected),
            **status_counts,
            "reported": len(findings),
            "rejected_findings": len(rejected),
        },
        "verification": per_dimension,
        "deduplication": dict(dedup_stats),
        "dimension_scores": {
            item.dimension: {
                "score": item.score,
                "weight": item.weight,
                "status": item.status,
                "finding_count": item.finding_count,
                "reason": item.reason,
            }
            for item in scorings
        },
        "overall_score": overall_score,
        "overall_score_display": format_score(overall_score),
        "overall_verdict": verdict,
        "verdict_reasons": list(verdict_reasons),
        "report_status": report_status,
        "usage": {
            "llm_calls": request.usage_summary.llm_calls,
            "input_tokens": request.usage_summary.input_tokens,
            "output_tokens": request.usage_summary.output_tokens,
        },
    }
