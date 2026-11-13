"""Stage 2.3 集成测试：LangGraph 四 Worker 并行评审流水线。

本测试使用真实 ``ManagerAgent`` 与 Fake 专业 Agent 走完 LangGraph 图：

```text
START → manager_plan → Send × 4 → manager_aggregate → final_reviewer → END
```

不联网、不调用真实 LLM、不执行被评审仓库代码、不写工作区。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from code_review.agents.contracts import ArtifactData, UsageSummary
from code_review.agents.manager import DIMENSIONS
from code_review.graph import (
    build_review_graph,
    run_review_graph,
)
from code_review.schemas.result import AgentResult
from code_review.schemas.task import AgentTask
from tests.stage2_helpers import (
    REVIEW_ID,
    make_dimension_factory,
    make_finding,
    make_graph_dependencies,
    make_review_state,
    make_test_report_block,
    make_tool_evidence,
)

APP_SOURCE = '''"""Sample module used only by the Stage 2.3 integration test."""

import os


def build_query(user_input):
    return "SELECT * FROM users WHERE name = '" + user_input + "'"


def run(user_input):
    os.system("echo " + user_input)
'''

ENV_SECRET = "integration-secret-value"


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "sample_repo"
    package = workspace / "pkg"
    package.mkdir(parents=True)
    (package / "app.py").write_text(APP_SOURCE, encoding="utf-8")
    (workspace / ".env").write_text(
        f"API_KEY={ENV_SECRET}\n",
        encoding="utf-8",
    )
    return workspace


def snapshot(workspace: Path) -> list[str]:
    return sorted(
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
    )


def run_pipeline(workspace: Path, **overrides: Any) -> dict:
    graph = build_review_graph(make_graph_dependencies(**overrides))
    return asyncio.run(graph.ainvoke(make_review_state(workspace.resolve())))


def test_full_pipeline_fans_out_and_fans_in(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    before = snapshot(workspace)

    output = run_pipeline(workspace)

    assert output["review_id"] == REVIEW_ID
    assert output["review_status"] == "completed"
    report = output["review_report"]
    assert report is not None
    assert report.report_status == "completed"
    assert report.overall_verdict == "APPROVE"
    assert report.overall_score == 100.0
    assert report.findings == []
    assert report.rejected_findings == []
    assert set(report.agent_results) == set(DIMENSIONS)
    assert output["review_statistics"]["implemented"] is True
    assert output["review_statistics"]["agent_task_count"] == 4
    assert output["review_statistics"]["aggregated_dimensions"] == sorted(
        DIMENSIONS
    )
    assert output["review_statistics"]["artifact_data_available"] is True

    results = output["agent_results"]
    assert set(results) == set(DIMENSIONS)
    for dimension in DIMENSIONS:
        result = results[dimension]
        assert isinstance(result, AgentResult)
        assert result.status == "completed"
        assert result.commit_sha == output["commit_sha"]
        assert result.review_id == REVIEW_ID
        assert all(
            finding.verification_status == "unverified"
            for finding in result.findings
        )
        task = output[f"{dimension}_task"]
        assert isinstance(task, AgentTask)
        assert task.status == "completed"
        assert task.max_retries == 0
        assert output[f"{dimension}_result"].task_id == task.task_id
        assert output[f"{dimension}_evidence"].agent_name == task.agent_name

    artifact_data = output["artifact_data"]
    assert isinstance(artifact_data, ArtifactData)
    for dimension in DIMENSIONS:
        assert artifact_data.resolve(
            f"static_analysis.json#/agents/{dimension}/agent_name"
        ) == output[f"{dimension}_result"].agent_name
        assert artifact_data.resolve(
            f"static_analysis.json#/agents/{dimension}/result_status"
        ) == "completed"
    assert artifact_data.resolve(
        "static_analysis.json#/agents/security/tools/bandit/findings/0"
    )["rule_id"] == "B608"
    assert artifact_data.resolve(
        "test_report.json#/execution_status"
    ) == "executed"
    assert artifact_data.resolve("test_report.json#/coverage") == 91.0
    assert artifact_data.resolve("test_report.json#/counts/total") == 3

    usage = output["usage_summary"]
    assert isinstance(usage, UsageSummary)
    assert usage.llm_calls == 0
    assert usage.reported_usage_calls == 0
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0

    summary = output["execution_summary"]
    assert summary.total_tasks == 4
    assert summary.completed_tasks == 4
    assert summary.partial_tasks == 0
    assert summary.failed_tasks == 0
    assert summary.cancelled_tasks == 0

    assert output["root_task"].status == "completed"
    assert output["root_task"].last_error is None
    assert len(output["completed_tasks"]) == 4
    assert output["failed_tasks"] == []
    assert output["warnings"] == []
    assert len(output["worker_timings"]) == 4
    assert {timing.task_id for timing in output["worker_timings"]} == {
        output[f"{dimension}_task"].task_id for dimension in DIMENSIONS
    }

    # 只读边界：工作区内容与文件清单均未变化，不产生缓存或字节码。
    assert snapshot(workspace) == before
    assert not any(workspace.rglob("__pycache__"))
    assert not any(workspace.rglob("*.pyc"))


def test_partial_agent_keeps_tool_evidence(tmp_path: Path) -> None:
    quality_finding = make_finding(
        finding_id="QUA-0001",
        agent_name="QualityAgent",
        category="high_complexity",
        severity="medium",
        title="Function complexity is too high",
        description="Radon reports a complex function.",
        evidence="def build_query(user_input):",
        tool_evidence=[
            make_tool_evidence(
                tool_name="radon",
                rule_id="RADON_CC",
                raw_output_ref=(
                    "static_analysis.json#/agents/quality/tools/radon/"
                    "findings/0"
                ),
            )
        ],
    )
    workspace = make_workspace(tmp_path)

    output = run_pipeline(
        workspace,
        factories={
            "quality": make_dimension_factory(
                "quality",
                status="partial",
                findings=[quality_finding],
            )
        },
    )

    result = output["agent_results"]["quality"]
    assert result.status == "partial"
    assert result.error is not None
    assert result.error.retryable is False
    assert result.findings[0].finding_id == "QUA-0001"
    assert result.findings[0].verification_status == "unverified"

    # D-11：LLM/单一阶段失败保留工具证据，其余维度不受影响。
    artifact_data = output["artifact_data"]
    assert artifact_data.resolve(
        "static_analysis.json#/agents/quality/result_status"
    ) == "partial"
    assert artifact_data.resolve(
        "static_analysis.json#/agents/quality/tools/radon/findings/0"
    )["rule_id"] == "RADON_CC"
    assert output["agent_results"]["security"].status == "completed"
    assert output["agent_results"]["performance"].status == "completed"
    assert output["agent_results"]["testing"].status == "completed"

    summary = output["execution_summary"]
    assert summary.completed_tasks == 3
    assert summary.partial_tasks == 1
    assert summary.failed_tasks == 0
    assert output["quality_task"].status == "completed"
    assert output["quality_task"].task_id in output["completed_tasks"]
    assert output["failed_tasks"] == []

    # 终审保留 partial 状态；合成 Finding 的位置非法，因此被拒绝而非计分。
    report = output["review_report"]
    assert report is not None
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    assert report.dimension_scores["quality"].status == "partial"
    assert report.dimension_scores["quality"].score == 100.0
    assert [item.finding_id for item in report.rejected_findings] == [
        "QUA-0001"
    ]
    assert output["review_status"] == "completed"


def test_external_testing_not_executed_is_completed(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    report = make_test_report_block(
        execution_status="not_executed",
        reason="external repository tests are not executed",
    )

    output = run_pipeline(
        workspace,
        factories={
            "testing": make_dimension_factory(
                "testing",
                test_report=report,
            )
        },
    )

    result = output["agent_results"]["testing"]
    assert result.status == "completed"
    assert result.error is None
    assert output["testing_task"].status == "completed"

    artifact_data = output["artifact_data"]
    assert artifact_data.resolve(
        "test_report.json#/execution_status"
    ) == "not_executed"
    assert artifact_data.resolve(
        "test_report.json#/reason"
    ) == "external repository tests are not executed"
    assert artifact_data.resolve("test_report.json#/coverage") is None
    assert artifact_data.resolve("test_report.json#/counts/passed") is None
    assert artifact_data.resolve(
        "test_report.json#/result_status"
    ) == "completed"

    # D-12：外部仓库未执行测试不构成 Agent 失败；测试维度无法评分，报告为 partial。
    assert output["execution_summary"].completed_tasks == 4
    assert output["execution_summary"].failed_tasks == 0
    report = output["review_report"]
    assert report is not None
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    assert report.dimension_scores["testing"].score is None
    assert report.dimension_scores["testing"].reason
    assert report.test_summary.execution_status == "not_executed"
    assert report.test_summary.reason == (
        "external repository tests are not executed"
    )
    assert output["review_status"] == "completed"


def test_single_worker_failure_keeps_other_results(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    before = snapshot(workspace)
    error = RuntimeError(f"radon crashed at {workspace.resolve()}")

    output = run_pipeline(workspace, errors={"performance": error})

    results = output["agent_results"]
    assert results["performance"].status == "failed"
    assert results["performance"].error is not None
    assert results["performance"].error.retryable is False
    assert str(workspace.resolve()) not in results["performance"].error.message
    assert "<workspace>" in results["performance"].error.message
    assert results["security"].status == "completed"
    assert results["quality"].status == "completed"
    assert results["testing"].status == "completed"

    summary = output["execution_summary"]
    assert summary.completed_tasks == 3
    assert summary.failed_tasks == 1
    assert len(output["failed_tasks"]) == 1
    assert output["failed_tasks"][0] == output["performance_task"].task_id
    assert output["performance_task"].status == "failed"
    assert output["performance_task"].last_error is not None

    artifact_data = output["artifact_data"]
    assert artifact_data.resolve(
        "static_analysis.json#/agents/performance/result_status"
    ) == "failed"
    assert artifact_data.resolve(
        "static_analysis.json#/agents/security/result_status"
    ) == "completed"
    report = output["review_report"]
    assert report is not None
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    assert report.dimension_scores["performance"].score is None
    assert report.dimension_scores["performance"].status == "failed"
    assert output["review_status"] == "completed"
    assert snapshot(workspace) == before


def test_consecutive_runs_do_not_share_state(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    graph = build_review_graph(make_graph_dependencies())
    state = make_review_state(workspace.resolve())

    first = asyncio.run(graph.ainvoke(state))
    second = asyncio.run(graph.ainvoke(state))

    # 未安装 Checkpointer：两次执行互不共享任务、结果与数组型状态。
    assert graph.checkpointer is None
    assert first["root_task"].task_id != second["root_task"].task_id
    for dimension in DIMENSIONS:
        assert (
            first[f"{dimension}_task"].task_id
            != second[f"{dimension}_task"].task_id
        )
    assert len(second["completed_tasks"]) == 4
    assert second["failed_tasks"] == []
    assert second["review_status"] == "completed"
    assert second["review_report"] is not None
    assert second["review_report"].overall_verdict == "APPROVE"


def test_sync_entrypoint_runs_the_same_graph(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    output = run_review_graph(
        make_graph_dependencies(),
        make_review_state(workspace.resolve()),
    )

    assert output["review_status"] == "completed"
    assert output["review_report"] is not None
    assert output["review_report"].report_status == "completed"
    assert set(output["agent_results"]) == set(DIMENSIONS)
    assert set(output["completed_tasks"]) == {
        output[f"{dimension}_task"].task_id for dimension in DIMENSIONS
    }
    assert ENV_SECRET not in str(output)
