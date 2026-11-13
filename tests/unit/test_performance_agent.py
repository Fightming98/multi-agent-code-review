"""Stage 2.2 PerformanceAgent 单元测试（Fake Radon 与 Fake LLM）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from code_review.agents.performance import PerformanceAgent
from code_review.tools.base import ToolExecutionStatus, ToolFinding
from config.settings import Settings
from tests.stage2_helpers import (
    FakeAnalysisTool,
    FakeLLMClient,
    make_agent_task,
    make_dispatch,
    make_tool_finding,
    make_tool_result,
    make_worker_runtime,
)


def radon_cc(
    *,
    rank: str = "D",
    complexity: float = 12.0,
    line: int | None = 20,
) -> ToolFinding:
    return make_tool_finding(
        tool_name="radon",
        rule_id="RADON_CC",
        message="cyclomatic complexity",
        line=line,
        severity=None,
        confidence=None,
        metadata={"rank": rank, "complexity": complexity},
    )


def radon_mi() -> ToolFinding:
    return make_tool_finding(
        tool_name="radon",
        rule_id="RADON_MI",
        message="maintainability index",
        line=None,
        severity=None,
        confidence=None,
        metadata={"rank": "C", "mi": 42.0},
    )


def make_tool(
    findings: tuple[ToolFinding, ...] = (),
    *,
    status: str | ToolExecutionStatus = ToolExecutionStatus.SUCCESS,
    error: Exception | None = None,
) -> FakeAnalysisTool:
    return FakeAnalysisTool(
        tool_name="radon",
        error=error,
        result=make_tool_result(
            tool_name="radon",
            status=status,
            findings=findings,
            tool_version="6.0.1",
        ),
    )


def make_agent(
    tool: FakeAnalysisTool,
    *,
    llm_client: FakeLLMClient | None = None,
) -> PerformanceAgent:
    return PerformanceAgent(
        settings=Settings(),
        radon_tool=tool,
        llm_client=llm_client,
    )


def make_dispatch_for(
    tmp_path: Path,
    *,
    input_data: dict[str, object] | None = None,
):
    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "app.py").write_text(
        "def f(items):\n    return sum(items)\n", encoding="utf-8"
    )
    task = make_agent_task(
        agent_name="PerformanceAgent",
        task_type="performance_review",
        task_id="task-performance",
        input_data=dict(input_data or {}),
    )
    runtime = make_worker_runtime(
        tmp_path,
        allowed_files=("pkg/app.py",),
        review_id=task.review_id,
    )
    return make_dispatch(task=task, runtime=runtime)


def run(agent: PerformanceAgent, dispatch):
    return asyncio.run(agent.execute(dispatch))


def llm_payload(*proposals: dict[str, object]) -> str:
    return json.dumps(
        {
            "findings": list(proposals),
            "summary": "performance supplement",
            "warnings": [],
        }
    )


def proposal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "category": "algorithmic_complexity",
        "severity": "low",
        "title": "Suspected super-linear loop",
        "description": "The nested loop suggests a super-linear path.",
        "file_path": "pkg/app.py",
        "start_line": 1,
        "end_line": 2,
        "evidence": "for item in items: for other in items:",
        "tool_evidence": [],
        "recommendation": "Use a set or map for the inner lookup.",
        "confidence": 0.4,
    }
    payload.update(overrides)
    return payload


class TestDeterministicFindings:
    @pytest.mark.parametrize(
        ("rank", "severity"), [("B", "info"), ("D", "medium"), ("E", "high")]
    )
    def test_complexity_rank_uses_rules_mapping(
        self, tmp_path: Path, rank: str, severity: str
    ) -> None:
        execution = run(
            make_agent(make_tool((radon_cc(rank=rank),))),
            make_dispatch_for(tmp_path),
        )
        finding = execution.result.findings[0]
        assert finding.category == "high_complexity"
        assert finding.severity == severity
        assert "not a runtime benchmark" in finding.description
        assert finding.tool_evidence[0].raw_output_ref == (
            "static_analysis.json#/agents/performance/tools/radon/findings/0"
        )

    def test_rank_a_does_not_create_finding(self, tmp_path: Path) -> None:
        execution = run(
            make_agent(make_tool((radon_cc(rank="A"),))),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []

    def test_maintainability_index_is_outside_performance_scope(
        self, tmp_path: Path
    ) -> None:
        execution = run(
            make_agent(make_tool((radon_mi(),))),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []
        assert any(
            "outside the performance dimension" in warning
            for warning in execution.evidence.warnings
        )

    def test_metadata_declares_static_inference(self, tmp_path: Path) -> None:
        execution = run(
            make_agent(make_tool((radon_cc(),))),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.metadata["analysis_mode"] == (
            "static_inference"
        )
        assert execution.result.metadata["benchmark_executed"] is False

    def test_tool_exception_without_llm_is_failed(
        self, tmp_path: Path
    ) -> None:
        execution = run(
            make_agent(make_tool(error=RuntimeError("radon crashed"))),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "failed"
        assert execution.result.error is not None
        assert execution.result.findings == []
        assert execution.evidence.static_analysis["tools"]["radon"][
            "execution_status"
        ] == "failed"

    def test_partial_tool_status_is_partial(self, tmp_path: Path) -> None:
        execution = run(
            make_agent(
                make_tool(
                    (radon_cc(),), status=ToolExecutionStatus.PARTIAL
                )
            ),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "tool_degraded"
        assert len(execution.result.findings) == 1


class TestLLMProposals:
    def test_tool_success_plus_llm_failure_is_partial(
        self, tmp_path: Path
    ) -> None:
        client = FakeLLMClient(error=RuntimeError("network disabled"))
        execution = run(
            make_agent(make_tool((radon_cc(),)), llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "llm_analysis_error"
        assert len(execution.result.findings) == 1

    def test_tool_failure_plus_llm_success_is_partial(
        self, tmp_path: Path
    ) -> None:
        client = FakeLLMClient(content=llm_payload(proposal()))
        execution = run(
            make_agent(
                make_tool(error=RuntimeError("radon crashed")),
                llm_client=client,
            ),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "tool_execution_error"
        finding = execution.result.findings[0]
        assert finding.finding_id == "PERF-LLM-0001"
        assert finding.description.startswith("Static inference")

    def test_benchmark_claim_is_rejected(self, tmp_path: Path) -> None:
        client = FakeLLMClient(
            content=llm_payload(
                proposal(
                    title="Measured throughput improvement",
                    description="Benchmark measured 1200 ops/sec.",
                )
            )
        )
        execution = run(
            make_agent(make_tool(), llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []
        assert any(
            "benchmark-claim" in warning
            for warning in execution.evidence.warnings
        )

    @pytest.mark.parametrize(
        "category", ["sql_injection", "style", "test_failure", "duplication"]
    )
    def test_cross_dimension_category_is_rejected(
        self, tmp_path: Path, category: str
    ) -> None:
        client = FakeLLMClient(
            content=llm_payload(proposal(category=category))
        )
        execution = run(
            make_agent(make_tool(), llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []

    @pytest.mark.parametrize("severity", ["high", "critical"])
    def test_high_or_critical_is_rejected(
        self, tmp_path: Path, severity: str
    ) -> None:
        client = FakeLLMClient(
            content=llm_payload(proposal(severity=severity))
        )
        execution = run(
            make_agent(make_tool(), llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []

    def test_prompt_excludes_input_data(self, tmp_path: Path) -> None:
        client = FakeLLMClient(content=llm_payload())
        dispatch = make_dispatch_for(
            tmp_path, input_data={"super_secret_token": "do-not-leak"}
        )
        run(make_agent(make_tool(), llm_client=client), dispatch)
        prompt = client.calls[0]["user_prompt"]
        assert "do-not-leak" not in prompt
        assert "super_secret_token" not in prompt
        assert "radon" in prompt

    def test_usage_is_not_fabricated(self, tmp_path: Path) -> None:
        client = FakeLLMClient(content=llm_payload(), usage=None)
        execution = run(
            make_agent(make_tool(), llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.evidence.usage.llm_calls == 1
        assert execution.evidence.usage.reported_usage_calls == 0
        assert execution.evidence.usage.total_tokens == 0
