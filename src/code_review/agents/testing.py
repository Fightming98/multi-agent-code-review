"""TestingAgent：真实 Pytest/JUnit/Coverage 结果的确定性投影。

TestingAgent 不使用 LLM：测试数量、失败数和覆盖率只能来自 TestRunner 的
真实工具输出。外部不可信仓库的测试必须保持 ``not_executed``；项目级
``low_coverage`` Finding 不携带伪造的文件或行号。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from code_review.agents.base import BaseAgent
from code_review.agents.contracts import (
    AgentRunOutput,
    UsageSummary,
    WorkerEvidence,
)
from code_review.schemas.result import AgentResult, Finding, ToolEvidence
from code_review.schemas.task import ErrorInfo, utc_now
from code_review.services.redaction import redact_sensitive_text
from code_review.tools.test_runner import (
    CoverageFileReport,
    TestExecutionResult,
    TestExecutionStatus,
    TestRecord,
    TestRunner,
)
from config.review_rules import ReviewRules
from config.settings import Settings

__all__ = ["TESTING_CATEGORIES", "TestingAgent"]

TESTING_CATEGORIES = frozenset(
    {"test_failure", "low_coverage", "missing_tests"}
)

_MAX_TEXT = 4000
_MAX_TITLE = 200
_MAX_PATH_LIST = 20


class TestingAgent(BaseAgent):
    """测试维度专业 Agent；只投影真实工具统计。"""

    agent_name = "TestingAgent"
    task_type = "testing_review"

    def __init__(
        self,
        *,
        settings: Settings,
        test_runner: TestRunner | None = None,
        clock: Callable[[], datetime] = utc_now,
        timer: Callable[[], float] | None = None,
        redactor: Callable[..., str] = redact_sensitive_text,
    ) -> None:
        if timer is None:
            import time as _time

            timer = _time.perf_counter
        super().__init__(clock=clock, timer=timer, redactor=redactor)
        self.settings = settings
        self._runner = (
            test_runner if test_runner is not None else TestRunner(settings)
        )

    async def _run(self, dispatch: Any) -> AgentRunOutput:
        runtime = dispatch.runtime
        warnings: list[str] = []

        fixture, fixture_warnings = self._trusted_fixture(dispatch)
        warnings.extend(fixture_warnings)

        result: TestExecutionResult | None = None
        try:
            result = await asyncio.to_thread(
                self._runner.execute, trusted_fixture=fixture
            )
        except Exception:  # noqa: BLE001 - 测试执行异常降级为工具失败
            result = None
        if result is None:
            warnings.append("testing tool execution failed")
            block = _default_test_report(
                "testing tool execution failed"
            )
        else:
            block = _test_report_block(result)
            warnings.extend(_result_warnings(result))

        findings: list[Finding] = []
        if result is not None and result.status is TestExecutionStatus.EXECUTED:
            findings, finding_warnings = self._deterministic_findings(
                result, runtime.rules
            )
            warnings.extend(finding_warnings)

        if result is None:
            status = "failed"
            error: ErrorInfo | None = _error(
                "testing_tool_error",
                "test execution tool failed; no test statistics are available",
            )
        elif result.status is TestExecutionStatus.EXECUTED:
            status = "completed"
            error = None
        elif result.status is TestExecutionStatus.NOT_EXECUTED:
            status = "completed"
            error = None
            reason = result.summary.reason or "tests were not executed"
            warnings.append(f"tests not executed: {reason}")
        else:
            status = "failed"
            error = _error(
                "testing_tool_error",
                "test execution did not complete; no reliable test statistics "
                "are available",
            )
            findings = []

        summary_text = _summary(status, result, block)
        block["warnings"] = list(warnings)

        result_model = AgentResult(
            task_id=dispatch.task.task_id,
            parent_task_id=dispatch.task.parent_task_id,
            review_id=dispatch.task.review_id,
            agent_name=self.agent_name,
            status=status,
            commit_sha=runtime.commit_sha,
            score=None,
            findings=findings,
            summary=summary_text,
            error=error,
            metadata={
                "dimension": "testing",
                "llm_used": False,
                "test_execution_status": block.get("execution_status"),
                "counts": block.get("counts"),
                "coverage": block.get("coverage"),
                "trusted_fixture_requested": fixture is not None,
            },
        )
        evidence = WorkerEvidence(
            agent_name=self.agent_name,
            static_analysis={"tools": {}},
            test_report=block,
            usage=UsageSummary(),
            warnings=tuple(warnings),
        )
        return AgentRunOutput(result=result_model, evidence=evidence)

    # ------------------------------------------------------------------
    # Trusted fixture gate

    def _trusted_fixture(
        self, dispatch: Any
    ) -> tuple[str | None, list[str]]:
        raw = dispatch.task.input_data.get("trusted_fixture")
        if raw is None:
            return None, []
        if (
            isinstance(raw, str)
            and raw == self.settings.trusted_fixture_name
        ):
            return raw, []
        return None, [
            (
                "unapproved trusted_fixture request was ignored; tests were "
                "not executed"
            )
        ]

    # ------------------------------------------------------------------
    # Deterministic Findings

    def _deterministic_findings(
        self,
        result: TestExecutionResult,
        rules: ReviewRules,
    ) -> tuple[list[Finding], list[str]]:
        findings: list[Finding] = []
        warnings: list[str] = []
        summary = result.summary
        counts = _counts(result)
        total = counts["total"]
        failed = summary.failed or 0
        coverage = summary.coverage

        if failed > 0:
            try:
                severity = rules.map_severity("testing", "test_failure")
            except KeyError:
                warnings.append(
                    "testing severity mapping is missing for test_failure"
                )
            else:
                findings.append(
                    Finding(
                        finding_id=f"TEST-{len(findings) + 1:04d}",
                        agent_name=self.agent_name,
                        category="test_failure",
                        severity=severity,
                        title=f"{failed} test(s) failed",
                        description=(
                            f"pytest reported {failed} failed/error test(s) out "
                            f"of {total if total is not None else 'unknown'} "
                            "collected test(s)."
                        ),
                        evidence=(
                            f"pytest counts: passed={summary.passed}, "
                            f"failed={summary.failed}, "
                            f"skipped={summary.skipped}"
                        ),
                        tool_evidence=[
                            ToolEvidence(
                                tool_name="pytest",
                                tool_version=result.pytest_version,
                                raw_output_ref="test_report.json#/counts",
                            )
                        ],
                        recommendation=(
                            "Fix or quarantine the failing tests and rerun the "
                            "suite before merging."
                        ),
                        confidence=1.0,
                    )
                )

        if (
            coverage is not None
            and coverage < rules.min_coverage_percent
        ):
            try:
                severity = rules.map_severity("testing", "low_coverage")
            except KeyError:
                warnings.append(
                    "testing severity mapping is missing for low_coverage"
                )
            else:
                findings.append(
                    Finding(
                        finding_id=f"TEST-{len(findings) + 1:04d}",
                        agent_name=self.agent_name,
                        category="low_coverage",
                        severity=severity,
                        title="Coverage below configured threshold",
                        description=(
                            f"Measured coverage is {coverage:.1f}% against the "
                            f"configured minimum of "
                            f"{rules.min_coverage_percent:.1f}%."
                        ),
                        evidence=(
                            f"coverage source: {summary.source or 'unknown'}; "
                            f"measured: {coverage:.1f}%"
                        ),
                        tool_evidence=[
                            ToolEvidence(
                                tool_name="coverage",
                                tool_version=result.coverage_version,
                                raw_output_ref="test_report.json#/coverage",
                            )
                        ],
                        recommendation=(
                            "Add focused tests for uncovered branches, "
                            "especially the changed code paths."
                        ),
                        confidence=1.0,
                    )
                )

        if result.status is TestExecutionStatus.EXECUTED and total == 0:
            try:
                severity = rules.map_severity("testing", "missing_tests")
            except KeyError:
                warnings.append(
                    "testing severity mapping is missing for missing_tests"
                )
            else:
                findings.append(
                    Finding(
                        finding_id=f"TEST-{len(findings) + 1:04d}",
                        agent_name=self.agent_name,
                        category="missing_tests",
                        severity=severity,
                        title="No tests were collected",
                        description=(
                            "pytest completed without collecting any test "
                            "case from the approved fixture."
                        ),
                        evidence="pytest collected 0 test(s)",
                        tool_evidence=[
                            ToolEvidence(
                                tool_name="pytest",
                                tool_version=result.pytest_version,
                                raw_output_ref="test_report.json#/counts",
                            )
                        ],
                        recommendation=(
                            "Add tests for the reviewed behavior or confirm "
                            "that the fixture is the intended test target."
                        ),
                        confidence=1.0,
                    )
                )

        return findings, warnings


# ----------------------------------------------------------------------
# Local helpers


def _counts(result: TestExecutionResult) -> dict[str, int | None]:
    summary = result.summary
    counts: dict[str, int | None] = {
        "total": result.collected_tests,
        "passed": summary.passed,
        "failed": summary.failed,
        "skipped": summary.skipped,
    }
    if counts["total"] is None and all(
        isinstance(value, int)
        for value in (summary.passed, summary.failed, summary.skipped)
    ):
        counts["total"] = sum(
            int(value)
            for value in (summary.passed, summary.failed, summary.skipped)
        )
    return counts


def _test_report_block(result: TestExecutionResult) -> dict[str, Any]:
    summary = result.summary
    return {
        "schema_version": "1.0",
        "execution_status": summary.execution_status,
        "reason": summary.reason,
        "counts": _counts(result),
        "coverage": summary.coverage,
        "source": summary.source,
        "duration_seconds": result.test_duration_seconds,
        "fixture": (
            None
            if result.fixture_name is None
            else {
                "name": result.fixture_name,
                "version": result.fixture_version,
                "manifest_sha256": result.fixture_manifest_sha256,
            }
        ),
        "records": [
            _record_block(record) for record in result.test_records
        ],
        "records_truncated": result.test_records_truncated,
        "coverage_files": [
            _coverage_file_block(item) for item in result.coverage_files
        ],
        "coverage_files_truncated": result.coverage_files_truncated,
        "tool_versions": {
            "pytest": result.pytest_version,
            "coverage": result.coverage_version,
        },
        "read_only_verified": result.read_only_verified,
        "modified_paths": list(result.modified_paths),
        "exit_code": result.exit_code,
        "coverage_exit_code": result.coverage_exit_code,
        "warnings": [],
    }


def _default_test_report(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "execution_status": "not_executed",
        "reason": reason,
        "counts": {
            "total": None,
            "passed": None,
            "failed": None,
            "skipped": None,
        },
        "coverage": None,
        "source": None,
        "duration_seconds": None,
        "fixture": None,
        "records": [],
        "records_truncated": False,
        "coverage_files": [],
        "coverage_files_truncated": False,
        "tool_versions": {},
        "read_only_verified": None,
        "modified_paths": [],
        "exit_code": None,
        "coverage_exit_code": None,
        "warnings": [],
    }


def _record_block(record: TestRecord) -> dict[str, Any]:
    message = (
        None
        if record.message is None
        else redact_sensitive_text(record.message, max_chars=_MAX_TEXT)
    )
    return {
        "name": redact_sensitive_text(record.name, max_chars=_MAX_TITLE),
        "outcome": record.outcome,
        "file_path": record.file_path,
        "line": record.line,
        "duration_seconds": record.duration_seconds,
        "message": message,
    }


def _coverage_file_block(item: CoverageFileReport) -> dict[str, Any]:
    return {
        "file_path": item.file_path,
        "percent_covered": item.percent_covered,
        "covered_lines": item.covered_lines,
        "num_statements": item.num_statements,
        "missing_lines": list(item.missing_lines[:_MAX_PATH_LIST]),
    }


def _result_warnings(result: TestExecutionResult) -> list[str]:
    warnings: list[str] = []
    if result.stdout_truncated:
        warnings.append("pytest stdout was truncated")
    if result.stderr_truncated:
        warnings.append("pytest stderr was truncated")
    if result.test_records_truncated:
        warnings.append("test records were truncated")
    if result.coverage_files_truncated:
        warnings.append("coverage files were truncated")
    if result.modified_paths:
        warnings.append(
            "fixture workspace modification was detected during test execution"
        )
    return warnings


def _summary(
    status: str,
    result: TestExecutionResult | None,
    block: Mapping[str, Any],
) -> str:
    if status == "failed":
        return "Testing analysis failed; no reliable test statistics."
    if result is None:
        return "Testing analysis failed; no test result was produced."
    if result.status is TestExecutionStatus.NOT_EXECUTED:
        reason = result.summary.reason or "tests were not executed"
        return f"Tests were not executed: {reason}."
    counts = block.get("counts") or {}
    coverage = block.get("coverage")
    coverage_text = (
        "coverage unavailable"
        if coverage is None
        else f"coverage {coverage:.1f}%"
    )
    return (
        f"pytest executed {counts.get('total')} test(s): "
        f"{counts.get('passed')} passed, {counts.get('failed')} failed, "
        f"{counts.get('skipped')} skipped; {coverage_text}."
    )


def _error(error_type: str, message: str) -> ErrorInfo:
    return ErrorInfo(
        error_type=error_type,
        message=message,
        retryable=False,
        details={},
    )
