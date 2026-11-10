"""阶段 1 专用报告产物模型。

阶段 1 只生成 ``metadata.json``、``static_analysis.json``、``test_report.json``
与 ``report.md`` 四件产物，不生成完整 ``ReviewReport``。本模块定义三份 JSON
产物的 Pydantic 合同，与阶段 0 的 ``schemas/task.py``、``schemas/result.py``、
``schemas/report.py`` 保持独立，不得修改三个核心 Schema。

所有模型使用 ``extra="forbid"``，时间字段必须是带时区的 UTC 时间。产物中
不得包含密钥、令牌或宿主机绝对路径；路径净化由报告生成器统一完成。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from code_review.schemas.result import Finding
from code_review.schemas.task import ErrorInfo

ARTIFACT_SCHEMA_VERSION = "1.0"
STAGE1_AGENT_NAME = "Stage1Analyzer"

_REVIEW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FIXTURE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_REPOSITORY_URL_PREFIX = "https://github.com/"
_FIXTURE_URL_PREFIX = "fixture://"

ToolStatus = Literal[
    "success",
    "findings",
    "partial",
    "timeout",
    "not_found",
    "parse_error",
    "failed",
]
TestStatus = Literal["executed", "not_executed", "timeout", "failed"]
LLMStatus = Literal["completed", "not_configured", "skipped", "timeout", "failed"]
ReviewStatus = Literal["completed", "partial"]


def _require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _require_review_id(value: str) -> str:
    if not _REVIEW_ID_RE.fullmatch(value) or ".." in value:
        raise ValueError(
            "review_id must contain only letters, digits, dot, underscore or "
            "hyphen and must not contain '..'"
        )
    return value


def _require_commit_sha(value: str) -> str:
    if not _COMMIT_SHA_RE.fullmatch(value):
        raise ValueError("commit_sha must be a full 40-character lowercase SHA")
    return value


def _require_repo_path(value: str) -> str:
    if not value or len(value) > 512:
        raise ValueError("path must be a non-empty repository-relative path")
    if (
        "\\" in value
        or "\x00" in value
        or ":" in value
        or value.startswith("/")
        or ".." in value.split("/")
        or value != value.strip()
    ):
        raise ValueError("path must be a safe POSIX repository-relative path")
    return value


class _ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionEnvironmentArtifact(_ArtifactModel):
    """执行环境摘要；不包含主机名、用户名或宿主机路径。"""

    python_version: str = Field(min_length=1, max_length=64)
    python_implementation: str = Field(min_length=1, max_length=64)
    platform_system: str = Field(min_length=1, max_length=64)
    platform_release: str = Field(min_length=1, max_length=128)
    platform_machine: str = Field(min_length=1, max_length=64)


class InventorySummaryArtifact(_ArtifactModel):
    """仓库扫描统计摘要。"""

    total_files: int = Field(ge=0)
    python_source_files: int = Field(ge=0)
    python_test_files: int = Field(ge=0)
    filtered_files: int = Field(ge=0)
    excluded_directories: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    scanned_bytes: int = Field(ge=0)
    total_line_count: int = Field(ge=0)
    is_partial: bool = False
    partial_reason: str | None = None

    @model_validator(mode="after")
    def _validate_partial_reason(self) -> InventorySummaryArtifact:
        if self.is_partial and not self.partial_reason:
            raise ValueError("partial_reason is required when is_partial is true")
        if not self.is_partial and self.partial_reason is not None:
            raise ValueError("partial_reason must be null when is_partial is false")
        return self


class MetadataArtifact(_ArtifactModel):
    """``metadata.json`` 的合同。

    普通审查记录 GitHub 仓库与固定 Commit SHA；项目自维护可信 Fixture 的
    受控验收使用 ``fixture://<name>``，此时不伪造 Git Commit，而以 Fixture
    清单 SHA-256 作为内容快照标识。
    """

    schema_version: Literal["1.0"] = ARTIFACT_SCHEMA_VERSION
    stage: Literal["stage_1"] = "stage_1"
    source_type: Literal["github_repository", "trusted_fixture"] = (
        "github_repository"
    )
    review_id: str = Field(min_length=1, max_length=128)
    repository_url: str = Field(min_length=1, max_length=2048)
    repository_name: str = Field(min_length=1, max_length=512)
    branch: str = Field(min_length=1, max_length=255)
    commit_sha: str | None = None
    fixture_manifest_sha256: str | None = None
    review_status: ReviewStatus
    reviewed_at: datetime
    project_language: Literal["python"] = "python"
    discovered_file_count: int = Field(ge=0)
    analyzed_file_count: int = Field(ge=0)
    tool_versions: dict[str, str | None] = Field(default_factory=dict)
    execution_environment: ExecutionEnvironmentArtifact
    inventory: InventorySummaryArtifact | None = None
    review_duration_seconds: float = Field(ge=0)

    @field_validator("review_id")
    @classmethod
    def _validate_review_id(cls, value: str) -> str:
        return _require_review_id(value)

    @field_validator("reviewed_at")
    @classmethod
    def _validate_reviewed_at(cls, value: datetime) -> datetime:
        return _require_utc(value, "reviewed_at")

    @model_validator(mode="after")
    def _validate_source(self) -> MetadataArtifact:
        if self.source_type == "github_repository":
            if not self.repository_url.startswith(_REPOSITORY_URL_PREFIX):
                raise ValueError(
                    "repository_url must be an https://github.com URL"
                )
            if "@" in self.repository_url.split("/", 3)[2]:
                raise ValueError("repository_url must not contain credentials")
            if self.commit_sha is None:
                raise ValueError(
                    "commit_sha is required for a GitHub repository review"
                )
            _require_commit_sha(self.commit_sha)
            if self.fixture_manifest_sha256 is not None:
                raise ValueError(
                    "fixture_manifest_sha256 is only valid for a trusted fixture"
                )
        else:
            if not _FIXTURE_NAME_RE.fullmatch(self.repository_name):
                raise ValueError(
                    "trusted fixture repository_name must be a fixture name"
                )
            if self.repository_url != f"{_FIXTURE_URL_PREFIX}{self.repository_name}":
                raise ValueError(
                    "trusted fixture repository_url must be fixture://<name>"
                )
            if self.commit_sha is not None:
                raise ValueError(
                    "trusted fixture review must not claim a Git commit SHA"
                )
            if (
                self.fixture_manifest_sha256 is None
                or not _SHA256_RE.fullmatch(self.fixture_manifest_sha256)
            ):
                raise ValueError(
                    "fixture_manifest_sha256 is required for a trusted fixture"
                )
        return self


class RawToolFindingArtifact(_ArtifactModel):
    """工具原始 Finding，与解析后的合同 Finding 明确区分。"""

    tool_name: str = Field(min_length=1, max_length=64)
    rule_id: str | None = None
    file_path: str
    message: str
    line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    severity: str | None = None
    confidence: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str) -> str:
        return _require_repo_path(value)


class ToolRunArtifact(_ArtifactModel):
    """单个静态分析工具的真实执行记录。"""

    tool_name: str = Field(min_length=1, max_length=64)
    tool_version: str | None = None
    execution_status: ToolStatus
    exit_code: int | None = None
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0)
    analyzed_file_count: int = Field(ge=0)
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    findings_truncated: bool = False
    findings: list[RawToolFindingArtifact] = Field(default_factory=list)
    finding_count: int = Field(ge=0)
    error: ErrorInfo | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def _validate_timestamps(cls, value: datetime, info: Any) -> datetime:
        return _require_utc(value, info.field_name)


class TestReferenceEntryArtifact(_ArtifactModel):
    """``static_analysis.json#/tests/pytest`` 的摘要。"""

    execution_status: Literal["executed", "not_executed", "failed"]
    passed: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    skipped: int | None = Field(default=None, ge=0)
    coverage: float | None = Field(default=None, ge=0, le=100)
    source: str | None = None
    reason: str | None = None


