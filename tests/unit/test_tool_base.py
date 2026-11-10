"""工具层公共模型、输入校验与版本信息的单元测试。"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import pytest

from config.settings import Settings
from src.code_review.schemas.task import ErrorInfo
from src.code_review.tools.base import (
    AnalysisTool,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
)
from src.code_review.tools.process_runner import ProcessResult, ProcessStatus
from src.code_review.tools.ruff_tool import RuffTool


class _NoopTool(AnalysisTool):
    tool_name = "noop"
    module_name = "noop"
    distribution_name = "definitely-not-installed-code-review-tool"

    def run(self, workspace_path: Path, files: list[str]) -> ToolExecutionResult:
        raise NotImplementedError


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def completed(stdout: str = "[]", returncode: int = 0) -> ProcessResult:
    return ProcessResult(
        status=ProcessStatus.COMPLETED,
        returncode=returncode,
        stdout=stdout,
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=1,
    )


def test_tool_finding_accepts_valid_values() -> None:
    finding = ToolFinding(
        tool_name="ruff",
        rule_id="F401",
        file_path="pkg/module.py",
        message="unused import",
        line=3,
        end_line=3,
        column=1,
    )

    assert finding.file_path == "pkg/module.py"


@pytest.mark.parametrize(
    "file_path",
    ["/absolute/path.py", "pkg\\module.py", "../outside.py", ""],
)
def test_tool_finding_rejects_unsafe_paths(file_path: str) -> None:
    with pytest.raises(ValueError):
        ToolFinding(
            tool_name="ruff",
            rule_id="F401",
            file_path=file_path,
            message="unused import",
        )


def test_tool_finding_rejects_invalid_lines_and_message() -> None:
    with pytest.raises(ValueError):
        ToolFinding(
            tool_name="ruff",
            rule_id="F401",
            file_path="module.py",
            message="unused import",
            line=0,
        )
    with pytest.raises(ValueError):
        ToolFinding(
            tool_name="ruff",
            rule_id="F401",
            file_path="module.py",
            message="unused import",
            line=4,
            end_line=3,
        )
    with pytest.raises(ValueError):
        ToolFinding(
            tool_name="ruff",
            rule_id="F401",
            file_path="module.py",
            message="   ",
        )


def test_tool_execution_result_truncated_property() -> None:
    now = datetime.now(UTC)
    base = {
        "tool_name": "ruff",
        "tool_version": "0.17.4",
        "execution_status": ToolExecutionStatus.SUCCESS,
        "exit_code": 0,
        "started_at": now,
        "finished_at": now,
        "duration_ms": 1,
        "stdout": "[]",
        "stderr": "",
        "findings": (),
        "error": None,
    }

    assert ToolExecutionResult(**base).truncated is False
    assert ToolExecutionResult(**base, stdout_truncated=True).truncated is True
    assert ToolExecutionResult(**base, stderr_truncated=True).truncated is True
    assert ToolExecutionResult(**base, findings_truncated=True).truncated is True


def test_tool_version_uses_installed_distribution() -> None:
    tool = RuffTool(settings())

    assert tool.tool_version == metadata.version("ruff")


def test_tool_version_is_none_when_distribution_missing() -> None:
    assert _NoopTool(settings()).tool_version is None


@pytest.mark.parametrize(
    "relative",
    ["/absolute/path.py", "pkg\\module.py", "../outside.py", "README.md", ""],
)
def test_unsafe_or_unsupported_input_is_rejected_without_running(
    tmp_path: Path,
    relative: str,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    calls: list[object] = []

    def fake_runner(*args: object, **kwargs: object) -> ProcessResult:
        calls.append((args, kwargs))
        return completed()

    result = RuffTool(settings(), process_runner=fake_runner).run(
        workspace, [relative]
    )

    assert result.execution_status is ToolExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.error_type == "invalid_input"
    assert result.analyzed_file_count == 0
    assert calls == []


def test_missing_input_file_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    result = RuffTool(settings()).run(workspace, ["missing.py"])

    assert result.execution_status is ToolExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.error_type == "invalid_input"


def test_duplicate_input_paths_are_analyzed_once(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "module.py").write_text("x = 1\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_runner(command: list[str], **kwargs: object) -> ProcessResult:
        commands.append(list(command))
        return completed()

    result = RuffTool(settings(), process_runner=fake_runner).run(
        workspace, ["module.py", "module.py"]
    )

    assert result.execution_status is ToolExecutionStatus.SUCCESS
    assert result.analyzed_file_count == 1
    assert len(commands) == 1
    assert sum(part.endswith("module.py") for part in commands[0]) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_junction_escape_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "module.py").write_text("x = 1\n", encoding="utf-8")
    link = workspace / "link"

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("unable to create a Windows junction")

    try:
        tool_result = RuffTool(settings()).run(workspace, ["link/module.py"])

        assert tool_result.execution_status is ToolExecutionStatus.FAILED
        assert tool_result.error is not None
        assert tool_result.error.error_type == "invalid_input"
    finally:
        if link.exists():
            os.rmdir(link)


def test_error_info_is_and_schema_type() -> None:
    """工具错误直接使用阶段 0 合同 ErrorInfo。"""

    now = datetime.now(UTC)
    result = ToolExecutionResult(
        tool_name="ruff",
        tool_version=None,
        execution_status=ToolExecutionStatus.FAILED,
        exit_code=2,
        started_at=now,
        finished_at=now,
        duration_ms=1,
        stdout="",
        stderr="",
        findings=(),
        error=ErrorInfo(
            error_type="tool_error",
            message="failed",
            retryable=False,
        ),
    )

    assert isinstance(result.error, ErrorInfo)
