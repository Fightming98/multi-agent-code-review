"""TestRunner 安全门禁、状态映射与只读校验的单元测试。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from src.code_review.schemas.report import TestSummary as ContractTestSummary
from config.settings import Settings
from src.code_review.tools.process_runner import ProcessResult, ProcessStatus
from src.code_review.tools.test_runner import (
    TestExecutionStatus as ExecutionStatus,
)
from src.code_review.tools.test_runner import (
    TestRunner as Runner,
)
from src.code_review.tools.trusted_fixture import verify_trusted_fixture
from tests.fixture_factory import make_trusted_fixture

FIXTURE_FILES = {
    "calc/__init__.py": "from .core import add\n",
    "calc/core.py": "def add(a, b):\n    return a + b\n",
    "tests/test_core.py": "def test_add():\n    assert True\n",
}


class RecordingRunner:
    def __init__(
        self,
        handler: Callable[[list[str], Mapping[str, object]], ProcessResult],
    ) -> None:
        self.calls: list[list[str]] = []
        self.cwds: list[object] = []
        self.envs: list[object] = []
        self._handler = handler

    def __call__(
        self,
        command: list[str],
        **kwargs: object,
    ) -> ProcessResult:
        self.calls.append(list(command))
        self.cwds.append(kwargs.get("cwd"))
        self.envs.append(kwargs.get("env"))
        return self._handler(list(command), kwargs)


def completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stdout_truncated: bool = False,
) -> ProcessResult:
    return ProcessResult(
        status=ProcessStatus.COMPLETED,
        returncode=returncode,
        stdout=stdout,
        stderr="",
        stdout_truncated=stdout_truncated,
        stderr_truncated=False,
        duration_ms=1,
    )


def process_status(status: ProcessStatus) -> ProcessResult:
    return ProcessResult(
        status=status,
        returncode=None,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=1,
    )


def arg_after(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def junit_body(
    cases: list[tuple[str, str, str | None]],
) -> bytes:
    body: list[str] = []
    for name, outcome, message in cases:
        if outcome == "passed":
            body.append(
                f'<testcase classname="tests.test_core" name="{escape(name)}" />'
            )
        elif outcome == "failed":
            body.append(
                f'<testcase classname="tests.test_core" name="{escape(name)}">'
                f'<failure message="{escape(message or "failed")}" '
                f'type="AssertionError">trace</failure></testcase>'
            )
        elif outcome == "error":
            body.append(
                f'<testcase classname="tests.test_core" name="{escape(name)}">'
                f'<error message="{escape(message or "error")}" '
                'type="RuntimeError" /></testcase>'
            )
        else:
            body.append(
                f'<testcase classname="tests.test_core" name="{escape(name)}">'
                f'<skipped message="{escape(message or "skipped")}" />'
                "</testcase>"
            )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<testsuites><testsuite>"
        + "".join(body)
        + "</testsuite></testsuites>"
    ).encode("utf-8")


def coverage_body(root: Path, percent: float = 90.0) -> bytes:
    return json.dumps(
        {
            "meta": {"version": "7.17.2"},
            "totals": {"percent_covered": percent},
            "files": {
                str(root / "calc" / "core.py"): {
                    "summary": {
                        "percent_covered": percent,
                        "covered_lines": 1,
                        "num_statements": 1,
                    },
                    "missing_lines": [],
                }
            },
        }
    ).encode("utf-8")


def success_handler(
    root: Path,
    *,
    cases: list[tuple[str, str, str | None]] | None = None,
    pytest_returncode: int = 0,
    pytest_stdout: str = "",
    pytest_stdout_truncated: bool = False,
    coverage_percent: float = 90.0,
    mutate: bool = False,
    write_junit: bool = True,
    write_coverage: bool = True,
    coverage_returncode: int = 0,
    coverage_status: ProcessStatus | None = None,
) -> Callable[[list[str], Mapping[str, object]], ProcessResult]:
    cases = cases or [("test_add", "passed", None)]

    def handler(
        command: list[str],
        kwargs: Mapping[str, object],
    ) -> ProcessResult:
        if "run" in command and "pytest" in command:
            if mutate:
                (root / "MUTATION.txt").write_bytes(b"mutated\n")
            if write_junit:
                Path(arg_after(command, "--junitxml")).write_bytes(
                    junit_body(cases)
                )
            return completed(
                returncode=pytest_returncode,
                stdout=pytest_stdout,
                stdout_truncated=pytest_stdout_truncated,
            )
        if "json" in command:
            if coverage_status is not None:
                return process_status(coverage_status)
            if write_coverage:
                Path(arg_after(command, "-o")).write_bytes(
                    coverage_body(root, coverage_percent)
                )
            return completed(returncode=coverage_returncode)
        raise AssertionError(f"unexpected command: {command}")

    return handler


def build_runner(
    tmp_path: Path,
    handler: Callable[[list[str], Mapping[str, object]], ProcessResult],
    **settings_overrides: object,
) -> tuple[Runner, RecordingRunner, Path]:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(handler)
    settings = Settings(_env_file=None, **settings_overrides)
    runner = Runner(
        settings,
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )
    return runner, recording, root


def test_external_repository_is_not_executed(tmp_path: Path) -> None:
    def handler(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("external repository must not start a process")

    runner = Runner(
        Settings(_env_file=None),
        fixture_root=tmp_path / "missing",
        allow_custom_fixture_root=True,
        process_runner=RecordingRunner(handler),
    )

    result = runner.execute(trusted_fixture=None)

    assert result.status is ExecutionStatus.NOT_EXECUTED
    assert result.summary.execution_status == "not_executed"
    assert result.summary.passed is None
    assert result.summary.failed is None
    assert result.summary.skipped is None
    assert result.summary.coverage is None
    assert result.summary.source is None
    assert result.summary.reason
    assert result.fixture_name is None
    assert result.read_only_verified is None
    assert result.pytest_version is None
    assert result.coverage_version is None
    assert result.error is None


def test_custom_fixture_root_requires_explicit_opt_in(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="test-only"):
        Runner(
            Settings(_env_file=None),
            fixture_root=tmp_path / "fixture",
        )


def test_unapproved_fixture_name_is_refused(tmp_path: Path) -> None:
    def handler(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("unapproved fixture must not start a process")

    recording = RecordingRunner(handler)
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=tmp_path / "missing",
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="pallets/itsdangerous")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "not_executed"
    assert result.error is not None
    assert result.error.error_type == "invalid_input"
    assert recording.calls == []


def test_configured_fixture_name_cannot_widen_allowlist(
    tmp_path: Path,
) -> None:
    root = make_trusted_fixture(
        tmp_path / "fixture",
        FIXTURE_FILES,
        name="other_fixture",
    )

    def handler(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("unapproved fixture must not start a process")

    recording = RecordingRunner(handler)
    runner = Runner(
        Settings(_env_file=None, trusted_fixture_name="other_fixture"),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="other_fixture")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "not_executed"
    assert result.error is not None
    assert result.error.error_type == "invalid_input"
    assert recording.calls == []


def test_tampered_fixture_is_not_executed(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    (root / "calc" / "core.py").write_bytes(b"tampered = True\n")

    def handler(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("tampered fixture must not start a process")

    recording = RecordingRunner(handler)
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "not_executed"
    assert result.error is not None
    assert result.error.error_type == "invalid_input"
    assert recording.calls == []


def test_missing_fixture_is_not_executed(tmp_path: Path) -> None:
    def handler(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("missing fixture must not start a process")

    recording = RecordingRunner(handler)
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=tmp_path / "missing",
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "not_executed"
    assert result.error is not None
    assert recording.calls == []


def test_fixture_without_tests_directory_is_not_executed(
    tmp_path: Path,
) -> None:
    root = make_trusted_fixture(
        tmp_path / "fixture",
        {"calc/__init__.py": ""},
    )

    def handler(*args: object, **kwargs: object) -> ProcessResult:
        raise AssertionError("fixture without tests must not start a process")

    recording = RecordingRunner(handler)
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "not_executed"
    assert result.error is not None
    assert result.error.error_type == "invalid_input"
    assert recording.calls == []


def test_valid_fixture_executes_pytest_and_coverage(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(
        success_handler(
            root,
            cases=[
                ("test_add", "passed", None),
                ("test_skipped", "skipped", "not today"),
            ],
        )
    )
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.EXECUTED
    assert isinstance(result.summary, ContractTestSummary)
    assert result.summary.execution_status == "executed"
    assert result.summary.passed == 1
    assert result.summary.failed == 0
    assert result.summary.skipped == 1
    assert result.summary.coverage == 90.0
    assert result.summary.source == "pytest+coverage"
    assert result.collected_tests == 2
    assert result.fixture_name == "trusted_fixture_v1"
    assert result.fixture_version == "1.0.0"
    assert result.fixture_manifest_sha256 is not None
    assert result.read_only_verified is True
    assert result.modified_paths == ()
    assert result.exit_code == 0
    assert result.coverage_exit_code == 0
    assert result.pytest_version is not None
    assert result.coverage_version is not None
    assert result.error is None
    assert len(recording.calls) == 2

    pytest_command = recording.calls[0]
    assert "--source" in pytest_command
    assert "--omit" in pytest_command
    omit = arg_after(pytest_command, "--omit")
    assert omit.startswith(root.resolve().as_posix())
    assert "*/tests/*" not in omit
    assert "no:cacheprovider" in pytest_command
    assert "--rootdir" in pytest_command
    assert "--junitxml" in pytest_command
    assert "--basetemp" in pytest_command
    assert str(root.resolve()) == str(recording.envs[0]["PYTHONPATH"])
    assert recording.envs[0]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert recording.cwds[0] != root


def test_report_record_limit_is_applied(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    cases = [(f"test_{index}", "passed", None) for index in range(5)]
    recording = RecordingRunner(success_handler(root, cases=cases))
    runner = Runner(
        Settings(_env_file=None, max_test_records=2),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.EXECUTED
    assert result.collected_tests == 5
    assert result.summary.passed == 5
    assert len(result.test_records) == 2
    assert result.test_records_truncated is True
    assert result.truncated is True


def test_failed_tests_are_executed_not_tool_failure(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(
        success_handler(
            root,
            cases=[
                ("test_add", "passed", None),
                ("test_fail", "failed", "boom"),
            ],
            pytest_returncode=1,
        )
    )
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.EXECUTED
    assert result.summary.execution_status == "executed"
    assert result.summary.failed == 1
    assert result.summary.passed == 1
    assert result.has_failed_tests is True
    assert result.error is None


def test_pytest_timeout_is_reported_as_timeout(tmp_path: Path) -> None:
    runner, recording, _ = build_runner(
        tmp_path,
        lambda command, kwargs: process_status(ProcessStatus.TIMEOUT),
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.TIMEOUT
    assert result.summary.execution_status == "failed"
    assert result.summary.passed is None
    assert result.summary.coverage is None
    assert result.error is not None
    assert result.error.error_type == "timeout"
    assert result.error.retryable is True
    assert result.read_only_verified is True
    assert len(recording.calls) == 1


def test_pytest_not_found_is_not_executed(tmp_path: Path) -> None:
    runner, recording, _ = build_runner(
        tmp_path,
        lambda command, kwargs: process_status(ProcessStatus.NOT_FOUND),
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "not_executed"
    assert result.error is not None
    assert result.error.error_type == "tool_error"
    assert len(recording.calls) == 1


def test_pytest_os_error_is_not_executed(tmp_path: Path) -> None:
    runner, _, _ = build_runner(
        tmp_path,
        lambda command, kwargs: process_status(ProcessStatus.OS_ERROR),
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "not_executed"
    assert result.error is not None


def test_unexpected_pytest_exit_code_is_failure(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(
        success_handler(root, write_junit=False, pytest_returncode=2)
    )
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert result.error is not None
    assert result.error.details["exit_code"] == 2


def test_no_tests_collected_is_failure(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(
        success_handler(root, write_junit=False, pytest_returncode=5)
    )
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert result.summary.reason is not None
    assert "no tests" in result.summary.reason


def test_missing_junit_report_is_failure(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(success_handler(root, write_junit=False))
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert result.error is not None
    assert result.error.details["stage"] == "junit"
    assert len(recording.calls) == 1


def test_junit_size_limit_fails_without_coverage_run(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    cases = [(f"test_{index}", "passed", None) for index in range(50)]
    recording = RecordingRunner(success_handler(root, cases=cases))
    runner = Runner(
        Settings(_env_file=None, max_test_output_bytes=1024),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert "size limit" in (result.summary.reason or "")
    assert len(recording.calls) == 1


def test_coverage_timeout_is_reported(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(
        success_handler(root, coverage_status=ProcessStatus.TIMEOUT)
    )
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.TIMEOUT
    assert result.summary.execution_status == "failed"
    assert result.summary.passed == 1
    assert result.summary.coverage is None
    assert result.summary.source == "pytest"
    assert result.error is not None
    assert result.error.error_type == "timeout"
    assert result.error.details["stage"] == "coverage"


def test_coverage_failure_is_reported(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(
        success_handler(
            root,
            write_coverage=False,
            coverage_returncode=1,
        )
    )
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert result.summary.passed == 1
    assert result.summary.coverage is None
    assert result.summary.source == "pytest"
    assert result.error is not None
    assert result.error.details["stage"] == "coverage"


def test_coverage_missing_report_is_reported(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(
        success_handler(root, write_coverage=False)
    )
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert result.error is not None
    assert result.error.details["stage"] == "coverage"


def test_coverage_parse_error_is_reported(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)

    def handler(
        command: list[str],
        kwargs: Mapping[str, object],
    ) -> ProcessResult:
        if "run" in command and "pytest" in command:
            Path(arg_after(command, "--junitxml")).write_bytes(
                junit_body([("test_add", "passed", None)])
            )
            return completed()
        Path(arg_after(command, "-o")).write_bytes(b"{not-json")
        return completed()

    recording = RecordingRunner(handler)
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert result.error is not None
    assert result.error.details["stage"] == "coverage"


def test_read_only_violation_is_detected(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(success_handler(root, mutate=True))
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert result.summary.passed == 1
    assert result.read_only_verified is False
    assert "MUTATION.txt" in result.modified_paths
    assert result.error is not None
    assert result.error.error_type == "read_only_violation"


def test_output_truncation_is_marked(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    recording = RecordingRunner(
        success_handler(root, pytest_stdout="x" * 25_000)
    )
    runner = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
        process_runner=recording,
    )

    result = runner.execute(trusted_fixture="trusted_fixture_v1")

    assert result.status is ExecutionStatus.EXECUTED
    assert result.stdout_truncated is True
    assert len(result.stdout) <= 20_000 + 100
    assert "output truncated" in result.stdout
    assert result.truncated is True


def test_verified_fixture_exposes_only_relative_metadata(tmp_path: Path) -> None:
    root = make_trusted_fixture(tmp_path / "fixture", FIXTURE_FILES)
    verified = verify_trusted_fixture(
        root,
        expected_name="trusted_fixture_v1",
    )

    assert verified.file_count == 3
    assert all(not path.startswith("/") for path in verified.file_hashes)
    assert all("\\" not in path for path in verified.file_hashes)