class TestReferenceArtifact(_ArtifactModel):
    """测试结果在静态分析产物中的引用点。"""

    pytest: TestReferenceEntryArtifact


class StaticAnalysisStatisticsArtifact(_ArtifactModel):
    """确定性聚合与 LLM 合并后的统计。"""

    source_finding_count: int = Field(ge=0)
    mapped_finding_count: int = Field(ge=0)
    deterministic_finding_count: int = Field(ge=0)
    final_finding_count: int = Field(ge=0)
    semantic_finding_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    skipped_finding_count: int = Field(ge=0)
    test_failure_finding_count: int = Field(ge=0)
    tool_failure_count: int = Field(ge=0)
    partial_tool_count: int = Field(ge=0)
    severity_counts: dict[str, int] = Field(default_factory=dict)
    category_counts: dict[str, int] = Field(default_factory=dict)

    @field_validator("severity_counts", "category_counts")
    @classmethod
    def _validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("finding counts must be non-negative")
        return value


class LLMAcceptedProposalArtifact(_ArtifactModel):
    finding_id: str = Field(min_length=1, max_length=128)
    proposal_index: int = Field(ge=0)
    source: Literal["tool_explanation", "semantic_supplement"]
    related_finding_id: str | None = None
    merged: bool = False


class LLMRejectedProposalArtifact(_ArtifactModel):
    """不合格的 LLM 提案；只记录安全原因与必要定位信息。"""

    proposal_index: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)
    kind: str | None = None
    category: str | None = None
    title: str | None = None
    file_path: str | None = None
    start_line: int | None = Field(default=None, ge=1)

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_repo_path(value)


