"""Stage 2.3 ``ReviewState`` 字段、Reducer 与初始状态单元测试（AC-2-05）。"""

from __future__ import annotations

import asyncio
import operator
from pathlib import Path
from typing import Annotated, TypedDict, get_type_hints

import pytest
from langgraph.errors import InvalidUpdateError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from code_review.agents.contracts import ContractValidationError
from code_review.graph.state import (
    PLACEHOLDER_REVIEW_STATUS,
    REVIEW_STATUS_RUNNING,
    RepositoryContext,
    ReviewState,
    ReviewStateError,
    build_initial_state,
)
from tests.stage2_helpers import (
    COMMIT_SHA,
    make_inventory_summary,
    make_repository_context,
    make_review_rules,
    make_review_state,
)

EXPECTED_FIELDS = {
    "review_id",
    "trace_id",
    "commit_sha",
    "repository",
    "workspace_path",
    "allowed_files",
    "inventory",
    "rules",
    "task_plan",
    "root_task",
    "agent_tasks",
    "security_task",
    "quality_task",
    "performance_task",
    "testing_task",
    "security_result",
    "quality_result",
    "performance_result",
    "testing_result",
    "security_evidence",
    "quality_evidence",
    "performance_evidence",
    "testing_evidence",
    "completed_tasks",
    "failed_tasks",
    "worker_timings",
    "warnings",
    "agent_results",
    "artifact_data",
    "usage_summary",
    "execution_summary",
    "review_report",
    "review_statistics",
    "review_status",
}

REDUCER_FIELDS = {
    "completed_tasks",
    "failed_tasks",
    "worker_timings",
    "warnings",
}


def build_state(tmp_path: Path) -> dict:
    return build_initial_state(
        review_id="review-state-001",
        commit_sha=COMMIT_SHA,
        repository=make_repository_context(),
        workspace_path=tmp_path.resolve(),
        allowed_files=("pkg/app.py",),
        inventory=make_inventory_summary(),
        rules=make_review_rules(),
        trace_id="trace-state-001",
    )


class TestReviewStateContract:
    def test_state_declares_every_audit_field(self) -> None:
        hints = get_type_hints(ReviewState, include_extras=True)
        assert set(hints) == EXPECTED_FIELDS

    def test_reducer_fields_use_operator_add(self) -> None:
        hints = get_type_hints(ReviewState, include_extras=True)
        for name in REDUCER_FIELDS:
            annotation = hints[name]
            assert getattr(annotation, "__metadata__", ()) == (
                operator.add,
            ), f"{name} must use operator.add"
        for name in EXPECTED_FIELDS - REDUCER_FIELDS:
            assert not hasattr(hints[name], "__metadata__"), (
                f"{name} must not declare a reducer"
            )

    def test_key_types_match_existing_contracts(self) -> None:
        hints = get_type_hints(ReviewState, include_extras=True)
        assert hints["review_id"] is str
        assert hints["workspace_path"] is str
        assert hints["allowed_files"] == tuple[str, ...]
        assert hints["review_status"] is str
        assert "TaskPlan" in str(hints["task_plan"])
        assert "ArtifactData" in str(hints["artifact_data"])
        assert "InventorySummary" in str(hints["inventory"])

    def test_initial_state_matches_audit_defaults(self, tmp_path: Path) -> None:
        state = build_state(tmp_path)
        assert set(state) == EXPECTED_FIELDS
        assert state["review_status"] == REVIEW_STATUS_RUNNING
        for name in (
            "task_plan",
            "root_task",
            "security_task",
            "quality_task",
            "performance_task",
            "testing_task",
            "security_result",
            "quality_result",
            "performance_result",
            "testing_result",
            "security_evidence",
            "quality_evidence",
            "performance_evidence",
            "testing_evidence",
            "artifact_data",
            "usage_summary",
            "execution_summary",
            "review_report",
        ):
            assert state[name] is None, name
        for name in (
            "agent_tasks",
            "completed_tasks",
            "failed_tasks",
            "worker_timings",
            "warnings",
        ):
            assert state[name] == [], name
        assert state["agent_results"] == {}
        assert state["review_statistics"] == {}

    def test_initial_state_paths_are_normalized(self, tmp_path: Path) -> None:
        state = build_state(tmp_path)
        assert state["workspace_path"] == str(tmp_path.resolve())
        assert isinstance(state["workspace_path"], str)
        assert state["allowed_files"] == ("pkg/app.py",)
        assert state["commit_sha"] == COMMIT_SHA


