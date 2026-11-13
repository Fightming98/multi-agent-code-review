"""Stage 2.3 LangGraph ``ReviewState`` 与初始状态构造。

字段、初始值、写入节点与 Reducer 严格遵循
``阶段2实施前架构审计与实施计划.md`` §5.1：

- 四个 Worker 只写自己的 ``{dimension}_task`` / ``{dimension}_result`` /
  ``{dimension}_evidence``，外加 ``completed_tasks`` / ``failed_tasks`` /
  ``worker_timings`` / ``warnings`` 四个 Reducer 列表；
- ``agent_results``、``artifact_data``、``usage_summary``、
  ``execution_summary`` 只由 Manager Aggregate 单写者构建；
- ``review_report`` 只预留，Stage 2.3 的 Final Reviewer 仍是占位节点。
"""

from __future__ import annotations

import operator
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypedDict

from code_review.agents.contracts import (
    ArtifactData,
    UsageSummary,
    WorkerEvidence,
    WorkerRuntime,
    WorkerTiming,
)
from code_review.agents.manager import TaskPlan
from code_review.reporting.report_generator import InventorySummary
from code_review.schemas.report import ExecutionSummary, ReviewReport
from code_review.schemas.result import AgentResult
from code_review.schemas.task import AgentTask
from config.review_rules import ReviewRules

__all__ = [
    "PLACEHOLDER_REVIEW_STATUS",
    "REVIEW_STATUS_RUNNING",
    "RepositoryContext",
    "ReviewState",
    "ReviewStateError",
    "build_initial_state",
]

REVIEW_STATUS_RUNNING = "running"
# Stage 2.3 的 Final Reviewer 只是占位节点，不得宣称审核完成。
PLACEHOLDER_REVIEW_STATUS = "pending_final_review"

_SOURCE_TYPES = frozenset({"github_repository", "trusted_fixture"})


class ReviewStateError(ValueError):
    """Graph 初始状态或节点输入不符合 Stage 2.3 合同。"""


