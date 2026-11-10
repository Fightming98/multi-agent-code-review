"""静态分析工具的统一接口、结果模型与公共执行辅助。

``AnalysisTool`` 是 Ruff / Bandit / Radon 的共同抽象；``ToolExecutionResult``
保留工具版本、执行状态、退出码、耗时、原始输出、结构化发现与错误信息。
工具失败只影响自身结果，不会清空其他工具的结果。
"""

from __future__ import annotations

import sys
import tempfile
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import ClassVar

from code_review.schemas.task import ErrorInfo
from config.settings import Settings

from .process_runner import ProcessResult, ProcessStatus, run_process

_MAX_COMMAND_CHARS = 24_000
_DEFAULT_COMMAND_RESERVE = 300

ProcessRunner = Callable[..., ProcessResult]


class ToolOutputParseError(ValueError):
    """工具输出无法解析为内部结构化结果。"""


class ToolInputError(ValueError):
    """工具输入路径不安全或不符合约定。"""


def relative_posix_path(workspace: Path, emitted: str) -> str:
    """把工具输出中的文件路径规范为仓库相对 POSIX 路径。

    工具进程使用仓库外的工作目录，因此输出可能是绝对路径；无论输入形态，
    结果都必须落在工作区内，否则视为不可信输出。
    """

    if not isinstance(emitted, str) or not emitted.strip():
        raise ToolOutputParseError("tool output path is not a valid file path")
    candidate = Path(emitted)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise ToolOutputParseError(
            "tool output path is not a valid file path"
        ) from exc
    try:
        relative = resolved.relative_to(workspace)
    except ValueError as exc:
        raise ToolOutputParseError(
            "tool output path escapes the workspace"
        ) from exc
    return PurePosixPath(*relative.parts).as_posix()


class ToolExecutionStatus(StrEnum):
    """工具执行状态。

    - ``success``：工具正常执行，未报告问题；
    - ``findings``：工具正常执行并报告了问题；
    - ``partial``：工具执行完成但部分文件分析失败或输出不完整；
    - ``timeout`` / ``not_found`` / ``parse_error`` / ``failed``：执行异常。
    """

    SUCCESS = "success"
    FINDINGS = "findings"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    PARSE_ERROR = "parse_error"
    FAILED = "failed"


@dataclass(frozen=True)
class ToolFinding:
    """工具自身的结构化发现。

    这是工具层 DTO，不是 ``docs/task_contracts.md`` 中的正式 ``Finding``；
    Stage 1.5 负责将其映射为合同对象。``severity`` / ``confidence`` 保留
    工具原始取值，不做未经裁定的归一化。
    """

    tool_name: str
    rule_id: str | None
    file_path: str
    message: str
    line: int | None = None
    end_line: int | None = None
    column: int | None = None
    severity: str | None = None
    confidence: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        path = PurePosixPath(self.file_path)
        if (
            not self.file_path
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in self.file_path
        ):
            raise ValueError("file_path must be a relative POSIX path")
        if not self.message.strip():
            raise ValueError("message must not be empty")
        if self.line is not None and self.line < 1:
            raise ValueError("line must be positive")
        if (
            self.line is not None
            and self.end_line is not None
            and self.end_line < self.line
        ):
            raise ValueError("end_line must be >= line")


@dataclass(frozen=True)
class ToolExecutionResult:
    """一次工具执行的完整结果。"""

    tool_name: str
    tool_version: str | None
    execution_status: ToolExecutionStatus
    exit_code: int | None
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    stdout: str
    stderr: str
    findings: tuple[ToolFinding, ...]
    error: ErrorInfo | None
    analyzed_file_count: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    findings_truncated: bool = False

    @property
    def truncated(self) -> bool:
        """任一输出流或 Finding 列表是否被截断。"""

        return (
            self.stdout_truncated
            or self.stderr_truncated
            or self.findings_truncated
        )

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


