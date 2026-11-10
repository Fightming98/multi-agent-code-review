"""Bandit 工具解析与执行行为的单元测试。"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from config.settings import Settings
from src.code_review.tools.bandit_tool import (
    BanditTool,
    parse_bandit_output,
)
from src.code_review.tools.base import ToolExecutionStatus, ToolOutputParseError
from src.code_review.tools.process_runner import ProcessResult, ProcessStatus


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def completed(
    stdout: str,
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
) -> tuple[Callable[..., ProcessResult], list[list[str]]]:
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> ProcessResult:
        calls.append(list(command))
        index = min(len(calls) - 1, len(results) - 1)
        return results[index]

    return runner, calls


def bandit_payload(
    workspace: Path,
    *,
    results: int = 1,
    errors: int = 0,
) -> str:
    findings = []
    for index in range(1, results + 1):
        findings.append(
            {
                "code": "7 os.system('echo hi')\n",
                "col_offset": 23,
                "end_col_offset": 43,
                "filename": str(workspace / "pkg" / "module.py"),
                "issue_confidence": "HIGH",
                "issue_cwe": {
                    "id": 78,
                    "link": "https://cwe.mitre.org/data/definitions/78.html",
                },
                "issue_severity": "LOW",
                "issue_text": f"Starting a process with a shell {index}",
                "line_number": index,
                "line_range": [index],
                "more_info": "https://bandit.readthedocs.io/",
                "test_id": "B605",
                "test_name": "start_process_with_a_shell",
            }
        )
    error_items = [
        {"filename": str(workspace / "broken.py"), "reason": "parse error"}
        for _ in range(errors)
    ]
    return json.dumps(
        {
            "errors": error_items,
            "generated_at": "2026-11-10T00:00:00Z",
            "metrics": {},
            "results": findings,
        }
    )


def test_parse_bandit_output_maps_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    parsed = parse_bandit_output(bandit_payload(workspace), workspace)

    assert parsed.error_count == 0
    assert len(parsed.findings) == 1
    finding = parsed.findings[0]
    assert finding.tool_name == "bandit"
    assert finding.rule_id == "B605"
    assert finding.file_path == "pkg/module.py"
    assert finding.line == 1
    assert finding.end_line == 1
    assert finding.column == 24
    assert finding.severity == "LOW"
    assert finding.confidence == "HIGH"
    assert finding.metadata["test_name"] == "start_process_with_a_shell"
    assert finding.metadata["cwe_id"] == 78
    assert "code" not in finding.metadata


def test_parse_bandit_output_counts_errors(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    parsed = parse_bandit_output(
        bandit_payload(workspace, results=1, errors=2),
        workspace,
    )

    assert parsed.error_count == 2
    assert len(parsed.findings) == 1


def test_parse_bandit_output_rejects_invalid_json(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_bandit_output("not-json", tmp_path)


def test_parse_bandit_output_rejects_empty_output(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_bandit_output("", tmp_path)


def test_parse_bandit_output_rejects_wrong_shape(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_bandit_output("[]", tmp_path)


def test_parse_bandit_output_rejects_path_outside_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    payload = json.dumps(
        {
            "errors": [],
            "results": [
                {
                    "filename": str(tmp_path / "outside.py"),
                    "issue_confidence": "HIGH",
                    "issue_severity": "LOW",
                    "issue_text": "issue",
                    "line_number": 1,
                    "test_id": "B101",
                }
            ],
        }
    )

    with pytest.raises(ToolOutputParseError):
        parse_bandit_output(payload, workspace)


def test_real_bandit_execution_reports_findings(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text(
        "import os\n\n\ndef run():\n    return os.system('echo hi')\n",
        encoding="utf-8",
    )

    result = BanditTool(settings()).run(workspace, ["example.py"])

    assert result.execution_status is ToolExecutionStatus.FINDINGS
    assert result.exit_code == 1
    assert result.error is None
    assert result.analyzed_file_count == 1
    assert result.tool_version == "1.9.4"
    assert result.findings
    assert all(finding.file_path == "example.py" for finding in result.findings)
    assert any(finding.rule_id == "B605" for finding in result.findings)
    assert all(finding.severity for finding in result.findings)
    assert all(finding.confidence for finding in result.findings)


def test_real_bandit_execution_clean_file(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    result = BanditTool(settings()).run(workspace, ["example.py"])

    assert result.execution_status is ToolExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert result.findings == ()


def test_partial_file_errors_are_not_reported_as_success(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner(
        [completed(bandit_payload(workspace, results=1, errors=1), returncode=1)]
    )

    result = BanditTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.execution_status is ToolExecutionStatus.PARTIAL
    assert result.error is not None
    assert result.error.error_type == "tool_error"
    assert result.error.details["error_count"] == 1
    assert len(result.findings) == 1


def test_partial_errors_without_findings_still_report_error(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner(
        [completed(bandit_payload(workspace, results=0, errors=1))]
    )

    result = BanditTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.execution_status is ToolExecutionStatus.PARTIAL
    assert result.findings == ()
    assert result.error is not None


def test_missing_executable_is_reported(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")

    result = BanditTool(
        settings(),
        python_executable=str(tmp_path / "missing-python"),
    ).run(workspace, ["example.py"])

    assert result.execution_status is ToolExecutionStatus.NOT_FOUND


def test_timeout_is_reported(tmp_path: Path) -> None:
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

    result = BanditTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.execution_status is ToolExecutionStatus.TIMEOUT
    assert result.error is not None
    assert result.error.error_type == "timeout"


def test_parse_error_is_reported(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner([completed("not-json")])

    result = BanditTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.execution_status is ToolExecutionStatus.PARSE_ERROR


def test_unexpected_exit_code_is_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = scripted_runner(
        [completed(bandit_payload(workspace, results=0), returncode=2)]
    )

    result = BanditTool(settings(), process_runner=runner).run(
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
        [completed(bandit_payload(workspace, results=3), returncode=1)]
    )

    result = BanditTool(
        settings(max_tool_findings=2),
        process_runner=runner,
    ).run(workspace, ["pkg/module.py"])

    assert len(result.findings) == 2
    assert result.findings_truncated is True


def test_empty_file_list_does_not_run_process(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    def runner(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("process must not run")

    result = BanditTool(settings(), process_runner=runner).run(workspace, [])

    assert result.execution_status is ToolExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert result.analyzed_file_count == 0
