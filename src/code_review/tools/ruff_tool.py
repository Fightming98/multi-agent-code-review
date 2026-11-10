"""Ruff 静态代码质量分析工具。"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
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

__all__ = ["RuffTool", "parse_ruff_output"]


def parse_ruff_output(
    stdout: str,
    workspace_path: Path,
) -> tuple[ToolFinding, ...]:
    """解析 ``ruff check --output-format json`` 的 JSON 数组。"""

    if not stdout.strip():
        raise ToolOutputParseError("ruff output is empty")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ToolOutputParseError("ruff output is not valid JSON") from exc
    if not isinstance(payload, list):
        raise ToolOutputParseError("ruff output must be a JSON array")

    workspace = Path(workspace_path).resolve(strict=False)
    findings: list[ToolFinding] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ToolOutputParseError("ruff finding must be a JSON object")
        code = item.get("code")
        message = item.get("message")
        filename = item.get("filename")
        location = item.get("location")
        if not isinstance(code, str) or not code:
            raise ToolOutputParseError("ruff finding is missing a rule code")
        if not isinstance(message, str) or not message.strip():
            raise ToolOutputParseError("ruff finding is missing a message")
        if not isinstance(filename, str):
            raise ToolOutputParseError("ruff finding is missing a filename")
        if not isinstance(location, dict):
            raise ToolOutputParseError("ruff finding is missing a location")

        line = _positive_int(location.get("row"), "row")
        column = _optional_positive_int(location.get("column"), "column")
        end_line = _end_line(item.get("end_location"), line)
        fix = item.get("fix")
        metadata: dict[str, object] = {
            "name": item.get("name"),
            "url": item.get("url"),
            "fix_available": isinstance(fix, dict),
        }
        if isinstance(fix, dict):
            metadata["fix_applicability"] = fix.get("applicability")

        findings.append(
            ToolFinding(
                tool_name="ruff",
                rule_id=code,
                file_path=relative_posix_path(workspace, filename),
                message=message,
                line=line,
                end_line=end_line,
                column=column,
                severity=(
                    item.get("severity")
                    if isinstance(item.get("severity"), str)
                    else None
                ),
                metadata=metadata,
            )
        )
    return tuple(findings)


class RuffTool(AnalysisTool):
    """执行真实 Ruff CLI 并解析 JSON 结果。"""

    tool_name = "ruff"
    module_name = "ruff"
    distribution_name = "ruff"
    allowed_exit_codes = frozenset({0, 1})

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
                remaining = self._remaining_seconds(deadline)
                if remaining <= 0:
                    state.fail(
                        ToolExecutionStatus.TIMEOUT,
                        error_type="timeout",
                        message="ruff execution timed out",
                        retryable=True,
                        details={
                            "tool": self.tool_name,
                            "batch_index": batch_index,
                            "batch_count": len(batches),
                        },
                    )
                    break
                command = [
                    *self._module_command(),
                    "check",
                    "--isolated",
                    "--no-cache",
                    "--output-format",
                    "json",
                    "--",
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
                    batch_count=len(batches),
                ):
                    break
                findings = self._parse_or_fail(
                    state,
                    parse_ruff_output,
                    result.stdout,
                    workspace,
                    batch_index=batch_index,
                    batch_count=len(batches),
                )
                if findings is None:
                    break
                state.add_findings(findings)
                state.analyzed_file_count += len(batch)

        return self._finish(
            state,
            started_at=started_at,
            started_clock=started_clock,
        )


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ToolOutputParseError(f"ruff finding has an invalid {field_name}")
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _end_line(value: object, start_line: int) -> int | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ToolOutputParseError("ruff end_location must be an object")
    end_line = _positive_int(value.get("row"), "end_location.row")
    if end_line < start_line:
        raise ToolOutputParseError(
            "ruff end_location.row must be >= location.row"
        )
    return end_line
