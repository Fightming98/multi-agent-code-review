"""受限子进程执行器的单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.code_review.tools.process_runner import ProcessStatus, run_process


def test_run_process_captures_output_and_exit_code(tmp_path: Path) -> None:
    result = run_process(
        [sys.executable, "-c", "print('hello')"],
        cwd=tmp_path,
        timeout_seconds=30,
        stdout_limit_bytes=1024,
        stderr_limit_bytes=1024,
    )

    assert result.status is ProcessStatus.COMPLETED
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
    assert result.stdout_truncated is False
    assert result.stderr_truncated is False
    assert result.duration_ms >= 0


def test_run_process_uses_argument_array_without_shell(tmp_path: Path) -> None:
    script = (
        "import sys; print('|'.join(sys.argv[1:]))"
    )
    arguments = ["a&b", "c|d", "$HOME", "x y"]

    result = run_process(
        [sys.executable, "-c", script, *arguments],
        cwd=tmp_path,
        timeout_seconds=30,
        stdout_limit_bytes=1024,
        stderr_limit_bytes=1024,
    )

    assert result.status is ProcessStatus.COMPLETED
    assert result.stdout.strip() == "|".join(arguments)


def test_run_process_truncates_each_stream(tmp_path: Path) -> None:
    script = (
        "import sys; "
        "sys.stdout.write('a' * 200); "
        "sys.stderr.write('b' * 200)"
    )

    result = run_process(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=30,
        stdout_limit_bytes=50,
        stderr_limit_bytes=40,
    )

    assert result.status is ProcessStatus.COMPLETED
    assert len(result.stdout) == 50
    assert len(result.stderr) == 40
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True


def test_run_process_decodes_utf8_output(tmp_path: Path) -> None:
    result = run_process(
        [sys.executable, "-X", "utf8", "-c", "print('中文')"],
        cwd=tmp_path,
        timeout_seconds=30,
        stdout_limit_bytes=1024,
        stderr_limit_bytes=1024,
    )

    assert result.stdout.strip() == "中文"


def test_run_process_timeout_terminates_process(tmp_path: Path) -> None:
    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        timeout_seconds=0.5,
        stdout_limit_bytes=1024,
        stderr_limit_bytes=1024,
    )

    assert result.status is ProcessStatus.TIMEOUT
    assert result.duration_ms < 15_000


def test_run_process_missing_executable(tmp_path: Path) -> None:
    result = run_process(
        [str(tmp_path / "missing-python")],
        cwd=tmp_path,
        timeout_seconds=30,
        stdout_limit_bytes=1024,
        stderr_limit_bytes=1024,
    )

    assert result.status is ProcessStatus.NOT_FOUND
    assert result.returncode is None


def test_run_process_missing_cwd_is_os_error(tmp_path: Path) -> None:
    result = run_process(
        [sys.executable, "-c", "print('x')"],
        cwd=tmp_path / "missing",
        timeout_seconds=30,
        stdout_limit_bytes=1024,
        stderr_limit_bytes=1024,
    )

    assert result.status is ProcessStatus.OS_ERROR


def test_run_process_rejects_empty_command(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_process(
            [],
            cwd=tmp_path,
            timeout_seconds=30,
            stdout_limit_bytes=1024,
            stderr_limit_bytes=1024,
        )