class TestInitialStateValidation:
    def test_empty_review_id_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ReviewStateError):
            build_initial_state(
                review_id=" ",
                commit_sha=COMMIT_SHA,
                repository=make_repository_context(),
                workspace_path=tmp_path,
                allowed_files=("pkg/app.py",),
                inventory=None,
                rules=make_review_rules(),
            )

    def test_relative_workspace_path_is_rejected(self) -> None:
        with pytest.raises(ReviewStateError):
            build_initial_state(
                review_id="review-001",
                commit_sha=COMMIT_SHA,
                repository=make_repository_context(),
                workspace_path=Path("relative/workspace"),
                allowed_files=("pkg/app.py",),
                inventory=None,
                rules=make_review_rules(),
            )

    def test_invalid_commit_sha_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ContractValidationError):
            build_initial_state(
                review_id="review-001",
                commit_sha="not-a-sha",
                repository=make_repository_context(),
                workspace_path=tmp_path,
                allowed_files=("pkg/app.py",),
                inventory=None,
                rules=make_review_rules(),
            )

    @pytest.mark.parametrize(
        "unsafe_path",
        ["../escape.py", "C:/abs.py", "pkg\\app.py", "/rooted.py"],
    )
    def test_unsafe_allowed_files_are_rejected(
        self,
        tmp_path: Path,
        unsafe_path: str,
    ) -> None:
        with pytest.raises(ContractValidationError):
            build_initial_state(
                review_id="review-001",
                commit_sha=COMMIT_SHA,
                repository=make_repository_context(),
                workspace_path=tmp_path,
                allowed_files=(unsafe_path,),
                inventory=None,
                rules=make_review_rules(),
            )

    def test_repository_context_is_required(self, tmp_path: Path) -> None:
        with pytest.raises(ReviewStateError):
            build_initial_state(
                review_id="review-001",
                commit_sha=COMMIT_SHA,
                repository="https://github.com/acme/demo",  # type: ignore[arg-type]
                workspace_path=tmp_path,
                allowed_files=("pkg/app.py",),
                inventory=None,
                rules=make_review_rules(),
            )

    def test_repository_context_validates_fields(self) -> None:
        with pytest.raises(ReviewStateError):
            RepositoryContext(
                repository_url="",
                repository_name="acme/demo",
                branch="main",
            )
        with pytest.raises(ReviewStateError):
            RepositoryContext(
                repository_url="https://github.com/acme/demo",
                repository_name="acme/demo",
                branch="main",
                source_type="unknown",
            )

    def test_repository_context_trusted_fixture_flag(self) -> None:
        fixture = make_repository_context(source_type="trusted_fixture")
        assert fixture.trusted_fixture is True
        assert make_repository_context().trusted_fixture is False


# ----------------------------------------------------------------------
# Reducer runtime behaviour


class _ReducerProbe(TypedDict, total=False):
    completed_tasks: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]


def _reducer_fan(_state: dict) -> list[Send]:
    return [Send("probe_worker", "a"), Send("probe_worker", "b")]


async def _reducer_worker(payload: str) -> dict:
    return {
        "completed_tasks": [f"task-{payload}"],
        "warnings": [f"warning-{payload}"],
    }


def test_operator_add_merges_parallel_worker_updates() -> None:
    graph = StateGraph(_ReducerProbe)
    graph.add_node("probe_worker", _reducer_worker)
    graph.add_node("dispatch", lambda state: {})
    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges(
        "dispatch", _reducer_fan, ["probe_worker"]
    )
    graph.add_edge("probe_worker", END)
    compiled = graph.compile()

    output = asyncio.run(
        compiled.ainvoke({"completed_tasks": [], "warnings": []})
    )

    assert sorted(output["completed_tasks"]) == ["task-a", "task-b"]
    assert sorted(output["warnings"]) == ["warning-a", "warning-b"]


def test_real_review_state_reducers_merge_parallel_updates(
    tmp_path: Path,
) -> None:
    async def worker(payload: str) -> dict:
        return {
            "completed_tasks": [f"task-{payload}"],
            "warnings": [f"warning-{payload}"],
        }

    def fan(_state: dict) -> list[Send]:
        return [Send("worker", "a"), Send("worker", "b")]

    graph = StateGraph(ReviewState)
    graph.add_node("worker", worker)
    graph.add_node("dispatch", lambda state: {})
    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges("dispatch", fan, ["worker"])
    graph.add_edge("worker", END)
    compiled = graph.compile()

    output = asyncio.run(compiled.ainvoke(build_state(tmp_path)))

    assert sorted(output["completed_tasks"]) == ["task-a", "task-b"]
    assert sorted(output["warnings"]) == ["warning-a", "warning-b"]


class _NoReducerProbe(TypedDict, total=False):
    shared: list[str]


def test_parallel_write_to_non_reducer_raises_invalid_update() -> None:
    async def worker(payload: str) -> dict:
        return {"shared": [payload]}

    def fan(_state: dict) -> list[Send]:
        return [Send("worker", "a"), Send("worker", "b")]

    graph = StateGraph(_NoReducerProbe)
    graph.add_node("worker", worker)
    graph.add_node("dispatch", lambda state: {})
    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges("dispatch", fan, ["worker"])
    graph.add_edge("worker", END)
    compiled = graph.compile()

    with pytest.raises(InvalidUpdateError):
        asyncio.run(compiled.ainvoke({"shared": []}))


# ----------------------------------------------------------------------
# Exported constants


def test_review_status_constants_are_distinct() -> None:
    assert REVIEW_STATUS_RUNNING == "running"
    assert PLACEHOLDER_REVIEW_STATUS == "pending_final_review"
    assert REVIEW_STATUS_RUNNING != PLACEHOLDER_REVIEW_STATUS


def test_make_review_state_helper_uses_real_contracts(
    tmp_path: Path,
) -> None:
    state = make_review_state(tmp_path)
    assert isinstance(state["rules"], type(make_review_rules()))
    assert isinstance(state["repository"], RepositoryContext)
    assert state["allowed_files"] == ("pkg/app.py",)
    assert state["task_plan"] is None
    assert state["artifact_data"] is None
    assert state["review_report"] is None