@dataclass(frozen=True)
class RepositoryContext:
    """ReviewService 构造的只读仓库身份上下文。

    审计计划 §5.1 把 ``repository`` 的类型记为 ``RepositoryContext``；
    Stage 2.3 在 graph 包中落地该只读 DTO，Stage 2.5 由 ReviewService
    用真实仓库快照填充。``language`` 是 v1 唯一支持的 Python。
    """

    repository_url: str
    repository_name: str
    branch: str
    language: str = "python"
    source_type: str = "github_repository"

    def __post_init__(self) -> None:
        for name in (
            "repository_url",
            "repository_name",
            "branch",
            "language",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ReviewStateError(
                    f"RepositoryContext.{name} must be a non-empty string"
                )
        if self.source_type not in _SOURCE_TYPES:
            raise ReviewStateError(
                "RepositoryContext.source_type must be one of "
                f"{sorted(_SOURCE_TYPES)}"
            )

    @property
    def trusted_fixture(self) -> bool:
        return self.source_type == "trusted_fixture"


class ReviewState(TypedDict, total=False):
    """LangGraph 的共享状态；并发安全由字段级 Reducer 保证。

    ``total=False`` 与审计计划一致：初始状态显式提供所有字段，节点只返回
    自己负责的键。普通字段是 LastValue Channel，Reducer 字段在并行
    superstep 中通过 ``operator.add`` 合并。
    """

    # ---- 只读上下文（ReviewService 构造，任何节点不得改写）----
    review_id: str
    trace_id: str | None
    commit_sha: str
    repository: RepositoryContext
    workspace_path: str
    allowed_files: tuple[str, ...]
    inventory: InventorySummary | None
    rules: ReviewRules

    # ---- Manager Planning ----
    task_plan: TaskPlan | None
    root_task: AgentTask | None
    agent_tasks: list[AgentTask]

    # ---- 四个 Worker 的独立键（每个 Worker 只写自己的一组）----
    security_task: AgentTask | None
    quality_task: AgentTask | None
    performance_task: AgentTask | None
    testing_task: AgentTask | None
    security_result: AgentResult | None
    quality_result: AgentResult | None
    performance_result: AgentResult | None
    testing_result: AgentResult | None
    security_evidence: WorkerEvidence | None
    quality_evidence: WorkerEvidence | None
    performance_evidence: WorkerEvidence | None
    testing_evidence: WorkerEvidence | None

    # ---- Reducer 列表：四个 Worker 与 Manager Aggregate 追加 ----
    completed_tasks: Annotated[list[str], operator.add]
    failed_tasks: Annotated[list[str], operator.add]
    worker_timings: Annotated[list[WorkerTiming], operator.add]
    warnings: Annotated[list[str], operator.add]

    # ---- Manager Aggregate 单写者 ----
    agent_results: dict[str, AgentResult]
    artifact_data: ArtifactData | None
    usage_summary: UsageSummary | None
    execution_summary: ExecutionSummary | None

    # ---- Final Reviewer（Stage 2.3 仅占位）----
    review_report: ReviewReport | None
    review_statistics: dict[str, Any]
    review_status: str


def build_initial_state(
    *,
    review_id: str,
    commit_sha: str,
    repository: RepositoryContext,
    workspace_path: str | Path,
    allowed_files: Sequence[str],
    inventory: InventorySummary | None,
    rules: ReviewRules,
    trace_id: str | None = None,
) -> ReviewState:
    """构造审计计划 §5.1 规定的初始状态并做合同校验。

    初始状态中的 ``task_plan`` / ``*_task`` / ``*_result`` / ``*_evidence``
    / ``artifact_data`` / ``usage_summary`` / ``execution_summary`` /
    ``review_report`` 均为 ``None``；四个 Reducer 列表为空。
    路径与 SHA 校验复用 ``WorkerRuntime``，避免出现第二套规则。
    """

    if not isinstance(review_id, str) or not review_id.strip():
        raise ReviewStateError("review_id must be a non-empty string")
    if not isinstance(repository, RepositoryContext):
        raise ReviewStateError("repository must be a RepositoryContext")
    if inventory is not None and not isinstance(inventory, InventorySummary):
        raise ReviewStateError("inventory must be InventorySummary or None")
    if not isinstance(rules, ReviewRules):
        raise ReviewStateError("rules must be a ReviewRules instance")
    if isinstance(allowed_files, (str, bytes)):
        raise ReviewStateError("allowed_files must be a sequence of paths")

    resolved_workspace = Path(workspace_path)
    if not resolved_workspace.is_absolute():
        raise ReviewStateError("workspace_path must be an absolute path")

    validated_runtime = WorkerRuntime(
        workspace_path=resolved_workspace,
        allowed_files=tuple(allowed_files),
        commit_sha=commit_sha,
        language=repository.language,
        review_id=review_id,
        rules=rules,
        trace_id=trace_id,
    )

    return ReviewState(
        review_id=review_id,
        trace_id=trace_id,
        commit_sha=validated_runtime.commit_sha,
        repository=repository,
        workspace_path=str(resolved_workspace),
        allowed_files=validated_runtime.allowed_files,
        inventory=inventory,
        rules=rules,
        task_plan=None,
        root_task=None,
        agent_tasks=[],
        security_task=None,
        quality_task=None,
        performance_task=None,
        testing_task=None,
        security_result=None,
        quality_result=None,
        performance_result=None,
        testing_result=None,
        security_evidence=None,
        quality_evidence=None,
        performance_evidence=None,
        testing_evidence=None,
        completed_tasks=[],
        failed_tasks=[],
        worker_timings=[],
        warnings=[],
        agent_results={},
        artifact_data=None,
        usage_summary=None,
        execution_summary=None,
        review_report=None,
        review_statistics={},
        review_status=REVIEW_STATUS_RUNNING,
    )
