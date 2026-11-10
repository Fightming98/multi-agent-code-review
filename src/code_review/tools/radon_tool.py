"""Radon 代码复杂度与可维护性分析工具。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from .base import (
    AnalysisTool,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
    ToolInputError,
    ToolOutputParseError,
    _ToolRunState,
    relative_posix_path,
)

__all__ = [
    "RadonTool",
    "parse_radon_cc_output",
    "parse_radon_mi_output",
]


def parse_radon_cc_output(
    stdout: str,
    workspace_path: Path,
) -> tuple[ToolFinding, ...]:
    """解析 ``radon cc --json``：文件到代码块列表的映射。"""

    payload = _load_json_object(stdout, "radon cc")
    workspace = Path(workspace_path).resolve(strict=False)
    findings: list[ToolFinding] = []
    for filename, blocks in payload.items():
        if not isinstance(filename, str) or not filename:
            raise ToolOutputParseError("radon cc output has an invalid filename")
        if not isinstance(blocks, list):
            raise ToolOutputParseError("radon cc blocks must be a JSON array")
        file_path = relative_posix_path(workspace, filename)
        for block in blocks:
            if not isinstance(block, dict):
                raise ToolOutputParseError("radon cc block must be a JSON object")
            object_type = block.get("type")
            object_name = block.get("name")
            line = block.get("lineno")
            end_line = block.get("endline")
            complexity = block.get("complexity")
            rank = block.get("rank")
            if not isinstance(object_type, str) or not object_type:
                raise ToolOutputParseError(
                    "radon cc block is missing an object type"
                )
            if not isinstance(object_name, str) or not object_name:
                raise ToolOutputParseError(
                    "radon cc block is missing an object name"
                )
            if not _is_positive_int(line):
                raise ToolOutputParseError(
                    "radon cc block has an invalid line number"
                )
            if end_line is not None and not _is_positive_int(end_line):
                raise ToolOutputParseError(
                    "radon cc block has an invalid end line"
                )
            if not _is_number(complexity):
                raise ToolOutputParseError(
                    "radon cc block has an invalid complexity"
                )
            if not isinstance(rank, str) or not rank:
                raise ToolOutputParseError("radon cc block is missing a rank")
            if end_line is not None and end_line < line:
                raise ToolOutputParseError(
                    "radon cc block end line must be >= start line"
                )

            findings.append(
                ToolFinding(
                    tool_name="radon",
                    rule_id="RADON_CC",
                    file_path=file_path,
                    message=(
                        f"{object_type} '{object_name}' has cyclomatic "
                        f"complexity {complexity} (rank {rank})"
                    ),
                    line=line,
                    end_line=end_line,
                    metadata={
                        "object_type": object_type,
                        "object_name": object_name,
                        "complexity": complexity,
                        "rank": rank,
                    },
                )
            )
    return tuple(findings)


def parse_radon_mi_output(
    stdout: str,
    workspace_path: Path,
) -> tuple[ToolFinding, ...]:
    """解析 ``radon mi --json``：文件到可维护性指数的映射。"""

    payload = _load_json_object(stdout, "radon mi")
    workspace = Path(workspace_path).resolve(strict=False)
    findings: list[ToolFinding] = []
    for filename, score in payload.items():
        if not isinstance(filename, str) or not filename:
            raise ToolOutputParseError("radon mi output has an invalid filename")
        if not isinstance(score, dict):
            raise ToolOutputParseError("radon mi score must be a JSON object")
        mi = score.get("mi")
        rank = score.get("rank")
        if not _is_number(mi):
            raise ToolOutputParseError(
                "radon mi score is missing a numeric maintainability index"
            )
        if not isinstance(rank, str) or not rank:
            raise ToolOutputParseError("radon mi score is missing a rank")
        findings.append(
            ToolFinding(
                tool_name="radon",
                rule_id="RADON_MI",
                file_path=relative_posix_path(workspace, filename),
                message=(
                    f"Maintainability index {float(mi):.2f} (rank {rank})"
                ),
                metadata={"mi": mi, "rank": rank},
            )
        )
    return tuple(findings)


class RadonTool(AnalysisTool):
    """执行真实 Radon CLI，合并复杂度与可维护性结果。"""

    tool_name = "radon"
    module_name = "radon"
    distribution_name = "radon"
    allowed_exit_codes = frozenset({0})

    def run(
        self,
        workspace_path: Path,
        files: Sequence[str],
    ) -> ToolExecutionResult:
        started_at = datetime.now(UTC)
        started_clock = time.perf_counter()
        try:
            workspace, paths = self._prepare_files(workspace_path, files)
        except ToolInputError as exc:
            return self._invalid_input_result(
                exc,
                started_at=started_at,
                started_clock=started_clock,
            )

        state = _ToolRunState(self.settings)
        if not paths:
            return self._finish(
                state,
                started_at=started_at,
                started_clock=started_clock,
            )

        deadline = (
            time.monotonic() + self.settings.static_tool_timeout_seconds
        )
        batches = self._make_batches(paths)
        with self._temporary_cwd() as cwd_text:
            cwd = Path(cwd_text)
            for batch_index, batch in enumerate(batches, start=1):
                completed = self._run_phase(
                    state,
                    cwd=cwd,
                    workspace=workspace,
                    batch=batch,
                    batch_index=batch_index,
                    batch_count=len(batches),
                    deadline=deadline,
                    phase="cc",
                    parser=parse_radon_cc_output,
                )
                if not completed:
                    break
                completed = self._run_phase(
                    state,
                    cwd=cwd,
                    workspace=workspace,
                    batch=batch,
                    batch_index=batch_index,
                    batch_count=len(batches),
                    deadline=deadline,
                    phase="mi",
                    parser=parse_radon_mi_output,
                )
                if not completed:
                    break
                state.analyzed_file_count += len(batch)

        return self._finish(
            state,
            started_at=started_at,
            started_clock=started_clock,
        )

    def _run_phase(
        self,
        state: _ToolRunState,
        *,
        cwd: Path,
        workspace: Path,
        batch: Sequence[Path],
        batch_index: int,
        batch_count: int,
        deadline: float,
        phase: str,
        parser: Callable[[str, Path], tuple[ToolFinding, ...]],
    ) -> bool:
        remaining = self._remaining_seconds(deadline)
        if remaining <= 0:
            state.fail(
                ToolExecutionStatus.TIMEOUT,
                error_type="timeout",
                message="radon execution timed out",
                retryable=True,
                details={
                    "tool": self.tool_name,
                    "batch_index": batch_index,
                    "batch_count": batch_count,
                    "phase": phase,
                },
            )
            return False

        command = [
            *self._module_command(),
            phase,
            "--json",
            *(str(path) for path in batch),
        ]
        result = self._run_process(
            state,
            command,
            cwd=cwd,
            timeout_seconds=remaining,
        )
        if not self._record_process(
            state,
            result,
            batch_index=batch_index,
            batch_count=batch_count,
            phase=phase,
        ):
            return False
        findings = self._parse_or_fail(
            state,
            parser,
            result.stdout,
            workspace,
            batch_index=batch_index,
            batch_count=batch_count,
            phase=phase,
        )
        if findings is None:
            return False
        state.add_findings(findings)
        return True


def _load_json_object(stdout: str, tool_label: str) -> dict[str, object]:
    if not stdout.strip():
        raise ToolOutputParseError(f"{tool_label} output is empty")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ToolOutputParseError(
            f"{tool_label} output is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ToolOutputParseError(
            f"{tool_label} output must be a JSON object"
        )
    return payload


def _is_positive_int(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 1
    )


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )
