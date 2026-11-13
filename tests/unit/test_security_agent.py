"""Stage 2.2 SecurityAgent 单元测试（全部使用 Fake 工具与 Fake LLM）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from code_review.agents.base import AgentContractError
from code_review.agents.security import SecurityAgent
from code_review.tools.base import ToolExecutionStatus
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


def make_dispatch_for(
    tmp_path: Path,
    *,
    input_data: dict[str, object] | None = None,
    allowed_files: tuple[str, ...] = ("pkg/app.py",),
):
    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "app.py").write_text(
        "password = 'hunter2'\nprint('ok')\n", encoding="utf-8"
    )
    task = make_agent_task(
        agent_name="SecurityAgent",
        task_type="security_review",
        task_id="task-security",
        input_data=dict(input_data or {}),
    )
    runtime = make_worker_runtime(
        tmp_path,
        allowed_files=allowed_files,
        review_id=task.review_id,
    )
    return make_dispatch(task=task, runtime=runtime)


def make_agent(
    tool: FakeAnalysisTool,
    *,
    llm_client: FakeLLMClient | None = None,
) -> SecurityAgent:
    return SecurityAgent(
        settings=Settings(),
        bandit_tool=tool,
        llm_client=llm_client,
    )


def run(agent: SecurityAgent, dispatch):
    return asyncio.run(agent.execute(dispatch))


def llm_payload(*proposals: dict[str, object]) -> str:
    return json.dumps(
        {
            "findings": list(proposals),
            "summary": "security supplement",
            "warnings": [],
        }
    )


def proposal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "category": "hardcoded_secret",
        "severity": "medium",
        "title": "Credential in source",
        "description": "A password literal appears in the source file.",
        "file_path": "pkg/app.py",
        "start_line": 1,
        "end_line": 1,
        "evidence": "password = 'hunter2'",
        "tool_evidence": [],
        "recommendation": "Load the secret from the environment.",
        "confidence": 0.6,
    }
    payload.update(overrides)
    return payload


class TestToolOnly:
    def test_tool_findings_are_mapped_with_rules(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(
            result=make_tool_result(
                status=ToolExecutionStatus.FINDINGS,
                findings=(
                    make_tool_finding(
                        rule_id="B608", severity="MEDIUM", line=12
                    ),
                    make_tool_finding(
                        rule_id="B107",
                        severity="HIGH",
                        line=3,
                        message="hardcoded password",
                    ),
                ),
            )
        )
        execution = run(make_agent(tool), make_dispatch_for(tmp_path))
        result = execution.result
        assert result.status == "completed"
        assert result.score is None
        assert len(result.findings) == 2
        by_rule = {item.tool_evidence[0].rule_id: item for item in result.findings}
        assert by_rule["B608"].category == "sql_injection"
        assert by_rule["B608"].severity == "medium"
        assert by_rule["B107"].category == "hardcoded_secret"
        assert by_rule["B107"].severity == "high"
        assert all(
            item.verification_status == "unverified" for item in result.findings
        )
        assert by_rule["B608"].tool_evidence[0].raw_output_ref == (
            "static_analysis.json#/agents/security/tools/bandit/findings/0"
        )
        assert by_rule["B107"].tool_evidence[0].raw_output_ref == (
            "static_analysis.json#/agents/security/tools/bandit/findings/1"
        )

    def test_b107_and_b608_are_never_critical(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(
            result=make_tool_result(
                status=ToolExecutionStatus.FINDINGS,
                findings=(
                    make_tool_finding(rule_id="B107", severity="HIGH"),
                    make_tool_finding(rule_id="B608", severity="HIGH"),
                ),
            )
        )
        execution = run(make_agent(tool), make_dispatch_for(tmp_path))
        assert all(
            item.severity != "critical"
            for item in execution.result.findings
        )

    def test_success_without_findings_is_completed(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(
            result=make_tool_result(status=ToolExecutionStatus.SUCCESS)
        )
        execution = run(make_agent(tool), make_dispatch_for(tmp_path))
        assert execution.result.status == "completed"
        assert execution.result.findings == []
        assert execution.evidence.static_analysis["tools"]["bandit"][
            "execution_status"
        ] == "success"

    def test_unmapped_rule_is_skipped_but_preserved_in_evidence(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(
            result=make_tool_result(
                status=ToolExecutionStatus.FINDINGS,
                findings=(make_tool_finding(rule_id="B999"),),
            )
        )
        execution = run(make_agent(tool), make_dispatch_for(tmp_path))
        assert execution.result.status == "completed"
        assert execution.result.findings == []
        assert any(
            "not representable" in warning
            for warning in execution.evidence.warnings
        )
        raw = execution.evidence.static_analysis["tools"]["bandit"]
        assert raw["findings"][0]["rule_id"] == "B999"

    def test_unknown_raw_severity_is_skipped(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(
            result=make_tool_result(
                status=ToolExecutionStatus.FINDINGS,
                findings=(make_tool_finding(severity="UNKNOWN"),),
            )
        )
        execution = run(make_agent(tool), make_dispatch_for(tmp_path))
        assert execution.result.findings == []
        assert any(
            "not representable" in warning
            for warning in execution.evidence.warnings
        )

    def test_tool_exception_without_llm_is_failed(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(error=RuntimeError("bandit crashed"))
        execution = run(make_agent(tool), make_dispatch_for(tmp_path))
        result = execution.result
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.error_type == "tool_execution_error"
        assert result.findings == []
        assert result.score is None
        assert execution.evidence.static_analysis["tools"]["bandit"][
            "execution_status"
        ] == "failed"

    def test_tool_partial_status_is_partial(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(
            result=make_tool_result(
                status=ToolExecutionStatus.PARTIAL,
                findings=(make_tool_finding(),),
            )
        )
        execution = run(make_agent(tool), make_dispatch_for(tmp_path))
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "tool_degraded"
        assert len(execution.result.findings) == 1

    def test_empty_allowed_files_are_passed_to_tool(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        run(make_agent(tool), make_dispatch_for(tmp_path, allowed_files=()))
        assert tool.calls[0]["files"] == ()


class TestLLMFailure:
    def test_tool_success_plus_llm_error_is_partial(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(
            result=make_tool_result(
                status=ToolExecutionStatus.FINDINGS,
                findings=(make_tool_finding(),),
            )
        )
        client = FakeLLMClient(error=RuntimeError("network disabled"))
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        result = execution.result
        assert result.status == "partial"
        assert result.error is not None
        assert result.error.error_type == "llm_analysis_error"
        assert len(result.findings) == 1
        assert execution.evidence.usage.llm_calls == 1
        assert execution.evidence.usage.reported_usage_calls == 0
        assert result.metadata["llm_succeeded"] is False
        assert any(
            "llm semantic supplement failed" in warning
            and "RuntimeError" in warning
            for warning in execution.evidence.warnings
        )

    def test_invalid_llm_structure_is_partial(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(
            result=make_tool_result(
                findings=(make_tool_finding(),),
                status=ToolExecutionStatus.FINDINGS,
            )
        )
        client = FakeLLMClient(
            content='{"findings": [], "summary": ""}'
        )
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "partial"
        assert execution.result.error is not None
        assert execution.result.error.error_type == "llm_analysis_error"
        assert len(execution.result.findings) == 1

    def test_tool_failure_plus_llm_success_is_partial(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(error=RuntimeError("bandit crashed"))
        client = FakeLLMClient(
            content=llm_payload(proposal()),
            usage={"prompt_tokens": 10, "completion_tokens": 2},
        )
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        result = execution.result
        assert result.status == "partial"
        assert result.error is not None
        assert result.error.error_type == "tool_execution_error"
        assert [item.finding_id for item in result.findings] == ["SEC-LLM-0001"]
        assert result.findings[0].tool_evidence == []
        assert execution.evidence.usage.total_tokens == 12
        assert result.metadata["tool_status"]["bandit"] == "failed"


class TestLLMProposals:
    def test_valid_supplement_is_accepted(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        client = FakeLLMClient(content=llm_payload(proposal()))
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "completed"
        assert len(execution.result.findings) == 1
        finding = execution.result.findings[0]
        assert finding.finding_id == "SEC-LLM-0001"
        assert finding.verification_status == "unverified"
        assert finding.file_path == "pkg/app.py"

    @pytest.mark.parametrize("severity", ["high", "critical"])
    def test_llm_high_or_critical_is_rejected(
        self, tmp_path: Path, severity: str
    ) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        client = FakeLLMClient(
            content=llm_payload(proposal(severity=severity))
        )
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.status == "completed"
        assert execution.result.findings == []
        assert any(
            "rejected" in warning for warning in execution.evidence.warnings
        )

    def test_category_outside_whitelist_is_rejected(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        client = FakeLLMClient(
            content=llm_payload(proposal(category="style"))
        )
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []

    def test_location_outside_allowed_files_is_rejected(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        client = FakeLLMClient(
            content=llm_payload(proposal(file_path="pkg/other.py"))
        )
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []

    def test_proposal_without_location_is_rejected(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        client = FakeLLMClient(
            content=llm_payload(
                proposal(file_path=None, start_line=None, end_line=None)
            )
        )
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.result.findings == []

    def test_prompt_excludes_input_data_and_secrets(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        client = FakeLLMClient(content=llm_payload())
        dispatch = make_dispatch_for(
            tmp_path,
            input_data={"super_secret_token": "do-not-leak"},
        )
        run(make_agent(tool, llm_client=client), dispatch)
        user_prompt = client.calls[0]["user_prompt"]
        assert "do-not-leak" not in user_prompt
        assert "super_secret_token" not in user_prompt
        assert '"input_data"' not in user_prompt
        assert "bandit" in user_prompt
        assert "hunter2" not in user_prompt

    def test_llm_usage_without_reported_tokens_is_not_fabricated(
        self, tmp_path: Path
    ) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        client = FakeLLMClient(content=llm_payload(), usage=None)
        execution = run(
            make_agent(tool, llm_client=client),
            make_dispatch_for(tmp_path),
        )
        assert execution.evidence.usage.llm_calls == 1
        assert execution.evidence.usage.reported_usage_calls == 0
        assert execution.evidence.usage.total_tokens == 0


class TestPromptBudget:
    def test_budget_omissions_are_reported(self, tmp_path: Path) -> None:
        package = tmp_path / "pkg"
        package.mkdir()
        names = tuple(f"pkg/file{index}.py" for index in range(8))
        for name in names:
            (tmp_path / name).write_text("x" * 6000, encoding="utf-8")
        task = make_agent_task(
            agent_name="SecurityAgent",
            task_type="security_review",
            task_id="task-security",
        )
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=names,
            review_id=task.review_id,
        )
        tool = FakeAnalysisTool(result=make_tool_result())
        client = FakeLLMClient(content=llm_payload())
        agent = SecurityAgent(
            settings=Settings(llm_max_input_chars=20_000),
            bandit_tool=tool,
            llm_client=client,
        )
        execution = run(
            agent,
            make_dispatch(task=task, runtime=runtime),
        )

        assert execution.result.status == "completed"
        assert len(client.calls) == 1
        assert any(
            "prompt budget" in warning
            for warning in execution.evidence.warnings
        )


class TestContractBoundary:
    def test_wrong_dispatch_agent_is_rejected(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        task = make_agent_task(
            agent_name="QualityAgent",
            task_type="quality_review",
            task_id="task-quality",
        )
        runtime = make_worker_runtime(tmp_path, review_id=task.review_id)
        with pytest.raises(AgentContractError):
            run(
                make_agent(tool),
                make_dispatch(task=task, runtime=runtime),
            )
        assert tool.calls == []

    def test_result_identity_matches_task(self, tmp_path: Path) -> None:
        tool = FakeAnalysisTool(result=make_tool_result())
        dispatch = make_dispatch_for(tmp_path)
        execution = run(make_agent(tool), dispatch)
        assert execution.result.task_id == dispatch.task.task_id
        assert execution.result.agent_name == "SecurityAgent"
        assert execution.result.review_id == dispatch.task.review_id
        assert execution.result.commit_sha == dispatch.runtime.commit_sha
