"""Stage 2.2 TestingAgent 单元测试（Fake TestRunner，真实统计语义）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from code_review.agents.testing import TestingAgent as AgentUnderTest
from code_review.tools.test_runner import CoverageFileReport
from code_review.tools.test_runner import TestExecutionStatus as ExecutionStatus
from code_review.tools.test_runner import TestRecord as Record
from config.settings import Settings
from tests.stage2_helpers import (
    FakeTestRunner,
    make_agent_task,
    make_dispatch,
    make_test_execution_result,
    make_worker_runtime,
)


def make_agent(runner: FakeTestRunner) -> AgentUnderTest:
    return AgentUnderTest(settings=Settings(), test_runner=runner)


def make_dispatch_for(
    tmp_path: Path,
    *,
    input_data: dict[str, object] | None = None,
):
    task = make_agent_task(
        agent_name="TestingAgent",
        task_type="testing_review",
        task_id="task-testing",
        input_data=dict(input_data or {}),
    )
    runtime = make_worker_runtime(
        tmp_path,
        allowed_files=("pkg/app.py",),
        review_id=task.review_id,
    )
    return make_dispatch(task=task, runtime=runtime)


def run(agent: AgentUnderTest, dispatch):
    return asyncio.run(agent.execute(dispatch))


class TestExecutedResults:
    def test_failures_and_low_coverage_are_deterministic(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                passed=4,
                failed=2,
                skipped=1,
                coverage=70.0,
                records=(
                    Record(
                        name="tests/test_app.py::test_bad",
                        outcome="failed",
                        file_path="tests/test_app.py",
                        line=7,
                        message="assert 1 == 2",
                    ),
                ),
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        result = execution.result
        assert result.status == "completed"
        assert result.score is None
        assert result.metadata["llm_used"] is False
        assert execution.evidence.usage.total_tokens == 0
        categories = {item.category for item in result.findings}
        assert categories == {"test_failure", "low_coverage"}
        assert [item.finding_id for item in result.findings] == [
            "TEST-0001",
            "TEST-0002",
        ]
        assert all(
            item.verification_status == "unverified"
            for item in result.findings
        )
        block = execution.evidence.test_report
        assert block is not None
        assert block["counts"] == {
            "total": 7,
            "passed": 4,
            "failed": 2,
            "skipped": 1,
        }
        assert block["coverage"] == 70.0
        assert block["records"][0]["name"] == "tests/test_app.py::test_bad"

    def test_passing_suite_with_good_coverage_has_no_findings(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                passed=5, coverage=90.0
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        assert execution.result.status == "completed"
        assert execution.result.findings == []
        assert execution.result.summary.startswith("pytest executed 5 test(s)")

    def test_coverage_at_threshold_does_not_trigger_finding(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(passed=2, coverage=80.0)
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        assert execution.result.findings == []

    def test_coverage_below_threshold_triggers_finding(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(passed=2, coverage=79.9)
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        assert [item.category for item in execution.result.findings] == [
            "low_coverage"
        ]

    def test_low_coverage_is_project_level_without_fake_location(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                passed=1, coverage=10.0
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        finding = execution.result.findings[0]
        assert finding.file_path is None
        assert finding.start_line is None
        assert finding.end_line is None
        assert finding.severity == "medium"
        assert finding.tool_evidence[0].raw_output_ref == (
            "test_report.json#/coverage"
        )

    def test_test_failure_uses_counts_pointer(self, tmp_path: Path) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                passed=1, failed=1, coverage=95.0
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        finding = execution.result.findings[0]
        assert finding.category == "test_failure"
        assert finding.severity == "medium"
        assert finding.file_path is None
        assert finding.tool_evidence[0].raw_output_ref == (
            "test_report.json#/counts"
        )

    def test_coverage_files_and_tool_versions_are_projected(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                passed=1,
                coverage=88.0,
                coverage_files=(
                    CoverageFileReport(
                        file_path="pkg/app.py",
                        percent_covered=88.0,
                        covered_lines=8,
                        num_statements=9,
                        missing_lines=(9,),
                    ),
                ),
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        block = execution.evidence.test_report
        assert block is not None
        assert block["coverage_files"][0]["file_path"] == "pkg/app.py"
        assert block["tool_versions"] == {
            "pytest": "9.2.0",
            "coverage": "7.17.2",
        }

    def test_zero_collected_tests_creates_missing_tests(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                passed=0, failed=0, skipped=0, coverage=None
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        assert [item.category for item in execution.result.findings] == [
            "missing_tests"
        ]
        assert execution.result.findings[0].severity == "low"


class TestNotExecuted:
    def test_external_repository_is_completed_with_no_statistics(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                status=ExecutionStatus.NOT_EXECUTED,
                reason="external repository tests are not executed",
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        result = execution.result
        assert result.status == "completed"
        assert result.findings == []
        block = execution.evidence.test_report
        assert block is not None
        assert block["execution_status"] == "not_executed"
        assert block["counts"] == {
            "total": None,
            "passed": None,
            "failed": None,
            "skipped": None,
        }
        assert block["coverage"] is None
        assert any(
            "tests not executed" in warning
            for warning in execution.evidence.warnings
        )
        assert "not executed" in result.summary.lower()

    def test_approved_fixture_is_passed_to_runner(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(result=make_test_execution_result())
        dispatch = make_dispatch_for(
            tmp_path, input_data={"trusted_fixture": "trusted_fixture_v1"}
        )
        run(make_agent(runner), dispatch)
        assert runner.calls == ["trusted_fixture_v1"]

    def test_unapproved_fixture_is_not_executed(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                status=ExecutionStatus.NOT_EXECUTED,
                reason="tests are only executed for the approved fixture",
            )
        )
        dispatch = make_dispatch_for(
            tmp_path, input_data={"trusted_fixture": "evil_fixture"}
        )
        execution = run(make_agent(runner), dispatch)
        assert runner.calls == [None]
        assert execution.result.status == "completed"
        assert execution.result.findings == []
        assert any(
            "unapproved trusted_fixture" in warning
            for warning in execution.evidence.warnings
        )
        assert execution.result.metadata["trusted_fixture_requested"] is False


class TestToolFailures:
    def test_runner_exception_is_failed(self, tmp_path: Path) -> None:
        runner = FakeTestRunner(error=RuntimeError("pytest crashed"))
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        result = execution.result
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.error_type == "testing_tool_error"
        assert result.findings == []
        block = execution.evidence.test_report
        assert block is not None
        assert block["execution_status"] == "not_executed"
        assert block["reason"] == "testing tool execution failed"

    def test_runner_failed_status_is_failed_but_evidence_preserved(
        self, tmp_path: Path
    ) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                status=ExecutionStatus.FAILED,
                reason="junit report could not be parsed",
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        assert execution.result.status == "failed"
        assert execution.result.findings == []
        block = execution.evidence.test_report
        assert block is not None
        assert block["execution_status"] == "failed"
        assert block["reason"] == "junit report could not be parsed"

    def test_runner_timeout_is_failed(self, tmp_path: Path) -> None:
        runner = FakeTestRunner(
            result=make_test_execution_result(
                status=ExecutionStatus.TIMEOUT,
                reason="pytest timed out",
            )
        )
        execution = run(make_agent(runner), make_dispatch_for(tmp_path))
        assert execution.result.status == "failed"
        assert execution.result.findings == []
        assert execution.result.metadata["test_execution_status"] == "failed"


class TestSafetyBoundaries:
    def test_no_llm_is_used(self) -> None:
        agent = AgentUnderTest(settings=Settings())
        assert not hasattr(agent, "_llm_client")

    def test_result_identity_and_status_metadata(self, tmp_path: Path) -> None:
        runner = FakeTestRunner(result=make_test_execution_result())
        dispatch = make_dispatch_for(tmp_path)
        execution = run(make_agent(runner), dispatch)
        assert execution.result.task_id == dispatch.task.task_id
        assert execution.result.agent_name == "TestingAgent"
        assert execution.result.review_id == dispatch.task.review_id
        assert execution.result.commit_sha == dispatch.runtime.commit_sha
        assert execution.result.metadata["dimension"] == "testing"
        assert execution.result.metadata["llm_used"] is False
