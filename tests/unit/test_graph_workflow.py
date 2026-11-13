"""Stage 2.3 图节点、边、Send/Fan-in 与异常隔离单元测试（AC-2-01/03/05）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import structlog

from code_review.agents.contracts import (
    AgentExecution,
    AgentRunOutput,
    ArtifactData,
    WorkerDispatch,
    WorkerRuntime,
)
from code_review.agents.manager import DIMENSIONS, ManagerAgent, TaskPlan
from code_review.graph import (
    GRAPH_NODE_NAMES,
    PLACEHOLDER_REVIEW_STATUS,
    GraphDependencies,
    build_review_graph,
    dispatch_workers,
    final_reviewer_node,
    make_worker_node,
    manager_aggregate_node,
    manager_plan_node,
    run_review_graph,
    worker_state_update,
)
from code_review.graph.nodes import WORKER_NODE_NAMES
from code_review.graph.state import ReviewStateError
from tests.stage2_helpers import (
    COMMIT_SHA,
    FakeAgent,
    make_dimension_factory,
    make_graph_dependencies,
    make_plan_execution,
    make_review_state,
)


def planned_state(tmp_path: Path) -> dict:
    state = make_review_state(tmp_path.resolve())
    plan_update = manager_plan_node(state, manager=ManagerAgent())
    return {**state, **plan_update}


def runtime_for(state: dict) -> WorkerRuntime:
    repository = state["repository"]
    return WorkerRuntime(
        workspace_path=Path(state["workspace_path"]),
        allowed_files=tuple(state["allowed_files"]),
        commit_sha=state["commit_sha"],
        language=repository.language,
        review_id=state["review_id"],
        rules=state["rules"],
        trace_id=state["trace_id"],
    )


def aggregated_state(tmp_path: Path, *, missing: str | None = None) -> dict:
    state = planned_state(tmp_path)
    plan = state["task_plan"]
    executions = {
        dimension: make_plan_execution(plan, dimension)
        for dimension in DIMENSIONS
        if dimension != missing
    }
    merged = dict(state)
    timings = []
    completed = []
    for dimension, execution in executions.items():
        merged[f"{dimension}_task"] = execution.task
        merged[f"{dimension}_result"] = execution.result
        merged[f"{dimension}_evidence"] = execution.evidence
        timings.append(execution.timing)
        completed.append(execution.task.task_id)
    merged["worker_timings"] = timings
    merged["completed_tasks"] = completed
    merged["failed_tasks"] = []
    return merged


class TestManagerPlanNode:
    def test_creates_root_and_four_professional_tasks(
        self, tmp_path: Path
    ) -> None:
        state = planned_state(tmp_path)
        plan = state["task_plan"]
        assert isinstance(plan, TaskPlan)
        assert plan.root_task.agent_name == "ManagerAgent"
        assert plan.root_task.task_type == "review_orchestration"
        assert plan.root_task.status == "pending"
        assert plan.root_task.max_retries == 0
        assert len(state["agent_tasks"]) == 4
        assert [task.agent_name for task in plan.agent_tasks] == [
            "SecurityAgent",
            "QualityAgent",
            "PerformanceAgent",
            "TestingAgent",
        ]
        for task in plan.agent_tasks:
            assert task.parent_task_id == plan.root_task.task_id
            assert task.status == "pending"
            assert task.max_retries == 0

    def test_missing_repository_raises(self, tmp_path: Path) -> None:
        state = make_review_state(tmp_path.resolve())
        state["repository"] = None  # type: ignore[typeddict-item]
        with pytest.raises(ReviewStateError):
            manager_plan_node(state, manager=ManagerAgent())

    def test_invalid_commit_sha_fails_the_plan(self, tmp_path: Path) -> None:
        state = make_review_state(tmp_path.resolve())
        state["commit_sha"] = "bad-sha"
        with pytest.raises(ValueError):
            manager_plan_node(state, manager=ManagerAgent())


class TestDispatchWorkers:
    def test_one_send_per_dimension_with_isolated_payload(
        self, tmp_path: Path
    ) -> None:
        state = planned_state(tmp_path)
        plan = state["task_plan"]
        sends = dispatch_workers(state)

        assert [send.node for send in sends] == [
            WORKER_NODE_NAMES[dimension] for dimension in DIMENSIONS
        ]
        for dimension, send in zip(DIMENSIONS, sends, strict=True):
            assert isinstance(send.arg, WorkerDispatch)
            dispatch = send.arg
            assert dispatch.task is plan.task_for(dimension)
            assert dispatch.runtime.review_id == state["review_id"]
            assert dispatch.runtime.commit_sha == COMMIT_SHA
            assert dispatch.runtime.allowed_files == ("pkg/app.py",)
            assert dispatch.runtime.language == "python"
            assert dispatch.runtime.rules is state["rules"]
            # Worker 只拿到调度载荷，而不是完整 ReviewState。
            assert not isinstance(dispatch, dict)

    def test_dispatch_requires_plan(self, tmp_path: Path) -> None:
        state = make_review_state(tmp_path.resolve())
        with pytest.raises(ReviewStateError):
            dispatch_workers(state)


class TestWorkerNode:
    def test_returns_only_its_own_keys(self, tmp_path: Path) -> None:
        state = planned_state(tmp_path)
        dispatch = WorkerDispatch(
            task=state["task_plan"].task_for("security"),
            runtime=runtime_for(state),
        )
        node = make_worker_node(
            dimension="security",
            agent=FakeAgent(
                agent_name="SecurityAgent",
                task_type="security_review",
                result_factory=make_dimension_factory("security"),
            ),
        )

        update = asyncio.run(node(dispatch))

        assert set(update) == {
            "security_task",
            "security_result",
            "security_evidence",
            "completed_tasks",
            "failed_tasks",
            "worker_timings",
            "warnings",
        }
        assert update["security_result"].status == "completed"
        assert update["completed_tasks"] == [dispatch.task.task_id]
        assert update["failed_tasks"] == []
        assert len(update["worker_timings"]) == 1
        assert update["worker_timings"][0].task_id == dispatch.task.task_id

    def test_worker_exception_becomes_failed_result(
        self, tmp_path: Path
    ) -> None:
        class ExplodingAgent(FakeAgent):
            async def execute(
                self, dispatch: WorkerDispatch
            ) -> AgentExecution:
                raise RuntimeError(
                    f"tool crashed at {dispatch.runtime.workspace_path}"
                )

        state = planned_state(tmp_path)
        dispatch = WorkerDispatch(
            task=state["task_plan"].task_for("quality"),
            runtime=runtime_for(state),
        )
        node = make_worker_node(
            dimension="quality",
            agent=ExplodingAgent(
                agent_name="QualityAgent",
                task_type="quality_review",
            ),
        )

        update = asyncio.run(node(dispatch))

        result = update["quality_result"]
        assert result.status == "failed"
        assert result.score is None
        assert result.error is not None
        assert result.error.retryable is False
        assert update["failed_tasks"] == [dispatch.task.task_id]
        assert update["completed_tasks"] == []
        assert str(tmp_path) not in result.error.message
        assert "<workspace>" in result.error.message
        assert update["quality_task"].status == "failed"

    def test_unknown_dimension_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            make_worker_node(
                dimension="unknown",
                agent=FakeAgent(
                    agent_name="SecurityAgent",
                    task_type="security_review",
                ),
            )

    def test_worker_state_update_rejects_unknown_dimension(self) -> None:
        with pytest.raises(ValueError):
            worker_state_update("unknown", object())  # type: ignore[arg-type]


class TestManagerAggregateNode:
    def test_builds_artifacts_and_execution_summary(
        self, tmp_path: Path
    ) -> None:
        state = aggregated_state(tmp_path)
        update = manager_aggregate_node(state, manager=ManagerAgent())

        results = update["agent_results"]
        assert set(results) == set(DIMENSIONS)
        assert all(result.status == "completed" for result in results.values())

        artifact_data = update["artifact_data"]
        assert isinstance(artifact_data, ArtifactData)
        assert artifact_data.resolve(
            "static_analysis.json#/agents/security/tools/bandit/findings/0"
        )["rule_id"] == "B608"
        assert artifact_data.resolve(
            "static_analysis.json#/agents/testing"
        )["agent_name"] == "TestingAgent"
        assert artifact_data.resolve("test_report.json#/coverage") == 91.0
        assert artifact_data.resolve("test_report.json#/counts")["total"] == 3

        assert update["usage_summary"].llm_calls == 0
        execution_summary = update["execution_summary"]
        assert execution_summary.total_tasks == 4
        assert execution_summary.completed_tasks == 4
        assert execution_summary.failed_tasks == 0
        assert execution_summary.duration_seconds >= 0

        root_task = update["root_task"]
        assert root_task.status == "completed"
        assert root_task.last_error is None
        assert update["warnings"] == []

    def test_missing_worker_is_synthesized_as_failed(
        self, tmp_path: Path
    ) -> None:
        state = aggregated_state(tmp_path, missing="performance")
        update = manager_aggregate_node(state, manager=ManagerAgent())

        results = update["agent_results"]
        assert set(results) == set(DIMENSIONS)
        assert results["performance"].status == "failed"
        assert results["performance"].error is not None
        assert (
            results["performance"].error.error_type
            == "missing_agent_result"
        )
        assert results["security"].status == "completed"
        assert results["quality"].status == "completed"
        assert results["testing"].status == "completed"
        assert update["execution_summary"].failed_tasks == 1
        assert update["execution_summary"].completed_tasks == 3
        assert any(
            "performance" in warning for warning in update["warnings"]
        )
        assert isinstance(update["artifact_data"], ArtifactData)

    def test_aggregate_requires_plan(self, tmp_path: Path) -> None:
        state = make_review_state(tmp_path.resolve())
        with pytest.raises(ReviewStateError):
            manager_aggregate_node(state, manager=ManagerAgent())


class TestFinalReviewerPlaceholder:
    def test_marks_itself_as_not_implemented(self, tmp_path: Path) -> None:
        state = aggregated_state(tmp_path)
        state["artifact_data"] = ArtifactData()
        state["agent_results"] = {
            dimension: make_plan_execution(
                state["task_plan"], dimension
            ).result
            for dimension in DIMENSIONS
        }

        update = final_reviewer_node(state)

        assert update["review_report"] is None
        assert update["review_status"] == PLACEHOLDER_REVIEW_STATUS
        statistics = update["review_statistics"]
        assert statistics["implemented"] is False
        assert statistics["final_reviewer"] == "placeholder"
        assert statistics["stage"] == "2.3"
        assert statistics["artifact_data_available"] is True
        assert statistics["aggregated_dimensions"] == sorted(DIMENSIONS)
        assert "Stage 2.4" in statistics["note"]

    def test_initial_state_has_no_artifact_yet(self, tmp_path: Path) -> None:
        update = final_reviewer_node(make_review_state(tmp_path.resolve()))
        assert update["review_statistics"]["artifact_data_available"] is False
        assert update["review_statistics"]["aggregated_dimensions"] == []


class TestFullGraph:
    def test_happy_path_runs_all_nodes_in_order(
        self, tmp_path: Path
    ) -> None:
        graph = build_review_graph(make_graph_dependencies())
        state = make_review_state(tmp_path.resolve())

        with structlog.testing.capture_logs() as logs:
            output = asyncio.run(graph.ainvoke(state))

        events = [entry["event"] for entry in logs]
        assert events[0] == "manager_planning"
        assert "task_dispatch" in events
        assert events.count("worker_node_finished") == 4
        assert events.count("agent_started") == 4
        assert events.count("agent_finished") == 4
        assert events.index("workers_aggregated") > max(
            index
            for index, event in enumerate(events)
            if event == "worker_node_finished"
        )
        assert events[-1] == "final_reviewer_placeholder"

        assert output["review_status"] == PLACEHOLDER_REVIEW_STATUS
        assert output["review_report"] is None
        assert output["review_statistics"]["implemented"] is False
        assert set(output["agent_results"]) == set(DIMENSIONS)
        assert len(output["completed_tasks"]) == 4
        assert output["failed_tasks"] == []
        assert len(output["worker_timings"]) == 4
        assert output["execution_summary"].completed_tasks == 4
        assert output["root_task"].status == "completed"
        assert output["usage_summary"].llm_calls == 0
        assert isinstance(output["artifact_data"], ArtifactData)

        plan = output["task_plan"]
        for dimension in DIMENSIONS:
            assert (
                output[f"{dimension}_result"].task_id
                == plan.task_for(dimension).task_id
            )
            assert output[f"{dimension}_task"].status == "completed"

    def test_graph_has_all_seven_nodes_and_no_checkpointer(
        self,
    ) -> None:
        graph = build_review_graph(make_graph_dependencies())
        nodes = set(graph.get_graph().nodes)
        assert nodes == {
            "__start__",
            "__end__",
            *GRAPH_NODE_NAMES,
        }
        assert graph.checkpointer is None
        assert GRAPH_NODE_NAMES == (
            "manager_plan",
            "security_worker",
            "quality_worker",
            "performance_worker",
            "testing_worker",
            "manager_aggregate",
            "final_reviewer",
        )

    def test_single_worker_failure_preserves_other_results(
        self, tmp_path: Path
    ) -> None:
        graph = build_review_graph(
            make_graph_dependencies(
                errors={"security": RuntimeError("bandit exploded")}
            )
        )
        output = asyncio.run(
            graph.ainvoke(make_review_state(tmp_path.resolve()))
        )

        results = output["agent_results"]
        assert results["security"].status == "failed"
        assert results["security"].error is not None
        assert results["quality"].status == "completed"
        assert results["performance"].status == "completed"
        assert results["testing"].status == "completed"
        assert len(output["failed_tasks"]) == 1
        assert len(output["completed_tasks"]) == 3
        assert output["execution_summary"].failed_tasks == 1
        assert output["execution_summary"].completed_tasks == 3
        assert output["root_task"].status == "completed"
        assert isinstance(output["artifact_data"], ArtifactData)
        assert output["artifact_data"].resolve(
            "static_analysis.json#/agents/security"
        )["result_status"] == "failed"
        assert output["review_status"] == PLACEHOLDER_REVIEW_STATUS

    def test_all_workers_failed_still_reaches_placeholder(
        self, tmp_path: Path
    ) -> None:
        graph = build_review_graph(
            make_graph_dependencies(
                errors={
                    dimension: RuntimeError("tool unavailable")
                    for dimension in DIMENSIONS
                }
            )
        )
        output = asyncio.run(
            graph.ainvoke(make_review_state(tmp_path.resolve()))
        )

        assert all(
            result.status == "failed"
            for result in output["agent_results"].values()
        )
        assert output["root_task"].status == "failed"
        assert output["root_task"].last_error is not None
        assert (
            output["root_task"].last_error.error_type
            == "aggregate_incomplete"
        )
        assert output["execution_summary"].failed_tasks == 4
        assert output["execution_summary"].completed_tasks == 0
        assert output["review_status"] == PLACEHOLDER_REVIEW_STATUS
        assert output["review_report"] is None

    def test_manager_planning_failure_fails_the_run(
        self, tmp_path: Path
    ) -> None:
        graph = build_review_graph(make_graph_dependencies())
        state = make_review_state(tmp_path.resolve())
        state["commit_sha"] = "not-a-valid-sha"

        with pytest.raises(ValueError):
            asyncio.run(graph.ainvoke(state))

    def test_worker_is_not_retried_after_failure(
        self, tmp_path: Path
    ) -> None:
        class CountingFailAgent(FakeAgent):
            def __init__(self) -> None:
                super().__init__(
                    agent_name="TestingAgent",
                    task_type="testing_review",
                )
                self.calls = 0

            async def _run(
                self, dispatch: WorkerDispatch
            ) -> AgentRunOutput:
                self.calls += 1
                raise RuntimeError("always fails")

        agent = CountingFailAgent()
        dependencies = GraphDependencies(
            manager=ManagerAgent(),
            security_agent=FakeAgent(
                agent_name="SecurityAgent",
                task_type="security_review",
                result_factory=make_dimension_factory("security"),
            ),
            quality_agent=FakeAgent(
                agent_name="QualityAgent",
                task_type="quality_review",
                result_factory=make_dimension_factory("quality"),
            ),
            performance_agent=FakeAgent(
                agent_name="PerformanceAgent",
                task_type="performance_review",
                result_factory=make_dimension_factory("performance"),
            ),
            testing_agent=agent,
        )

        output = asyncio.run(
            build_review_graph(dependencies).ainvoke(
                make_review_state(tmp_path.resolve())
            )
        )

        assert agent.calls == 1
        assert output["agent_results"]["testing"].status == "failed"
        assert len(output["failed_tasks"]) == 1


class TestRunReviewGraph:
    def test_sync_runner_executes_graph(self, tmp_path: Path) -> None:
        output = run_review_graph(
            make_graph_dependencies(),
            make_review_state(tmp_path.resolve()),
        )
        assert output["review_status"] == PLACEHOLDER_REVIEW_STATUS

    def test_sync_runner_rejects_running_loop(
        self, tmp_path: Path
    ) -> None:
        dependencies = make_graph_dependencies()
        state = make_review_state(tmp_path.resolve())

        async def call_inside_loop() -> None:
            with pytest.raises(RuntimeError, match="running event loop"):
                run_review_graph(dependencies, state)

        asyncio.run(call_inside_loop())


class TestGraphDependencies:
    def test_rejects_mismatched_agent_name(self) -> None:
        with pytest.raises(ValueError):
            GraphDependencies(
                manager=ManagerAgent(),
                security_agent=FakeAgent(
                    agent_name="QualityAgent",
                    task_type="security_review",
                ),
                quality_agent=FakeAgent(
                    agent_name="QualityAgent",
                    task_type="quality_review",
                ),
                performance_agent=FakeAgent(
                    agent_name="PerformanceAgent",
                    task_type="performance_review",
                ),
                testing_agent=FakeAgent(
                    agent_name="TestingAgent",
                    task_type="testing_review",
                ),
            )

    def test_rejects_non_base_agent(self) -> None:
        with pytest.raises(TypeError):
            GraphDependencies(
                manager=ManagerAgent(),
                security_agent=object(),  # type: ignore[arg-type]
                quality_agent=FakeAgent(
                    agent_name="QualityAgent",
                    task_type="quality_review",
                ),
                performance_agent=FakeAgent(
                    agent_name="PerformanceAgent",
                    task_type="performance_review",
                ),
                testing_agent=FakeAgent(
                    agent_name="TestingAgent",
                    task_type="testing_review",
                ),
            )

    def test_agent_for_unknown_dimension(self) -> None:
        dependencies = make_graph_dependencies()
        with pytest.raises(ValueError):
            dependencies.agent_for("unknown")
        assert isinstance(dependencies.agent_for("security"), FakeAgent)
