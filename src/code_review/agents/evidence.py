"""Stage 2 Final Reviewer 证据验证：V1～V7 与内存 ArtifactData 引用。

本模块只做确定性校验，不调用 LLM、不访问网络、不写入任何文件：

- V1：代码位置型 Finding 的文件存在且是普通文件；
- V2：路径必须是仓库相对 POSIX 路径、位于允许分析集合内、不越界、
  不通过符号链接或 junction 逃逸；
- V3：行号范围合法；
- V4：代码片段与固定 commit 源码匹配，邻域唯一匹配可修正行号；
- V5：工具证据引用在 **内存 ArtifactData** 上解析，且工具/规则/文件/行/
  指标一致；绝不打开尚未写盘的报告文件；
- V6：测试/示例代码误报启发，只记录并降级；
- V7：标题、描述、证据与建议中的敏感信息脱敏。

两类 Finding 的验证状态见 ``FindingValidation``。``verified`` 只能由
V1～V5 的确定性证据产生，LLM 自我确认不会出现在本模块。
"""

from __future__ import annotations

import math
import tokenize
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from code_review.agents.contracts import ArtifactData, ArtifactPointerError
from code_review.schemas.result import Finding, ToolEvidence
from code_review.services.redaction import redact_sensitive_text
from code_review.tools.file_filters import FileFilterPolicy
from config.review_rules import ReviewRules

__all__ = [
    "CHECK_IDS",
    "EVENT_CODE_LOCATION",
    "EVENT_TOOL_REPORT",
    "STATUS_REJECTED",
    "STATUS_UNVERIFIED",
    "STATUS_VERIFIED",
    "EvidenceCheck",
    "EvidenceKind",
    "EvidenceRecord",
    "EvidenceReferenceError",
    "EvidenceRegistry",
    "FindingValidation",
    "Stage2EvidenceValidator",
]

STATUS_VERIFIED = "verified"
STATUS_UNVERIFIED = "unverified"
STATUS_REJECTED = "rejected"

EVENT_CODE_LOCATION = "code_location"
EVENT_TOOL_REPORT = "tool_report"

EvidenceKind = Literal["code_location", "tool_report"]

CHECK_IDS: tuple[str, ...] = ("V1", "V2", "V3", "V4", "V5", "V6", "V7")

_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_TITLE = 200
_MAX_TEXT = 4_000
_MAX_REASON = 300
_EVIDENCE_SEARCH_RADIUS = 3

_TEST_PATH_PARTS = frozenset(
    {
        "test",
        "tests",
        "testing",
        "example",
        "examples",
        "docs",
        "fixture",
        "fixtures",
        "sample",
        "samples",
    }
)

_TEST_REPORT_STATUSES = frozenset({"executed", "not_executed", "failed"})
_TESTING_CATEGORIES = frozenset(
    {"test_failure", "low_coverage", "missing_tests"}
)


class EvidenceReferenceError(ValueError):
    """工具证据引用无法在内存 ArtifactData 中安全解析。"""


def _reason(text: str) -> str:
    return redact_sensitive_text(text, max_chars=_MAX_REASON)


def _normalize_repo_path(value: object) -> str | None:
    """校验并规范化仓库相对 POSIX 路径；任何不安全输入返回 None。"""

    if not isinstance(value, str) or not value:
        return None
    if len(value) > 512:
        return None
    if "\\" in value or "\x00" in value or ":" in value:
        return None
    pure = PurePosixPath(value)
    if (
        not pure.parts
        or pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
    ):
        return None
    if pure.as_posix() != value:
        return None
    return value


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


# ----------------------------------------------------------------------
# Memory evidence registry


@dataclass(frozen=True)
class EvidenceRecord:
    """ArtifactData 中的一条稳定引用。"""

    pointer: str
    file_name: str
    kind: str
    value: Any
    dimension: str | None = None
    tool_name: str | None = None
    index: int | None = None


