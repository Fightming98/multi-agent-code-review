"""Stage 2.4：Final Reviewer、报告构建与失败语义测试。"""

from __future__ import annotations

import ast
import builtins
import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from code_review.agents.contracts import ArtifactData, UsageSummary
from code_review.agents.manager import AGENT_SPECS
from code_review.agents.reviewer import (
    FinalReviewer,
    FinalReviewError,
    FinalReviewRequest,
)
from code_review.schemas.report import ExecutionSummary
from code_review.schemas.result import ToolEvidence
from config.llm_pricing import ModelPricing
from tests.stage2_helpers import (
    COMMIT_SHA,
    REVIEW_ID,
    make_dimension_result,
    make_final_review_request,
    make_finding,
    make_review_rules,
    make_test_report_block,
)

SOURCE = "\n".join(  # noqa: FLY002 - line-numbered fixture source
    [
        '"""Sample module for final reviewer tests."""',
        "",
        "import os",
        "",
        'api_key = "sample-token-value"',
        "",
        "",
        "def build_query(user_input):",
        '    query = "SELECT * FROM users WHERE name = \'" + user_input',
        "    return query",
        "",
        "",
        "def run(user_input):",
        '    os.system("echo " + user_input)',
        "",
    ]
) + "\n"

TEST_SOURCE = "\n".join(  # noqa: FLY002 - line-numbered fixture source
    [
        '"""Tests for the sample module."""',
        "",
        "def test_ok():",
        "    assert True",
        "",
    ]
) + "\n"

APP_FILE = "pkg/sample.py"
TEST_FILE = "tests/test_app.py"
SQL_EVIDENCE = 'query = "SELECT * FROM users WHERE name = \'" + user_input'
RUN_EVIDENCE = 'os.system("echo " + user_input)'

AGENT_NAME = {
    dimension: agent_name
    for dimension, agent_name, _, _ in AGENT_SPECS
}


def make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "sample.py").write_text(SOURCE, encoding="utf-8")
    (root / "tests").mkdir()
    (root / TEST_FILE).write_text(TEST_SOURCE, encoding="utf-8")
    return root


def tool_record(
    *,
    rule_id: str = "B608",
    file_path: str = APP_FILE,
    line: int = 9,
    message: str = "sample tool finding",
    severity: str = "MEDIUM",
) -> dict:
    return {
        "rule_id": rule_id,
        "file_path": file_path,
        "line": line,
        "end_line": line,
        "severity": severity,
        "message": message,
        "metadata": {},
    }


def tool_block(tool_name: str, records: list[dict]) -> dict:
    return {
        "tool_name": tool_name,
        "tool_version": "1.9.4",
        "execution_status": "findings",
        "findings": records,
    }


def make_artifact(
    *,
    security_records: list[dict] | None = None,
    quality_records: list[dict] | None = None,
    performance_records: list[dict] | None = None,
    test_report: dict | None = None,
) -> ArtifactData:
    tools_by_dimension = {
        "security": {
            "bandit": tool_block(
                "bandit",
                security_records
                if security_records is not None
                else [tool_record()],
            )
        },
        "quality": {
            "radon": tool_block(
                "radon",
                quality_records
                if quality_records is not None
                else [tool_record(rule_id="RADON_CC")],
            )
        },
        "performance": {
            "radon": tool_block(
                "radon",
                performance_records
                if performance_records is not None
                else [tool_record(rule_id="RADON_CC")],
            )
        },
        "testing": {},
    }
    agents = {
        dimension: {
            "agent_name": agent_name,
            "result_status": "completed",
            "warnings": [],
            "tools": tools_by_dimension[dimension],
        }
        for dimension, agent_name, _, _ in AGENT_SPECS
    }
    return ArtifactData(
        static_analysis={"schema_version": "1.0", "agents": agents},
        test_report=(
            test_report
            if test_report is not None
            else make_test_report_block()
        ),
    )


def static_evidence(
    *,
    dimension: str,
    tool_name: str,
    rule_id: str,
    index: int = 0,
) -> ToolEvidence:
    return ToolEvidence(
        tool_name=tool_name,
        rule_id=rule_id,
        raw_output_ref=(
            f"static_analysis.json#/agents/{dimension}/tools/{tool_name}/"
            f"findings/{index}"
        ),
    )


