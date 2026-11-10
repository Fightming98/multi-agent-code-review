"""可信 Fixture 的 Pytest / Coverage.py 受限执行与结果解析。

安全边界：

- 只有通过 :mod:`trusted_fixture` 哈希校验的项目自维护 Fixture 才会被启动；
- 外部仓库调用 ``execute(trusted_fixture=None)`` 时只返回 ``not_executed``，
  不创建进程；
- Fixture 进程使用仓库外临时工作目录、最小环境变量、禁用第三方 Pytest
  插件自动加载，禁止生成 ``.pytest_cache`` 与字节码；
- Coverage 数据文件、JUnit XML 与 JSON 报告都写在 Fixture 之外；
- 执行前后对 Fixture 做 SHA-256 快照，任何变化都判定只读边界失败；
- 结果进入 ``TestExecutionResult``，其中 ``summary`` 直接使用阶段 0 合同
  ``TestSummary``，未执行时严格保持 null 语义。
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

from code_review.schemas.report import TestSummary
from code_review.schemas.task import ErrorInfo
from config.settings import Settings

from .base import ProcessRunner, ToolOutputParseError, relative_posix_path
from .process_runner import ProcessResult, ProcessStatus, run_process
from .trusted_fixture import (
    DEFAULT_TRUSTED_FIXTURE_ROOT,
    TrustedFixture,
    TrustedFixtureError,
    verify_trusted_fixture,
)
from .workspace_snapshot import (
    SnapshotDiff,
    WorkspaceSnapshot,
    WorkspaceSnapshotError,
    compare_snapshots,
    snapshot_workspace,
)

_MAX_TEST_NAME_CHARS = 300
_MAX_TEST_MESSAGE_CHARS = 2_000
_MAX_REASON_CHARS = 500
_MAX_STORED_OUTPUT_CHARS = 20_000
_MAX_MODIFIED_PATHS = 50
_OUTPUT_TRUNCATION_MARKER = "\n... [output truncated]"

_PYTEST_EXIT_SUCCESS = 0
_PYTEST_EXIT_TESTS_FAILED = 1
_PYTEST_EXIT_NO_TESTS = 5
_PYTEST_ALLOWED_EXIT_CODES = frozenset(
    {_PYTEST_EXIT_SUCCESS, _PYTEST_EXIT_TESTS_FAILED}
)


def _coverage_omit_patterns(fixture_root: Path) -> str:
    """只排除 Fixture 自己的测试文件，避免误伤路径中含 ``tests`` 的源码。

    项目 Fixture 位于仓库的 ``tests/fixtures/trusted_repo/`` 下，使用
    ``*/tests/*`` 这类通配模式会把 ``tests/fixtures/...`` 中的全部源码一起
    排除，导致 Coverage 报 "No data was collected"。因此这里使用以
    Fixture 根目录为前缀的绝对模式。
    """

    root = fixture_root.as_posix()
    return ",".join(
        (
            f"{root}/tests/*",
            f"{root}/test_*.py",
            f"{root}/conftest.py",
        )
    )


class TestReportParseError(ValueError):
    """Pytest / Coverage 的机器可读输出无法解析。"""


class TestExecutionStatus(StrEnum):
    """测试执行工具层状态；与合同 ``TestSummary.execution_status`` 不同。"""

    EXECUTED = "executed"
    NOT_EXECUTED = "not_executed"
    TIMEOUT = "timeout"
    FAILED = "failed"


@dataclass(frozen=True)
class TestRecord:
    """单条测试结果的摘要，不包含完整 traceback。"""

    name: str
    outcome: str
    file_path: str | None = None
    line: int | None = None
    duration_seconds: float | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("test record name must not be empty")
        if self.outcome not in {"passed", "failed", "error", "skipped"}:
            raise ValueError("test record outcome is invalid")
        if self.file_path is not None:
            _validate_relative_path(self.file_path)
        if self.line is not None and self.line < 1:
            raise ValueError("test record line must be positive")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("test record duration must not be negative")
        if self.message is not None and not self.message.strip():
            raise ValueError("test record message must not be empty")


@dataclass(frozen=True)
class PytestReport:
    """解析后的 JUnit XML 测试摘要。"""

    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float
    records: tuple[TestRecord, ...]
    records_truncated: bool

    @property
    def failure_count(self) -> int:
        return self.failed + self.errors


@dataclass(frozen=True)
class CoverageFileReport:
    """单个文件的覆盖率摘要。"""

    file_path: str
    percent_covered: float
    covered_lines: int
    num_statements: int
    missing_lines: tuple[int, ...]

    def __post_init__(self) -> None:
        _validate_relative_path(self.file_path)
        if not 0.0 <= self.percent_covered <= 100.0:
            raise ValueError("coverage percentage must be within 0..100")
        if self.covered_lines < 0 or self.num_statements < 0:
            raise ValueError("coverage line counts must not be negative")
        if self.covered_lines > self.num_statements:
            raise ValueError("covered lines must not exceed statements")
        if any(line < 1 for line in self.missing_lines):
            raise ValueError("missing line numbers must be positive")


@dataclass(frozen=True)
class CoverageReport:
    """解析后的 Coverage JSON 摘要。"""

    percent_covered: float
    files: tuple[CoverageFileReport, ...]
    files_truncated: bool


@dataclass(frozen=True)
class TestExecutionResult:
    """一次测试执行（或未执行判定）的完整结果。"""

    status: TestExecutionStatus
    summary: TestSummary
    fixture_name: str | None
    fixture_version: str | None
    fixture_manifest_sha256: str | None
    collected_tests: int | None
    test_records: tuple[TestRecord, ...]
    test_records_truncated: bool
    coverage_files: tuple[CoverageFileReport, ...]
    coverage_files_truncated: bool
    read_only_verified: bool | None
    modified_paths: tuple[str, ...]
    pytest_version: str | None
    coverage_version: str | None
    exit_code: int | None
    coverage_exit_code: int | None
    test_duration_seconds: float | None
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    error: ErrorInfo | None

    @property
    def truncated(self) -> bool:
        return (
            self.stdout_truncated
            or self.stderr_truncated
            or self.test_records_truncated
            or self.coverage_files_truncated
        )

    @property
    def has_failed_tests(self) -> bool:
        return self.summary.failed is not None and self.summary.failed > 0


class TestRunner:
    """在可信 Fixture 上执行 Pytest / Coverage.py。

    生产调用必须使用 ``tests/fixtures/trusted_repo/`` 默认路径。测试注入其他
    Fixture 根目录时，必须显式传入 ``allow_custom_fixture_root=True``，避免
    调用方把外部仓库路径当作可信 Fixture 执行。
    """

    def __init__(
        self,
        settings: Settings,
        *,
        fixture_root: Path | None = None,
        allow_custom_fixture_root: bool = False,
        python_executable: str | None = None,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self.settings = settings
        if fixture_root is None:
            self.fixture_root = DEFAULT_TRUSTED_FIXTURE_ROOT
        else:
            candidate = Path(fixture_root).expanduser()
            if (
                not allow_custom_fixture_root
                and candidate != DEFAULT_TRUSTED_FIXTURE_ROOT
            ):
                raise ValueError(
                    "custom trusted fixture roots are test-only and require "
                    "allow_custom_fixture_root=True"
                )
            self.fixture_root = candidate
        self.python_executable = python_executable or sys.executable
        self._process_runner = process_runner or run_process

    @property
    def pytest_version(self) -> str | None:
        return _distribution_version("pytest")

    @property
    def coverage_version(self) -> str | None:
        return _distribution_version("coverage")

    def execute(self, *, trusted_fixture: str | None = None) -> TestExecutionResult:
        """执行一次测试任务。

        ``trusted_fixture=None`` 表示外部仓库：不执行任何测试，返回
        ``not_executed``。只有与配置名称完全一致的已校验 Fixture 才会被启动。
        """

        started_at = datetime.now(UTC)
        started_clock = time.perf_counter()

        if trusted_fixture is None:
            return self._not_executed(
                reason=(
                    "external repository: test execution is not permitted "
                    "without a sandbox; tests remain not_executed"
                ),
                status=TestExecutionStatus.NOT_EXECUTED,
                fixture_name=None,
                error=None,
                started_at=started_at,
                started_clock=started_clock,
            )

        if trusted_fixture != self.settings.trusted_fixture_name:
            return self._not_executed(
                reason=(
                    "only the configured trusted fixture may be executed; "
                    "no test was run"
                ),
                status=TestExecutionStatus.FAILED,
                fixture_name=None,
                error=ErrorInfo(
                    error_type="invalid_input",
                    message="trusted fixture name is not approved",
                    retryable=False,
                    details={"reason": "unapproved_fixture"},
                ),
                started_at=started_at,
                started_clock=started_clock,
            )

        try:
            fixture = verify_trusted_fixture(
                self.fixture_root,
                expected_name=self.settings.trusted_fixture_name,
            )
        except TrustedFixtureError as exc:
            return self._not_executed(
                reason=(
                    "trusted fixture integrity verification failed; "
                    "no test was run"
                ),
                status=TestExecutionStatus.FAILED,
                fixture_name=trusted_fixture,
                error=ErrorInfo(
                    error_type="invalid_input",
                    message=_truncate(str(exc), _MAX_REASON_CHARS),
                    retryable=False,
                    details={"reason": "fixture_integrity_failure"},
                ),
                started_at=started_at,
                started_clock=started_clock,
            )

        tests_dir = fixture.root / "tests"
        if not tests_dir.is_dir():
            return self._not_executed(
                reason=(
                    "trusted fixture does not contain a tests directory; "
                    "no test was run"
                ),
                status=TestExecutionStatus.FAILED,
                fixture_name=trusted_fixture,
                error=ErrorInfo(
                    error_type="invalid_input",
                    message="trusted fixture tests directory is missing",
                    retryable=False,
                    details={"reason": "fixture_layout_invalid"},
                ),
                started_at=started_at,
                started_clock=started_clock,
            )

        try:
            before = snapshot_workspace(fixture.root, excluded_dirs=())
        except WorkspaceSnapshotError:
            return self._not_executed(
                reason=(
                    "trusted fixture could not be snapshotted; "
                    "no test was run"
                ),
                status=TestExecutionStatus.FAILED,
                fixture_name=trusted_fixture,
                error=ErrorInfo(
                    error_type="tool_error",
                    message="trusted fixture snapshot failed",
                    retryable=False,
                    details={"stage": "read_only"},
                ),
                started_at=started_at,
                started_clock=started_clock,
            )

        try:
            with tempfile.TemporaryDirectory(
                prefix="code-review-tests-",
                ignore_cleanup_errors=True,
            ) as temp_name:
                return self._execute_in_temp(
                    fixture=fixture,
                    tests_dir=tests_dir,
                    before=before,
                    temp_root=Path(temp_name),
                    started_at=started_at,
                    started_clock=started_clock,
                )
        except OSError:
            return self._not_executed(
                reason=(
                    "test workspace could not be created; no test was run"
                ),
                status=TestExecutionStatus.FAILED,
                fixture_name=trusted_fixture,
                error=ErrorInfo(
                    error_type="tool_error",
                    message="test workspace could not be created",
                    retryable=False,
                    details={"stage": "workspace"},
                ),
                started_at=started_at,
                started_clock=started_clock,
            )

    def _execute_in_temp(
        self,
        *,
        fixture: TrustedFixture,
        tests_dir: Path,
        before: WorkspaceSnapshot,
        temp_root: Path,
        started_at: datetime,
        started_clock: float,
    ) -> TestExecutionResult:
        pytest_ini = temp_root / "pytest.ini"
        coverage_rc = temp_root / "coverage.rc"
        pytest_tmp = temp_root / "pytest-tmp"
        junit_path = temp_root / "junit.xml"
        coverage_json_path = temp_root / "coverage.json"
        coverage_data_path = temp_root / ".coverage"

        pytest_ini.write_bytes(b"[pytest]\n")
        coverage_rc.write_bytes(b"[run]\nbranch = False\n")
        pytest_tmp.mkdir()

        environment = {
            "PYTHONPATH": str(fixture.root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONHASHSEED": "0",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "COVERAGE_FILE": str(coverage_data_path),
        }

        pytest_command = [
            self.python_executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "coverage",
            "run",
            "--rcfile",
            str(coverage_rc),
            "--source",
            str(fixture.root),
            "--omit",
            _coverage_omit_patterns(fixture.root),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            str(pytest_ini),
            "--rootdir",
            str(fixture.root),
            "--junitxml",
            str(junit_path),
            "--basetemp",
            str(pytest_tmp),
            str(tests_dir),
        ]

        try:
            pytest_process = self._process_runner(
                pytest_command,
                cwd=temp_root,
                timeout_seconds=self.settings.pytest_timeout_seconds,
                stdout_limit_bytes=self.settings.max_test_output_bytes,
                stderr_limit_bytes=self.settings.max_test_output_bytes,
                env=environment,
            )
        except Exception:  # noqa: BLE001 - 执行器异常必须转为失败结果
            pytest_process = _os_error_process()

        junit_report: PytestReport | None = None
        junit_error: str | None = None
        if (
            pytest_process.status is ProcessStatus.COMPLETED
            and pytest_process.returncode is not None
        ):
            if junit_path.is_file():
                try:
                    junit_report = parse_junit_xml(
                        junit_path,
                        fixture.root,
                        max_bytes=self.settings.max_test_output_bytes,
                        max_records=self.settings.max_test_records,
                        temp_root=temp_root,
                    )
                except TestReportParseError as exc:
                    junit_error = str(exc)
            elif pytest_process.returncode in _PYTEST_ALLOWED_EXIT_CODES:
                junit_error = "pytest did not produce a JUnit report"

        coverage_process: ProcessResult | None = None
        coverage_report: CoverageReport | None = None
        coverage_error: str | None = None
        coverage_timeout = False
        should_run_coverage = (
            pytest_process.status is ProcessStatus.COMPLETED
            and pytest_process.returncode in _PYTEST_ALLOWED_EXIT_CODES
            and junit_report is not None
            and junit_report.total > 0
            and junit_error is None
        )
        if should_run_coverage:
            coverage_command = [
                self.python_executable,
                "-B",
                "-X",
                "utf8",
                "-m",
                "coverage",
                "json",
                "--rcfile",
                str(coverage_rc),
                "-o",
                str(coverage_json_path),
            ]
            try:
                coverage_process = self._process_runner(
                    coverage_command,
                    cwd=temp_root,
                    timeout_seconds=self.settings.coverage_timeout_seconds,
                    stdout_limit_bytes=self.settings.max_test_output_bytes,
                    stderr_limit_bytes=self.settings.max_test_output_bytes,
                    env={
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONNOUSERSITE": "1",
                        "PYTHONIOENCODING": "utf-8",
                        "COVERAGE_FILE": str(coverage_data_path),
                    },
                )
            except Exception:  # noqa: BLE001 - 执行器异常必须转为失败结果
                coverage_process = _os_error_process()

            if coverage_process.status is ProcessStatus.TIMEOUT:
                coverage_timeout = True
            elif coverage_process.status is not ProcessStatus.COMPLETED:
                coverage_error = "coverage command could not be started"
            elif coverage_process.returncode != 0:
                coverage_error = (
                    "coverage command exited with status "
                    f"{coverage_process.returncode}"
                )
            elif not coverage_json_path.is_file():
                coverage_error = "coverage did not produce a JSON report"
            else:
                try:
                    coverage_report = parse_coverage_json(
                        coverage_json_path,
                        fixture.root,
                        max_bytes=self.settings.max_test_output_bytes,
                        max_files=self.settings.max_coverage_files,
                    )
                except TestReportParseError as exc:
                    coverage_error = str(exc)

        try:
            after = snapshot_workspace(fixture.root, excluded_dirs=())
            diff = compare_snapshots(before, after)
            read_only_error = False
        except WorkspaceSnapshotError:
            diff = None
            read_only_error = True

        return self._finalize(
            fixture=fixture,
            pytest_process=pytest_process,
            junit_report=junit_report,
            junit_error=junit_error,
            coverage_process=coverage_process,
            coverage_report=coverage_report,
            coverage_error=coverage_error,
            coverage_timeout=coverage_timeout,
            diff=diff,
            read_only_error=read_only_error,
            temp_root=temp_root,
            started_at=started_at,
            started_clock=started_clock,
        )

    def _finalize(
        self,
        *,
        fixture: TrustedFixture,
        pytest_process: ProcessResult,
        junit_report: PytestReport | None,
        junit_error: str | None,
        coverage_process: ProcessResult | None,
        coverage_report: CoverageReport | None,
        coverage_error: str | None,
        coverage_timeout: bool,
        diff: SnapshotDiff | None,
        read_only_error: bool,
        temp_root: Path,
        started_at: datetime,
        started_clock: float,
    ) -> TestExecutionResult:
        modified_paths = (
            tuple(diff.paths[:_MAX_MODIFIED_PATHS])
            if diff is not None and diff.changed
            else ()
        )
        read_only_verified = not read_only_error and not modified_paths

        if read_only_error:
            status = TestExecutionStatus.FAILED
            summary = _failed_summary(
                "workspace read-only verification could not be completed",
                junit_report,
                coverage_report,
            )
            error = ErrorInfo(
                error_type="tool_error",
                message="workspace read-only verification failed",
                retryable=False,
                details={"stage": "read_only"},
            )
        elif modified_paths:
            status = TestExecutionStatus.FAILED
            summary = _failed_summary(
                "workspace was modified during test execution",
                junit_report,
                coverage_report,
            )
            error = ErrorInfo(
                error_type="read_only_violation",
                message="workspace was modified during test execution",
                retryable=False,
                details={
                    "modified_count": len(diff.paths) if diff is not None else 0,
                    "paths": list(modified_paths[:20]),
                },
            )
        else:
            status, summary, error = self._execution_outcome(
                pytest_process=pytest_process,
                junit_report=junit_report,
                junit_error=junit_error,
                coverage_report=coverage_report,
                coverage_error=coverage_error,
                coverage_timeout=coverage_timeout,
            )

        stdout, stdout_cut = _sanitize_output(
            pytest_process.stdout,
            fixture.root,
            temp_root,
        )
        stderr, stderr_cut = _sanitize_output(
            pytest_process.stderr,
            fixture.root,
            temp_root,
        )

        return TestExecutionResult(
            status=status,
            summary=summary,
            fixture_name=fixture.name,
            fixture_version=fixture.version,
            fixture_manifest_sha256=fixture.manifest_sha256,
            collected_tests=(
                junit_report.total if junit_report is not None else None
            ),
            test_records=(
                junit_report.records if junit_report is not None else ()
            ),
            test_records_truncated=(
                junit_report.records_truncated
                if junit_report is not None
                else False
            ),
            coverage_files=(
                coverage_report.files if coverage_report is not None else ()
            ),
            coverage_files_truncated=(
                coverage_report.files_truncated
                if coverage_report is not None
                else False
            ),
            read_only_verified=read_only_verified,
            modified_paths=modified_paths,
            pytest_version=self.pytest_version,
            coverage_version=self.coverage_version,
            exit_code=pytest_process.returncode,
            coverage_exit_code=(
                coverage_process.returncode
                if coverage_process is not None
                else None
            ),
            test_duration_seconds=(
                junit_report.duration_seconds
                if junit_report is not None
                else None
            ),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            duration_ms=max(
                0,
                int((time.perf_counter() - started_clock) * 1000),
            ),
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=pytest_process.stdout_truncated or stdout_cut,
            stderr_truncated=pytest_process.stderr_truncated or stderr_cut,
            error=error,
        )

    def _execution_outcome(
        self,
        *,
        pytest_process: ProcessResult,
        junit_report: PytestReport | None,
        junit_error: str | None,
        coverage_report: CoverageReport | None,
        coverage_error: str | None,
        coverage_timeout: bool,
    ) -> tuple[TestExecutionStatus, TestSummary, ErrorInfo | None]:
        if pytest_process.status is ProcessStatus.TIMEOUT:
            reason = (
                "pytest execution timed out after "
                f"{self.settings.pytest_timeout_seconds} seconds"
            )
            return (
                TestExecutionStatus.TIMEOUT,
                _failed_summary(reason, None, None),
                ErrorInfo(
                    error_type="timeout",
                    message="pytest execution timed out",
                    retryable=True,
                    details={
                        "stage": "pytest",
                        "timeout_seconds": self.settings.pytest_timeout_seconds,
                    },
                ),
            )

        if pytest_process.status is ProcessStatus.NOT_FOUND:
            return (
                TestExecutionStatus.FAILED,
                _not_executed_summary(
                    "pytest or coverage executable was not found; "
                    "no test was run"
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="pytest or coverage executable was not found",
                    retryable=False,
                    details={"stage": "pytest"},
                ),
            )

        if pytest_process.status is ProcessStatus.OS_ERROR:
            return (
                TestExecutionStatus.FAILED,
                _not_executed_summary(
                    "test process could not be started; no test was run"
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="test process could not be started",
                    retryable=False,
                    details={"stage": "pytest"},
                ),
            )

        return_code = pytest_process.returncode
        if return_code == _PYTEST_EXIT_NO_TESTS:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    "pytest collected no tests",
                    junit_report,
                    coverage_report,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="pytest collected no tests",
                    retryable=False,
                    details={"stage": "pytest", "exit_code": return_code},
                ),
            )

        if return_code not in _PYTEST_ALLOWED_EXIT_CODES:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    "pytest exited with an unexpected status",
                    junit_report,
                    coverage_report,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="pytest exited with an unexpected status",
                    retryable=False,
                    details={"stage": "pytest", "exit_code": return_code},
                ),
            )

        if junit_error is not None:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    f"pytest report could not be read: {junit_error}",
                    junit_report,
                    coverage_report,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="pytest report could not be read",
                    retryable=False,
                    details={"stage": "junit"},
                ),
            )

        if junit_report is None:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    "pytest did not produce a JUnit report",
                    None,
                    coverage_report,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="pytest did not produce a JUnit report",
                    retryable=False,
                    details={"stage": "junit"},
                ),
            )

        if junit_report.total == 0:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    "pytest collected no tests",
                    junit_report,
                    coverage_report,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="pytest collected no tests",
                    retryable=False,
                    details={"stage": "pytest", "exit_code": return_code},
                ),
            )

        if return_code == _PYTEST_EXIT_SUCCESS and junit_report.failure_count:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    "pytest report is inconsistent with a successful exit code",
                    junit_report,
                    coverage_report,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="pytest report is inconsistent with its exit code",
                    retryable=False,
                    details={"stage": "pytest", "exit_code": return_code},
                ),
            )

        if return_code == _PYTEST_EXIT_TESTS_FAILED and not junit_report.failure_count:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    "pytest exited with failure but reported no failed tests",
                    junit_report,
                    coverage_report,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="pytest exit code is inconsistent with its report",
                    retryable=False,
                    details={"stage": "pytest", "exit_code": return_code},
                ),
            )

        if coverage_timeout:
            reason = (
                "coverage report timed out after "
                f"{self.settings.coverage_timeout_seconds} seconds"
            )
            return (
                TestExecutionStatus.TIMEOUT,
                _failed_summary(reason, junit_report, None),
                ErrorInfo(
                    error_type="timeout",
                    message="coverage report timed out",
                    retryable=True,
                    details={
                        "stage": "coverage",
                        "timeout_seconds": self.settings.coverage_timeout_seconds,
                    },
                ),
            )

        if coverage_error is not None:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    f"coverage report could not be generated: {coverage_error}",
                    junit_report,
                    None,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="coverage report could not be generated",
                    retryable=False,
                    details={"stage": "coverage"},
                ),
            )

        if coverage_report is None:
            return (
                TestExecutionStatus.FAILED,
                _failed_summary(
                    "coverage report is missing",
                    junit_report,
                    None,
                ),
                ErrorInfo(
                    error_type="tool_error",
                    message="coverage report is missing",
                    retryable=False,
                    details={"stage": "coverage"},
                ),
            )

        return (
            TestExecutionStatus.EXECUTED,
            TestSummary(
                execution_status="executed",
                passed=junit_report.passed,
                failed=junit_report.failure_count,
                skipped=junit_report.skipped,
                coverage=coverage_report.percent_covered,
                source="pytest+coverage",
            ),
            None,
        )

    def _not_executed(
        self,
        *,
        reason: str,
        status: TestExecutionStatus,
        fixture_name: str | None,
        error: ErrorInfo | None,
        started_at: datetime,
        started_clock: float,
    ) -> TestExecutionResult:
        return TestExecutionResult(
            status=status,
            summary=TestSummary(
                execution_status="not_executed",
                reason=_truncate(reason, _MAX_REASON_CHARS),
            ),
            fixture_name=fixture_name,
            fixture_version=None,
            fixture_manifest_sha256=None,
            collected_tests=None,
            test_records=(),
            test_records_truncated=False,
            coverage_files=(),
            coverage_files_truncated=False,
            read_only_verified=None,
            modified_paths=(),
            pytest_version=None,
            coverage_version=None,
            exit_code=None,
            coverage_exit_code=None,
            test_duration_seconds=None,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            duration_ms=max(
                0,
                int((time.perf_counter() - started_clock) * 1000),
            ),
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            error=error,
        )


def parse_junit_xml(
    path: Path,
    fixture_root: Path,
    *,
    max_bytes: int,
    max_records: int,
    temp_root: Path | None = None,
) -> PytestReport:
    """解析 Pytest JUnit XML；路径与消息会做安全规范化。"""

    data = _read_limited_file(path, max_bytes, "pytest report exceeds the size limit")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise TestReportParseError(
            "pytest report contains a document type declaration"
        )
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise TestReportParseError("pytest report is not valid XML") from exc

    root_name = _local_name(root.tag)
    if root_name not in {"testsuites", "testsuite"}:
        raise TestReportParseError("pytest report has an unexpected root element")

    cases = [
        element
        for element in root.iter()
        if _local_name(element.tag) == "testcase"
    ]
    if not cases:
        return PytestReport(
            total=0,
            passed=0,
            failed=0,
            errors=0,
            skipped=0,
            duration_seconds=0.0,
            records=(),
            records_truncated=False,
        )

    failed = 0
    errors = 0
    skipped = 0
    total_duration = 0.0
    records: list[TestRecord] = []
    records_truncated = False

    for index, case in enumerate(cases):
        name = _clean_name(case.get("name") or "unnamed")
        classname = _clean_name(case.get("classname") or "")
        full_name = f"{classname}::{name}" if classname else name
        full_name = _truncate(
            _sanitize_text(full_name, fixture_root, temp_root),
            _MAX_TEST_NAME_CHARS,
        )

        failure = _first_child(case, "failure")
        error_node = _first_child(case, "error")
        skip_node = _first_child(case, "skipped")
        if failure is not None:
            outcome = "failed"
            node = failure
            failed += 1
        elif error_node is not None:
            outcome = "error"
            node = error_node
            errors += 1
        elif skip_node is not None:
            outcome = "skipped"
            node = skip_node
            skipped += 1
        else:
            outcome = "passed"
            node = None

        duration = _optional_duration(case.get("time"))
        if duration is not None:
            total_duration += duration

        file_path = _test_file_path(case, fixture_root, classname)
        line = _optional_positive_int(case.get("line"))
        message = _test_message(node, fixture_root, temp_root)

        if index < max_records:
            try:
                records.append(
                    TestRecord(
                        name=full_name,
                        outcome=outcome,
                        file_path=file_path,
                        line=line,
                        duration_seconds=duration,
                        message=message,
                    )
                )
            except ValueError as exc:
                raise TestReportParseError(
                    "pytest report contains an invalid test record"
                ) from exc
        else:
            records_truncated = True

    total = len(cases)
    passed = total - failed - errors - skipped
    if passed < 0:
        raise TestReportParseError("pytest report contains inconsistent counts")

    return PytestReport(
        total=total,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_seconds=round(total_duration, 6),
        records=tuple(records),
        records_truncated=records_truncated,
    )


def parse_coverage_json(
    path: Path,
    fixture_root: Path,
    *,
    max_bytes: int,
    max_files: int,
) -> CoverageReport:
    """解析 Coverage.py JSON 报告；拒绝越界路径与重复键。"""

    data = _read_limited_file(
        path,
        max_bytes,
        "coverage report exceeds the size limit",
    )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TestReportParseError("coverage report is not valid UTF-8") from exc
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    except TestReportParseError:
        raise
    except json.JSONDecodeError as exc:
        raise TestReportParseError("coverage report is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TestReportParseError("coverage report must be a JSON object")

    files = payload.get("files")
    totals = payload.get("totals")
    if not isinstance(files, dict) or not isinstance(totals, dict):
        raise TestReportParseError("coverage report has an unexpected structure")

    overall = _percentage(totals.get("percent_covered"), "overall coverage")
    parsed: list[CoverageFileReport] = []
    seen: set[str] = set()

    for raw_path, entry in files.items():
        file_path = _safe_relative_path(fixture_root, raw_path)
        if file_path in seen:
            raise TestReportParseError(
                "coverage report contains duplicate file paths"
            )
        seen.add(file_path)
        if not isinstance(entry, dict):
            raise TestReportParseError(
                "coverage report contains an invalid file entry"
            )
        summary = entry.get("summary")
        if not isinstance(summary, dict):
            raise TestReportParseError(
                "coverage report contains an invalid file summary"
            )
        percent = _percentage(
            summary.get("percent_covered"),
            "file coverage",
        )
        covered = _non_negative_int(
            summary.get("covered_lines"),
            "covered lines",
        )
        statements = _non_negative_int(
            summary.get("num_statements"),
            "statement count",
        )
        if covered > statements:
            raise TestReportParseError(
                "coverage report contains inconsistent line counts"
            )
        missing = _line_numbers(entry.get("missing_lines"))
        try:
            parsed.append(
                CoverageFileReport(
                    file_path=file_path,
                    percent_covered=percent,
                    covered_lines=covered,
                    num_statements=statements,
                    missing_lines=missing,
                )
            )
        except ValueError as exc:
            raise TestReportParseError(
                "coverage report contains an invalid file entry"
            ) from exc

    parsed.sort(key=lambda item: item.file_path)
    truncated = len(parsed) > max_files
    return CoverageReport(
        percent_covered=overall,
        files=tuple(parsed[:max_files]),
        files_truncated=truncated,
    )


def _failed_summary(
    reason: str,
    junit_report: PytestReport | None,
    coverage_report: CoverageReport | None,
) -> TestSummary:
    kwargs: dict[str, Any] = {
        "execution_status": "failed",
        "reason": _truncate(reason, _MAX_REASON_CHARS),
    }
    has_counts = junit_report is not None and junit_report.total > 0
    if has_counts:
        kwargs["passed"] = junit_report.passed
        kwargs["failed"] = junit_report.failure_count
        kwargs["skipped"] = junit_report.skipped
    if coverage_report is not None:
        kwargs["coverage"] = coverage_report.percent_covered
        kwargs["source"] = "pytest+coverage"
    elif has_counts:
        kwargs["source"] = "pytest"
    return TestSummary(**kwargs)


def _not_executed_summary(reason: str) -> TestSummary:
    return TestSummary(
        execution_status="not_executed",
        reason=_truncate(reason, _MAX_REASON_CHARS),
    )


def _test_file_path(
    case: ET.Element,
    fixture_root: Path,
    classname: str,
) -> str | None:
    file_attr = case.get("file")
    if file_attr:
        return _safe_relative_path(fixture_root, file_attr)
    if not classname:
        return None
    parts = [part for part in classname.split(".") if part]
    for length in range(len(parts), 0, -1):
        candidate = "/".join(parts[:length]) + ".py"
        try:
            safe = _validate_relative_path(candidate)
        except TestReportParseError:
            return None
        if (fixture_root / safe).is_file():
            return safe
    return None


def _test_message(
    node: ET.Element | None,
    fixture_root: Path,
    temp_root: Path | None,
) -> str | None:
    if node is None:
        return None
    pieces: list[str] = []
    type_attr = node.get("type")
    message_attr = node.get("message")
    if type_attr:
        pieces.append(type_attr)
    if message_attr:
        pieces.append(message_attr)
    if node.text:
        pieces.append(node.text)
    if not pieces:
        return None
    text = _sanitize_text(": ".join(pieces), fixture_root, temp_root)
    return _truncate(text, _MAX_TEST_MESSAGE_CHARS)


def _safe_relative_path(fixture_root: Path, emitted: object) -> str:
    if not isinstance(emitted, str) or not emitted.strip():
        raise TestReportParseError("test report contains an invalid file path")
    try:
        relative = relative_posix_path(fixture_root, emitted)
    except ToolOutputParseError as exc:
        raise TestReportParseError(
            "test report contains a path outside the trusted fixture"
        ) from exc
    return _validate_relative_path(relative)


def _validate_relative_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or "\x00" in value
    ):
        raise TestReportParseError("test report contains an unsafe file path")
    pure = PurePosixPath(value)
    if (
        not pure.parts
        or pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
    ):
        raise TestReportParseError("test report contains an unsafe file path")
    if pure.as_posix() != value:
        raise TestReportParseError(
            "test report contains a non-canonical file path"
        )
    return value


def _read_limited_file(path: Path, limit: int, message: str) -> bytes:
    try:
        if path.is_symlink() or path.is_junction():
            raise TestReportParseError("test report must not be a link")
        if not path.is_file():
            raise TestReportParseError("test report is missing")
        size = path.stat().st_size
        if size > limit:
            raise TestReportParseError(message)
        data = path.read_bytes()
    except TestReportParseError:
        raise
    except OSError as exc:
        raise TestReportParseError("test report could not be read") from exc
    if len(data) > limit:
        raise TestReportParseError(message)
    return data


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TestReportParseError(
                "coverage report contains duplicate keys"
            )
        result[key] = value
    return result


def _percentage(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TestReportParseError(f"coverage report has an invalid {label}")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 100.0:
        raise TestReportParseError(f"coverage report has an invalid {label}")
    return round(number, 2)


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TestReportParseError(f"coverage report has an invalid {label}")
    return value


def _line_numbers(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TestReportParseError(
            "coverage report has an invalid missing line list"
        )
    lines: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise TestReportParseError(
                "coverage report has an invalid missing line number"
            )
        lines.append(item)
    return tuple(lines)


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _optional_duration(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _first_child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if _local_name(child.tag) == name:
            return child
    return None


def _local_name(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _clean_name(value: str) -> str:
    return _truncate(" ".join(value.split()), _MAX_TEST_NAME_CHARS)


def _sanitize_text(
    text: str,
    fixture_root: Path,
    temp_root: Path | None,
) -> str:
    replacements = [
        (str(fixture_root), "<fixture>"),
        (fixture_root.as_posix(), "<fixture>"),
        (str(Path.home()), "<home>"),
        (str(Path(sys.executable).parent), "<python>"),
        (str(Path(sys.base_prefix)), "<python>"),
    ]
    if temp_root is not None:
        replacements.extend(
            [
                (str(temp_root), "<temp>"),
                (temp_root.as_posix(), "<temp>"),
            ]
        )
    for value, replacement in sorted(
        replacements,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if value:
            text = text.replace(value, replacement)
    return text


def _sanitize_output(
    text: str,
    fixture_root: Path,
    temp_root: Path,
) -> tuple[str, bool]:
    sanitized = _sanitize_text(text, fixture_root, temp_root)
    if len(sanitized) <= _MAX_STORED_OUTPUT_CHARS:
        return sanitized, False
    return (
        sanitized[:_MAX_STORED_OUTPUT_CHARS] + _OUTPUT_TRUNCATION_MARKER,
        True,
    )


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _os_error_process() -> ProcessResult:
    return ProcessResult(
        status=ProcessStatus.OS_ERROR,
        returncode=None,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=0,
    )