class EvidenceRegistry:
    """把 ``ArtifactData`` 索引为稳定的 JSON Pointer 到记录映射。

    注册表只在内存对象上工作。它不检查磁盘上是否存在
    ``static_analysis.json`` / ``test_report.json``，也不允许其他文件名。
    """

    def __init__(self, artifact_data: ArtifactData) -> None:
        if not isinstance(artifact_data, ArtifactData):
            raise TypeError("artifact_data must be an ArtifactData")
        self._artifact_data = artifact_data
        self._records = self._index(artifact_data)

    @classmethod
    def from_artifact_data(cls, artifact_data: ArtifactData) -> EvidenceRegistry:
        return cls(artifact_data)

    def pointers(self) -> tuple[str, ...]:
        return tuple(self._records)

    def get(self, pointer: str) -> EvidenceRecord | None:
        if not isinstance(pointer, str):
            return None
        return self._records.get(pointer)

    def resolve(self, pointer: str) -> EvidenceRecord:
        record = self.get(pointer)
        if record is not None:
            return record
        # 区分“未注册但可解析”的引用；V5 不接受未注册的引用。
        try:
            self._artifact_data.resolve(pointer)
        except (ArtifactPointerError, ValueError) as exc:
            raise EvidenceReferenceError(
                _reason(f"invalid artifact reference: {exc}")
            ) from exc
        raise EvidenceReferenceError(
            _reason("artifact reference is not a recognized evidence pointer")
        )

    @staticmethod
    def _index(artifact_data: ArtifactData) -> dict[str, EvidenceRecord]:
        records: dict[str, EvidenceRecord] = {}
        static = artifact_data.static_analysis_dict()
        agents = static.get("agents")
        if isinstance(agents, Mapping):
            for dimension, block in agents.items():
                if not isinstance(dimension, str) or not isinstance(
                    block, Mapping
                ):
                    continue
                tools = block.get("tools")
                if not isinstance(tools, Mapping):
                    continue
                for tool_name, tool_block in tools.items():
                    if not isinstance(tool_name, str) or not isinstance(
                        tool_block, Mapping
                    ):
                        continue
                    findings = tool_block.get("findings")
                    if not isinstance(findings, (list, tuple)):
                        continue
                    for index, item in enumerate(findings):
                        pointer = (
                            "static_analysis.json#/agents/"
                            f"{dimension}/tools/{tool_name}/findings/{index}"
                        )
                        records[pointer] = EvidenceRecord(
                            pointer=pointer,
                            file_name="static_analysis.json",
                            kind="static_tool_finding",
                            value=item,
                            dimension=dimension,
                            tool_name=tool_name,
                            index=index,
                        )

        report = artifact_data.test_report_dict()
        for key, value in report.items():
            if not isinstance(key, str) or not key:
                continue
            pointer = f"test_report.json#/{key}"
            records[pointer] = EvidenceRecord(
                pointer=pointer,
                file_name="test_report.json",
                kind="test_report_field",
                value=value,
            )
            if isinstance(value, Mapping):
                for child_key, child_value in value.items():
                    if not isinstance(child_key, str) or not child_key:
                        continue
                    child_pointer = f"{pointer}/{child_key}"
                    records[child_pointer] = EvidenceRecord(
                        pointer=child_pointer,
                        file_name="test_report.json",
                        kind="test_report_field",
                        value=child_value,
                    )
            if key == "records" and isinstance(value, (list, tuple)):
                for index, item in enumerate(value):
                    record_pointer = f"{pointer}/{index}"
                    records[record_pointer] = EvidenceRecord(
                        pointer=record_pointer,
                        file_name="test_report.json",
                        kind="test_record",
                        value=item,
                        index=index,
                    )
        return records


# ----------------------------------------------------------------------
# Validation result


@dataclass(frozen=True)
class EvidenceCheck:
    check_id: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class FindingValidation:
    """单个 Finding 的完整验证结果。"""

    finding: Finding
    status: str
    evidence_kind: EvidenceKind
    checks: tuple[EvidenceCheck, ...]
    reasons: tuple[str, ...]
    false_positive: bool = False
    adjusted: bool = False

    @property
    def rejected(self) -> bool:
        return self.status == STATUS_REJECTED


@dataclass(frozen=True)
class _LocationCheck:
    ok: bool
    reason: str | None
    start_line: int | None = None
    end_line: int | None = None
    adjusted: bool = False


# ----------------------------------------------------------------------
# Validator


