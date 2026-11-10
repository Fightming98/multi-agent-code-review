"""Radon 工具解析与执行行为的单元测试。"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from config.settings import Settings
from src.code_review.tools.base import ToolExecutionStatus, ToolOutputParseError
from src.code_review.tools.process_runner import ProcessResult, ProcessStatus
from src.code_review.tools.radon_tool import (
    RadonTool,
    parse_radon_cc_output,
    parse_radon_mi_output,
)


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def completed(
    stdout: str,
    *,
    returncode: int = 0,
    stderr: str = "",
) -> ProcessResult:
    return ProcessResult(
        status=ProcessStatus.COMPLETED,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=1,
    )


def timed_out() -> ProcessResult:
    return ProcessResult(
        status=ProcessStatus.TIMEOUT,
        returncode=None,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=10,
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


def cc_payload(
    workspace: Path,
    *,
    blocks: Sequence[tuple[str, int, int, int, str]] | None = None,
) -> str:
    if blocks is None:
        blocks = [("function", 1, 5, 7, "B")]
    items = [
        {
            "closures": [],
            "col_offset": 0,
            "complexity": complexity,
            "endline": end_line,
            "lineno": line,
            "name": f"object_{index}",
            "rank": rank,
            "type": object_type,
        }
        for index, (object_type, line, end_line, complexity, rank) in enumerate(
            blocks,
            start=1,
        )
    ]
    return json.dumps({str(workspace / "pkg" / "module.py"): items})


def mi_payload(workspace: Path, mi: float = 87.5, rank: str = "A") -> str:
    return json.dumps({str(workspace / "pkg" / "module.py"): {"mi": mi, "rank": rank}})


def phase_runner(
    workspace: Path,
    *,
    cc: Callable[[list[str]], ProcessResult] | None = None,
    mi: Callable[[list[str]], ProcessResult] | None = None,
) -> tuple[Callable[..., ProcessResult], list[list[str]]]:
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> ProcessResult:
        calls.append(list(command))
        if "cc" in command:
            if cc is not None:
                return cc(command)
            return completed(cc_payload(workspace))
        if mi is not None:
            return mi(command)
        return completed(mi_payload(workspace))

    return runner, calls


def test_parse_radon_cc_output_maps_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    findings = parse_radon_cc_output(cc_payload(workspace), workspace)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.tool_name == "radon"
    assert finding.rule_id == "RADON_CC"
    assert finding.file_path == "pkg/module.py"
    assert finding.line == 1
    assert finding.end_line == 5
    assert finding.metadata["object_type"] == "function"
    assert finding.metadata["complexity"] == 7
    assert finding.metadata["rank"] == "B"
    assert "complexity 7" in finding.message


def test_parse_radon_cc_output_accepts_empty_object(tmp_path: Path) -> None:
    assert parse_radon_cc_output("{}", tmp_path) == ()


def test_parse_radon_cc_output_rejects_invalid_json(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_radon_cc_output("not-json", tmp_path)


def test_parse_radon_cc_output_rejects_empty_output(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_radon_cc_output("", tmp_path)


def test_parse_radon_cc_output_rejects_wrong_shape(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_radon_cc_output("[]", tmp_path)


def test_parse_radon_cc_output_rejects_malformed_block(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_radon_cc_output(
            json.dumps({str(tmp_path / "module.py"): [{"type": "function"}]}),
            tmp_path,
        )


def test_parse_radon_cc_output_rejects_invalid_end_line(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            str(tmp_path / "module.py"): [
                {
                    "type": "function",
                    "name": "f",
                    "lineno": 5,
                    "endline": 3,
                    "complexity": 2,
                    "rank": "A",
                }
            ]
        }
    )

    with pytest.raises(ToolOutputParseError):
        parse_radon_cc_output(payload, tmp_path)


def test_parse_radon_cc_output_rejects_path_outside_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    payload = json.dumps(
        {
            str(tmp_path / "outside.py"): [
                {
                    "type": "function",
                    "name": "f",
                    "lineno": 1,
                    "endline": 2,
                    "complexity": 2,
                    "rank": "A",
                }
            ]
        }
    )

    with pytest.raises(ToolOutputParseError):
        parse_radon_cc_output(payload, workspace)


def test_parse_radon_mi_output_maps_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    findings = parse_radon_mi_output(mi_payload(workspace), workspace)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "RADON_MI"
    assert finding.file_path == "pkg/module.py"
    assert finding.line is None
    assert finding.metadata["mi"] == 87.5
    assert finding.metadata["rank"] == "A"
    assert "Maintainability index 87.50" in finding.message


def test_parse_radon_mi_output_rejects_malformed_score(tmp_path: Path) -> None:
    with pytest.raises(ToolOutputParseError):
        parse_radon_mi_output(
            json.dumps({str(tmp_path / "module.py"): {"rank": "A"}}),
            tmp_path,
        )


def test_real_radon_execution_reports_findings(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    result = RadonTool(settings()).run(workspace, ["example.py"])

    assert result.execution_status is ToolExecutionStatus.FINDINGS
    assert result.exit_code == 0
    assert result.error is None
    assert result.analyzed_file_count == 1
    assert result.tool_version == "6.0.1"
    rule_ids = {finding.rule_id for finding in result.findings}
    assert rule_ids == {"RADON_CC", "RADON_MI"}
    assert all(
        finding.file_path == "example.py" for finding in result.findings
    )


def test_empty_file_list_does_not_run_process(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    def runner(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("process must not run")

    result = RadonTool(settings(), process_runner=runner).run(workspace, [])

    assert result.execution_status is ToolExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert result.analyzed_file_count == 0


def test_missing_executable_is_reported(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")

    result = RadonTool(
        settings(),
        python_executable=str(tmp_path / "missing-python"),
    ).run(workspace, ["example.py"])

    assert result.execution_status is ToolExecutionStatus.NOT_FOUND


def test_cc_timeout_is_reported(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, calls = phase_runner(
        workspace,
        cc=lambda command: timed_out(),
    )

    result = RadonTool(settings(), process_runner=runner).run(
        workspace, ["example.py"]
    )

    assert result.execution_status is ToolExecutionStatus.TIMEOUT
    assert result.error is not None
    assert result.error.error_type == "timeout"
    assert result.findings == ()
    assert result.analyzed_file_count == 0
    assert len(calls) == 1


def test_mi_failure_keeps_cc_findings(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "module.py").write_text("x = 1\n", encoding="utf-8")
    runner, calls = phase_runner(
        workspace,
        mi=lambda command: timed_out(),
    )

    result = RadonTool(settings(), process_runner=runner).run(
        workspace, ["pkg/module.py"]
    )

    assert result.execution_status is ToolExecutionStatus.TIMEOUT
    assert [finding.rule_id for finding in result.findings] == ["RADON_CC"]
    assert result.analyzed_file_count == 0
    assert len(calls) == 2


def test_cc_parse_error_is_reported(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "module.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = phase_runner(
        workspace,
        cc=lambda command: completed("not-json"),
    )

    result = RadonTool(settings(), process_runner=runner).run(
        workspace, ["pkg/module.py"]
    )

    assert result.execution_status is ToolExecutionStatus.PARSE_ERROR
    assert result.findings == ()


def test_mi_parse_error_keeps_cc_findings(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "module.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = phase_runner(
        workspace,
        mi=lambda command: completed("[]"),
    )

    result = RadonTool(settings(), process_runner=runner).run(
        workspace, ["pkg/module.py"]
    )

    assert result.execution_status is ToolExecutionStatus.PARSE_ERROR
    assert [finding.rule_id for finding in result.findings] == ["RADON_CC"]


def test_unexpected_exit_code_is_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "example.py").write_text("x = 1\n", encoding="utf-8")
    runner, _ = phase_runner(
        workspace,
        cc=lambda command: completed(cc_payload(workspace), returncode=2),
    )

    result = RadonTool(settings(), process_runner=runner).run(
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
    blocks = [("function", 1, 5, 7, "B")] * 3
    runner, _ = phase_runner(
        workspace,
        cc=lambda command: completed(cc_payload(workspace, blocks=blocks)),
    )

    result = RadonTool(
        settings(max_tool_findings=2),
        process_runner=runner,
    ).run(workspace, ["pkg/module.py"])

    assert result.execution_status is ToolExecutionStatus.FINDINGS
    assert len(result.findings) == 2
    assert result.findings_truncated is True
    assert result.truncated is True


def test_long_file_list_runs_both_phases_per_batch(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    names = ["module_a.py", "module_b.py"]
    for name in names:
        (workspace / name).write_text("x = 1\n", encoding="utf-8")

    def per_file_payload(command: list[str], phase: str) -> str:
        batch = [
            Path(argument)
            for argument in command
            if argument.endswith(".py")
        ]
        if phase == "cc":
            return json.dumps(
                {
                    str(path): [
                        {
                            "type": "function",
                            "name": "f",
                            "lineno": 1,
                            "endline": 2,
                            "complexity": 2,
                            "rank": "A",
                        }
                    ]
                    for path in batch
                }
            )
        return json.dumps(
            {str(path): {"mi": 90.0, "rank": "A"} for path in batch}
        )

    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: object) -> ProcessResult:
        calls.append(list(command))
        phase = "cc" if "cc" in command else "mi"
        return completed(per_file_payload(command, phase))

    result = RadonTool(
        settings(),
        process_runner=runner,
        max_command_chars=1,
    ).run(workspace, names)

    assert result.execution_status is ToolExecutionStatus.FINDINGS
    assert result.analyzed_file_count == 2
    assert [command[-3] for command in calls] == [
        "cc",
        "mi",
        "cc",
        "mi",
    ]
    assert len(result.findings) == 4
