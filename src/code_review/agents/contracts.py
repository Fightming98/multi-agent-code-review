"""Stage 2 Agent 内部合同与内存证据结构。

这些类型是 Agent/Graph 的内部 DTO，不替代冻结的 Pydantic Schema。
外部可见结果仍必须转换为 ``AgentTask``/``AgentResult``/``Finding`` 等合同模型。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from code_review.schemas.result import AgentResult
from code_review.schemas.task import AgentTask
from config.review_rules import ReviewRules

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TIMING_STATUSES = frozenset({"completed", "partial", "failed"})


class ArtifactPointerError(ValueError):
    """ArtifactData 无法解析给定 JSON Pointer。"""


class ContractValidationError(ValueError):
    """内部 DTO 不符合 Stage 2 合同。"""


def _freeze_json(value: Any, path: str = "$") -> Any:
    """递归冻结 JSON 数据，避免 Worker/Reviewer/报告生成器共享可变对象。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(f"{path} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ContractValidationError(
                    f"{path} keys must be non-empty strings"
                )
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise ContractValidationError(
        f"{path} contains a non-JSON-serializable value: "
        f"{type(value).__name__}"
    )


def _thaw_json(value: Any) -> Any:
    """将冻结的内部结构复制为普通 JSON 数据。"""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_nonempty_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _validate_repo_path(value: str, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{path} must be a non-empty path")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or value.startswith(("/", "./"))
        or re.match(r"^[A-Za-z]:", value) is not None
        or "\\" in value
        or ".." in candidate.parts
        or str(candidate) in {"", "."}
    ):
        raise ContractValidationError(
            f"{path} must be a safe repo-relative POSIX path"
        )
    return candidate.as_posix()


@dataclass(frozen=True)
class UsageSummary:
    """Agent 调用次数与真实 Token 汇总，不冒充冻结的 CostSummary。"""

    llm_calls: int = 0
    reported_usage_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        values = {
            "llm_calls": self.llm_calls,
            "reported_usage_calls": self.reported_usage_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(
                    f"UsageSummary.{name} must be a non-negative integer"
                )
        if self.reported_usage_calls > self.llm_calls:
            raise ContractValidationError(
                "reported_usage_calls cannot exceed llm_calls"
            )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: UsageSummary) -> UsageSummary:
        if not isinstance(other, UsageSummary):
            return NotImplemented
        return UsageSummary(
            llm_calls=self.llm_calls + other.llm_calls,
            reported_usage_calls=(
                self.reported_usage_calls + other.reported_usage_calls
            ),
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True)
class WorkerRuntime:
    """Worker 执行所需的最小只读上下文。"""

    workspace_path: Path
    allowed_files: tuple[str, ...]
    commit_sha: str
    language: str
    review_id: str
    rules: ReviewRules
    trace_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_path, Path):
            try:
                object.__setattr__(
                    self, "workspace_path", Path(self.workspace_path)
                )
            except TypeError as exc:
                raise ContractValidationError(
                    "WorkerRuntime.workspace_path is invalid"
                ) from exc
        if isinstance(self.allowed_files, str):
            raise ContractValidationError(
                "WorkerRuntime.allowed_files must be a sequence of paths"
            )
        object.__setattr__(
            self,
            "allowed_files",
            tuple(
                _validate_repo_path(path, f"allowed_files[{index}]")
                for index, path in enumerate(self.allowed_files)
            ),
        )
        if not _COMMIT_SHA_RE.fullmatch(str(self.commit_sha)):
            raise ContractValidationError(
                "WorkerRuntime.commit_sha must be 40 lowercase hex characters"
            )
        _require_nonempty_str(self.language, "WorkerRuntime.language")
        _require_nonempty_str(self.review_id, "WorkerRuntime.review_id")
        if not isinstance(self.rules, ReviewRules):
            raise ContractValidationError("WorkerRuntime.rules is invalid")
        if self.trace_id is not None:
            _require_nonempty_str(self.trace_id, "WorkerRuntime.trace_id")


@dataclass(frozen=True)
class WorkerDispatch:
    """Send Fan-out 传给单个 Worker 的最小有效载荷。"""

    task: AgentTask
    runtime: WorkerRuntime

    def __post_init__(self) -> None:
        if not isinstance(self.task, AgentTask):
            raise ContractValidationError("WorkerDispatch.task is invalid")
        if not isinstance(self.runtime, WorkerRuntime):
            raise ContractValidationError("WorkerDispatch.runtime is invalid")


@dataclass(frozen=True)
class WorkerEvidence:
    """Worker 返回的规范化证据；由 Manager Aggregate 汇总为 ArtifactData。"""

    agent_name: str
    static_analysis: Mapping[str, Any] = field(default_factory=dict)
    test_report: Mapping[str, Any] | None = None
    usage: UsageSummary = field(default_factory=UsageSummary)
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty_str(self.agent_name, "WorkerEvidence.agent_name")
        if not isinstance(self.static_analysis, Mapping):
            raise ContractValidationError(
                "WorkerEvidence.static_analysis must be a mapping"
            )
        object.__setattr__(
            self,
            "static_analysis",
            _freeze_json(self.static_analysis, "static_analysis"),
        )
        if self.test_report is not None:
            if not isinstance(self.test_report, Mapping):
                raise ContractValidationError(
                    "WorkerEvidence.test_report must be a mapping or None"
                )
            object.__setattr__(
                self,
                "test_report",
                _freeze_json(self.test_report, "test_report"),
            )
        if not isinstance(self.usage, UsageSummary):
            raise ContractValidationError("WorkerEvidence.usage is invalid")
        object.__setattr__(
            self,
            "warnings",
            tuple(
                _require_nonempty_str(item, "WorkerEvidence.warnings[]")
                for item in self.warnings
            ),
        )