class Stage2EvidenceValidator:
    """在固定 commit 工作区与内存 ArtifactData 上执行 V1～V7。"""

    def __init__(
        self,
        *,
        workspace_path: Path,
        allowed_files: Iterable[str],
        artifact_data: ArtifactData,
        rules: ReviewRules,
    ) -> None:
        candidate = Path(workspace_path).expanduser()
        try:
            workspace = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValueError("evidence workspace does not exist") from exc
        if not workspace.is_dir():
            raise ValueError("evidence workspace is not a directory")
        self.workspace = workspace
        self.rules = rules
        if not isinstance(artifact_data, ArtifactData):
            raise TypeError("artifact_data must be an ArtifactData")
        self.artifact_data = artifact_data
        self.registry = EvidenceRegistry.from_artifact_data(artifact_data)
        self.allowed_files = frozenset(self._normalize_allowed(allowed_files))

    # ------------------------------------------------------------------
    # Public API

    def validate(self, finding: Finding) -> FindingValidation:
        if not isinstance(finding, Finding):
            raise TypeError("finding must be a Finding")

        # V1～V6 必须在未脱敏的原始 Finding 上执行：V4 需要原始证据
        # 才能与源码比较，V7 脱敏放在最后，避免改写证据导致误判。
        has_location = (
            finding.file_path is not None
            and finding.start_line is not None
        )
        kind: EvidenceKind = (
            EVENT_CODE_LOCATION if has_location else EVENT_TOOL_REPORT
        )
        checks: list[EvidenceCheck] = []
        reasons: list[str] = []
        false_positive = False

        if has_location:
            status, checks, reasons, sanitized, adjusted = (
                self._validate_code_location(finding, checks, reasons)
            )
        else:
            status, checks, reasons, sanitized, adjusted = (
                self._validate_tool_report(finding, checks, reasons)
            )

        v6_check, is_false_positive = self._check_false_positive(
            sanitized
        )
        checks.append(v6_check)
        if is_false_positive:
            false_positive = True
            if status == STATUS_VERIFIED:
                status = STATUS_UNVERIFIED
                reasons.append(
                    "V6: finding is located in test/example code; "
                    "verification was downgraded"
                )

        # V7：验证完成后再脱敏输出，保证校验依据是原始内容。
        sanitized = self._apply_v7(
            sanitized.model_copy(update={"verification_status": status})
        )

        return FindingValidation(
            finding=sanitized,
            status=status,
            evidence_kind=kind,
            checks=tuple(checks),
            reasons=tuple(reasons),
            false_positive=false_positive,
            adjusted=adjusted,
        )

    # ------------------------------------------------------------------
    # V1～V4

    def _validate_code_location(
        self,
        finding: Finding,
        checks: list[EvidenceCheck],
        reasons: list[str],
    ) -> tuple[str, list[EvidenceCheck], list[str], Finding, bool]:
        assert finding.file_path is not None
        assert finding.start_line is not None
        start_line = finding.start_line
        end_line = finding.end_line or start_line

        path_check = self._check_path(finding.file_path)
        checks.append(path_check)
        if not path_check.passed:
            reasons.append(path_check.detail)
            return STATUS_REJECTED, checks, reasons, finding, False

        file_check = self._check_exists(finding.file_path)
        checks.append(file_check)
        if not file_check.passed:
            reasons.append(file_check.detail)
            return STATUS_REJECTED, checks, reasons, finding, False

        read = self._read_lines(finding.file_path)
        if isinstance(read, str):
            checks.append(EvidenceCheck("V1", False, read))
            reasons.append(read)
            return STATUS_REJECTED, checks, reasons, finding, False
        lines = read
        checks.append(
            EvidenceCheck(
                "V1", True, "file exists and is a regular file"
            )
        )
        checks.append(
            EvidenceCheck("V2", True, "path is safe and inside the workspace")
        )

        range_check = self._check_line_range(start_line, end_line, len(lines))
        checks.append(range_check)
        if not range_check.passed:
            reasons.append(range_check.detail)
            return STATUS_REJECTED, checks, reasons, finding, False

        location = self._check_snippet(
            finding.evidence, lines, start_line, end_line
        )
        if location.ok:
            checks.append(
                EvidenceCheck(
                    "V4",
                    True,
                    location.reason or "code snippet matches the fixed source",
                )
            )
        elif finding.tool_evidence and self._tool_record_substantiates(finding):
            # 确定性工具 Finding 的 evidence 是工具消息而非源码；由同一
            # 位置的真实工具记录佐证，V5 会再次确认工具/文件/行一致性。
            checks.append(
                EvidenceCheck(
                    "V4",
                    True,
                    "evidence matches the raw tool record at the "
                    "reported location",
                )
            )
        else:
            detail = location.reason or "code snippet did not match"
            checks.append(EvidenceCheck("V4", False, detail))
            reasons.append(detail)
            if finding.severity in {"critical", "high"}:
                return STATUS_REJECTED, checks, reasons, finding, False
            return STATUS_UNVERIFIED, checks, reasons, finding, False

        adjusted = location.adjusted and location.ok
        updated = finding
        if location.start_line is not None and location.end_line is not None:
            payload: dict[str, Any] = {"start_line": location.start_line}
            if finding.end_line is not None:
                payload["end_line"] = location.end_line
            updated = finding.model_copy(update=payload)

        if not finding.tool_evidence:
            reasons.append(
                "V5: no tool evidence; the code location alone is "
                "not sufficient for verification"
            )
            return STATUS_UNVERIFIED, checks, reasons, updated, adjusted

        v5_checks, v5_reasons = self._check_tool_evidence(
            updated, has_location=True
        )
        checks.extend(v5_checks)
        if v5_reasons:
            reasons.extend(v5_reasons)
            return STATUS_REJECTED, checks, reasons, updated, adjusted
        return STATUS_VERIFIED, checks, reasons, updated, adjusted

    def _tool_record_substantiates(self, finding: Finding) -> bool:
        """V4 工具佐证：同一位置的真实工具记录包含该证据文本。

        只接受 ``static_analysis.json`` 的工具 Finding 记录；记录必须属于
        同一工具、同一文件且行号范围重叠，并且记录 message 与 Finding 证据
        存在包含关系。工具/规则/行的最终一致性仍由 V5 复核。
        """

        evidence_text = _normalize_text(finding.evidence)
        if not evidence_text:
            return False
        for evidence in finding.tool_evidence:
            record = self.registry.get(evidence.raw_output_ref)
            if record is None or record.kind != "static_tool_finding":
                continue
            if evidence.tool_name != record.tool_name:
                continue
            if not isinstance(record.value, Mapping):
                continue
            raw_path = record.value.get("file_path")
            if isinstance(raw_path, str) and raw_path != finding.file_path:
                continue
            if not _line_overlaps(
                record.value.get("line"), record.value.get("end_line"), finding
            ):
                continue
            message = record.value.get("message")
            if not isinstance(message, str):
                continue
            normalized_message = _normalize_text(message)
            if (
                evidence_text in normalized_message
                or normalized_message in evidence_text
            ):
                return True
        return False

    # ------------------------------------------------------------------
    # V5 only (tool report)

    def _validate_tool_report(
        self,
        finding: Finding,
        checks: list[EvidenceCheck],
        reasons: list[str],
    ) -> tuple[str, list[EvidenceCheck], list[str], Finding, bool]:
        if not finding.tool_evidence:
            checks.append(
                EvidenceCheck(
                    "V5",
                    False,
                    "project-level finding requires tool report evidence",
                )
            )
            reasons.append("project-level finding requires tool report evidence")
            return STATUS_REJECTED, checks, reasons, finding, False

        v5_checks, v5_reasons = self._check_tool_evidence(
            finding, has_location=False
        )
        checks.extend(v5_checks)
        if v5_reasons:
            reasons.extend(v5_reasons)
            return STATUS_REJECTED, checks, reasons, finding, False
        return STATUS_VERIFIED, checks, reasons, finding, False

    # ------------------------------------------------------------------
    # V1/V2 helpers

    def _normalize_allowed(self, allowed_files: Iterable[str]) -> list[str]:
        policy = FileFilterPolicy()
        normalized: list[str] = []
        for index, path in enumerate(allowed_files):
            value = _normalize_repo_path(path)
            if value is None:
                raise ValueError(
                    f"allowed_files[{index}] must be a safe repo-relative path"
                )
            if policy.is_sensitive_path(value):
                continue
            normalized.append(value)
        return normalized

    def _check_path(self, file_path: str) -> EvidenceCheck:
        normalized = _normalize_repo_path(file_path)
        if normalized is None:
            return EvidenceCheck(
                "V2", False, "V2: file_path is not a safe POSIX relative path"
            )
        if normalized not in self.allowed_files:
            return EvidenceCheck(
                "V2", False, "V2: file_path is not in the analyzed file set"
            )
        candidate = self._candidate(normalized)
        if _is_link(candidate):
            return EvidenceCheck(
                "V2", False, "V2: file_path must not be a link"
            )
        return EvidenceCheck("V2", True, "path is safe")

    def _check_exists(self, file_path: str) -> EvidenceCheck:
        candidate = self._candidate(file_path)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return EvidenceCheck("V1", False, "V1: file does not exist")
        if not resolved.is_relative_to(self.workspace):
            return EvidenceCheck(
                "V2",
                False,
                "V2: file_path resolves outside the workspace",
            )
        if _is_link(resolved):
            return EvidenceCheck(
                "V2", False, "V2: file_path must not be a link"
            )
        if not resolved.is_file():
            return EvidenceCheck(
                "V1", False, "V1: file_path is not a regular file"
            )
        return EvidenceCheck("V1", True, "file exists")

    def _candidate(self, file_path: str) -> Path:
        return self.workspace.joinpath(*PurePosixPath(file_path).parts)

    # ------------------------------------------------------------------
    # V3/V4 helpers

    @staticmethod
    def _check_line_range(
        start_line: int, end_line: int, line_count: int
    ) -> EvidenceCheck:
        if start_line < 1 or end_line < start_line:
            return EvidenceCheck(
                "V3", False, "V3: line range is invalid"
            )
        if end_line > line_count:
            return EvidenceCheck(
                "V3",
                False,
                "V3: line range exceeds the file line count",
            )
        return EvidenceCheck("V3", True, "line range is valid")

    def _read_lines(self, file_path: str) -> list[str] | str:
        resolved = self._candidate(file_path).resolve(strict=True)
        try:
            if resolved.stat().st_size > _MAX_FILE_BYTES:
                return "V1: file exceeds the analysis size limit"
            with tokenize.open(resolved) as handle:
                text = handle.read(_MAX_FILE_BYTES + 1)
        except (OSError, SyntaxError, UnicodeDecodeError):
            return "V1: file could not be read as Python source"
        if len(text) > _MAX_FILE_BYTES:
            return "V1: file exceeds the analysis size limit"
        return text.splitlines()

    @staticmethod
    def _check_snippet(
        evidence: str,
        lines: list[str],
        start_line: int,
        end_line: int,
    ) -> _LocationCheck:
        normalized = _normalize_text(evidence)
        if not normalized:
            return _LocationCheck(
                ok=False, reason="V4: evidence has no visible characters"
            )

        excerpt = "\n".join(lines[start_line - 1 : end_line])
        if normalized in _normalize_text(excerpt):
            return _LocationCheck(
                ok=True,
                reason=None,
                start_line=start_line,
                end_line=end_line,
            )

        evidence_line_count = max(1, len(evidence.splitlines()))
        if evidence_line_count > len(lines):
            return _LocationCheck(
                ok=False, reason="V4: evidence is longer than the file"
            )
        lower = max(1, start_line - _EVIDENCE_SEARCH_RADIUS)
        upper = min(
            len(lines) - evidence_line_count + 1,
            start_line + _EVIDENCE_SEARCH_RADIUS,
        )
        matches: list[tuple[int, int]] = []
        for candidate_start in range(lower, upper + 1):
            candidate_end = candidate_start + evidence_line_count - 1
            block = "\n".join(lines[candidate_start - 1 : candidate_end])
            if normalized in _normalize_text(block):
                matches.append((candidate_start, candidate_end))
        if len(matches) == 1:
            adjusted_start, adjusted_end = matches[0]
            return _LocationCheck(
                ok=True,
                reason=None,
                start_line=adjusted_start,
                end_line=adjusted_end,
                adjusted=True,
            )
        if not matches:
            return _LocationCheck(
                ok=False,
                reason=(
                    "V4: evidence snippet was not found near the "
                    "specified line"
                ),
            )
        return _LocationCheck(
            ok=False,
            reason="V4: evidence snippet is ambiguous near the specified line",
        )

    # ------------------------------------------------------------------
    # V5 helpers

    def _check_tool_evidence(
        self,
        finding: Finding,
        *,
        has_location: bool,
    ) -> tuple[list[EvidenceCheck], list[str]]:
        checks: list[EvidenceCheck] = []
        reasons: list[str] = []
        for index, evidence in enumerate(finding.tool_evidence):
            check, detail = self._check_single_evidence(
                finding, evidence, has_location=has_location
            )
            checks.append(
                EvidenceCheck(
                    "V5",
                    check,
                    detail or "tool evidence reference is consistent",
                )
            )
            if not check:
                reasons.append(
                    detail or f"V5: tool evidence #{index} is inconsistent"
                )
        return checks, reasons

    def _check_single_evidence(
        self,
        finding: Finding,
        evidence: ToolEvidence,
        *,
        has_location: bool,
    ) -> tuple[bool, str | None]:
        try:
            record = self.registry.resolve(evidence.raw_output_ref)
        except EvidenceReferenceError as exc:
            return False, f"V5: {exc}"

        if record.kind == "static_tool_finding":
            return self._check_static_record(
                finding, evidence, record, has_location=has_location
            )
        if record.kind == "test_record":
            return self._check_test_record(
                finding, evidence, record, has_location=has_location
            )
        if record.kind == "test_report_field":
            return self._check_test_report_field(finding, record)
        return False, "V5: unsupported evidence reference kind"

    def _check_static_record(
        self,
        finding: Finding,
        evidence: ToolEvidence,
        record: EvidenceRecord,
        *,
        has_location: bool,
    ) -> tuple[bool, str | None]:
        if evidence.tool_name != record.tool_name:
            return False, "V5: tool evidence tool_name does not match the record"
        finding_dimension = _dimension_for_agent(finding.agent_name)
        if (
            record.dimension is not None
            and finding_dimension is not None
            and record.dimension != finding_dimension
        ):
            return (
                False,
                "V5: tool evidence belongs to a different agent dimension",
            )
        if not isinstance(record.value, Mapping):
            return False, "V5: tool evidence record is not a mapping"

        raw_rule = record.value.get("rule_id")
        if (
            evidence.rule_id is not None
            and isinstance(raw_rule, str)
            and raw_rule
            and raw_rule != evidence.rule_id
        ):
            return False, "V5: tool evidence rule_id does not match the record"

        if not has_location:
            return (
                False,
                (
                    "V5: project-level finding must reference test report "
                    "evidence, not a location-bound tool finding"
                ),
            )

        raw_path = record.value.get("file_path")
        if isinstance(raw_path, str) and raw_path != finding.file_path:
            return False, "V5: tool evidence file_path does not match"
        if finding.file_path is None:
            return False, "V5: code-location finding is missing file_path"

        raw_line = record.value.get("line")
        if not _line_overlaps(raw_line, record.value.get("end_line"), finding):
            return False, "V5: tool evidence line does not match"
        return True, None

    def _check_test_record(
        self,
        finding: Finding,
        evidence: ToolEvidence,
        record: EvidenceRecord,
        *,
        has_location: bool,
    ) -> tuple[bool, str | None]:
        if evidence.tool_name not in {"pytest", "coverage", "testing"}:
            return False, "V5: test record must be referenced by a test tool"
        if not isinstance(record.value, Mapping):
            return False, "V5: test record is not a mapping"
        if has_location:
            raw_path = record.value.get("file_path")
            if isinstance(raw_path, str) and raw_path != finding.file_path:
                return False, "V5: test record file_path does not match"
            raw_line = record.value.get("line")
            if not _line_overlaps(
                raw_line, record.value.get("end_line"), finding
            ):
                return False, "V5: test record line does not match"
            return True, None
        return self._check_test_category(finding, record.value)

    def _check_test_report_field(
        self,
        finding: Finding,
        record: EvidenceRecord,
    ) -> tuple[bool, str | None]:
        if finding.file_path is not None:
            return (
                False,
                (
                    "V5: code-location finding must reference a test record, "
                    "not a test report metric"
                ),
            )
        if finding.category in _TESTING_CATEGORIES:
            return self._check_test_category(finding, record.value)
        if record.value is None:
            return False, "V5: tool report evidence resolves to null"
        return True, None

    def _check_test_category(
        self,
        finding: Finding,
        value: Any,
    ) -> tuple[bool, str | None]:
        if finding.category == "low_coverage":
            if not _is_number(value):
                return False, "V5: low_coverage requires a numeric coverage value"
            if not 0 <= float(value) <= 100:
                return False, "V5: coverage value is outside [0, 100]"
            if float(value) >= self.rules.min_coverage_percent:
                return (
                    False,
                    "V5: coverage is not below the configured minimum",
                )
            return True, None
        if finding.category == "test_failure":
            failed = _failed_count(value)
            if failed is None or failed <= 0:
                return False, "V5: test_failure requires a positive failed count"
            return True, None
        if finding.category == "missing_tests":
            total = _total_count(value)
            if total != 0:
                return False, "V5: missing_tests requires zero collected tests"
            return True, None
        if value is None:
            return False, "V5: tool report evidence resolves to null"
        return True, None

    # ------------------------------------------------------------------
    # V6/V7

    @staticmethod
    def _check_false_positive(finding: Finding) -> tuple[EvidenceCheck, bool]:
        if finding.file_path is None:
            return (
                EvidenceCheck(
                    "V6", True, "no file location; false-positive heuristic skipped"
                ),
                False,
            )
        # 测试类 Finding 指向测试文件是正常现象，不按误报降级。
        if (
            finding.agent_name == "TestingAgent"
            or finding.category in _TESTING_CATEGORIES
        ):
            return (
                EvidenceCheck(
                    "V6", True, "testing findings are exempt from the heuristic"
                ),
                False,
            )
        if _is_test_or_example_path(finding.file_path):
            return (
                EvidenceCheck(
                    "V6",
                    False,
                    "finding is located in test/example code",
                ),
                True,
            )
        return EvidenceCheck("V6", True, "no false-positive heuristic matched"), False

    @staticmethod
    def _apply_v7(finding: Finding) -> Finding:
        return finding.model_copy(
            update={
                "title": redact_sensitive_text(
                    finding.title, max_chars=_MAX_TITLE
                ),
                "description": redact_sensitive_text(
                    finding.description, max_chars=_MAX_TEXT
                ),
                "evidence": redact_sensitive_text(
                    finding.evidence, max_chars=_MAX_TEXT
                ),
                "recommendation": redact_sensitive_text(
                    finding.recommendation, max_chars=_MAX_TEXT
                ),
            }
        )


