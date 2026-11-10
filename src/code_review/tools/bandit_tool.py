"""Bandit 安全分析工具。"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
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

__all__ = ["BanditOutput", "BanditTool", "parse_bandit_output"]

_BANDIT_CONFIG_TEXT = "[bandit]\n"


@dataclass(frozen=True)
class BanditOutput:
    """Bandit JSON 中的结构化发现与文件级错误数量。"""

    findings: tuple[ToolFinding, ...]
    error_count: int


def parse_bandit_output(
    stdout: str,
    workspace_path: Path,
) -> BanditOutput:
    """解析 ``bandit -f json`` 输出。

    ``errors`` 表示 Bandit 对部分文件的分析失败；即使同时有结果，也不能
    当作完整成功。
    """

    if not stdout.strip():
        raise ToolOutputParseError("bandit output is empty")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ToolOutputParseError("bandit output is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ToolOutputParseError("bandit output must be a JSON object")

    raw_results = payload.get("results", [])
    raw_errors = payload.get("errors", [])
    if not isinstance(raw_results, list) or not isinstance(raw_errors, list):
        raise ToolOutputParseError(
            "bandit output must contain results and errors arrays"
        )

    workspace = Path(workspace_path).resolve(strict=False)
    findings: list[ToolFinding] = []
    for item in raw_results:
        if not isinstance(item, dict):
            raise ToolOutputParseError("bandit finding must be a JSON object")
        test_id = item.get("test_id")
        filename = item.get("filename")
        issue_text = item.get("issue_text")
        line_number = item.get("line_number")
        if not isinstance(test_id, str) or not test_id:
            raise ToolOutputParseError("bandit finding is missing a test id")
        if not isinstance(filename, str):
            raise ToolOutputParseError("bandit finding is missing a filename")
        if not isinstance(issue_text, str) or not issue_text.strip():
            raise ToolOutputParseError("bandit finding is missing issue text")
        if (
            not isinstance(line_number, int)
            or isinstance(line_number, bool)
            or line_number < 1
        ):
            raise ToolOutputParseError("bandit finding has an invalid line number")

        line_range = item.get("line_range")
        end_line = _end_line(line_range, line_number)
        column = _column(item.get("col_offset"))
        cwe = item.get("issue_cwe")
        cwe_id = cwe.get("id") if isinstance(cwe, dict) else None
        metadata: dict[str, object] = {
            "test_name": item.get("test_name"),
            "more_info": item.get("more_info"),
            "cwe_id": cwe_id,
            "line_range": line_range if isinstance(line_range, list) else None,
            "col_offset": item.get("col_offset"),
        }

        findings.append(
            ToolFinding(
                tool_name="bandit",
                rule_id=test_id,
                file_path=relative_posix_path(workspace, filename),
                message=issue_text,
                line=line_number,
                end_line=end_line,
                column=column,
                severity=(
                    item.get("issue_severity")
                    if isinstance(item.get("issue_severity"), str)
                    else None
                ),
                confidence=(
                    item.get("issue_confidence")
                    if isinstance(item.get("issue_confidence"), str)
                    else None
                ),
                metadata=metadata,
            )
        )
    return BanditOutput(findings=tuple(findings), error_count=len(raw_errors))


class BanditTool(AnalysisTool):
    """执行真实 Bandit CLI 并解析 JSON 结果。"""

    tool_name = "bandit"
    module_name = "bandit"
    distribution_name = "bandit"
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
            config_path = cwd / "bandit-empty.ini"
            config_path.write_text(_BANDIT_CONFIG_TEXT, encoding="utf-8")

            for batch_index, batch in enumerate(batches, start=1):
                remaining = self._remaining_seconds(deadline)
                if remaining <= 0:
                    state.fail(
                        ToolExecutionStatus.TIMEOUT,
                        error_type="timeout",
                        message="bandit execution timed out",
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
                    "-f",
                    "json",
                    "-q",
                    "--ini",
                    str(config_path),
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
                parsed = self._parse_bandit_or_fail(
                    state,
                    result.stdout,
                    workspace,
                    batch_index=batch_index,
                    batch_count=len(batches),
                )
                if parsed is None:
                    break
                state.add_findings(parsed.findings)
                state.analyzed_file_count += len(batch)
                if parsed.error_count:
                    state.mark_partial(
                        message="bandit reported file analysis errors",
                        details={
                            "tool": self.tool_name,
                            "error_count": parsed.error_count,
                            "batch_index": batch_index,
                            "batch_count": len(batches),
                        },
                    )

        return self._finish(
            state,
            started_at=started_at,
            started_clock=started_clock,
        )

    def _parse_bandit_or_fail(
        self,
        state: _ToolRunState,
        stdout: str,
        workspace: Path,
        *,
        batch_index: int,
        batch_count: int,
    ) -> BanditOutput | None:
        try:
            return parse_bandit_output(stdout, workspace)
        except ToolOutputParseError:
            state.fail(
                ToolExecutionStatus.PARSE_ERROR,
                error_type="tool_error",
                message="bandit output could not be parsed",
                retryable=False,
                details={
                    "tool": self.tool_name,
                    "batch_index": batch_index,
                    "batch_count": batch_count,
                },
            )
            return None


def _end_line(line_range: object, start_line: int) -> int | None:
    if not isinstance(line_range, list) or not line_range:
        return None
    valid_lines = [
        line
        for line in line_range
        if isinstance(line, int) and not isinstance(line, bool) and line >= 1
    ]
    if not valid_lines:
        return None
    end_line = max(valid_lines)
    return end_line if end_line >= start_line else None


def _column(col_offset: object) -> int | None:
    if (
        not isinstance(col_offset, int)
        or isinstance(col_offset, bool)
        or col_offset < 0
    ):
        return None
    return col_offset + 1
