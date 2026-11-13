"""Stage 2 依赖装配工厂。

本模块只负责把 Manager、四个专业 Agent、确定性工具、可选 LLM 客户端与
评分规则装配为 LangGraph 依赖，不执行审查、不读写报告、不创建 Checkpointer。

默认 ``llm_client=None``：Stage 2 默认使用 Fake/无 LLM 路径，真实 LLM 的
成本语义（O-1）尚未解决。测试或 Stage 2.6 E2E 可以通过参数注入受控 Fake
LLM；不得在这里读取 API Key 或联网。

Stage 2 自有 Fixture 的测试执行需要把批准名写入子任务 ``input_data``。
``ManagerAgent.plan()`` 不包含该字段，且 ``manager.py`` 不在 Stage 2.5 的
允许修改范围内，因此这里使用一个仅增加字段的 Manager 子类；父任务与任务
树结构保持不变，仍通过 ``isinstance(manager, ManagerAgent)`` 校验。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from code_review.agents.contracts import LLMClientProtocol
from code_review.agents.manager import ManagerAgent, TaskPlan
from code_review.agents.performance import PerformanceAgent
from code_review.agents.quality import QualityAgent
from code_review.agents.security import SecurityAgent
from code_review.agents.testing import TestingAgent
from code_review.graph.workflow import GraphDependencies
from code_review.schemas.task import utc_now
from code_review.tools.base import AnalysisTool
from code_review.tools.test_runner import TestRunner
from config.review_rules import ReviewRules, load_review_rules
from config.settings import Settings

__all__ = [
    "FixtureManagerAgent",
    "Stage2Dependencies",
    "Stage2FactoryContext",
    "build_stage2_dependencies",
]

_FIXTURE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_REQUIRED_TOOLS = ("ruff", "bandit", "radon")


@dataclass(frozen=True)
class Stage2FactoryContext:
    """ReviewService 传给工厂的受控构建上下文。"""

    settings: Settings
    tools: tuple[AnalysisTool, ...]
    test_runner: TestRunner
    trusted_fixture: str | None = None
    clock: Callable[[], datetime] = utc_now


@dataclass(frozen=True)
class Stage2Dependencies:
    """一次 Stage 2 审查所需的图依赖与规则。"""

    manager: ManagerAgent
    graph: GraphDependencies
    rules: ReviewRules


class FixtureManagerAgent(ManagerAgent):
    """仅在四个子任务的 ``input_data`` 中增加批准 Fixture 名。"""

    def __init__(
        self,
        *,
        trusted_fixture: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not _FIXTURE_NAME_RE.fullmatch(trusted_fixture):
            raise ValueError("trusted_fixture must be a safe fixture name")
        super().__init__(clock=clock)
        self._trusted_fixture = trusted_fixture

    def plan(
        self,
        *,
        review_id: str,
        commit_sha: str,
        language: str = "python",
        timeout_seconds: float | None = None,
    ) -> TaskPlan:
        plan = super().plan(
            review_id=review_id,
            commit_sha=commit_sha,
            language=language,
            timeout_seconds=timeout_seconds,
        )
        tasks = tuple(
            task.model_copy(
                update={
                    "input_data": {
                        **task.input_data,
                        "trusted_fixture": self._trusted_fixture,
                    }
                }
            )
            for task in plan.agent_tasks
        )
        return TaskPlan(
            root_task=plan.root_task,
            agent_tasks=tasks,
            review_id=plan.review_id,
            commit_sha=plan.commit_sha,
        )


def build_stage2_dependencies(
    context: Stage2FactoryContext,
    *,
    tools: Sequence[AnalysisTool] | None = None,
    test_runner: TestRunner | None = None,
    llm_client: LLMClientProtocol | None = None,
    rules: ReviewRules | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Stage2Dependencies:
    """装配 Stage 2 图依赖；不联网、不调用真实 LLM。"""

    if not isinstance(context, Stage2FactoryContext):
        raise TypeError("context must be a Stage2FactoryContext")

    resolved_clock = clock or context.clock
    resolved_tools = tuple(
        tools if tools is not None else context.tools
    )
    by_name: dict[str, AnalysisTool] = {}
    for tool in resolved_tools:
        name = getattr(tool, "tool_name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("analysis tools must expose a non-empty tool_name")
        if name in by_name:
            raise ValueError("analysis tool names must be unique")
        by_name[name] = tool
    missing = [name for name in _REQUIRED_TOOLS if name not in by_name]
    if missing:
        raise ValueError(
            "stage 2 requires ruff, bandit and radon analysis tools"
        )

    resolved_test_runner = (
        test_runner if test_runner is not None else context.test_runner
    )
    if resolved_test_runner is None:
        raise ValueError("stage 2 requires a test runner")

    if context.trusted_fixture is not None:
        manager: ManagerAgent = FixtureManagerAgent(
            trusted_fixture=context.trusted_fixture,
            clock=resolved_clock,
        )
    else:
        manager = ManagerAgent(clock=resolved_clock)

    security = SecurityAgent(
        settings=context.settings,
        llm_client=llm_client,
        bandit_tool=by_name["bandit"],  # type: ignore[arg-type]
        clock=resolved_clock,
    )
    quality = QualityAgent(
        settings=context.settings,
        llm_client=llm_client,
        ruff_tool=by_name["ruff"],  # type: ignore[arg-type]
        radon_tool=by_name["radon"],  # type: ignore[arg-type]
        clock=resolved_clock,
    )
    performance = PerformanceAgent(
        settings=context.settings,
        llm_client=llm_client,
        radon_tool=by_name["radon"],  # type: ignore[arg-type]
        clock=resolved_clock,
    )
    testing = TestingAgent(
        settings=context.settings,
        test_runner=resolved_test_runner,  # type: ignore[arg-type]
        clock=resolved_clock,
    )

    graph = GraphDependencies(
        manager=manager,
        security_agent=security,
        quality_agent=quality,
        performance_agent=performance,
        testing_agent=testing,
    )
    resolved_rules = (
        rules
        if rules is not None
        else load_review_rules(context.settings.review_rules_path)
    )
    return Stage2Dependencies(
        manager=manager,
        graph=graph,
        rules=resolved_rules,
    )
