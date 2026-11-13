"""Stage 2.2 QualityAgent 单元测试（Fake Ruff/Radon 与 Fake LLM）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from code_review.agents.quality import QualityAgent
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


def ruff_finding(
    *,
    rule_id: str = "E501",
    message: str = "line too long",
    line: int | None = 10,
) -> ToolFinding:
    return make_tool_finding(
        tool_name="ruff",
        rule_id=rule_id,
        message=message,
        line=line,
        severity=None,
        confidence=None,
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


def radon_mi(*, rank: str = "C", file_path: str = "pkg/app.py") -> ToolFinding:
    return make_tool_finding(
        tool_name="radon",
        rule_id="RADON_MI",
        message="maintainability index",
        file_path=file_path,
        line=None,
        severity=None,
        confidence=None,
        metadata={"rank": rank, "mi": 42.0},
    )


def tools(
    *,
    ruff_findings: tuple[ToolFinding, ...] = (),
    radon_findings: tuple[ToolFinding, ...] = (),
    ruff_status: str | ToolExecutionStatus = ToolExecutionStatus.SUCCESS,
    radon_status: str | ToolExecutionStatus = ToolExecutionStatus.SUCCESS,
) -> tuple[FakeAnalysisTool, FakeAnalysisTool]:
    return (
        FakeAnalysisTool(
            result=make_tool_result(
                tool_name="ruff",
                status=ruff_status,
                findings=ruff_findings,
                tool_version="0.17.4",
            ),
            tool_name="ruff",
        ),
        FakeAnalysisTool(
            result=make_tool_result(
                tool_name="radon",
                status=radon_status,
                findings=radon_findings,
                tool_version="6.0.1",
            ),
            tool_name="radon",
        ),
    )


def make_agent(
    ruff_tool: FakeAnalysisTool,
    radon_tool: FakeAnalysisTool,
    *,
    llm_client: FakeLLMClient | None = None,
) -> QualityAgent:
    return QualityAgent(
        settings=Settings(),
        ruff_tool=ruff_tool,
        radon_tool=radon_tool,
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
        "def f():\n    return 1\n", encoding="utf-8"
    )
    task = make_agent_task(
        agent_name="QualityAgent",
        task_type="quality_review",
        task_id="task-quality",
        input_data=dict(input_data or {}),
    )
    runtime = make_worker_runtime(
        tmp_path,
        allowed_files=("pkg/app.py",),
        review_id=task.review_id,
    )
    return make_dispatch(task=task, runtime=runtime)


def run(agent: QualityAgent, dispatch):
    return asyncio.run(agent.execute(dispatch))


def llm_payload(*proposals: dict[str, object]) -> str:
    return json.dumps(
        {
            "findings": list(proposals),
            "summary": "quality supplement",
            "warnings": [],
        }
    )


def proposal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "category": "code_smell",
        "severity": "low",
        "title": "Repeated branching",
        "description": "The same branch is duplicated in this function.",
        "file_path": "pkg/app.py",
        "start_line": 1,
        "end_line": 2,
        "evidence": "if value: return value",
        "tool_evidence": [],
        "recommendation": "Extract the shared branch.",
        "confidence": 0.5,
    }
    payload.update(overrides)
    return payload


class TestRuffMapping:
    @pytest.mark.parametrize(
        ("rule_id", "category", "severity"),
        [
            ("E501", "style", "low"),
            ("F401", "code_smell", "low"),
            ("E999", "style", "medium"),
            ("TRY003", "error_handling", "low"),
            ("C901", "high_complexity", "low"),
        ],
    )
    def test_ruff_rule_families(
        self,
        tmp_path: Path,
        rule_id: str,
        category: str,
        severity: str,
    ) -> None:
        ruff, radon = tools(ruff_findings=(ruff_finding(rule_id=rule_id),))
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        assert execution.result.status == "completed"
        assert len(execution.result.findings) == 1
        finding = execution.result.findings[0]
        assert finding.category == category
        assert finding.severity == severity
        assert finding.finding_id == "QUA-RUFF-0000"
        assert finding.tool_evidence[0].raw_output_ref == (
            "static_analysis.json#/agents/quality/tools/ruff/findings/0"
        )

    def test_ruff_security_rule_is_left_to_security_agent(
        self, tmp_path: Path
    ) -> None:
        ruff, radon = tools(ruff_findings=(ruff_finding(rule_id="S603"),))
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        assert execution.result.findings == []
        assert execution.evidence.static_analysis["tools"]["ruff"][
            "findings"
        ][0]["rule_id"] == "S603"
        assert any(
            "left to SecurityAgent" in warning
            for warning in execution.evidence.warnings
        )


class TestRadonMapping:
    @pytest.mark.parametrize(
        ("rank", "severity"),
        [("B", "info"), ("C", "low"), ("D", "medium"), ("E", "high")],
    )
    def test_complexity_rank_maps_from_rules(
        self, tmp_path: Path, rank: str, severity: str
    ) -> None:
        ruff, radon = tools(radon_findings=(radon_cc(rank=rank),))
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        finding = execution.result.findings[0]
        assert finding.category == "high_complexity"
        assert finding.severity == severity
        assert finding.file_path == "pkg/app.py"
        assert finding.start_line == 20
        assert finding.tool_evidence[0].tool_name == "radon"

    def test_rank_a_does_not_create_finding(self, tmp_path: Path) -> None:
        ruff, radon = tools(radon_findings=(radon_cc(rank="A"),))
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        assert execution.result.findings == []

    def test_maintainability_is_project_level_without_fake_location(
        self, tmp_path: Path
    ) -> None:
        ruff, radon = tools(
            radon_findings=(
                radon_mi(rank="B"),
                radon_mi(rank="C", file_path="pkg/other.py"),
            )
        )
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        finding = execution.result.findings[0]
        assert finding.category == "maintainability"
        assert finding.finding_id == "QUA-RADON-MI-0001"
        assert finding.file_path is None
        assert finding.start_line is None
        assert finding.end_line is None
        assert finding.severity == "low"
        assert len(finding.tool_evidence) == 2
        assert finding.tool_evidence[0].raw_output_ref.startswith(
            "static_analysis.json#/agents/quality/tools/radon/findings/"
        )

    def test_maintainability_rank_a_is_ignored(self, tmp_path: Path) -> None:
        ruff, radon = tools(radon_findings=(radon_mi(rank="A"),))
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        assert execution.result.findings == []


class TestToolCombination:
    def test_both_tools_feed_one_result(self, tmp_path: Path) -> None:
        ruff, radon = tools(
            ruff_findings=(ruff_finding(),),
            radon_findings=(radon_cc(rank="D"),),
        )
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        assert execution.result.status == "completed"
        assert len(execution.result.findings) == 2
        assert execution.evidence.static_analysis["tools"].keys() == {
            "ruff",
            "radon",
        }
        assert execution.evidence.usage.total_tokens == 0
        assert execution.result.metadata["dimension"] == "quality"

    def test_ruff_failure_preserves_radon_findings(
        self, tmp_path: Path
    ) -> None:
        ruff, radon = tools(
            radon_findings=(radon_cc(rank="D"),),
            ruff_status=ToolExecutionStatus.FAILED,
        )
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "tool_execution_error"
        assert len(execution.result.findings) == 1
        assert execution.result.findings[0].tool_evidence[0].tool_name == (
            "radon"
        )

    def test_both_tools_fail_without_llm_is_failed(
        self, tmp_path: Path
    ) -> None:
        ruff, radon = tools(
            ruff_status=ToolExecutionStatus.FAILED,
            radon_status=ToolExecutionStatus.TIMEOUT,
        )
        execution = run(
            make_agent(ruff, radon), make_dispatch_for(tmp_path)
        )
        assert execution.result.status == "failed"
        assert execution.result.error is not None
        assert execution.result.findings == []

    def test_both_tools_fail_with_llm_is_partial(
        self, tmp_path: Path
    ) -> None:
        ruff, radon = tools(
            ruff_status=ToolExecutionStatus.FAILED,
            radon_status=ToolExecutionStatus.FAILED,
        )
        client = FakeLLMClient(content=llm_payload(proposal()))
        execution = run(
            make_agent(ruff, radon, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "tool_execution_error"
        assert [item.finding_id for item in execution.result.findings] == [
            "QUA-LLM-0001"
        ]

    def test_tool_success_with_llm_failure_is_partial(
        self, tmp_path: Path
    ) -> None:
        ruff, radon = tools(ruff_findings=(ruff_finding(),))
        client = FakeLLMClient(error=RuntimeError("network disabled"))
        execution = run(
            make_agent(ruff, radon, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "llm_analysis_error"
        assert len(execution.result.findings) == 1


class TestLLMProposals:
    def test_valid_quality_supplement_is_accepted(
        self, tmp_path: Path
    ) -> None:
        ruff, radon = tools()
        client = FakeLLMClient(
            content=llm_payload(proposal(category="duplication"))
        )
        execution = run(
            make_agent(ruff, radon, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "completed"
        finding = execution.result.findings[0]
        assert finding.finding_id == "QUA-LLM-0001"
        assert finding.category == "duplication"
        assert finding.verification_status == "unverified"

    def test_cross_dimension_category_is_rejected(
        self, tmp_path: Path
    ) -> None:
        ruff, radon = tools()
        client = FakeLLMClient(
            content=llm_payload(proposal(category="sql_injection"))
        )
        execution = run(
            make_agent(ruff, radon, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []

    @pytest.mark.parametrize("severity", ["high", "critical"])
    def test_high_or_critical_is_rejected(
        self, tmp_path: Path, severity: str
    ) -> None:
        ruff, radon = tools()
        client = FakeLLMClient(
            content=llm_payload(proposal(severity=severity))
        )
        execution = run(
            make_agent(ruff, radon, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []
        assert any(
            "rejected" in warning for warning in execution.evidence.warnings
        )

    def test_prompt_excludes_input_data(self, tmp_path: Path) -> None:
        ruff, radon = tools()
        client = FakeLLMClient(content=llm_payload())
        dispatch = make_dispatch_for(
            tmp_path, input_data={"super_secret_token": "do-not-leak"}
        )
        run(make_agent(ruff, radon, llm_client=client), dispatch)
        prompt = client.calls[0]["user_prompt"]
        assert "do-not-leak" not in prompt
        assert "super_secret_token" not in prompt
        assert "ruff" in prompt
        assert "radon" in prompt

    def test_usage_is_reported_honestly(self, tmp_path: Path) -> None:
        ruff, radon = tools()
        client = FakeLLMClient(
            content=llm_payload(),
            usage={"prompt_tokens": 4, "completion_tokens": 1},
        )
        execution = run(
            make_agent(ruff, radon, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.evidence.usage.llm_calls == 1
        assert execution.evidence.usage.input_tokens == 4
        assert execution.evidence.usage.output_tokens == 1
        assert execution.evidence.usage.total_tokens == 5
