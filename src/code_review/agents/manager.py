"""Stage 2.2 确定性 Manager：任务计划与结果聚合。

Manager 是纯 Python 组件，不调用 LLM、不扫描代码、不执行工具、不生成
Finding、不评分、不去重、不生成最终结论。它只负责：

- ``plan()``：创建根任务与四个固定的专业 AgentTask；
- ``aggregate()``：校验四个维度结果是否齐全，构建 ``agent_results``、
  ``ArtifactData``、``UsageSummary`` 与 ``ExecutionSummary``，并把根任务
  更新为合法终态。

缺失或非法的 Agent 结果不会被静默忽略，而是合成一个符合冻结 Schema 的
failed ``AgentResult`` 并记录 warning，其他维度的真实结果保持不变。
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from code_review.agents.contracts import (
    AgentExecution,
    ArtifactData,
    UsageSummary,
    WorkerEvidence,
    WorkerTiming,
)
from code_review.schemas.report import ExecutionSummary
from code_review.schemas.result import AgentResult
from code_review.schemas.task import AgentTask, ErrorInfo, utc_now

__all__ = [
    "AGENT_SPECS",
    "DIMENSIONS",
    "AggregatedResults",
    "ManagerAgent",
    "TaskPlan",
]

DIMENSIONS: tuple[str, ...] = ("security", "quality", "performance", "testing")

# (dimension, agent_name, task_type, description)
AGENT_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "security",
        "SecurityAgent",
        "security_review",
        (
            "Review the repository for security issues using deterministic "
            "security tools and evidence-based analysis."
        ),
    ),
    (
        "quality",
        "QualityAgent",
        "quality_review",
        (
            "Review the repository for code quality, complexity and "
            "error-handling issues using deterministic quality tools."
        ),
    ),
    (
        "performance",
        "PerformanceAgent",
        "performance_review",
        (
            "Review the repository for static performance risks such as "
            "algorithmic complexity and memory or I/O pressure."
        ),
    ),
    (
        "testing",
        "TestingAgent",
        "testing_review",
        (
            "Review the repository's real test execution results and coverage "
            "when test execution is permitted."
        ),
    ),
)

_ROOT_AGENT_NAME = "ManagerAgent"
_ROOT_TASK_TYPE = "review_orchestration"

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _thaw(value: Any) -> Any:
    """将 WorkerEvidence 的只读冻结结构复制为普通 JSON 数据。"""

    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class TaskPlan:
    """Manager Planning 的确定性产物：根任务与四个专业任务。"""

    root_task: AgentTask
    agent_tasks: tuple[AgentTask, ...]
    review_id: str
    commit_sha: str
    _by_dimension: Mapping[str, AgentTask] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.root_task, AgentTask):
            raise TypeError("TaskPlan.root_task must be an AgentTask")
        if isinstance(self.agent_tasks, (str, bytes)):
            raise TypeError("TaskPlan.agent_tasks must be a sequence")
        tasks = tuple(self.agent_tasks)
        if len(tasks) != len(DIMENSIONS):
            raise ValueError(
                "TaskPlan must contain exactly four professional agent tasks"
            )
        if self.root_task.agent_name != _ROOT_AGENT_NAME:
            raise ValueError("root task agent_name must be ManagerAgent")
        if self.root_task.task_type != _ROOT_TASK_TYPE:
            raise ValueError(
                "root task task_type must be review_orchestration"
            )
        if self.root_task.max_retries != 0:
            raise ValueError("root task max_retries must be 0")
        if self.root_task.review_id != self.review_id:
            raise ValueError("root task review_id does not match the plan")
        if not _COMMIT_SHA_RE.fullmatch(str(self.commit_sha)):
            raise ValueError(
                "TaskPlan.commit_sha must be 40 lowercase hex characters"
            )

        by_dimension: dict[str, AgentTask] = {}
        seen_ids: set[str] = {self.root_task.task_id}
        for index, (dimension, agent_name, task_type, _) in enumerate(
            AGENT_SPECS
        ):
            task = tasks[index]
            if not isinstance(task, AgentTask):
                raise TypeError(
                    "TaskPlan.agent_tasks must contain AgentTask objects"
                )
            if task.parent_task_id != self.root_task.task_id:
                raise ValueError(
                    f"{dimension} task parent_task_id must equal root task_id"
                )
            if task.agent_name != agent_name:
                raise ValueError(
                    f"{dimension} task agent_name must be {agent_name}"
                )
            if task.task_type != task_type:
                raise ValueError(
                    f"{dimension} task task_type must be {task_type}"
                )
            if task.max_retries != 0:
                raise ValueError(f"{dimension} task max_retries must be 0")
            if task.review_id != self.review_id:
                raise ValueError(
                    f"{dimension} task review_id does not match the plan"
                )
            if task.task_id in seen_ids:
                raise ValueError("agent task ids must be unique")
            seen_ids.add(task.task_id)
            by_dimension[dimension] = task

        object.__setattr__(self, "agent_tasks", tasks)
        object.__setattr__(
            self, "_by_dimension", MappingProxyType(by_dimension)
        )

    @property
    def dimensions(self) -> tuple[str, ...]:
        return DIMENSIONS

    def task_for(self, dimension: str) -> AgentTask:
        """按维度取得专业任务；未知维度明确报错。"""

        try:
            return self._by_dimension[dimension]
        except KeyError as exc:
            raise ValueError(f"unknown dimension: {dimension}") from exc

    def by_dimension(self) -> Mapping[str, AgentTask]:
        return self._by_dimension


@dataclass(frozen=True)
class AggregatedResults:
    """Manager Aggregate 的完整输出，供 Final Reviewer 与报告生成器使用。"""

    agent_results: dict[str, AgentResult]
    artifact_data: ArtifactData
    usage_summary: UsageSummary
    execution_summary: ExecutionSummary
    root_task: AgentTask
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.agent_results, dict):
            raise TypeError("AggregatedResults.agent_results must be a dict")
        if set(self.agent_results) != set(DIMENSIONS):
            raise ValueError(
                "AggregatedResults.agent_results must contain exactly the "
                "four dimensions"
            )
        for dimension, result in self.agent_results.items():
            if not isinstance(result, AgentResult):
                raise TypeError(
                    f"agent_results[{dimension}] must be an AgentResult"
                )
        if not isinstance(self.artifact_data, ArtifactData):
            raise TypeError(
                "AggregatedResults.artifact_data must be ArtifactData"
            )
        if not isinstance(self.usage_summary, UsageSummary):
            raise TypeError(
                "AggregatedResults.usage_summary must be UsageSummary"
            )
        if not isinstance(self.execution_summary, ExecutionSummary):
            raise TypeError(
                "AggregatedResults.execution_summary must be ExecutionSummary"
            )
        if not isinstance(self.root_task, AgentTask):
            raise TypeError("AggregatedResults.root_task must be an AgentTask")
        object.__setattr__(self, "warnings", tuple(self.warnings))


class ManagerAgent:
    """确定性 Manager：只做计划与聚合。"""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    # ------------------------------------------------------------------
    # Planning

    def plan(
        self,
        *,
        review_id: str,
        commit_sha: str,
        language: str = "python",
        timeout_seconds: float | None = None,
    ) -> TaskPlan:
        """创建根任务与四个专业任务。本方法不读取工作区、不调用工具。"""

        if not isinstance(review_id, str) or not review_id.strip():
            raise ValueError("review_id must be a non-empty string")
        if not _COMMIT_SHA_RE.fullmatch(str(commit_sha)):
            raise ValueError(
                "commit_sha must be 40 lowercase hex characters"
            )
        if not isinstance(language, str) or not language.strip():
            raise ValueError("language must be a non-empty string")
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")

        created_at = self._clock()
        root_task = AgentTask(
            review_id=review_id,
            agent_name=_ROOT_AGENT_NAME,
            task_type=_ROOT_TASK_TYPE,
            description=(
                "Orchestrate a deterministic four-dimension code review."
            ),
            input_data={
                "dimensions": list(DIMENSIONS),
                "language": language,
                "commit_sha": commit_sha,
            },
            expected_output={
                "task_plan": "root task and four professional agent tasks"
            },
            priority="high",
            required=True,
            status="pending",
            max_retries=0,
            timeout_seconds=timeout_seconds,
            created_at=created_at,
        )

        agent_tasks = tuple(
            AgentTask(
                parent_task_id=root_task.task_id,
                review_id=review_id,
                agent_name=agent_name,
                task_type=task_type,
                description=description,
                input_data={
                    "dimension": dimension,
                    "language": language,
                },
                expected_output={
                    "agent_result": "AgentResult",
                    "evidence": "WorkerEvidence",
                },
                priority="medium",
                required=True,
                status="pending",
                max_retries=0,
                timeout_seconds=timeout_seconds,
                created_at=created_at,
            )
            for dimension, agent_name, task_type, description in AGENT_SPECS
        )
        return TaskPlan(
            root_task=root_task,
            agent_tasks=agent_tasks,
            review_id=review_id,
            commit_sha=commit_sha,
        )

    # ------------------------------------------------------------------
    # Aggregation

    def aggregate(
        self,
        plan: TaskPlan,
        *,
        executions: Mapping[str, AgentExecution | None],
        warnings: Sequence[str] = (),
    ) -> AggregatedResults:
        """汇总四个维度结果；缺失/非法结果合成 failed 并记录 warning。"""

        if not isinstance(plan, TaskPlan):
            raise TypeError("plan must be a TaskPlan")
        if not isinstance(executions, Mapping):
            raise TypeError("executions must be a mapping")

        collected_warnings = [
            self._require_warning(item) for item in warnings
        ]

        agent_results: dict[str, AgentResult] = {}
        evidences: dict[str, WorkerEvidence] = {}
        timings: list[WorkerTiming] = []

        for dimension, agent_name, _, _ in AGENT_SPECS:
            task = plan.task_for(dimension)
            execution = executions.get(dimension)
            reason = self._invalid_execution_reason(
                execution, task=task, plan=plan
            )
            if reason is not None:
                collected_warnings.append(
                    f"{dimension} agent result is unavailable ({reason}); "
                    "a failed result was synthesized"
                )
                agent_results[dimension] = self._synthesized_failed_result(
                    task, plan, reason
                )
                evidences[dimension] = WorkerEvidence(
                    agent_name=agent_name,
                    warnings=(
                        (
                            "manager synthesized a failed result for a missing "
                            "agent execution"
                        ),
                    ),
                )
                continue
            assert isinstance(execution, AgentExecution)
            agent_results[dimension] = execution.result
            evidences[dimension] = execution.evidence
            timings.append(execution.timing)

        for key in executions:
            if key not in DIMENSIONS:
                collected_warnings.append(
                    f"unknown execution key was ignored: {key}"
                )

        static_analysis = {
            "schema_version": "1.0",
            "agents": {
                dimension: self._agent_static_block(
                    dimension,
                    agent_results[dimension],
                    evidences[dimension],
                )
                for dimension in DIMENSIONS
            },
        }
        test_report = self._build_test_report(evidences["testing"], agent_results["testing"])
        artifact_data = ArtifactData(
            static_analysis=static_analysis,
            test_report=test_report,
        )

        usage_summary = UsageSummary()
        for dimension in DIMENSIONS:
            usage_summary = usage_summary + evidences[dimension].usage

        execution_summary = self._execution_summary(
            agent_results,
            timings,
        )
        root_task = self._finalize_root(plan.root_task, agent_results, timings)

        return AggregatedResults(
            agent_results=dict(agent_results),
            artifact_data=artifact_data,
            usage_summary=usage_summary,
            execution_summary=execution_summary,
            root_task=root_task,
            warnings=tuple(collected_warnings),
        )

    # ------------------------------------------------------------------
    # Validation helpers

    @staticmethod
    def _require_warning(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("aggregate warnings must be non-empty strings")
        return value

    def _invalid_execution_reason(
        self,
        execution: AgentExecution | None,
        *,
        task: AgentTask,
        plan: TaskPlan,
    ) -> str | None:
        if execution is None:
            return "missing"
        if not isinstance(execution, AgentExecution):
            return "invalid type"
        result = execution.result
        evidence = execution.evidence
        if result.task_id != task.task_id:
            return "task_id mismatch"
        if result.agent_name != task.agent_name:
            return "agent_name mismatch"
        if result.review_id != plan.review_id:
            return "review_id mismatch"
        if result.commit_sha != plan.commit_sha:
            return "commit_sha mismatch"
        if evidence.agent_name != task.agent_name:
            return "evidence agent_name mismatch"
        return None

    def _synthesized_failed_result(
        self,
        task: AgentTask,
        plan: TaskPlan,
        reason: str,
    ) -> AgentResult:
        finished_at = self._clock()
        return AgentResult(
            task_id=task.task_id,
            parent_task_id=task.parent_task_id,
            review_id=task.review_id,
            agent_name=task.agent_name,
            status="failed",
            commit_sha=plan.commit_sha,
            score=None,
            findings=[],
            summary=f"{task.agent_name} result was unavailable for aggregation.",
            execution_time=0.0,
            error=ErrorInfo(
                error_type="missing_agent_result",
                message=(
                    "manager aggregate did not receive a valid agent result"
                ),
                retryable=False,
                occurred_at=finished_at,
                details={"reason": reason},
            ),
            metadata={"synthesized": True, "reason": reason},
        )

    # ------------------------------------------------------------------
    # ArtifactData helpers

    @staticmethod
    def _agent_static_block(
        dimension: str,
        result: AgentResult,
        evidence: WorkerEvidence,
    ) -> dict[str, Any]:
        block = _thaw(evidence.static_analysis)
        if not isinstance(block, dict):
            block = {}
        tools = block.get("tools")
        if not isinstance(tools, dict):
            block["tools"] = {}
        block["agent_name"] = evidence.agent_name
        block["result_status"] = result.status
        block["warnings"] = list(evidence.warnings)
        return block

    @staticmethod
    def _build_test_report(
        evidence: WorkerEvidence,
        result: AgentResult,
    ) -> dict[str, Any]:
        if evidence.test_report is None:
            report = ManagerAgent._default_test_report(
                "testing result is unavailable"
            )
        else:
            report = _thaw(evidence.test_report)
            if not isinstance(report, dict):
                report = ManagerAgent._default_test_report(
                    "testing result is unavailable"
                )
            report.setdefault("execution_status", "not_executed")
        report.setdefault("warnings", list(evidence.warnings))
        report["agent_name"] = evidence.agent_name
        report["result_status"] = result.status
        return report

    @staticmethod
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
            "warnings": [],
        }

    # ------------------------------------------------------------------
    # Execution summary and root finalization

    @staticmethod
    def _execution_summary(
        agent_results: Mapping[str, AgentResult],
        timings: Sequence[WorkerTiming],
    ) -> ExecutionSummary:
        completed = sum(
            1
            for result in agent_results.values()
            if result.status == "completed"
        )
        partial = sum(
            1 for result in agent_results.values() if result.status == "partial"
        )
        failed = sum(
            1 for result in agent_results.values() if result.status == "failed"
        )
        if timings:
            started = min(timing.started_at for timing in timings)
            finished = max(timing.finished_at for timing in timings)
            duration = max(0.0, (finished - started).total_seconds())
        else:
            duration = 0.0
        return ExecutionSummary(
            total_tasks=len(DIMENSIONS),
            completed_tasks=completed,
            partial_tasks=partial,
            failed_tasks=failed,
            cancelled_tasks=0,
            duration_seconds=duration,
        )

    def _finalize_root(
        self,
        root_task: AgentTask,
        agent_results: Mapping[str, AgentResult],
        timings: Sequence[WorkerTiming],
    ) -> AgentTask:
        finished_at = self._clock()
        for timing in timings:
            finished_at = max(finished_at, timing.finished_at)
        finished_at = max(finished_at, root_task.created_at)

        all_failed = all(
            result.status == "failed" for result in agent_results.values()
        )
        payload = root_task.model_dump()
        payload["finished_at"] = finished_at
        if all_failed:
            payload["status"] = "failed"
            payload["last_error"] = ErrorInfo(
                error_type="aggregate_incomplete",
                message="all agent dimensions failed",
                retryable=False,
                occurred_at=finished_at,
                details={
                    "failed_dimensions": [
                        dimension
                        for dimension in DIMENSIONS
                        if agent_results[dimension].status == "failed"
                    ]
                },
            )
        else:
            payload["status"] = "completed"
            payload["last_error"] = None
        return AgentTask.model_validate(payload)
