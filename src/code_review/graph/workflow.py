"""Stage 2.3 LangGraph 工作流装配。

拓扑（审计计划 §5.2，不得更改）：

```text
START → manager_plan
manager_plan → Send(security_worker / quality_worker /
                    performance_worker / testing_worker)
四个 Worker → manager_aggregate（四路 fan-in）
manager_aggregate → final_reviewer
final_reviewer → END
```

本模块不创建 Checkpointer、不做重试、不引入 Redis/ARQ/持久化；图仅在
进程内执行。Stage 2.3 的 ``final_reviewer`` 是占位节点，Stage 2.4 再替换。
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial
from types import MappingProxyType

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from code_review.agents.base import BaseAgent
from code_review.agents.manager import AGENT_SPECS, DIMENSIONS, ManagerAgent
from code_review.graph.nodes import (
    WORKER_NODE_NAMES,
    dispatch_workers,
    final_reviewer_node,
    make_worker_node,
    manager_aggregate_node,
    manager_plan_node,
)
from code_review.graph.state import ReviewState

__all__ = [
    "GRAPH_NODE_NAMES",
    "GraphDependencies",
    "build_review_graph",
    "run_review_graph",
]

GRAPH_NODE_NAMES: tuple[str, ...] = (
    "manager_plan",
    *(WORKER_NODE_NAMES[dimension] for dimension in DIMENSIONS),
    "manager_aggregate",
    "final_reviewer",
)


@dataclass(frozen=True)
class GraphDependencies:
    """图的四个 Worker Agent 与 Manager；Stage 2.5 由工厂注入。"""

    manager: ManagerAgent
    security_agent: BaseAgent
    quality_agent: BaseAgent
    performance_agent: BaseAgent
    testing_agent: BaseAgent
    _by_dimension: Mapping[str, BaseAgent] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.manager, ManagerAgent):
            raise TypeError("GraphDependencies.manager must be a ManagerAgent")

        mapping: dict[str, BaseAgent] = {}
        for dimension, agent_name, task_type, _ in AGENT_SPECS:
            agent = getattr(self, f"{dimension}_agent")
            if not isinstance(agent, BaseAgent):
                raise TypeError(
                    f"GraphDependencies.{dimension}_agent must be a BaseAgent"
                )
            if agent.agent_name != agent_name:
                raise ValueError(
                    f"{dimension}_agent must be {agent_name}, "
                    f"got {agent.agent_name}"
                )
            if agent.task_type != task_type:
                raise ValueError(
                    f"{dimension}_agent task_type must be {task_type}, "
                    f"got {agent.task_type}"
                )
            mapping[dimension] = agent
        object.__setattr__(
            self, "_by_dimension", MappingProxyType(mapping)
        )

    def agent_for(self, dimension: str) -> BaseAgent:
        try:
            return self._by_dimension[dimension]
        except KeyError as exc:
            raise ValueError(f"unknown dimension: {dimension}") from exc


def build_review_graph(
    dependencies: GraphDependencies,
) -> CompiledStateGraph:
    """编译进程内 StateGraph；不附加 Checkpointer。"""

    if not isinstance(dependencies, GraphDependencies):
        raise TypeError("dependencies must be a GraphDependencies")

    graph: StateGraph = StateGraph(ReviewState)
    graph.add_node(
        "manager_plan",
        partial(manager_plan_node, manager=dependencies.manager),
    )
    for dimension in DIMENSIONS:
        graph.add_node(
            WORKER_NODE_NAMES[dimension],
            make_worker_node(
                dimension=dimension,
                agent=dependencies.agent_for(dimension),
            ),
        )
    graph.add_node(
        "manager_aggregate",
        partial(manager_aggregate_node, manager=dependencies.manager),
    )
    graph.add_node("final_reviewer", final_reviewer_node)

    graph.add_edge(START, "manager_plan")
    graph.add_conditional_edges(
        "manager_plan",
        dispatch_workers,
        [WORKER_NODE_NAMES[dimension] for dimension in DIMENSIONS],
    )
    for dimension in DIMENSIONS:
        graph.add_edge(WORKER_NODE_NAMES[dimension], "manager_aggregate")
    graph.add_edge("manager_aggregate", "final_reviewer")
    graph.add_edge("final_reviewer", END)

    return graph.compile()


def run_review_graph(
    dependencies: GraphDependencies,
    initial_state: ReviewState,
) -> ReviewState:
    """同步入口：在独立事件循环中执行图；禁止在运行中的 loop 内调用。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "run_review_graph must not be called inside a running event "
            "loop; await build_review_graph(...).ainvoke(...) instead"
        )
    graph = build_review_graph(dependencies)
    return asyncio.run(graph.ainvoke(initial_state))