def critical_finding(dimension: str):
    if dimension == "security":
        return make_finding(
            finding_id="SEC-CRIT",
            agent_name="SecurityAgent",
            category="sql_injection",
            severity="critical",
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[
                static_evidence(
                    dimension="security", tool_name="bandit", rule_id="B608"
                )
            ],
        )
    if dimension == "quality":
        return make_finding(
            finding_id="QUA-CRIT",
            agent_name="QualityAgent",
            category="high_complexity",
            severity="critical",
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[
                static_evidence(
                    dimension="quality",
                    tool_name="radon",
                    rule_id="RADON_CC",
                )
            ],
        )
    if dimension == "performance":
        return make_finding(
            finding_id="PER-CRIT",
            agent_name="PerformanceAgent",
            category="algorithmic_complexity",
            severity="critical",
            file_path=APP_FILE,
            start_line=9,
            evidence=SQL_EVIDENCE,
            tool_evidence=[
                static_evidence(
                    dimension="performance",
                    tool_name="radon",
                    rule_id="RADON_CC",
                )
            ],
        )
    if dimension == "testing":
        return make_finding(
            finding_id="TST-CRIT",
            agent_name="TestingAgent",
            category="test_failure",
            severity="critical",
            file_path=TEST_FILE,
            start_line=3,
            end_line=3,
            evidence="def test_ok():",
            tool_evidence=[
                ToolEvidence(
                    tool_name="pytest",
                    raw_output_ref="test_report.json#/records/0",
                )
            ],
        )
    raise ValueError(dimension)


def make_test_pricing() -> ModelPricing:
    return ModelPricing(
        model="test-model",
        input_per_million_tokens=Decimal("0.25"),
        output_per_million_tokens=Decimal("1.00"),
        currency="USD",
        source_url="https://example.invalid/pricing",
        retrieved_at="2026-11-13",
    )


def run_review(workspace: Path, **overrides):
    overrides.setdefault("allowed_files", (APP_FILE, TEST_FILE))
    overrides.setdefault("artifact_data", make_artifact())
    request = make_final_review_request(workspace, **overrides)
    return FinalReviewer().review(request)


# ----------------------------------------------------------------------
# 基本报告