class AnalysisTool(ABC):
    """静态分析工具抽象。

    子类只负责构造命令与解析输出；超时、输出上限、进程树终止、路径校验、
    Finding 数量上限与结果汇总由本基类统一处理。
    """

    tool_name: ClassVar[str]
    module_name: ClassVar[str]
    distribution_name: ClassVar[str]
    allowed_exit_codes: ClassVar[frozenset[int]] = frozenset({0})

    def __init__(
        self,
        settings: Settings,
        *,
        python_executable: str | None = None,
        process_runner: ProcessRunner | None = None,
        max_command_chars: int = _MAX_COMMAND_CHARS,
    ) -> None:
        self.settings = settings
        self.python_executable = python_executable or sys.executable
        self._process_runner = process_runner or run_process
        self.max_command_chars = max(max_command_chars, 1)
        self._version: str | None = None
        self._version_resolved = False

    @property
    def tool_version(self) -> str | None:
        """已安装发行版版本；无法确定时返回 ``None``。"""

        if not self._version_resolved:
            try:
                self._version = metadata.version(self.distribution_name)
            except metadata.PackageNotFoundError:
                self._version = None
            self._version_resolved = True
        return self._version

    @abstractmethod
    def run(
        self,
        workspace_path: Path,
        files: Sequence[str],
    ) -> ToolExecutionResult:
        """分析工作区内的指定 Python 文件。"""

    def _prepare_files(
        self,
        workspace_path: Path,
        files: Sequence[str],
    ) -> tuple[Path, tuple[Path, ...]]:
        """校验工作区与相对路径，返回去重后的绝对路径。"""

        workspace = Path(workspace_path).expanduser()
        try:
            workspace = workspace.resolve(strict=True)
        except OSError as exc:
            raise ToolInputError(
                "workspace path does not exist or is not a directory"
            ) from exc
        if not workspace.is_dir():
            raise ToolInputError(
                "workspace path does not exist or is not a directory"
            )

        prepared: list[Path] = []
        seen: set[Path] = set()
        for raw in files:
            if not isinstance(raw, str) or not raw.strip():
                raise ToolInputError(
                    "analysis file paths must be non-empty relative POSIX paths"
                )
            if "\\" in raw:
                raise ToolInputError(
                    "analysis paths must not contain backslashes"
                )
            pure = PurePosixPath(raw)
            if pure.is_absolute() or ".." in pure.parts:
                raise ToolInputError(
                    "analysis paths must be relative and must not contain '..'"
                )
            if pure.suffix.lower() != ".py":
                raise ToolInputError("only Python source files can be analyzed")
            candidate = workspace.joinpath(*pure.parts)
            try:
                resolved = candidate.resolve(strict=True)
            except OSError as exc:
                raise ToolInputError(
                    "analysis file is missing or is not a regular file"
                ) from exc
            if not resolved.is_relative_to(workspace):
                raise ToolInputError("analysis file resolves outside the workspace")
            if not resolved.is_file():
                raise ToolInputError(
                    "analysis file is missing or is not a regular file"
                )
            if resolved in seen:
                continue
            seen.add(resolved)
            prepared.append(resolved)
        return workspace, tuple(prepared)

    def _make_batches(
        self,
        paths: Sequence[Path],
        *,
        reserved_chars: int = _DEFAULT_COMMAND_RESERVE,
    ) -> list[tuple[Path, ...]]:
        """按命令长度上限切分文件列表，避免超过 Windows 命令行限制。"""

        if not paths:
            return []
        budget = max(self.max_command_chars - reserved_chars, 1)
        batches: list[tuple[Path, ...]] = []
        current: list[Path] = []
        current_chars = 0
        for path in paths:
            path_chars = len(str(path)) + 3
            if current and current_chars + path_chars > budget:
                batches.append(tuple(current))
                current = []
                current_chars = 0
            current.append(path)
            current_chars += path_chars
        if current:
            batches.append(tuple(current))
        return batches

    def _module_command(self) -> list[str]:
        return [
            self.python_executable,
            "-I",
            "-B",
            "-X",
            "utf8",
            "-m",
            self.module_name,
        ]

    def _run_process(
        self,
        state: _ToolRunState,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
    ) -> ProcessResult:
        return self._process_runner(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            stdout_limit_bytes=state.stdout_budget,
            stderr_limit_bytes=state.stderr_budget,
        )

    def _record_process(
        self,
        state: _ToolRunState,
        result: ProcessResult,
        *,
        batch_index: int,
        batch_count: int,
        phase: str | None = None,
    ) -> bool:
        """记录进程结果；返回 ``True`` 表示可继续解析输出。"""

        state.record_process(result)
        details: dict[str, object] = {
            "tool": self.tool_name,
            "batch_index": batch_index,
            "batch_count": batch_count,
        }
        if phase is not None:
            details["phase"] = phase

        if result.status is ProcessStatus.TIMEOUT:
            state.fail(
                ToolExecutionStatus.TIMEOUT,
                error_type="timeout",
                message=f"{self.tool_name} execution timed out",
                retryable=True,
                details=details,
            )
            return False
        if result.status is ProcessStatus.NOT_FOUND:
            state.fail(
                ToolExecutionStatus.NOT_FOUND,
                error_type="tool_error",
                message=f"{self.tool_name} executable or module was not found",
                retryable=False,
                details=details,
            )
            return False
        if result.status is ProcessStatus.OS_ERROR:
            state.fail(
                ToolExecutionStatus.FAILED,
                error_type="tool_error",
                message=f"{self.tool_name} could not be started",
                retryable=False,
                details=details,
            )
            return False

        if result.returncode not in self.allowed_exit_codes:
            details["exit_code"] = result.returncode
            state.fail(
                ToolExecutionStatus.FAILED,
                error_type="tool_error",
                message=f"{self.tool_name} exited with an unexpected status",
                retryable=False,
                details=details,
            )
            return False
        return True

    def _parse_or_fail(
        self,
        state: _ToolRunState,
        parser: Callable[[str, Path], tuple[ToolFinding, ...]],
        stdout: str,
        workspace: Path,
        *,
        batch_index: int,
        batch_count: int,
        phase: str | None = None,
    ) -> tuple[ToolFinding, ...] | None:
        try:
            return parser(stdout, workspace)
        except ToolOutputParseError:
            details: dict[str, object] = {
                "tool": self.tool_name,
                "batch_index": batch_index,
                "batch_count": batch_count,
            }
            if phase is not None:
                details["phase"] = phase
            state.fail(
                ToolExecutionStatus.PARSE_ERROR,
                error_type="tool_error",
                message=f"{self.tool_name} output could not be parsed",
                retryable=False,
                details=details,
            )
            return None

    def _remaining_seconds(self, deadline: float) -> float:
        return deadline - time.monotonic()

    def _invalid_input_result(
        self,
        exc: ToolInputError,
        *,
        started_at: datetime,
        started_clock: float,
    ) -> ToolExecutionResult:
        finished_at = datetime.now(UTC)
        return ToolExecutionResult(
            tool_name=self.tool_name,
            tool_version=self.tool_version,
            execution_status=ToolExecutionStatus.FAILED,
            exit_code=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(
                0, int((time.perf_counter() - started_clock) * 1000)
            ),
            stdout="",
            stderr="",
            findings=(),
            error=ErrorInfo(
                error_type="invalid_input",
                message=str(exc),
                retryable=False,
                details={"tool": self.tool_name},
            ),
            analyzed_file_count=0,
        )

    def _relative_file_path(self, workspace: Path, emitted: str) -> str:
        """把工具输出中的文件路径规范为仓库相对 POSIX 路径。"""

        return relative_posix_path(workspace, emitted)

    def _temporary_cwd(self) -> tempfile.TemporaryDirectory[str]:
        """工具进程使用仓库外的工作目录，避免加载仓库内配置。"""

        return tempfile.TemporaryDirectory(prefix="code-review-tool-")

    def _finish(
        self,
        state: _ToolRunState,
        *,
        started_at: datetime,
        started_clock: float,
    ) -> ToolExecutionResult:
        return state.build(
            tool_name=self.tool_name,
            tool_version=self.tool_version,
            started_at=started_at,
            duration_ms=max(
                0, int((time.perf_counter() - started_clock) * 1000)
            ),
        )


