"""Stage 2 五件产物的补充合同。

Stage 1 的三份结构化产物模型固定在 ``artifact_models.py``，其中
``MetadataArtifact.stage`` 为 ``Literal["stage_1"]``，且可信 Fixture 不允许
携带 Git Commit SHA。Stage 2 的工作流同时满足以下两点：

- ``metadata.json`` 必须标记为 Stage 2；
- Stage 2 自有 Fixture 由真实临时 Git 仓库构建，必须记录真实 commit SHA。

因此本模块单独定义 Stage 2 的 ``metadata.json`` 合同，并复用 Stage 1 的
``ExecutionEnvironmentArtifact`` / ``InventorySummaryArtifact``。另外两份模型
（``static_analysis.json`` / ``test_report.json``）只做结构校验，内容必须
来自 ``ArtifactData`` 的同一份内存快照，不得重新拼装。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from code_review.reporting.artifact_models import (
    ARTIFACT_SCHEMA_VERSION,
    ExecutionEnvironmentArtifact,
    InventorySummaryArtifact,
    ReviewStatus,
)

__all__ = [
    "STAGE2_CORE_DIMENSIONS",
    "Stage2MetadataArtifact",
    "Stage2StaticAnalysisArtifact",
    "Stage2TestReportArtifact",
]

STAGE2_CORE_DIMENSIONS: frozenset[str] = frozenset(
    {"security", "quality", "performance", "testing"}
)

_REVIEW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FIXTURE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_REPOSITORY_URL_PREFIX = "https://github.com/"
_FIXTURE_URL_PREFIX = "fixture://"


def _require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


class _Stage2Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Stage2MetadataArtifact(_Stage2Model):
    """``metadata.json`` 的 Stage 2 合同。

    GitHub 仓库与 Stage 2 自有 Fixture 都必须有固定的 40 位小写 Git SHA。
    Fixture 的 ``repository_url`` 固定为 ``fixture://<name>``，清单 SHA-256
    可选，仅用于记录内容快照，不冒充 Git Commit。
    """

    schema_version: Literal["1.0"] = ARTIFACT_SCHEMA_VERSION
    stage: Literal["stage_2"] = "stage_2"
    source_type: Literal["github_repository", "trusted_fixture"]
    review_id: str = Field(min_length=1, max_length=128)
    repository_url: str = Field(min_length=1, max_length=2048)
    repository_name: str = Field(min_length=1, max_length=512)
    branch: str = Field(min_length=1, max_length=255)
    commit_sha: str
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
    warnings: list[str] = Field(default_factory=list)

    @field_validator("review_id")
    @classmethod
    def _validate_review_id(cls, value: str) -> str:
        if not _REVIEW_ID_RE.fullmatch(value) or ".." in value:
            raise ValueError(
                "review_id must contain only letters, digits, dot, underscore "
                "or hyphen and must not contain '..'"
            )
        return value

    @field_validator("reviewed_at")
    @classmethod
    def _validate_reviewed_at(cls, value: datetime) -> datetime:
        return _require_utc(value, "reviewed_at")

    @model_validator(mode="after")
    def _validate_source(self) -> Stage2MetadataArtifact:
        if not _COMMIT_SHA_RE.fullmatch(self.commit_sha):
            raise ValueError(
                "commit_sha must be a full 40-character lowercase SHA"
            )
        if self.fixture_manifest_sha256 is not None and not _SHA256_RE.fullmatch(
            self.fixture_manifest_sha256
        ):
            raise ValueError(
                "fixture_manifest_sha256 must be 64 lowercase hex characters"
            )

        if self.source_type == "github_repository":
            if not self.repository_url.startswith(_REPOSITORY_URL_PREFIX):
                raise ValueError(
                    "repository_url must be an https://github.com URL"
                )
            if "@" in self.repository_url.split("/", 3)[2]:
                raise ValueError("repository_url must not contain credentials")
            if self.fixture_manifest_sha256 is not None:
                raise ValueError(
                    "fixture_manifest_sha256 is only valid for a trusted fixture"
                )
        else:
            if not _FIXTURE_NAME_RE.fullmatch(self.repository_name):
                raise ValueError(
                    "trusted fixture repository_name must be a fixture name"
                )
            if self.repository_url != (
                f"{_FIXTURE_URL_PREFIX}{self.repository_name}"
            ):
                raise ValueError(
                    "trusted fixture repository_url must be fixture://<name>"
                )
        return self


class Stage2StaticAnalysisArtifact(_Stage2Model):
    """``static_analysis.json`` 的结构封装。

    ``agents`` 必须原样来自 ``ArtifactData.static_analysis``；本模型不复制
    或补造工具证据，只校验四个核心维度齐全。
    """

    schema_version: Literal["1.0"] = ARTIFACT_SCHEMA_VERSION
    agents: dict[str, dict[str, Any]]

    @field_validator("agents")
    @classmethod
    def _validate_agents(
        cls, value: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        if set(value) != STAGE2_CORE_DIMENSIONS:
            raise ValueError(
                "static_analysis agents must contain exactly the four core "
                "dimensions"
            )
        return value


class Stage2TestReportArtifact(_Stage2Model):
    """``test_report.json`` 的结构封装。

    字段集合与 Manager Aggregate 的 ``test_report`` 证据块一致；数值必须
    原样来自 ``ArtifactData``，不得估算或伪造。缺失的可选字段使用中性默认
    值，避免测试证据块因 Stage 2.2 的早期构造方式而失败。
    """

    schema_version: Literal["1.0"] = ARTIFACT_SCHEMA_VERSION
    execution_status: Literal["executed", "not_executed", "failed"]
    reason: str | None = None
    counts: dict[str, int | None] = Field(default_factory=dict)
    coverage: float | None = Field(default=None, ge=0, le=100)
    source: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    fixture: dict[str, Any] | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    records_truncated: bool = False
    coverage_files: list[dict[str, Any]] = Field(default_factory=list)
    coverage_files_truncated: bool = False
    tool_versions: dict[str, str | None] = Field(default_factory=dict)
    read_only_verified: bool | None = None
    modified_paths: list[str] = Field(default_factory=list)
    exit_code: int | None = None
    coverage_exit_code: int | None = None
    warnings: list[str] = Field(default_factory=list)
    agent_name: str = Field(default="TestingAgent", min_length=1, max_length=64)
    result_status: Literal["completed", "partial", "failed"] = "completed"