@dataclass(frozen=True)
class WorkerTiming:
    """单个 Worker 的可观测时间窗口。"""

    agent_name: str
    task_id: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    status: str

    def __post_init__(self) -> None:
        _require_nonempty_str(self.agent_name, "WorkerTiming.agent_name")
        _require_nonempty_str(self.task_id, "WorkerTiming.task_id")
        if not isinstance(self.started_at, datetime) or not isinstance(
            self.finished_at, datetime
        ):
            raise ContractValidationError("WorkerTiming timestamps are invalid")
        if self.finished_at < self.started_at:
            raise ContractValidationError(
                "WorkerTiming.finished_at cannot precede started_at"
            )
        if (
            isinstance(self.duration_seconds, bool)
            or not isinstance(self.duration_seconds, (int, float))
            or self.duration_seconds < 0
        ):
            raise ContractValidationError(
                "WorkerTiming.duration_seconds must be non-negative"
            )
        object.__setattr__(
            self, "duration_seconds", float(self.duration_seconds)
        )
        if self.status not in _TIMING_STATUSES:
            raise ContractValidationError(
                "WorkerTiming.status must be completed/partial/failed"
            )


@dataclass(frozen=True)
class AgentRunOutput:
    """子类 ``_run`` 的返回值，由 BaseAgent 补充任务终态和 timing。"""

    result: AgentResult
    evidence: WorkerEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.result, AgentResult):
            raise ContractValidationError("AgentRunOutput.result is invalid")
        if not isinstance(self.evidence, WorkerEvidence):
            raise ContractValidationError("AgentRunOutput.evidence is invalid")


@dataclass(frozen=True)
class AgentExecution:
    """BaseAgent.execute 的完整内部返回值。"""

    task: AgentTask
    result: AgentResult
    evidence: WorkerEvidence
    timing: WorkerTiming

    def __post_init__(self) -> None:
        if not isinstance(self.task, AgentTask):
            raise ContractValidationError("AgentExecution.task is invalid")
        if not isinstance(self.result, AgentResult):
            raise ContractValidationError("AgentExecution.result is invalid")
        if not isinstance(self.evidence, WorkerEvidence):
            raise ContractValidationError("AgentExecution.evidence is invalid")
        if not isinstance(self.timing, WorkerTiming):
            raise ContractValidationError("AgentExecution.timing is invalid")


@dataclass(frozen=True)
class ArtifactData:
    """Final Reviewer 与报告生成器共用的只读内存证据快照。

    JSON Pointer 采用未来报告文件名作为前缀，例如::

        static_analysis.json#/agents/security/tools/bandit/findings/0
        test_report.json#/coverage

    ``resolve`` 只解析当前内存对象，不读取磁盘文件。报告生成器必须将该对象
    的同一份内容写入文件，保证内存与落盘后的 Pointer 一致。
    """

    static_analysis: Mapping[str, Any] = field(default_factory=dict)
    test_report: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.static_analysis, Mapping):
            raise ContractValidationError(
                "ArtifactData.static_analysis must be a mapping"
            )
        if not isinstance(self.test_report, Mapping):
            raise ContractValidationError(
                "ArtifactData.test_report must be a mapping"
            )
        object.__setattr__(
            self,
            "static_analysis",
            _freeze_json(self.static_analysis, "static_analysis"),
        )
        object.__setattr__(
            self,
            "test_report",
            _freeze_json(self.test_report, "test_report"),
        )

    def resolve(self, pointer: str) -> Any:
        """在内存 ArtifactData 上解析稳定 JSON Pointer。"""
        if not isinstance(pointer, str) or "#" not in pointer:
            raise ArtifactPointerError("artifact pointer must contain '#'")
        file_name, fragment = pointer.split("#", 1)
        if file_name == "static_analysis.json":
            node: Any = self.static_analysis
        elif file_name == "test_report.json":
            node = self.test_report
        else:
            raise ArtifactPointerError(
                "artifact pointer must target static_analysis.json or "
                "test_report.json"
            )

        if fragment == "":
            return _thaw_json(node)
        if not fragment.startswith("/"):
            raise ArtifactPointerError(
                "artifact pointer fragment must start with '/'"
            )

        for raw_token in fragment[1:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, Mapping):
                if token not in node:
                    raise ArtifactPointerError(
                        f"artifact pointer key not found: {token}"
                    )
                node = node[token]
                continue
            if isinstance(node, tuple):
                if (
                    not token.isdigit()
                    or (len(token) > 1 and token.startswith("0"))
                ):
                    raise ArtifactPointerError(
                        f"artifact pointer array index is invalid: {token}"
                    )
                index = int(token)
                if index >= len(node):
                    raise ArtifactPointerError(
                        f"artifact pointer array index out of range: {token}"
                    )
                node = node[index]
                continue
            raise ArtifactPointerError(
                "artifact pointer traverses a non-container value"
            )
        return _thaw_json(node)

    def static_analysis_dict(self) -> dict[str, Any]:
        return _thaw_json(self.static_analysis)

    def test_report_dict(self) -> dict[str, Any]:
        return _thaw_json(self.test_report)


@runtime_checkable
class CompletionLike(Protocol):
    """结构化 LLM completion 协议；真实客户端无需继承。"""

    content: str
    finish_reason: str | None
    usage: Mapping[str, int] | None


class LLMClientProtocol(Protocol):
    """已存在 OpenAICompatibleClient 的结构化适配接口。"""

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float,
        timeout_seconds: float,
    ) -> CompletionLike: ...