class LLMExplanationArtifact(_ArtifactModel):
    related_finding_id: str = Field(min_length=1, max_length=128)
    proposal_index: int = Field(ge=0)
    description: str = Field(min_length=1, max_length=4000)


class LLMAnalysisArtifact(_ArtifactModel):
    """LLM 辅助分析的来源记录，位于 ``static_analysis.json``。"""

    status: LLMStatus
    model: str | None = None
    usage: dict[str, int] | None = None
    duration_ms: int = Field(default=0, ge=0)
    call_count: int = Field(default=0, ge=0)
    input_chars: int = Field(default=0, ge=0)
    proposal_count: int = Field(default=0, ge=0)
    dropped_proposal_count: int = Field(default=0, ge=0)
    context_finding_count: int = Field(default=0, ge=0)
    context_snippet_count: int = Field(default=0, ge=0)
    input_truncated: bool = False
    output_truncated: bool = False
    reason: str | None = None
    accepted: list[LLMAcceptedProposalArtifact] = Field(default_factory=list)
    rejected: list[LLMRejectedProposalArtifact] = Field(default_factory=list)
    explanations: list[LLMExplanationArtifact] = Field(default_factory=list)

    @field_validator("usage")
    @classmethod
    def _validate_usage(
        cls, value: dict[str, int] | None
    ) -> dict[str, int] | None:
        if value is not None and any(count < 0 for count in value.values()):
            raise ValueError("LLM usage values must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_reason(self) -> LLMAnalysisArtifact:
        if self.status in {"not_configured", "timeout", "failed"} and not self.reason:
            raise ValueError(f"reason is required when LLM status is {self.status}")
        return self


class ErrorSummaryArtifact(_ArtifactModel):
    """工具、测试、LLM 或扫描阶段的可读错误摘要。"""

    source: str = Field(min_length=1, max_length=64)
    error_type: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False


class StaticAnalysisArtifact(_ArtifactModel):
    """``static_analysis.json`` 的合同。"""

    schema_version: Literal["1.0"] = ARTIFACT_SCHEMA_VERSION
    review_id: str = Field(min_length=1, max_length=128)
    commit_sha: str | None = None
    generated_at: datetime
    tools: dict[str, ToolRunArtifact] = Field(min_length=1)
    tests: TestReferenceArtifact
    findings: list[Finding] = Field(default_factory=list)
    statistics: StaticAnalysisStatisticsArtifact
    llm_analysis: LLMAnalysisArtifact
    warnings: list[str] = Field(default_factory=list)
    error_summary: list[ErrorSummaryArtifact] = Field(default_factory=list)

    @field_validator("review_id")
    @classmethod
    def _validate_review_id(cls, value: str) -> str:
        return _require_review_id(value)

    @field_validator("commit_sha")
    @classmethod
    def _validate_commit_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_commit_sha(value)

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        return _require_utc(value, "generated_at")

    @model_validator(mode="after")
    def _validate_stage1_findings(self) -> StaticAnalysisArtifact:
        for finding in self.findings:
            if finding.agent_name != STAGE1_AGENT_NAME:
                raise ValueError(
                    "stage 1 findings must use agent_name Stage1Analyzer"
                )
            if finding.verification_status != "unverified":
                raise ValueError(
                    "stage 1 findings must remain unverified"
                )
        return self


class TestCountsArtifact(_ArtifactModel):
    collected: int | None = Field(default=None, ge=0)
    passed: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    skipped: int | None = Field(default=None, ge=0)
    errors: int | None = Field(default=None, ge=0)
    errors_complete: bool = True


class CoverageFileArtifact(_ArtifactModel):
    file_path: str
    percent_covered: float = Field(ge=0, le=100)
    covered_lines: int = Field(ge=0)
    num_statements: int = Field(ge=0)
    missing_lines: list[int] = Field(default_factory=list)

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str) -> str:
        return _require_repo_path(value)


