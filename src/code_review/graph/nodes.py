"""Stage 2.4 LangGraph 节点：Manager、四个 Worker 与 Final Reviewer。

并发写入约束（审计计划 §5.1/§5.4）：

- Worker 节点只返回自己的 ``{dimension}_task`` / ``{dimension}_result`` /
  ``{dimension}_evidence``，以及 ``completed_tasks`` / ``failed_tasks`` /
  ``worker_timings`` / ``warnings`` 四个 Reducer 列表更新；
- ``agent_results``、``artifact_data``、``usage_summary``、
  ``execution_summary`` 只由 ``manager_aggregate`` 单写者返回；
- ``final_reviewer`` 是独立节点但**不是 AgentTask**：不创建 task_id，不增加
  任务总数；它只读取 State 中的四个 AgentResult 与内存 ``ArtifactData``。

本模块不访问网络、不调用真实 LLM、不克隆或写入仓库。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog
from langgraph.types import Send

from code_review.agents.base import BaseAgent
from code_review.agents.contracts import (
    AgentExecution,
    ArtifactData,
    ContractValidationError,
    UsageSummary,
    WorkerDispatch,
    WorkerEvidence,
    WorkerRuntime,
    WorkerTiming,
)
from code_review.agents.manager import DIMENSIONS, ManagerAgent, TaskPlan
from code_review.agents.reviewer import (
    REVIEW_STATUS_COMPLETED,
    FinalReviewer,
    FinalReviewRequest,
)
from code_review.graph.state import (
    RepositoryContext,
    ReviewState,
    ReviewStateError,
)
from code_review.schemas.report import ExecutionSummary
from code_review.schemas.result import AgentResult
from code_review.schemas.task import AgentTask, ErrorInfo, utc_now
from code_review.services.redaction import redact_sensitive_text
from config.review_rules import ReviewRules

__all__ = [
    "WORKER_NODE_NAMES",
    "WorkerNode",
    "dispatch_workers",
    "final_reviewer_node",
    "make_worker_node",
    "manager_aggregate_node",
    "manager_plan_node",
    "worker_state_update",
]

LOGGER = structlog.get_logger(__name__)

WORKER_NODE_NAMES: dict[str, str] = {
    "security": "security_worker",
    "quality": "quality_worker",
    "performance": "performance_worker",
    "testing": "testing_worker",
}

WorkerNode = Callable[[WorkerDispatch], Awaitable[dict[str, object]]]

_MAX_ERROR_MESSAGE = 2000


# ----------------------------------------------------------------------
# Manager Planning


def manager_plan_node(
    state: ReviewState,
    *,
    manager: ManagerAgent,
) -> dict[str, object]:
    """确定性生成根任务与四个专业任务；失败则整次图执行失败。"""

    review_id = _required_str(state, "review_id")
    commit_sha = _required_str(state, "commit_sha")
    repository = _required_repository(state)

    LOGGER.info("manager_planning", review_id=review_id)
    plan = manager.plan(
        review_id=review_id,
        commit_sha=commit_sha,
        language=repository.language,
    )
    LOGGER.info(
        "manager_plan_ready",
        review_id=review_id,
        root_task_id=plan.root_task.task_id,
        task_ids=[task.task_id for task in plan.agent_tasks],
    )
    return {
        "task_plan": plan,
        "root_task": plan.root_task,
        "agent_tasks": list(plan.agent_tasks),
    }


def dispatch_workers(state: ReviewState) -> list[Send]:
    """条件边：为四个维度各生成一个 ``Send``，只携带该维度的调度载荷。"""

    plan = _required_plan(state)
    runtime = _runtime_from_state(state)
    review_id = _required_str(state, "review_id")

    sends = [
        Send(
            WORKER_NODE_NAMES[dimension],
            WorkerDispatch(task=plan.task_for(dimension), runtime=runtime),
        )
        for dimension in DIMENSIONS
    ]
    LOGGER.info(
        "task_dispatch",
        review_id=review_id,
        dimensions=list(DIMENSIONS),
        task_ids=[
            plan.task_for(dimension).task_id for dimension in DIMENSIONS
        ],
    )
    return sends


# ----------------------------------------------------------------------
# Worker nodes


def make_worker_node(
    *,
    dimension: str,
    agent: BaseAgent,
) -> WorkerNode:
    """构造只处理单个维度的异步 Worker 节点。

    ``Send`` 直接把 ``WorkerDispatch`` 作为节点输入，节点看不到完整
    ``ReviewState``，从结构上保证任务与上下文隔离。
    """

    if dimension not in DIMENSIONS:
        raise ValueError(f"unknown dimension: {dimension}")
    if not isinstance(agent, BaseAgent):
        raise TypeError("worker agent must be a BaseAgent")

    async def worker_node(dispatch: WorkerDispatch) -> dict[str, object]:
        try:
            execution = await agent.execute(dispatch)
        except Exception as exc:
            if not isinstance(dispatch, WorkerDispatch):
                raise
            execution = _failed_execution(dispatch, exc)
            LOGGER.warning(
                "worker_node_failed",
                dimension=dimension,
                agent_name=dispatch.task.agent_name,
                task_id=dispatch.task.task_id,
                error_type=type(exc).__name__,
            )
        LOGGER.info(
            "worker_node_finished",
            dimension=dimension,
            agent_name=execution.result.agent_name,
            task_id=execution.task.task_id,
            status=execution.result.status,
            duration_seconds=round(execution.timing.duration_seconds, 6),
        )
        return worker_state_update(dimension, execution)

    return worker_node


def worker_state_update(
    dimension: str,
    execution: AgentExecution,
) -> dict[str, object]:
    """构造单个 Worker 对共享状态的增量更新（只含自己的键）。"""

    if dimension not in DIMENSIONS:
        raise ValueError(f"unknown dimension: {dimension}")
    if not isinstance(execution, AgentExecution):
        raise TypeError("execution must be an AgentExecution")

    task_id = execution.task.task_id
    update: dict[str, object] = {
        f"{dimension}_task": execution.task,
        f"{dimension}_result": execution.result,
        f"{dimension}_evidence": execution.evidence,
        "worker_timings": [execution.timing],
        "warnings": list(execution.evidence.warnings),
    }
    if execution.result.status == "failed":
        update["failed_tasks"] = [task_id]
        update["completed_tasks"] = []
    else:
        update["completed_tasks"] = [task_id]
        update["failed_tasks"] = []
    return update


def _failed_execution(
    dispatch: WorkerDispatch,
    exc: Exception,
) -> AgentExecution:
    """把 Worker 节点层面的普通异常转换为合法的 failed ``AgentExecution``。"""

    if not isinstance(dispatch, WorkerDispatch):
        raise ContractValidationError(
            "worker node requires a WorkerDispatch payload"
        ) from exc

    finished_at = utc_now()
    started_at = dispatch.task.started_at or dispatch.task.created_at
    finished_at = max(finished_at, started_at)
    duration = (finished_at - started_at).total_seconds()

    error = ErrorInfo(
        error_type="agent_execution_error",
        message=_sanitize_error_message(
            exc,
            dispatch.runtime.workspace_path,
        ),
        retryable=False,
        occurred_at=finished_at,
        details={"exception_type": type(exc).__name__},
    )
    task_payload = dispatch.task.model_dump()
    task_payload.update(
        status="failed",
        started_at=started_at,
        finished_at=finished_at,
        last_error=error,
    )
    failed_task = AgentTask.model_validate(task_payload)
    failed_result = AgentResult(
        task_id=failed_task.task_id,
        parent_task_id=failed_task.parent_task_id,
        review_id=failed_task.review_id,
        agent_name=failed_task.agent_name,
        status="failed",
        commit_sha=dispatch.runtime.commit_sha,
        score=None,
        findings=[],
        summary=f"{failed_task.agent_name} execution failed",
        execution_time=duration,
        error=error,
        metadata={"worker_node_error": True},
    )
    evidence = WorkerEvidence(
        agent_name=failed_task.agent_name,
        warnings=("agent execution failed",),
    )
    timing = WorkerTiming(
        agent_name=failed_task.agent_name,
        task_id=failed_task.task_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        status="failed",
    )
    return AgentExecution(
        task=failed_task,
        result=failed_result,
        evidence=evidence,
        timing=timing,
    )


# ----------------------------------------------------------------------
# Manager Aggregate


def manager_aggregate_node(
    state: ReviewState,
    *,
    manager: ManagerAgent,
) -> dict[str, object]:
    """Fan-in：等待四个 Worker 后构建证据快照与执行统计。

    ``ArtifactData`` 必须在 Final Reviewer 节点之前构建并写入 State；
    缺失结果由 Manager 合成 failed ``AgentResult``，不静默丢弃。
    """

    plan = _required_plan(state)
    review_id = _required_str(state, "review_id")
    executions = {
        dimension: _execution_from_state(state, dimension)
        for dimension in DIMENSIONS
    }
    aggregated = manager.aggregate(plan, executions=executions)

    LOGGER.info(
        "workers_aggregated",
        review_id=review_id,
        dimensions=list(DIMENSIONS),
        completed_tasks=aggregated.execution_summary.completed_tasks,
        partial_tasks=aggregated.execution_summary.partial_tasks,
        failed_tasks=aggregated.execution_summary.failed_tasks,
        duration_seconds=round(
            aggregated.execution_summary.duration_seconds, 6
        ),
    )
    return {
        "agent_results": dict(aggregated.agent_results),
        "artifact_data": aggregated.artifact_data,
        "usage_summary": aggregated.usage_summary,
        "execution_summary": aggregated.execution_summary,
        "root_task": aggregated.root_task,
        "warnings": list(aggregated.warnings),
    }


def _execution_from_state(
    state: ReviewState,
    dimension: str,
) -> AgentExecution | None:
    """从 Worker 写入的独立键重建 ``AgentExecution``；缺失则为 None。"""

    task = state.get(f"{dimension}_task")
    result = state.get(f"{dimension}_result")
    evidence = state.get(f"{dimension}_evidence")
    if not (
        isinstance(task, AgentTask)
        and isinstance(result, AgentResult)
        and isinstance(evidence, WorkerEvidence)
    ):
        return None

    timing = _find_timing(state.get("worker_timings"), task.task_id)
    if timing is None:
        timing = _fallback_timing(task, result)
    return AgentExecution(
        task=task,
        result=result,
        evidence=evidence,
        timing=timing,
    )


def _find_timing(
    timings: object,
    task_id: str,
) -> WorkerTiming | None:
    if not isinstance(timings, (list, tuple)):
        return None
    for item in timings:
        if isinstance(item, WorkerTiming) and item.task_id == task_id:
            return item
    return None


def _fallback_timing(task: AgentTask, result: AgentResult) -> WorkerTiming:
    """为手工构造的状态用真实任务时间戳推导 timing（不伪造数值）。"""

    started_at = task.started_at or task.created_at
    finished_at = task.finished_at or started_at
    finished_at = max(finished_at, started_at)
    duration = max(
        0.0,
        float(result.execution_time),
        (finished_at - started_at).total_seconds(),
    )
    return WorkerTiming(
        agent_name=task.agent_name,
        task_id=task.task_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
        status=result.status,
    )


# ----------------------------------------------------------------------
# Final Reviewer


def final_reviewer_node(state: ReviewState) -> dict[str, object]:
    """真实 Final Reviewer：证据验证、去重、评分、verdict 与报告。

    该节点不是 AgentTask：不创建 task_id，也不改变四个专业 Agent 的任务
    总数。失败时异常直接向上抛出，由调用方判定整次审查失败，不伪造报告。
    """

    review_id = _required_str(state, "review_id")
    repository = _required_repository(state)
    agent_results = state.get("agent_results")
    if not isinstance(agent_results, dict) or not agent_results:
        raise ReviewStateError(
            "ReviewState.agent_results must be provided by manager_aggregate"
        )
    artifact_data = state.get("artifact_data")
    if not isinstance(artifact_data, ArtifactData):
        raise ReviewStateError(
            "ReviewState.artifact_data must be built by manager_aggregate "
            "before final review"
        )
    usage_summary = state.get("usage_summary")
    if not isinstance(usage_summary, UsageSummary):
        raise ReviewStateError(
            "ReviewState.usage_summary must be provided by manager_aggregate"
        )
    execution_summary = state.get("execution_summary")
    if execution_summary is not None and not isinstance(
        execution_summary, ExecutionSummary
    ):
        raise ReviewStateError(
            "ReviewState.execution_summary must be an ExecutionSummary"
        )

    request = FinalReviewRequest(
        review_id=review_id,
        trace_id=state.get("trace_id"),
        commit_sha=_required_str(state, "commit_sha"),
        repository=repository.repository_name,
        repository_url=repository.repository_url,
        branch=repository.branch,
        language=repository.language,
        workspace_path=Path(_required_str(state, "workspace_path")),
        allowed_files=tuple(state.get("allowed_files") or ()),
        rules=_required_rules(state),
        agent_results=agent_results,
        artifact_data=artifact_data,
        usage_summary=usage_summary,
        execution_summary=execution_summary,
        warnings=tuple(state.get("warnings") or ()),
    )
    outcome = FinalReviewer().review(request)

    LOGGER.info(
        "final_review_completed",
        review_id=review_id,
        report_status=outcome.report.report_status,
        overall_verdict=outcome.report.overall_verdict,
        overall_score=outcome.report.overall_score,
        findings=len(outcome.report.findings),
        rejected_findings=len(outcome.report.rejected_findings),
    )
    return {
        "review_report": outcome.report,
        "review_statistics": outcome.statistics,
        "review_status": (
            outcome.review_status
            if outcome.review_status
            else REVIEW_STATUS_COMPLETED
        ),
    }


# ----------------------------------------------------------------------
# State helpers


def _required_str(state: ReviewState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReviewStateError(
            f"ReviewState.{key} must be a non-empty string"
        )
    return value


def _required_repository(state: ReviewState) -> RepositoryContext:
    repository = state.get("repository")
    if not isinstance(repository, RepositoryContext):
        raise ReviewStateError(
            "ReviewState.repository must be a RepositoryContext"
        )
    return repository


def _required_plan(state: ReviewState) -> TaskPlan:
    plan = state.get("task_plan")
    if not isinstance(plan, TaskPlan):
        raise ReviewStateError(
            "ReviewState.task_plan must be a TaskPlan produced by "
            "manager_plan"
        )
    return plan


def _required_rules(state: ReviewState) -> ReviewRules:
    rules = state.get("rules")
    if not isinstance(rules, ReviewRules):
        raise ReviewStateError("ReviewState.rules must be a ReviewRules")
    return rules


def _runtime_from_state(state: ReviewState) -> WorkerRuntime:
    """按审计计划 §5.1 的最小上下文构造 WorkerRuntime。"""

    return WorkerRuntime(
        workspace_path=Path(_required_str(state, "workspace_path")),
        allowed_files=tuple(state.get("allowed_files") or ()),
        commit_sha=_required_str(state, "commit_sha"),
        language=_required_repository(state).language,
        review_id=_required_str(state, "review_id"),
        rules=_required_rules(state),
        trace_id=state.get("trace_id"),
    )


def _sanitize_error_message(exc: Exception, workspace_path: Path) -> str:
    raw = str(exc).strip() or type(exc).__name__
    for source in (
        str(workspace_path),
        str(workspace_path).replace("\\", "/"),
    ):
        if source:
            raw = raw.replace(source, "<workspace>")
    cleaned = redact_sensitive_text(raw, max_chars=_MAX_ERROR_MESSAGE)
    return cleaned or type(exc).__name__