def test_review_builds_complete_report(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    outcome = run_review(workspace)

    report = outcome.report
    assert report.review_id == REVIEW_ID
    assert report.commit_sha == COMMIT_SHA
    assert report.report_status == "completed"
    assert report.overall_verdict == "APPROVE"
    assert report.overall_score == pytest.approx(100.0)
    assert set(report.dimension_scores) == set(AGENT_NAME)
    assert set(report.agent_results) == set(AGENT_NAME)
    for dimension, score in report.dimension_scores.items():
        assert score.status == "completed"
        assert score.score == pytest.approx(100.0)
        expected_weight = make_review_rules().weight_for(dimension)
        assert score.weight == pytest.approx(expected_weight)
    assert report.findings == []
    assert report.rejected_findings == []
    assert report.test_summary.execution_status == "executed"
    assert report.test_summary.passed == 3
    assert report.test_summary.coverage == pytest.approx(91.0)
    assert report.cost_summary.estimated_cost == 0
    assert report.cost_summary.total_input_tokens == 0
    assert report.cost_summary.total_output_tokens == 0
    assert report.execution_summary.total_tasks == 4
    assert report.execution_summary.completed_tasks == 4

    assert outcome.review_status == "completed"
    assert outcome.statistics["final_reviewer"] == "implemented"
    assert outcome.statistics["stage"] == "2.4"
    assert outcome.statistics["implemented"] is True
    assert outcome.statistics["agent_task_count"] == 4
    assert outcome.statistics["aggregated_dimensions"] == sorted(AGENT_NAME)
    assert outcome.statistics["overall_verdict"] == "APPROVE"


def test_verified_finding_lowers_dimension_score(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    finding = make_finding(
        finding_id="SEC-0001",
        agent_name="SecurityAgent",
        category="sql_injection",
        severity="medium",
        file_path=APP_FILE,
        start_line=9,
        evidence=SQL_EVIDENCE,
        tool_evidence=[
            static_evidence(
                dimension="security", tool_name="bandit", rule_id="B608"
            )
        ],
    )
    outcome = run_review(
        workspace,
        results={"security": make_dimension_result("security", findings=[finding])},
    )

    report = outcome.report
    assert len(report.findings) == 1
    assert report.findings[0].verification_status == "verified"
    assert report.dimension_scores["security"].score == pytest.approx(95.0)
    expected = (0.35 * 95 + 0.25 * 100 + 0.20 * 100 + 0.20 * 100) / 1.0
    assert report.overall_score == pytest.approx(expected)
    assert report.overall_verdict == "APPROVE"


def test_project_level_low_coverage_is_scored(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        test_report=make_test_report_block(coverage=45.0)
    )
    finding = make_finding(
        finding_id="TST-LOW",
        agent_name="TestingAgent",
        category="low_coverage",
        severity="medium",
        title="Coverage is below the configured minimum",
        description="Coverage is 45.0%, below 80%.",
        file_path=None,
        start_line=None,
        end_line=None,
        evidence="Coverage is below the configured minimum.",
        tool_evidence=[
            ToolEvidence(
                tool_name="coverage",
                raw_output_ref="test_report.json#/coverage",
            )
        ],
    )

    outcome = run_review(
        workspace,
        artifact_data=artifact,
        results={
            "testing": make_dimension_result("testing", findings=[finding])
        },
    )

    report = outcome.report
    assert len(report.findings) == 1
    assert report.findings[0].file_path is None
    assert report.findings[0].start_line is None
    assert report.findings[0].verification_status == "verified"
    assert report.dimension_scores["testing"].score == pytest.approx(95.0)


# ----------------------------------------------------------------------
# 去重


def test_dedup_merges_cross_dimension_duplicates(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        security_records=[tool_record(rule_id="B105", line=5)],
        quality_records=[tool_record(rule_id="S105", line=5)],
    )
    security_finding = make_finding(
        finding_id="SEC-0001",
        agent_name="SecurityAgent",
        category="hardcoded_secret",
        severity="high",
        title="Hardcoded credential",
        description="security description",
        file_path=APP_FILE,
        start_line=5,
        evidence='api_key = "sample-token-value"',
        tool_evidence=[
            static_evidence(
                dimension="security", tool_name="bandit", rule_id="B105"
            )
        ],
        confidence=0.9,
    )
    quality_finding = make_finding(
        finding_id="QUA-0001",
        agent_name="QualityAgent",
        category="hardcoded_password",
        severity="medium",
        title="Hardcoded credential",
        description="quality description",
        file_path=APP_FILE,
        start_line=5,
        evidence='api_key = "sample-token-value"',
        tool_evidence=[
            static_evidence(
                dimension="quality", tool_name="radon", rule_id="S105"
            )
        ],
        confidence=0.6,
    )

    outcome = run_review(
        workspace,
        artifact_data=artifact,
        results={
            "security": make_dimension_result(
                "security", findings=[security_finding]
            ),
            "quality": make_dimension_result(
                "quality", findings=[quality_finding]
            ),
        },
    )

    report = outcome.report
    assert len(report.findings) == 1
    merged = report.findings[0]
    assert merged.finding_id == "SEC-0001"
    assert merged.merged_from == ["QUA-0001"]
    assert merged.severity == "high"
    assert "security description" in merged.description
    refs = {evidence.raw_output_ref for evidence in merged.tool_evidence}
    assert len(refs) == 2
    assert outcome.statistics["deduplication"]["merged_away"] == 1

    # 原始 AgentResult 不被修改：两条 Finding 仍在各自结果中保持原状。
    original = outcome.report.agent_results
    assert len(original["security"].findings) == 1
    assert len(original["quality"].findings) == 1
    assert (
        original["quality"].findings[0].verification_status == "unverified"
    )


def test_dedup_project_level_uses_category_and_tool(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        test_report=make_test_report_block(passed=0, failed=0, skipped=0)
    )
    testing_finding = make_finding(
        finding_id="TST-0001",
        agent_name="TestingAgent",
        category="missing_tests",
        severity="low",
        file_path=None,
        start_line=None,
        end_line=None,
        evidence="No tests were collected.",
        tool_evidence=[
            ToolEvidence(
                tool_name="pytest",
                raw_output_ref="test_report.json#/counts/total",
            )
        ],
        confidence=0.7,
    )
    quality_finding = make_finding(
        finding_id="QUA-0001",
        agent_name="QualityAgent",
        category="missing_tests",
        severity="medium",
        file_path=None,
        start_line=None,
        end_line=None,
        evidence="No tests were collected.",
        tool_evidence=[
            ToolEvidence(
                tool_name="pytest",
                raw_output_ref="test_report.json#/counts",
            )
        ],
        confidence=0.8,
    )

    outcome = run_review(
        workspace,
        artifact_data=artifact,
        results={
            "testing": make_dimension_result(
                "testing", findings=[testing_finding]
            ),
            "quality": make_dimension_result(
                "quality", findings=[quality_finding]
            ),
        },
    )

    report = outcome.report
    assert len(report.findings) == 1
    assert report.findings[0].finding_id == "QUA-0001"
    assert report.findings[0].merged_from == ["TST-0001"]
    assert report.findings[0].severity == "medium"


def test_dedup_does_not_merge_only_on_title(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        security_records=[
            tool_record(rule_id="B608", line=9),
            tool_record(rule_id="B608", line=14),
        ]
    )
    first = make_finding(
        finding_id="SEC-0001",
        category="sql_injection",
        file_path=APP_FILE,
        start_line=9,
        evidence=SQL_EVIDENCE,
        tool_evidence=[
            static_evidence(
                dimension="security", tool_name="bandit", rule_id="B608"
            )
        ],
    )
    second = make_finding(
        finding_id="SEC-0002",
        category="unsafe_network",
        title=first.title,
        file_path=APP_FILE,
        start_line=14,
        end_line=14,
        evidence=RUN_EVIDENCE,
        tool_evidence=[
            static_evidence(
                dimension="security",
                tool_name="bandit",
                rule_id="B608",
                index=1,
            )
        ],
    )

    outcome = run_review(
        workspace,
        artifact_data=artifact,
        results={
            "security": make_dimension_result(
                "security", findings=[first, second]
            )
        },
    )

    assert len(outcome.report.findings) == 2


# ----------------------------------------------------------------------
# B-2：报告保存精确值，展示一位小数


def test_report_keeps_exact_score_and_display_value(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        security_records=[tool_record(line=14)],
        test_report=make_test_report_block(
            execution_status="not_executed", reason="external repository"
        ),
    )
    security_finding = make_finding(
        finding_id="SEC-LOW",
        agent_name="SecurityAgent",
        category="unsafe_network",
        severity="low",
        file_path=APP_FILE,
        start_line=14,
        end_line=14,
        evidence=RUN_EVIDENCE,
        tool_evidence=[
            static_evidence(
                dimension="security", tool_name="bandit", rule_id="B608"
            )
        ],
    )
    quality_finding = make_finding(
        finding_id="QUA-MED",
        agent_name="QualityAgent",
        category="high_complexity",
        severity="medium",
        file_path=APP_FILE,
        start_line=9,
        evidence=SQL_EVIDENCE,
        tool_evidence=[
            static_evidence(
                dimension="quality", tool_name="radon", rule_id="RADON_CC"
            )
        ],
    )
    performance_finding = make_finding(
        finding_id="PER-LOW",
        agent_name="PerformanceAgent",
        category="io_efficiency",
        severity="low",
        file_path=APP_FILE,
        start_line=9,
        evidence=SQL_EVIDENCE,
        tool_evidence=[
            static_evidence(
                dimension="performance",
                tool_name="radon",
                rule_id="RADON_CC",
            )
        ],
    )

    outcome = run_review(
        workspace,
        artifact_data=artifact,
        results={
            "security": make_dimension_result(
                "security", findings=[security_finding]
            ),
            "quality": make_dimension_result(
                "quality", findings=[quality_finding]
            ),
            "performance": make_dimension_result(
                "performance", findings=[performance_finding]
            ),
        },
    )

    report = outcome.report
    # security 98、quality 95、performance 98、testing null：
    # (0.35×98 + 0.25×95 + 0.20×98) / 0.80 = 97.0625
    assert report.overall_score == pytest.approx(97.0625, abs=1e-9)
    assert outcome.statistics["overall_score_display"] == "97.1"
    assert report.dimension_scores["testing"].score is None
    assert report.dimension_scores["testing"].weight == pytest.approx(0.20)
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"


# ----------------------------------------------------------------------
# critical 硬阻断（四个维度独立验证）


@pytest.mark.parametrize(
    "dimension", ["security", "quality", "performance", "testing"]
)
def test_verified_critical_blocks_in_every_dimension(
    tmp_path: Path, dimension: str
) -> None:
    workspace = make_workspace(tmp_path)
    finding = critical_finding(dimension)
    outcome = run_review(
        workspace,
        results={
            dimension: make_dimension_result(
                dimension, findings=[finding]
            )
        },
    )

    report = outcome.report
    critical = [
        item
        for item in report.findings
        if item.finding_id == finding.finding_id
    ]
    assert len(critical) == 1
    assert critical[0].severity == "critical"
    assert critical[0].verification_status == "verified"
    assert report.overall_verdict == "REQUEST_CHANGES"
    assert any("critical" in reason for reason in report.verdict_reasons)


def test_forged_critical_is_rejected_without_blocking(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    forged = make_finding(
        finding_id="SEC-FORGED",
        category="sql_injection",
        severity="critical",
        file_path="pkg/missing.py",
        start_line=1,
        evidence="does not exist",
        tool_evidence=[
            static_evidence(
                dimension="security", tool_name="bandit", rule_id="B608"
            )
        ],
    )
    outcome = run_review(
        workspace,
        allowed_files=(APP_FILE, TEST_FILE, "pkg/missing.py"),
        results={"security": make_dimension_result("security", findings=[forged])},
    )

    report = outcome.report
    assert report.findings == []
    assert len(report.rejected_findings) == 1
    assert report.rejected_findings[0].verification_status == "rejected"
    assert report.dimension_scores["security"].score == pytest.approx(100.0)
    assert report.overall_verdict == "APPROVE"


# ----------------------------------------------------------------------
# 失败语义


def test_single_agent_failure_keeps_partial_report(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    outcome = run_review(
        workspace,
        results={
            "performance": make_dimension_result(
                "performance", status="failed"
            )
        },
    )

    report = outcome.report
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    dimension = report.dimension_scores["performance"]
    assert dimension.status == "failed"
    assert dimension.score is None
    assert dimension.reason
    assert report.agent_results["performance"].status == "failed"
    assert report.agent_results["security"].status == "completed"
    assert report.overall_score == pytest.approx(100.0)


def test_all_agents_failed_produces_null_scores(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    outcome = run_review(
        workspace,
        results={
            dimension: make_dimension_result(dimension, status="failed")
            for dimension in AGENT_NAME
        },
    )

    report = outcome.report
    assert report.report_status == "partial"
    assert report.overall_score is None
    assert report.overall_verdict == "COMMENT"
    assert report.verdict_reasons
    for dimension in report.dimension_scores.values():
        assert dimension.score is None
        assert dimension.status == "failed"
        assert dimension.reason
    assert report.execution_summary.failed_tasks == 4


def test_pytest_success_with_coverage_failure_keeps_counts(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    failed_report = {
        "schema_version": "1.0",
        "execution_status": "failed",
        "reason": "coverage report could not be generated",
        "counts": {"total": 3, "passed": 3, "failed": 0, "skipped": 0},
        "coverage": None,
        "source": "pytest",
        "records": [],
        "warnings": [],
    }
    artifact = make_artifact(test_report=failed_report)
    outcome = run_review(
        workspace,
        artifact_data=artifact,
        results={
            "testing": make_dimension_result("testing", status="failed")
        },
    )

    report = outcome.report
    summary = report.test_summary
    assert summary.execution_status == "failed"
    assert summary.passed == 3
    assert summary.failed == 0
    assert summary.coverage is None
    assert summary.reason
    assert report.dimension_scores["testing"].score is None
    assert report.report_status == "partial"


def test_external_testing_not_executed_scores_null(
    tmp_path: Path,
) -> None:
    workspace = make_workspace(tmp_path)
    artifact = make_artifact(
        test_report=make_test_report_block(
            execution_status="not_executed",
            reason="external repository tests are not executed",
        )
    )
    outcome = run_review(workspace, artifact_data=artifact)

    report = outcome.report
    assert report.agent_results["testing"].status == "completed"
    assert report.dimension_scores["testing"].score is None
    assert report.dimension_scores["testing"].reason
    assert report.test_summary.execution_status == "not_executed"
    assert report.test_summary.passed is None
    assert report.test_summary.coverage is None
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"


def test_real_llm_usage_is_priced_into_cost_summary(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    usage = UsageSummary(
        llm_calls=2,
        reported_usage_calls=2,
        input_tokens=1_234,
        output_tokens=567,
    )

    outcome = run_review(
        workspace,
        usage=usage,
        model_pricing=make_test_pricing(),
    )

    cost = outcome.report.cost_summary
    expected = (
        Decimal(1_234) * Decimal("0.25")
        + Decimal(567) * Decimal("1.00")
    ) / Decimal(1_000_000)
    assert cost.total_input_tokens == 1_234
    assert cost.total_output_tokens == 567
    assert cost.estimated_cost == pytest.approx(float(expected))
    assert cost.estimated_cost > 0
    assert cost.currency == "USD"


def test_real_llm_usage_without_pricing_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    with pytest.raises(FinalReviewError, match="pricing is required"):
        run_review(
            workspace,
            usage=UsageSummary(
                llm_calls=1,
                reported_usage_calls=1,
                input_tokens=100,
                output_tokens=20,
            ),
        )


def test_incomplete_llm_usage_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    with pytest.raises(FinalReviewError, match="usage is incomplete"):
        run_review(
            workspace,
            usage=UsageSummary(
                llm_calls=2,
                reported_usage_calls=1,
                input_tokens=100,
                output_tokens=20,
            ),
            model_pricing=make_test_pricing(),
        )


def test_tokens_without_llm_calls_are_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)

    with pytest.raises(FinalReviewError, match="without calls"):
        run_review(
            workspace,
            usage=UsageSummary(
                llm_calls=0,
                reported_usage_calls=0,
                input_tokens=10,
                output_tokens=0,
            ),
        )


def test_final_reviewer_failure_is_not_disguised(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    with pytest.raises(FinalReviewError):
        run_review(
            workspace,
            usage=UsageSummary(llm_calls=1, reported_usage_calls=1),
        )

    inconsistent = ExecutionSummary(
        total_tasks=5,
        completed_tasks=5,
        partial_tasks=0,
        failed_tasks=0,
        cancelled_tasks=0,
        duration_seconds=0.0,
    )
    with pytest.raises(FinalReviewError):
        run_review(workspace, execution_summary=inconsistent)


def test_request_contract_is_validated(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    request = make_final_review_request(workspace)
    payload = {
        field_name: getattr(request, field_name)
        for field_name in (
            "review_id",
            "commit_sha",
            "repository",
            "repository_url",
            "branch",
            "language",
            "workspace_path",
            "allowed_files",
            "rules",
            "agent_results",
            "artifact_data",
            "usage_summary",
        )
    }
    payload["agent_results"] = dict(payload["agent_results"])
    payload["agent_results"]["security"] = (
        payload["agent_results"]["security"].model_copy(
            update={"agent_name": "QualityAgent"}
        )
    )

    with pytest.raises(FinalReviewError):
        FinalReviewRequest(**payload)


# ----------------------------------------------------------------------
# 无 AgentTask、无写能力、内存闭环


def test_final_reviewer_creates_no_agent_task(tmp_path: Path) -> None:
    import code_review.agents.reviewer as reviewer_module

    workspace = make_workspace(tmp_path)
    outcome = run_review(workspace)

    assert outcome.statistics["agent_task_count"] == 4
    assert len(outcome.report.agent_results) == 4

    # 源码里没有对 AgentTask 或 task_id 的任何代码级引用（文档字符串除外）。
    tree = ast.parse(inspect.getsource(reviewer_module))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    names |= {
        keyword.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg is not None
    }
    assert "AgentTask" not in names
    assert "task_id" not in names


def test_final_reviewer_has_no_write_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = make_workspace(tmp_path)
    finding = make_finding(
        finding_id="SEC-0001",
        file_path=APP_FILE,
        start_line=9,
        evidence=SQL_EVIDENCE,
        tool_evidence=[
            static_evidence(
                dimension="security", tool_name="bandit", rule_id="B608"
            )
        ],
    )

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"write mode attempted: {mode}")
        return real_open(file, mode, *args, **kwargs)

    def forbidden_write(*args, **kwargs):
        raise AssertionError("file write attempted")

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "write_text", forbidden_write)
    monkeypatch.setattr(Path, "write_bytes", forbidden_write)

    outcome = run_review(
        workspace,
        results={"security": make_dimension_result("security", findings=[finding])},
    )

    assert outcome.report.findings[0].verification_status == "verified"


def test_review_uses_memory_artifacts_only(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    before = sorted(
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
    )
    finding = make_finding(
        finding_id="SEC-0001",
        file_path=APP_FILE,
        start_line=9,
        evidence=SQL_EVIDENCE,
        tool_evidence=[
            static_evidence(
                dimension="security", tool_name="bandit", rule_id="B608"
            )
        ],
    )

    outcome = run_review(
        workspace,
        results={"security": make_dimension_result("security", findings=[finding])},
    )

    assert outcome.report.findings[0].verification_status == "verified"
    assert not (workspace / "static_analysis.json").exists()
    assert not (workspace / "test_report.json").exists()
    after = sorted(
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
    )
    assert after == before
