"""受限子进程执行器。

静态分析工具统一通过本模块执行：参数数组 + ``shell=False``、独立进程组、
超时终止整棵进程树、stdout/stderr 分别限流并在超限时截断标记。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_READ_CHUNK_BYTES = 64 * 1024
_JOIN_TIMEOUT_SECONDS = 5.0


class ProcessStatus(StrEnum):
    """子进程执行状态。"""

    COMPLETED = "completed"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    OS_ERROR = "os_error"


@dataclass(frozen=True)
class ProcessResult:
    """一次受限子进程执行的结果。"""

    status: ProcessStatus
    returncode: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int


def run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    stdout_limit_bytes: int,
    stderr_limit_bytes: int,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    """执行命令并返回有界结果。

    超时会终止整个进程树；输出超过上限时继续排空管道但只保留上限内的
    内容，并通过 ``stdout_truncated`` / ``stderr_truncated`` 如实标记。
    """

    args = list(command)
    if not args or not all(isinstance(part, str) for part in args):
        raise ValueError("command must be a non-empty sequence of strings")

    started = time.perf_counter()
    cwd_path = Path(cwd)
    if not cwd_path.exists() or not cwd_path.is_dir():
        return _result(
            ProcessStatus.OS_ERROR,
            None,
            b"",
            b"",
            False,
            False,
            started,
        )

    stdout_limit = max(stdout_limit_bytes, 0)
    stderr_limit = max(stderr_limit_bytes, 0)
    kwargs: dict[str, object] = {
        "cwd": str(cwd_path),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "env": _build_env(env),
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(args, **kwargs)  # type: ignore[arg-type]
    except FileNotFoundError:
        return _result(
            ProcessStatus.NOT_FOUND,
            None,
            b"",
            b"",
            False,
            False,
            started,
        )
    except OSError:
        return _result(
            ProcessStatus.OS_ERROR,
            None,
            b"",
            b"",
            False,
            False,
            started,
        )

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    stdout_flag = [False]
    stderr_flag = [False]
    threads = [
        threading.Thread(
            target=_drain,
            args=(process.stdout, stdout_limit, stdout_buffer, stdout_flag),
            daemon=True,
        ),
        threading.Thread(
            target=_drain,
            args=(process.stderr, stderr_limit, stderr_buffer, stderr_flag),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    status = ProcessStatus.COMPLETED
    try:
        process.wait(timeout=max(timeout_seconds, 0.001))
    except subprocess.TimeoutExpired:
        status = ProcessStatus.TIMEOUT
        _terminate_tree(process)
    finally:
        if process.poll() is None:
            _terminate_tree(process)
        for thread in threads:
            thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    return _result(
        status,
        process.returncode if process.returncode is not None else -1,
        bytes(stdout_buffer),
        bytes(stderr_buffer),
        stdout_flag[0],
        stderr_flag[0],
        started,
    )


def _drain(
    stream: object,
    limit: int,
    sink: bytearray,
    truncated_flag: list[bool],
) -> None:
    """持续排空管道，只保留不超过 ``limit`` 的前缀。"""

    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)  # type: ignore[attr-defined]
            if not chunk:
                break
            room = limit - len(sink)
            if room > 0:
                sink.extend(chunk[:room])
            if len(chunk) > max(room, 0):
                truncated_flag[0] = True
    except (OSError, ValueError):
        pass


def _result(
    status: ProcessStatus,
    returncode: int | None,
    stdout_bytes: bytes,
    stderr_bytes: bytes,
    stdout_truncated: bool,
    stderr_truncated: bool,
    started: float,
) -> ProcessResult:
    return ProcessResult(
        status=status,
        returncode=returncode,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
    )


def _build_env(overrides: Mapping[str, str] | None) -> dict[str, str]:
    """构造最小环境变量，避免继承与工具无关的宿主配置。"""

    env = {
        "PATH": os.environ.get("PATH", ""),
        "SystemRoot": os.environ.get("SystemRoot", ""),
        "COMSPEC": os.environ.get("COMSPEC", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "HOME": os.environ.get("HOME", ""),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "LANG": os.environ.get("LANG", ""),
        "LC_ALL": os.environ.get("LC_ALL", ""),
    }
    env = {key: value for key, value in env.items() if value}
    if overrides is not None:
        env.update(overrides)
    return env


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    """终止子进程及其后代，避免超时后残留后台进程。"""

    if process.poll() is not None:
        return

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), 9)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