class _ToolRunState:
    """单个工具跨批次执行过程中的累积状态。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stdout_parts: list[str] = []
        self.stderr_parts: list[str] = []
        self.stdout_bytes = 0
        self.stderr_bytes = 0
        self.stdout_truncated = False
        self.stderr_truncated = False
        self.findings: list[ToolFinding] = []
        self.total_findings = 0
        self.findings_truncated = False
        self.analyzed_file_count = 0
        self.exit_codes: list[int | None] = []
        self.status: ToolExecutionStatus | None = None
        self.error: ErrorInfo | None = None

    @property
    def stdout_budget(self) -> int:
        return max(
            0,
            self.settings.static_tool_output_limit_bytes - self.stdout_bytes,
        )

    @property
    def stderr_budget(self) -> int:
        return max(
            0,
            self.settings.static_tool_output_limit_bytes - self.stderr_bytes,
        )

    def record_process(self, result: ProcessResult) -> None:
        if result.stdout:
            self.stdout_parts.append(result.stdout)
        if result.stderr:
            self.stderr_parts.append(result.stderr)
        self.stdout_bytes += len(result.stdout.encode("utf-8"))
        self.stderr_bytes += len(result.stderr.encode("utf-8"))
        if result.stdout_truncated:
            self.stdout_truncated = True
            self.stdout_bytes = self.settings.static_tool_output_limit_bytes
        if result.stderr_truncated:
            self.stderr_truncated = True
            self.stderr_bytes = self.settings.static_tool_output_limit_bytes
        self.exit_codes.append(result.returncode)

    def add_findings(self, findings: Sequence[ToolFinding]) -> None:
        limit = self.settings.max_tool_findings
        remaining = limit - len(self.findings)
        if remaining > 0:
            self.findings.extend(findings[:remaining])
        self.total_findings += len(findings)
        if self.total_findings > limit:
            self.findings_truncated = True

    def fail(
        self,
        status: ToolExecutionStatus,
        *,
        error_type: str,
        message: str,
        retryable: bool,
        details: Mapping[str, object],
    ) -> None:
        if (
            self.error is not None
            and self.status is not ToolExecutionStatus.PARTIAL
        ):
            return
        self.status = status
        self.error = ErrorInfo(
            error_type=error_type,
            message=message,
            retryable=retryable,
            details=dict(details),
        )

    def mark_partial(
        self,
        *,
        message: str,
        details: Mapping[str, object],
    ) -> None:
        if self.error is not None:
            return
        self.status = ToolExecutionStatus.PARTIAL
        self.error = ErrorInfo(
            error_type="tool_error",
            message=message,
            retryable=False,
            details=dict(details),
        )

    def build(
        self,
        *,
        tool_name: str,
        tool_version: str | None,
        started_at: datetime,
        duration_ms: int,
    ) -> ToolExecutionResult:
        if self.error is None:
            status = (
                ToolExecutionStatus.FINDINGS
                if self.total_findings > 0
                else ToolExecutionStatus.SUCCESS
            )
        else:
            status = self.status or ToolExecutionStatus.FAILED

        return ToolExecutionResult(
            tool_name=tool_name,
            tool_version=tool_version,
            execution_status=status,
            exit_code=(
                self.exit_codes[-1] if self.exit_codes else 0
            ),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            duration_ms=duration_ms,
            stdout="\n".join(self.stdout_parts),
            stderr="\n".join(self.stderr_parts),
            findings=tuple(self.findings),
            error=self.error,
            analyzed_file_count=self.analyzed_file_count,
            stdout_truncated=self.stdout_truncated,
            stderr_truncated=self.stderr_truncated,
            findings_truncated=self.findings_truncated,
        )
