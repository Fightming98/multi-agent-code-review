"""阶段 1 Markdown 报告结构与可追溯性测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.code_review.reporting.markdown_renderer import render_markdown
from src.code_review.reporting.report_generator import ReportGenerator
from src.code_review.services.llm_analyzer import (
    LLMAnalysisStatus,
    LLMRejectedProposal,
)
from src.code_review.tools.base import ToolExecutionStatus
from src.code_review.tools.test_runner import TestExecutionStatus as ExecutionStatus
from tests.stage1_helpers import (
    FIXTURE_MANIFEST_SHA,
    NOW,
    make_aggregation,
    make_finding,
    make_llm_result,
    make_review_input,
    make_test_result,
    make_tool_finding,
    make_tool_result,
)

REQUIRED_SECTIONS = [
    "## 1. 审查基本信息",
    "## 2. 仓库和 Commit 信息",
    "## 3. 工具执行概览",
    "## 4. 代码质量分析",
    "## 5. 安全分析",
    "## 6. 复杂度分析",
    "## 7. 测试与覆盖率",
    "## 8. 重要 Finding",
    "## 9. LLM 分析摘要",
    "## 10. 风险与限制",
    "## 11. 未执行任务及原因",
    "## 12. 审查结论",
]


def render(
    tmp_path: Path,
    findings: tuple = (),
    *,
    tool_results: tuple | None = None,
    test_result=None,
    llm_analysis=None,
    **overrides: object,
) -> str:
    if tool_results is None:
        tool_results = (
            make_tool_result("ruff", findings=(make_tool_finding(),)),
            make_tool_result("bandit"),
            make_tool_result("radon"),
        )
    if test_result is None:
        test_result = make_test_result()
    aggregation = make_aggregation(
        tool_results,
        findings,
        test_result=test_result,
    )
    if llm_analysis is None:
        llm_analysis = make_llm_result(findings)
    source = make_review_input(
        workspace_path=tmp_path / "workspace",
        tool_results=tool_results,
        test_result=test_result,
        aggregation=aggregation,
        llm_analysis=llm_analysis,
        **overrides,
    )
    artifacts = ReportGenerator(clock=lambda: NOW).generate(
        source, tmp_path / "reports"
    )
    return render_markdown(
        artifacts.metadata,
        artifacts.static_analysis,
        artifacts.test_report,
    )


def section(report: str, heading: str) -> str:
    start = report.index(heading)
    next_heading = report.find("\n## ", start + len(heading))
    return report[start:] if next_heading == -1 else report[start:next_heading]


def test_report_contains_all_twelve_sections_in_order(tmp_path: Path) -> None:
    report = render(tmp_path)

    positions = [report.index(heading) for heading in REQUIRED_SECTIONS]
    assert positions == sorted(positions)
    assert len(REQUIRED_SECTIONS) == 12


def test_report_does_not_issue_stage1_verdict(tmp_path: Path) -> None:
    report = render(tmp_path)

    conclusion = section(report, "## 12. 审查结论")
    assert "阶段 1 不输出最终审查裁定" in conclusion
    assert "阶段 1 不输出 `APPROVE`" in conclusion
    assert "`REQUEST_CHANGES`" in conclusion
    assert "最终裁定：APPROVE" not in report
    assert "最终结论：REQUEST_CHANGES" not in report
    assert "Overall Verdict" not in report


def test_findings_are_grouped_into_analysis_sections(tmp_path: Path) -> None:
    findings = (
        make_finding("RUFF-Q1", category="style_violation", title="Quality item"),
        make_finding(
            "BANDIT-S1",
            category="hardcoded_secret",
            severity="high",
            title="Security item",
        ),
        make_finding(
            "RADON-C1",
            category="high_complexity",
            severity="medium",
            title="Complexity item",
            file_path=None,
            start_line=None,
            evidence="cyclomatic complexity",
        ),
        make_finding(
            "TEST-T1",
            category="test_failure",
            severity="medium",
            title="Testing item",
        ),
    )
    report = render(tmp_path, findings)

    assert "RUFF-Q1" in section(report, "## 4. 代码质量分析")
    assert "BANDIT-S1" in section(report, "## 5. 安全分析")
    assert "RADON-C1" in section(report, "## 6. 复杂度分析")
    testing_section = section(report, "## 7. 测试与覆盖率")
    assert "TEST-T1" in testing_section
    findings_section = section(report, "## 8. 重要 Finding")
    for finding_id in ("RUFF-Q1", "BANDIT-S1", "RADON-C1", "TEST-T1"):
        assert finding_id in findings_section


def test_not_executed_section_does_not_claim_test_success(
    tmp_path: Path,
) -> None:
    report = render(tmp_path)

    testing = section(report, "## 7. 测试与覆盖率")
    assert "`not_executed`" in testing
    assert "不代表测试通过" in testing
    assert "没有测试数量或覆盖率数据" in testing
    risks = section(report, "## 10. 风险与限制")
    assert "本次未执行测试" in risks
    not_executed = section(report, "## 11. 未执行任务及原因")
    assert "Pytest / Coverage" in not_executed
    assert "external repository tests are not executed" in not_executed


def test_trusted_fixture_is_distinguished_from_external_repository(
    tmp_path: Path,
) -> None:
    test_result = make_test_result(
        ExecutionStatus.EXECUTED,
        trusted_fixture=True,
        read_only_verified=True,
    )
    tool_results = (
        make_tool_result("ruff", findings=(make_tool_finding(),)),
        make_tool_result("bandit"),
        make_tool_result("radon"),
    )
    report = render(
        tmp_path,
        tool_results=tool_results,
        test_result=test_result,
        review_id="stage1-fixture-review",
        repository_url="fixture://trusted_fixture_v1",
        repository_name="trusted_fixture_v1",
        branch="fixture",
        commit_sha=None,
        fixture_manifest_sha256=FIXTURE_MANIFEST_SHA,
        source_type="trusted_fixture",
    )

    repository = section(report, "## 2. 仓库和 Commit 信息")
    assert "不伪造 Git Commit" in repository
    assert FIXTURE_MANIFEST_SHA in repository
    testing = section(report, "## 7. 测试与覆盖率")
    assert "`trusted_fixture`" in testing
    assert "`executed`" in testing
    assert "Pytest 版本" in testing
    risks = section(report, "## 10. 风险与限制")
    assert "不代表对外部仓库执行了测试" in risks


def test_failed_tool_and_llm_failure_are_reported_as_risks(
    tmp_path: Path,
) -> None:
    tool_results = (
        make_tool_result(
            "ruff",
            status=ToolExecutionStatus.FAILED,
            error=None,
        ),
        make_tool_result("bandit"),
        make_tool_result("radon"),
    )
    report = render(
        tmp_path,
        tool_results=tool_results,
        llm_analysis=make_llm_result(
            (), status=LLMAnalysisStatus.NOT_CONFIGURED
        ),
        review_status="partial",
    )

    overview = section(report, "## 3. 工具执行概览")
    assert "`failed`" in overview
    not_executed = section(report, "## 11. 未执行任务及原因")
    assert "静态分析：ruff" in not_executed
    assert "LLM 辅助分析" in not_executed
    risks = section(report, "## 10. 风险与限制")
    assert "工具 ruff 的执行状态为 failed" in risks
    assert "LLM 未配置" in risks


def test_rejected_llm_proposals_stay_out_of_formal_findings(
    tmp_path: Path,
) -> None:
    finding = make_finding("RUFF-Q1", title="Accepted deterministic finding")
    rejected = LLMRejectedProposal(
        proposal_index=3,
        reason="evidence does not match file content",
        kind="semantic_supplement",
        category="hardcoded_secret",
        title="Rejected proposal title",
        file_path="pkg/app.py",
        start_line=2,
    )
    llm = replace(
        make_llm_result((finding,)),
        rejected=(rejected,),
        proposal_count=1,
    )
    report = render(
        tmp_path,
        (finding,),
        llm_analysis=llm,
    )

    llm_section = section(report, "## 9. LLM 分析摘要")
    assert "Rejected proposal title" in llm_section
    assert "evidence does not match file content" in llm_section
    assert "不作为正式 Finding" in llm_section
    formal = section(report, "## 8. 重要 Finding")
    assert "Rejected proposal title" not in formal
    assert "Accepted deterministic finding" in formal


def test_empty_findings_are_reported_as_empty_not_as_success(
    tmp_path: Path,
) -> None:
    report = render(tmp_path, ())

    assert "本次审查未产生 Finding。" in section(
        report, "## 8. 重要 Finding"
    )
    conclusion = section(report, "## 12. 审查结论")
    assert "这不等于审查通过" in conclusion


def test_markdown_table_cells_are_escaped(tmp_path: Path) -> None:
    finding = make_finding(
        "RUFF-Q1",
        title="pipe | and\nnewline",
    )
    report = render(tmp_path, (finding,))

    assert "pipe \\| and<br>newline" in report


def test_large_finding_list_is_truncated_in_section_view(
    tmp_path: Path,
) -> None:
    findings = tuple(
        make_finding(
            f"RUFF-{index:04d}",
            category="style_violation",
            title=f"Style finding {index}",
        )
        for index in range(11)
    )
    report = render(tmp_path, findings)

    quality = section(report, "## 4. 代码质量分析")
    assert "仅展示前 10 条；该分类共有 11 条 Finding" in quality
    assert "RUFF-0010" not in quality
    important = section(report, "## 8. 重要 Finding")
    assert "RUFF-0009" in important
    assert "RUFF-0010" not in important
    assert "完整列表见 `static_analysis.json`" in important
