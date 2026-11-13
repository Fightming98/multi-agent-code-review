"""Stage 2.3 LangGraph 工作流：State、节点与图装配。

LangGraph 只在进程内编排；本阶段不创建 Checkpointer，不持久化、不重试，
也不实现真实 Final Reviewer（Stage 2.4）。
"""

from code_review.graph.nodes import (
    WORKER_NODE_NAMES,
    dispatch_workers,
    final_reviewer_node,
    make_worker_node,
    manager_aggregate_node,
    manager_plan_node,
    worker_state_update,
)
from code_review.graph.state import (
    PLACEHOLDER_REVIEW_STATUS,
    REVIEW_STATUS_RUNNING,
    RepositoryContext,
    ReviewState,
    ReviewStateError,
    build_initial_state,
)
from code_review.graph.workflow import (
    GRAPH_NODE_NAMES,
    GraphDependencies,
    build_review_graph,
    run_review_graph,
)

__all__ = [
    "GRAPH_NODE_NAMES",
    "PLACEHOLDER_REVIEW_STATUS",
    "REVIEW_STATUS_RUNNING",
    "WORKER_NODE_NAMES",
    "GraphDependencies",
    "RepositoryContext",
    "ReviewState",
    "ReviewStateError",
    "build_initial_state",
    "build_review_graph",
    "dispatch_workers",
    "final_reviewer_node",
    "make_worker_node",
    "manager_aggregate_node",
    "manager_plan_node",
    "run_review_graph",
    "worker_state_update",
]
