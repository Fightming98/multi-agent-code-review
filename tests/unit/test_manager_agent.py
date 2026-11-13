"""Stage 2.2 ManagerAgent 计划与聚合单元测试。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from code_review.agents.contracts import (
    AgentExecution,
    ArtifactData,
    UsageSummary,
)
from code_review.agents.manager import (
    AGENT_SPECS,
    DIMENSIONS,
    AggregatedResults,
    ManagerAgent,
    TaskPlan,
)
from code_review.schemas.report import ExecutionSummary
from code_review.schemas.result import AgentResult
from tests.stage2_helpers import (
    COMMIT_SHA,
    NOW,
    REVIEW_ID,
    make_execution,
    make_finding,
    make_plan_execution,
)


def make_manager() -> ManagerAgent:
    return ManagerAgent(clock=lambda: NOW)


def make_plan() -> TaskPlan:
    return make_manager().plan(review_id=REVIEW_ID, commit_sha=COMMIT_SHA)


def all_executions(
    plan: TaskPlan,
    *,
    durations: dict[str, float] | None = None,
) -> dict[str, AgentExecution]:
    durations = durations or {}
    return {
        dimension: make_plan_execution(
            plan,
            dimension,
            duration_seconds=durations.get(dimension, 1.0),
        )
        for dimension in DIMENSIONS
    }


class TestManagerPlan:
    def test_creates_root_and_exactly_four_tasks(self) -> None:
        plan = make_plan()
        assert plan.root_task.agent_name == "ManagerAgent"
        assert plan.root_task.task_type == "review_orchestration"
        assert len(plan.agent_tasks) == 4
        assert plan.dimensions == DIMENSIONS
        expected = {
            dimension: (agent_name, task_type)
            for dimension, agent_name, task_type, _ in AGENT_SPECS
        }
        for dimension, task in plan.by_dimension().items():
            assert (task.agent_name, task.task_type) == expected[dimension]
            assert task.parent_task_id == plan.root_task.task_id
            assert task.review_id == REVIEW_ID

    def test_task_ids_are_unique(self) -> None:
        plan = make_plan()
        ids = [plan.root_task.task_id] + [
            task.task_id for task in plan.agent_tasks
        ]
        assert len(ids) == len(set(ids))

    def test_no_retries_and_no_manager_prompt(self) -> None:
        plan = make_plan()
        assert plan.root_task.max_retries == 0
        assert all(task.max_retries == 0 for task in plan.agent_tasks)
        manager = make_manager()
        assert not hasattr(manager, "_tool")
        assert not hasattr(manager, "_llm_client")
        assert not hasattr(manager, "settings")

    def test_tasks_start_pending(self) -> None:
        plan = make_plan()
        for task in (plan.root_task, *plan.agent_tasks):
            assert task.status == "pending"
            assert task.started_at is None
            assert task.finished_at is None

    def test_plan_input_contains_no_workspace_or_paths(self) -> None:
        plan = make_plan()
        assert plan.root_task.input_data["commit_sha"] == COMMIT_SHA
        for task in plan.agent_tasks:
            assert set(task.input_data) == {"dimension", "language"}
            assert "workspace" not in task.input_data

    def test_timeout_is_propagated(self) -> None:
        plan = make_manager().plan(
            review_id=REVIEW_ID,
            commit_sha=COMMIT_SHA,
            timeout_seconds=30,
        )
        assert plan.root_task.timeout_seconds == 30
        assert all(
            task.timeout_seconds == 30 for task in plan.agent_tasks
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"review_id": ""},
            {"review_id": "  "},
            {"commit_sha": "a" * 39},
            {"commit_sha": "A" * 40},
            {"language": ""},
            {"timeout_seconds": 0},
            {"timeout_seconds": -1},
            {"timeout_seconds": True},
            {"timeout_seconds": float("inf")},
        ],
    )
    def test_rejects_invalid_plan_input(self, kwargs: dict[str, object]) -> None:
        params: dict[str, object] = {
            "review_id": REVIEW_ID,
            "commit_sha": COMMIT_SHA,
        }
        params.update(kwargs)
        with pytest.raises(ValueError):
            make_manager().plan(**params)  # type: ignore[arg-type]

    def test_task_for_unknown_dimension(self) -> None:
        with pytest.raises(ValueError):
            make_plan().task_for("maintainability")

    def test_plan_rejects_wrong_task_order(self) -> None:
        plan = make_plan()
        with pytest.raises(ValueError):
            TaskPlan(
                root_task=plan.root_task,
                agent_tasks=tuple(reversed(plan.agent_tasks)),
                review_id=REVIEW_ID,
                commit_sha=COMMIT_SHA,
            )

    def test_plan_rejects_duplicate_task_ids(self) -> None:
        plan = make_plan()
        duplicate = plan.agent_tasks[0].model_copy(
            update={"task_id": plan.agent_tasks[1].task_id}
        )
        with pytest.raises(ValueError):
            TaskPlan(
                root_task=plan.root_task,
                agent_tasks=(
                    plan.agent_tasks[0],
                    duplicate,
                    plan.agent_tasks[2],
                    plan.agent_tasks[3],
                ),
                review_id=REVIEW_ID,
                commit_sha=COMMIT_SHA,
            )


class TestManagerAggregate:
    def test_returns_exactly_four_agent_results(self) -> None:
        plan = make_plan()
        aggregated = make_manager().aggregate(
            plan, executions=all_executions(plan)
        )
        assert isinstance(aggregated, AggregatedResults)
        assert set(aggregated.agent_results) == set(DIMENSIONS)
        assert all(
            isinstance(result, AgentResult)
            for result in aggregated.agent_results.values()
        )
        assert all(
            result.status == "completed"
            for result in aggregated.agent_results.values()
        )

    def test_artifact_data_has_stable_pointer_structure(self) -> None:
        plan = make_plan()
        aggregated = make_manager().aggregate(
            plan, executions=all_executions(plan)
        )
        data = aggregated.artifact_data
        assert isinstance(data, ArtifactData)
        assert data.resolve(
            "static_analysis.json#/agents/security/tools/bandit/"
            "findings/0/rule_id"
        ) == "B608"
        assert data.resolve(
            "static_analysis.json#/agents/quality/tools/ruff/"
            "findings/0/rule_id"
        ) == "E501"
        assert data.resolve(
            "static_analysis.json#/agents/performance/tools/radon/"
            "findings/0/rule_id"
        ) == "RADON_CC"
        assert data.resolve(
            "static_analysis.json#/agents/security/agent_name"
        ) == "SecurityAgent"
        assert data.resolve(
            "static_analysis.json#/agents/security/result_status"
        ) == "completed"
        assert data.resolve("test_report.json#/coverage") == 91.0
        assert data.resolve("test_report.json#/counts/passed") == 3
        assert data.resolve(
            "test_report.json#/records/0/name"
        ) == "tests/test_app.py::test_ok"

    def test_usage_summary_sums_all_dimensions(self) -> None:
        plan = make_plan()
        usages = {
            "security": UsageSummary(
                llm_calls=1, reported_usage_calls=1,
                input_tokens=10, output_tokens=1,
            ),
            "quality": UsageSummary(
                llm_calls=1, reported_usage_calls=1,
                input_tokens=20, output_tokens=2,
            ),
            "performance": UsageSummary(
                llm_calls=1, reported_usage_calls=1,
                input_tokens=30, output_tokens=3,
            ),
            "testing": UsageSummary(),
        }
        executions = {
            dimension: make_plan_execution(
                plan, dimension, usage=usages[dimension]
            )
            for dimension in DIMENSIONS
        }
        aggregated = make_manager().aggregate(plan, executions=executions)
        assert aggregated.usage_summary.llm_calls == 3
        assert aggregated.usage_summary.input_tokens == 60
        assert aggregated.usage_summary.output_tokens == 6
        assert aggregated.usage_summary.total_tokens == 66

    def test_execution_summary_counts_and_duration(self) -> None:
        plan = make_plan()
        executions = all_executions(
            plan,
            durations={
                "security": 1.0,
                "quality": 2.0,
                "performance": 3.0,
                "testing": 4.0,
            },
        )
        aggregated = make_manager().aggregate(plan, executions=executions)
        summary = aggregated.execution_summary
        assert isinstance(summary, ExecutionSummary)
        assert summary.total_tasks == 4
        assert summary.completed_tasks == 4
        assert summary.partial_tasks == 0
        assert summary.failed_tasks == 0
        assert summary.cancelled_tasks == 0
        assert summary.duration_seconds == 4.0
        assert (
            summary.completed_tasks
            + summary.partial_tasks
            + summary.failed_tasks
            + summary.cancelled_tasks
            == summary.total_tasks
        )

    def test_missing_result_is_synthesized_and_others_preserved(self) -> None:
        plan = make_plan()
        executions = all_executions(plan)
        del executions["testing"]
        aggregated = make_manager().aggregate(plan, executions=executions)
        assert aggregated.agent_results["security"].status == "completed"
        assert aggregated.agent_results["quality"].status == "completed"
        assert aggregated.agent_results["performance"].status == "completed"
        testing = aggregated.agent_results["testing"]
        assert testing.status == "failed"
        assert testing.error is not None
        assert testing.error.error_type == "missing_agent_result"
        assert testing.findings == []
        assert testing.score is None
        assert any("testing" in warning for warning in aggregated.warnings)
        assert aggregated.execution_summary.failed_tasks == 1
        assert aggregated.execution_summary.completed_tasks == 3
        assert aggregated.artifact_data.resolve(
            "test_report.json#/execution_status"
        ) == "not_executed"

    def test_all_failed_marks_root_failed(self) -> None:
        plan = make_plan()
        executions = {
            dimension: make_plan_execution(plan, dimension, status="failed")
            for dimension in DIMENSIONS
        }
        aggregated = make_manager().aggregate(plan, executions=executions)
        assert aggregated.root_task.status == "failed"
        assert aggregated.root_task.last_error is not None
        assert aggregated.root_task.last_error.error_type == (
            "aggregate_incomplete"
        )
        assert aggregated.execution_summary.failed_tasks == 4

    def test_partial_dimension_keeps_root_completed(self) -> None:
        plan = make_plan()
        executions = all_executions(plan)
        executions["security"] = make_plan_execution(
            plan, "security", status="partial"
        )
        aggregated = make_manager().aggregate(plan, executions=executions)
        assert aggregated.root_task.status == "completed"
        assert aggregated.execution_summary.partial_tasks == 1
        assert aggregated.execution_summary.completed_tasks == 3

    def test_identity_mismatch_is_treated_as_missing(self) -> None:
        plan = make_plan()
        executions = all_executions(plan)
        executions["security"] = make_plan_execution(plan, "quality")
        aggregated = make_manager().aggregate(plan, executions=executions)
        security = aggregated.agent_results["security"]
        assert security.status == "failed"
        assert security.error is not None
        assert security.error.details["reason"] == "task_id mismatch"

    def test_unknown_execution_key_is_ignored_with_warning(self) -> None:
        plan = make_plan()
        executions: dict[str, AgentExecution | None] = dict(
            all_executions(plan)
        )
        executions["extra"] = None
        aggregated = make_manager().aggregate(plan, executions=executions)
        assert set(aggregated.agent_results) == set(DIMENSIONS)
        assert any("extra" in warning for warning in aggregated.warnings)

    def test_findings_remain_unverified(self) -> None:
        plan = make_plan()
        task = plan.task_for("security")
        finding = make_finding()
        execution = make_execution(task=task, findings=[finding])
        executions = all_executions(plan)
        executions["security"] = execution
        aggregated = make_manager().aggregate(plan, executions=executions)
        assert all(
            item.verification_status == "unverified"
            for item in aggregated.agent_results["security"].findings
        )

    def test_manager_does_not_change_scores(self) -> None:
        plan = make_plan()
        executions = all_executions(plan)
        aggregated = make_manager().aggregate(plan, executions=executions)
        assert all(
            result.score == 85.0
            for result in aggregated.agent_results.values()
        )

    def test_root_finished_after_all_timings(self) -> None:
        plan = make_plan()
        executions = all_executions(plan, durations={"testing": 10.0})
        aggregated = make_manager().aggregate(plan, executions=executions)
        assert aggregated.root_task.finished_at is not None
        assert aggregated.root_task.finished_at >= NOW + timedelta(seconds=10)

    def test_root_finished_not_before_created(self) -> None:
        plan = make_plan()
        aggregated = make_manager().aggregate(plan, executions=all_executions(plan))
        assert aggregated.root_task.finished_at is not None
        assert aggregated.root_task.finished_at >= plan.root_task.created_at

    def test_rejects_invalid_plan_and_executions(self) -> None:
        manager = make_manager()
        plan = make_plan()
        with pytest.raises(TypeError):
            manager.aggregate(object(), executions={})
        with pytest.raises(TypeError):
            manager.aggregate(plan, executions=[])
        with pytest.raises(ValueError):
            manager.aggregate(
                plan, executions=all_executions(plan), warnings=[""]
            )

    def test_aggregated_results_requires_four_dimensions(self) -> None:
        plan = make_plan()
        aggregated = make_manager().aggregate(
            plan, executions=all_executions(plan)
        )
        with pytest.raises(ValueError):
            AggregatedResults(
                agent_results={
                    "security": aggregated.agent_results["security"]
                },
                artifact_data=aggregated.artifact_data,
                usage_summary=aggregated.usage_summary,
                execution_summary=aggregated.execution_summary,
                root_task=aggregated.root_task,
            )
