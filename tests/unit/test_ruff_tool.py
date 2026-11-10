"""Ruff 工具解析与执行行为的单元测试。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from code_review.tools.base import (
    ToolExecutionStatus,
    ToolOutputParseError,
)
from code_review.tools.process_runner import ProcessResult, ProcessStatus
from code_review.tools.ruff_tool import RuffTool, parse_ruff_output
from config.settings import Settings


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def completed(
    stdout: str = "[]",
    *,
    returncode: int = 0,
    stderr: str = "",
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
) -> ProcessResult:
    return ProcessResult(
        status=ProcessStatus.COMPLETED,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        duration_ms=1,
    )


def scripted_runner(
    results: Sequence[ProcessResult],
) -> tuple[object, list[list[str]]]:
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> ProcessResult:
        calls.append(list(command))
        index = min(len(calls) - 1, len(results) - 1)
        return results[index]

    return runner, calls


def ruff_payload(workspace: Path, count: int = 1) -> str:
    items = []
    for index in range(1, count + 1):
        items.append(
            {
                "cell": None,
                "code": "F401",
                "end_location": {"column": 10, "row": index},
                "filename": str(workspace / "pkg" / "module.py"),
                "fix": {"applicability": "safe", "edits": []},
                "location": {"column": 1, "row": index},
                "message": f"unused import {index}",
                "name": "unused-import",
                "noqa_row": index,
                "severity": "error",
                "url": "https://docs.astral.sh/ruff/rules/unused-import",
            }
        )
    return json.dumps(items)


def test_parse_ruff_output_maps_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    findings = parse_ruff_output(ruff_payload(workspace, 2), workspace)

    assert len(findings) == 2
    first = findings[0]
    assert first.tool_name == "ruff"
    assert first.rule_id == "F401"
    assert first.file_path == "pkg/module.py"
    assert first.line == 1
    assert first.end_line == 1
    assert first.column == 1
    assert first.severity == "error"
    assert first.metadata["fix_available"] is True
    assert first.metadata["fix_applicability"] == "safe"


def test_parse_ruff_output_rejects_invalid_json(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_ruff_output("not-json", tmp_path)


def test_parse_ruff_output_rejects_empty_output(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_ruff_output("", tmp_path)


def test_parse_ruff_output_rejects_wrong_shape(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_ruff_output("{}", tmp_path)


def test_parse_ruff_output_rejects_path_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    payload = json.dumps(
        [
            {
                "code": "F401",
                "filename": str(tmp_path / "outside.py"),
                "location": {"column": 1, "row": 1},
                "message": "unused import",
            }
        ]
    )

    with pytest.raises(ToolOutputParseError):
        parse_ruff_output(payload, workspace)


def test_real_ruff_execution_reports_findings(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text(
        "import os\n\n\ndef f():\n    return 1\n",
        encoding="utf-8",
    )

    result = RuffTool(settings()).run(workspace, ["example.py"])

    assert result.execution_status is ToolExecutionStatus.FINDINGS
    assert result.exit_code == 1
    assert result.error is None
    assert result.analyzed_file_count == 1
    assert result.tool_version == "0.17.4"
    assert result.findings
    assert any(finding.rule_id == "F401" for finding in result.findings)
    assert all(finding.file_path == "example.py" for finding in result.findings)
    assert json.loads(result.stdout)


def test_real_ruff_execution_clean_file(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    result = RuffTool(settings()).run(workspace, ["example.py"])

    assert result.execution_status is ToolExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert result.findings == ()
    assert result.analyzed_file_count == 1


def test_empty_file_list_does_not_run_process(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    def runner(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("process must not run")

    result = RuffTool(settings(), process_runner=runner).run(workspace, [])

    assert result.execution_status is ToolExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert result.analyzed_file_count == 0
    assert result.findings == ()


def test_missing_executable_is_reported(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")

    result = RuffTool(
        settings(),
        python_executable=str(tmp_path / "missing-python"),
    ).run(workspace, ["example.py"])

    assert result.execution_status is ToolExecutionStatus.NOT_FOUND
    assert result.error is not None
    assert result.error.error_type == "tool_error"


def test_timeout_result_is_preserved(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner(
        [
            ProcessResult(
                status=ProcessStatus.TIMEOUT,
                returncode=None,
                stdout="",
                stderr="",
                stdout_truncated=False,
                stderr_truncated=False,
                duration_ms=10,
            )
        ]
    )

    result = RuffTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.execution_status is ToolExecutionStatus.TIMEOUT
    assert result.error is not None
    assert result.error.error_type == "timeout"
    assert result.error.retryable is True


def test_parse_error_is_reported(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner([completed("not-json")])

    result = RuffTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.execution_status is ToolExecutionStatus.PARSE_ERROR
    assert result.error is not None
    assert result.error.error_type == "tool_error"


def test_unexpected_exit_code_is_failure_not_no_findings(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner([completed("[]", returncode=2)])

    result = RuffTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.execution_status is ToolExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.details.get("exit_code") == 2


def test_findings_are_capped_and_marked_truncated(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "module.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner(
        [completed(ruff_payload(workspace, 3), returncode=1)]
    )

    result = RuffTool(
        settings(max_tool_findings=2),
        process_runner=runner,
    ).run(workspace, ["pkg/module.py"])

    assert result.execution_status is ToolExecutionStatus.FINDINGS
    assert len(result.findings) == 2
    assert result.findings_truncated is True
    assert result.truncated is True


def test_stream_truncation_flags_are_propagated(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner(
        [
            completed(
                "[]",
                stderr="warning",
                stdout_truncated=True,
                stderr_truncated=True,
            )
        ]
    )

    result = RuffTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.stdout_truncated is True
    assert result.stderr_truncated is True
    assert result.stderr == "warning"


def test_long_file_list_is_split_into_multiple_batches(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    names = [f"module_{index:02d}.py" for index in range(3)]
    for name in names:
        (workspace / name).write_text("x = 1\n", encoding="utf-8")
    runner, calls = scripted_runner([completed("[]")])

    result = RuffTool(
        settings(),
        process_runner=runner,
        max_command_chars=1,
    ).run(workspace, names)

    assert result.execution_status is ToolExecutionStatus.SUCCESS
    assert result.analyzed_file_count == 3
    assert len(calls) == 3


def test_later_batch_failure_keeps_earlier_findings(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    names = ["module_a.py", "module_b.py"]
    for name in names:
        (workspace / name).write_text("x = 1\n", encoding="utf-8")
    first_payload = json.dumps(
        [
            {
                "code": "F401",
                "filename": str(workspace / names[0]),
                "location": {"column": 1, "row": 1},
                "message": "unused import",
            }
        ]
    )
    runner, calls = scripted_runner(
        [
            completed(first_payload, returncode=1),
            ProcessResult(
                status=ProcessStatus.TIMEOUT,
                returncode=None,
                stdout="",
                stderr="",
                stdout_truncated=False,
                stderr_truncated=False,
                duration_ms=10,
            ),
        ]
    )

    result = RuffTool(
        settings(),
        process_runner=runner,
        max_command_chars=1,
    ).run(workspace, names)

    assert result.execution_status is ToolExecutionStatus.TIMEOUT
    assert len(result.findings) == 1
    assert result.analyzed_file_count == 1
    assert len(calls) == 2