# ----------------------------------------------------------------------
# Module helpers


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _line_overlaps(
    raw_line: Any,
    raw_end_line: Any,
    finding: Finding,
) -> bool:
    if not isinstance(raw_line, int) or isinstance(raw_line, bool):
        raw_line = None
    if not isinstance(raw_end_line, int) or isinstance(raw_end_line, bool):
        raw_end_line = None
    if raw_line is None:
        return finding.start_line is None
    if finding.start_line is None:
        return False
    record_end = raw_end_line if raw_end_line is not None else raw_line
    finding_end = (
        finding.end_line
        if finding.end_line is not None
        else finding.start_line
    )
    return raw_line <= finding_end and finding.start_line <= record_end


def _failed_count(value: Any) -> int | None:
    if isinstance(value, Mapping):
        failed = value.get("failed")
        if isinstance(failed, int) and not isinstance(failed, bool):
            return failed
        outcome = value.get("outcome")
        if isinstance(outcome, str):
            return 1 if outcome in {"failed", "error"} else 0
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _total_count(value: Any) -> int | None:
    if isinstance(value, Mapping):
        total = value.get("total")
        if isinstance(total, int) and not isinstance(total, bool):
            return total
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _is_test_or_example_path(file_path: str) -> bool:
    parts = PurePosixPath(file_path).parts
    if any(part.lower() in _TEST_PATH_PARTS for part in parts[:-1]):
        return True
    name = parts[-1].lower() if parts else ""
    if name == "conftest.py":
        return True
    return (
        name.startswith(("test_", "example_"))
        or name.endswith("_test.py")
    )


_AGENT_DIMENSIONS = {
    "SecurityAgent": "security",
    "QualityAgent": "quality",
    "PerformanceAgent": "performance",
    "TestingAgent": "testing",
}


def _dimension_for_agent(agent_name: str) -> str | None:
    return _AGENT_DIMENSIONS.get(agent_name)