class CoverageArtifact(_ArtifactModel):
    percent_covered: float | None = Field(default=None, ge=0, le=100)
    files: list[CoverageFileArtifact] = Field(default_factory=list)
    files_truncated: bool = False


class FixtureArtifact(_ArtifactModel):
    name: str = Field(min_length=1, max_length=64)
    version: str | None = None
    manifest_sha256: str | None = None

    @field_validator("manifest_sha256")
    @classmethod
    def _validate_manifest_sha256(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256_RE.fullmatch(value):
            raise ValueError("manifest_sha256 must be a 64-character SHA-256")
        return value


class TestRecordArtifact(_ArtifactModel):
    name: str = Field(min_length=1, max_length=512)
    outcome: Literal["passed", "failed", "error", "skipped"]
    file_path: str | None = None
    line: int | None = Field(default=None, ge=1)
    duration_seconds: float | None = Field(default=None, ge=0)
    message: str | None = None

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_repo_path(value)


class TestReportArtifact(_ArtifactModel):
    """``test_report.json`` 的合同。

    ``not_executed`` 时所有计数与覆盖率必须为 ``null`` 且必须给出原因；
    Pytest / Coverage 超时记为 ``timeout``（失败语义），不得伪装为
    ``not_executed``。
    """

    schema_version: Literal["1.0"] = ARTIFACT_SCHEMA_VERSION
    review_id: str = Field(min_length=1, max_length=128)
    commit_sha: str | None = None
    generated_at: datetime
    execution_status: TestStatus
    data_source: Literal["trusted_fixture", "external_repository"]
    trusted_fixture: bool
    fixture: FixtureArtifact | None = None
    counts: TestCountsArtifact
    coverage: CoverageArtifact
    reason: str | None = None
    tool_versions: dict[str, str | None] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = Field(ge=0)
    test_duration_seconds: float | None = Field(default=None, ge=0)
    exit_code: int | None = None
    coverage_exit_code: int | None = None
    read_only_verified: bool | None = None
    modified_paths: list[str] = Field(default_factory=list)
    records: list[TestRecordArtifact] = Field(default_factory=list)
    records_truncated: bool = False
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    error: ErrorInfo | None = None

    @field_validator("review_id")
    @classmethod
    def _validate_review_id(cls, value: str) -> str:
        return _require_review_id(value)

    @field_validator("commit_sha")
    @classmethod
    def _validate_commit_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_commit_sha(value)

    @field_validator("generated_at", "started_at", "finished_at")
    @classmethod
    def _validate_timestamps(
        cls, value: datetime | None, info: Any
    ) -> datetime | None:
        if value is None:
            return None
        return _require_utc(value, info.field_name)

    @field_validator("modified_paths")
    @classmethod
    def _validate_modified_paths(cls, value: list[str]) -> list[str]:
        return [_require_repo_path(item) for item in value]

    @model_validator(mode="after")
    def _validate_semantics(self) -> TestReportArtifact:
        if self.trusted_fixture != (self.data_source == "trusted_fixture"):
            raise ValueError(
                "trusted_fixture must match data_source"
            )
        if not self.trusted_fixture and self.commit_sha is None:
            raise ValueError(
                "commit_sha is required for an external repository test report"
            )
        if self.trusted_fixture and self.fixture is None:
            raise ValueError("fixture metadata is required for a trusted fixture")
        if self.execution_status == "not_executed":
            counts = (
                self.counts.collected,
                self.counts.passed,
                self.counts.failed,
                self.counts.skipped,
                self.counts.errors,
            )
            if any(value is not None for value in counts):
                raise ValueError(
                    "not_executed tests must not report counts"
                )
            if self.coverage.percent_covered is not None:
                raise ValueError(
                    "not_executed tests must not report coverage"
                )
            if not self.reason:
                raise ValueError("not_executed tests must include a reason")
        elif self.execution_status == "executed":
            required = (
                self.counts.collected,
                self.counts.passed,
                self.counts.failed,
                self.counts.skipped,
                self.counts.errors,
            )
            if any(value is None for value in required):
                raise ValueError("executed tests must report all counts")
            if self.coverage.percent_covered is None:
                raise ValueError("executed tests must report coverage")
        else:
            if not self.reason and self.error is None:
                raise ValueError(
                    "failed or timed out tests must include a reason or error"
                )
        return self
