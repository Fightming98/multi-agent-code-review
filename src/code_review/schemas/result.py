"""Agent 执行结果合同：Finding、ToolEvidence、AgentResult。

对应 docs/task_contracts.md §5、§8。本模块依赖 task.py，不得反向依赖。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .task import ErrorInfo, _require_non_empty

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")

Severity = Literal["critical", "high", "medium", "low", "info"]
VerificationStatus = Literal["unverified", "verified", "rejected"]
ResultStatus = Literal["completed", "failed", "partial"]


class ToolEvidence(BaseModel):
    """工具佐证（docs/task_contracts.md §5.2）。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    rule_id: str | None = None
    tool_version: str | None = None
    raw_output_ref: str

    @field_validator("tool_name", "raw_output_ref")
    @classmethod
    def _required_non_empty(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("rule_id", "tool_version")
    @classmethod
    def _optional_non_empty(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)


class Finding(BaseModel):
    """具体审查发现（docs/task_contracts.md §5.1）。"""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    agent_name: str
    category: str
    severity: Severity
    title: str = Field(max_length=200)
    description: str = Field(max_length=4000)
    file_path: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    evidence: str = Field(max_length=4000)
    tool_evidence: list[ToolEvidence] = Field(default_factory=list)
    recommendation: str
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus = "unverified"
    merged_from: list[str] = Field(default_factory=list)

    @field_validator(
        "finding_id",
        "agent_name",
        "category",
        "title",
        "description",
        "evidence",
        "recommendation",
    )
    @classmethod
    def _required_non_empty(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("file_path")
    @classmethod
    def _relative_posix_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _require_non_empty(value, "file_path")
        if value.startswith("/") or "\\" in value:
            raise ValueError(
                "file_path must be a repo-relative POSIX path"
            )
        if _WINDOWS_DRIVE_RE.match(value):
            raise ValueError("file_path must not contain a drive letter")
        if ".." in PurePosixPath(value).parts:
            raise ValueError("file_path must not contain '..' segments")
        if value in {".", "./"}:
            raise ValueError("file_path must point to a file, not the repo root")
        return value

    @model_validator(mode="after")
    def _check_traceability(self) -> "Finding":
        has_path = self.file_path is not None
        has_line = self.start_line is not None

        # FD-03：file_path 与 start_line 必须同时提供或同时缺省。
        if has_path != has_line:
            raise ValueError(
                "file_path and start_line must be provided together"
            )

        # FD-04：end_line 不得早于 start_line。
        if self.end_line is not None:
            if self.start_line is None:
                raise ValueError("end_line requires start_line")
            if self.end_line < self.start_line:
                raise ValueError("end_line must be >= start_line")

        has_code_evidence = has_path and has_line and bool(self.evidence.strip())
        has_tool_evidence = len(self.tool_evidence) > 0

        # FD-01：至少满足 A 类（代码位置）或 B 类（工具证据）之一。
        if not has_code_evidence and not has_tool_evidence:
            raise ValueError(
                "finding must include a code location or tool evidence"
            )

        # FD-02：critical / high 必须有明确代码位置。
        if self.severity in {"critical", "high"} and not has_code_evidence:
            raise ValueError(
                "critical/high findings require file_path and start_line"
            )

        return self


class AgentResult(BaseModel):
    """Agent 执行结果（docs/task_contracts.md §8.1）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    task_id: str
    parent_task_id: str | None = None
    review_id: str
    agent_name: str
    status: ResultStatus
    commit_sha: str
    score: float | None = Field(default=None, ge=0, le=100)
    findings: list[Finding] = Field(default_factory=list)
    summary: str = Field(max_length=4000)
    execution_time: float = Field(default=0, ge=0)
    error: ErrorInfo | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "schema_version",
        "task_id",
        "review_id",
        "agent_name",
        "summary",
    )
    @classmethod
    def _required_non_empty(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("parent_task_id")
    @classmethod
    def _parent_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, "parent_task_id")

    @field_validator("commit_sha")
    @classmethod
    def _valid_commit_sha(cls, value: str) -> str:
        if not _COMMIT_SHA_RE.match(value):
            raise ValueError(
                "commit_sha must be 40 lowercase hexadecimal characters"
            )
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> "AgentResult":
        # RS-01：completed 不得携带 error。
        if self.status == "completed" and self.error is not None:
            raise ValueError("completed result must not include error")

        # RS-02：failed 必须携带 error，且 score/findings 为空。
        if self.status == "failed":
            if self.error is None:
                raise ValueError("failed result requires error")
            if self.score is not None:
                raise ValueError("failed result must have score = null")
            if self.findings:
                raise ValueError("failed result must have no findings")

        # RS-03：partial 必须说明缺失原因。
        if self.status == "partial" and self.error is None:
            raise ValueError("partial result requires error")

        # RS-06：同一结果内 finding_id 不得重复。
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding_id must be unique within AgentResult")

        # RS-07：Finding 的 agent_name 必须与结果一致。
        for finding in self.findings:
            if finding.agent_name != self.agent_name:
                raise ValueError(
                    "finding.agent_name must match AgentResult.agent_name"
                )

        return self
