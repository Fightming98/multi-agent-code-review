"""工具结果聚合、Finding 映射与去重的单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from code_review.schemas.report import TestSummary
from code_review.schemas.result import Finding, ToolEvidence
from code_review.schemas.task import ErrorInfo
from code_review.services.finding_aggregator import (
    aggregate_review_results,
    deduplicate_findings,
)
from code_review.tools.base import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
)


def tool_result(
    tool_name: str,
    findings: list[ToolFinding] | tuple[ToolFinding, ...] = (),
    *,
    status: ToolExecutionStatus = ToolExecutionStatus.FINDINGS,
    version: str = "1.0.0",
    error: ErrorInfo | None = None,
) -> ToolExecutionResult:
    now = datetime.now(UTC)
    return ToolExecutionResult(
        tool_name=tool_name,
        tool_version=version,
        execution_status=status,
        exit_code=0,
        started_at=now,
        finished_at=now,
        duration_ms=1,
        stdout="",
        stderr="",
        findings=tuple(findings),
        error=error,
        analyzed_file_count=1,
    )


def bandit_finding(**overrides: object) -> ToolFinding:
    values: dict[str, object] = {
        "tool_name": "bandit",
        "rule_id": "B602",
        "file_path": "pkg/app.py",
        "message": "subprocess call with shell equals true",
        "line": 5,
        "severity": "HIGH",
        "confidence": "MEDIUM",
        "metadata": {"test_name": "subprocess_popen_with_shell_equals_true"},
    }
    values.update(overrides)
    return ToolFinding(**values)  # type: ignore[arg-type]


def ruff_finding(**overrides: object) -> ToolFinding:
    values: dict[str, object] = {
        "tool_name": "ruff",
        "rule_id": "F401",
        "file_path": "pkg/app.py",
        "message": "`os` imported but unused",
        "line": 1,
    }
    values.update(overrides)
    return ToolFinding(**values)  # type: ignore[arg-type]


def radon_finding(rule_id: str, rank: str, **overrides: object) -> ToolFinding:
    values: dict[str, object] = {
        "tool_name": "radon",
        "rule_id": rule_id,
        "file_path": "pkg/app.py",
        "message": f"radon {rule_id} rank {rank}",
        "line": 3,
        "metadata": {
            "rank": rank,
            "complexity": 12,
            "mi": 42.5,
            "object_name": "run",
            "object_type": "function",
        },
    }
    values.update(overrides)
    return ToolFinding(**values)  # type: ignore[arg-type]


def test_bandit_finding_maps_to_contract() -> None:
    aggregation = aggregate_review_results(
        [tool_result("bandit", [bandit_finding()])]
    )

    assert len(aggregation.findings) == 1
    finding = aggregation.findings[0]
    assert finding.finding_id == "BANDIT-0000"
    assert finding.agent_name == "Stage1Analyzer"
    assert finding.category == "command_injection"
    assert finding.severity == "high"
    assert finding.confidence == 0.7
    assert finding.verification_status == "unverified"
    assert finding.file_path == "pkg/app.py"
    assert finding.start_line == 5
    assert finding.end_line == 5
    assert "B602" in finding.title
    assert "subprocess_popen_with_shell_equals_true" in finding.description
    assert finding.tool_evidence == [
        ToolEvidence(
            tool_name="bandit",
            rule_id="B602",
            tool_version="1.0.0",
            raw_output_ref="static_analysis.json#/tools/bandit/findings/0",
        )
    ]


def test_ruff_rule_mapping_and_severity() -> None:
    findings = [
        ruff_finding(rule_id="F401"),
        ruff_finding(rule_id="E501"),
        ruff_finding(rule_id="S603", message="subprocess call"),
    ]

    aggregation = aggregate_review_results(
        [tool_result("ruff", findings)]
    )

    by_rule = {
        finding.tool_evidence[0].rule_id: finding
        for finding in aggregation.findings
    }
    assert by_rule["F401"].category == "code_smell"
    assert by_rule["F401"].severity == "medium"
    assert by_rule["E501"].category == "style_violation"
    assert by_rule["E501"].severity == "low"
    assert by_rule["S603"].category == "command_injection"
    assert by_rule["S603"].severity == "high"


def test_ruff_sim_rule_is_style_not_security() -> None:
    findings = [
        ruff_finding(rule_id="SIM117", line=1),
        ruff_finding(rule_id="S603", line=2, message="subprocess call"),
        ruff_finding(rule_id="S110", line=3, message="try-except-pass"),
    ]

    aggregation = aggregate_review_results(
        [tool_result("ruff", findings)]
    )

    by_rule = {
        finding.tool_evidence[0].rule_id: finding
        for finding in aggregation.findings
    }
    assert by_rule["SIM117"].category == "style_violation"
    assert by_rule["SIM117"].severity == "low"
    assert by_rule["S603"].category == "command_injection"
    assert by_rule["S603"].severity == "high"
    assert by_rule["S110"].category == "security_issue"
    assert by_rule["S110"].severity == "high"


def test_radon_rank_a_is_skipped() -> None:
    aggregation = aggregate_review_results(
        [
            tool_result(
                "radon",
                [
                    radon_finding("RADON_CC", "A"),
                    radon_finding("RADON_CC", "B"),
                ],
            )
        ]
    )

    assert len(aggregation.findings) == 1
    finding = aggregation.findings[0]
    assert finding.category == "high_complexity"
    assert finding.severity == "low"
    assert aggregation.stats.source_finding_count == 2
    assert aggregation.stats.skipped_finding_count == 1


def test_radon_maintainability_is_aggregated_as_one_project_finding() -> None:
    aggregation = aggregate_review_results(
        [
            tool_result(
                "radon",
                [
                    radon_finding("RADON_MI", "A"),
                    radon_finding("RADON_MI", "B", file_path="pkg/a.py"),
                    radon_finding("RADON_MI", "C", file_path="pkg/b.py"),
                ],
            )
        ]
    )

    assert len(aggregation.findings) == 1
    finding = aggregation.findings[0]
    assert finding.finding_id == "RADON-MI-0001"
    assert finding.category == "low_maintainability"
    assert finding.severity == "medium"
    assert finding.file_path is None
    assert finding.start_line is None
    assert "pkg/a.py" in finding.evidence
    assert "pkg/b.py" in finding.evidence
    assert len(finding.tool_evidence) == 2
    assert aggregation.stats.skipped_finding_count == 1


def test_unknown_radon_maintainability_rank_is_skipped() -> None:
    aggregation = aggregate_review_results(
        [tool_result("radon", [radon_finding("RADON_MI", "?")])]
    )

    assert aggregation.findings == ()
    assert aggregation.stats.skipped_finding_count == 1


def test_executed_test_failures_create_a_test_finding() -> None:
    test_result = SimpleNamespace(
        summary=TestSummary(
            execution_status="executed",
            passed=2,
            failed=1,
            skipped=0,
            coverage=80.0,
            source="coverage.py",
        ),
        pytest_version="9.2.0",
        fixture_name="trusted_fixture_v1",
        fixture_version="1.0.0",
    )

    aggregation = aggregate_review_results([], test_result)

    assert len(aggregation.findings) == 1
    finding = aggregation.findings[0]
    assert finding.finding_id == "PYTEST-0001"
    assert finding.category == "test_failure"
    assert finding.severity == "medium"
    assert finding.file_path is None
    assert finding.tool_evidence == [
        ToolEvidence(
            tool_name="pytest",
            rule_id=None,
            tool_version="9.2.0",
            raw_output_ref="static_analysis.json#/tests/pytest",
        )
    ]
    assert aggregation.stats.test_failure_finding_count == 1


def test_not_executed_or_passing_tests_do_not_create_a_finding() -> None:
    not_executed = SimpleNamespace(
        summary=TestSummary(
            execution_status="not_executed",
            reason="external repository is untrusted",
        ),
        pytest_version=None,
        fixture_name=None,
        fixture_version=None,
    )
    passing = SimpleNamespace(
        summary=TestSummary(
            execution_status="executed",
            passed=3,
            failed=0,
            skipped=0,
        ),
        pytest_version="9.2.0",
        fixture_name="trusted_fixture_v1",
        fixture_version="1.0.0",
    )

    assert aggregate_review_results([], not_executed).findings == ()
    assert aggregate_review_results([], passing).findings == ()


def test_duplicate_findings_are_merged_and_keep_highest_severity() -> None:
    first = ruff_finding(
        rule_id="F401",
        line=3,
        message="first description",
    )
    second = ruff_finding(
        rule_id="F841",
        line=3,
        message="second description",
    )

    aggregation = aggregate_review_results(
        [tool_result("ruff", [first, second])]
    )

    assert len(aggregation.findings) == 1
    finding = aggregation.findings[0]
    assert finding.severity == "medium"
    assert finding.merged_from
    assert len(finding.tool_evidence) == 2
    assert aggregation.stats.duplicate_count == 1
    assert aggregation.stats.mapped_finding_count == 2
    assert aggregation.stats.final_finding_count == 1


def test_same_category_non_overlapping_lines_are_not_merged() -> None:
    aggregation = aggregate_review_results(
        [
            tool_result(
                "ruff",
                [
                    ruff_finding(rule_id="F401", line=1),
                    ruff_finding(rule_id="F841", line=10),
                ],
            )
        ]
    )

    assert len(aggregation.findings) == 2
    assert aggregation.stats.duplicate_count == 0


def test_same_location_different_category_is_not_merged() -> None:
    aggregation = aggregate_review_results(
        [
            tool_result(
                "ruff",
                [
                    ruff_finding(rule_id="F401", line=1),
                    ruff_finding(rule_id="E501", line=1),
                ],
            )
        ]
    )

    assert len(aggregation.findings) == 2


def test_same_category_different_file_is_not_merged() -> None:
    aggregation = aggregate_review_results(
        [
            tool_result(
                "ruff",
                [
                    ruff_finding(rule_id="F401", line=1, file_path="a.py"),
                    ruff_finding(rule_id="F841", line=1, file_path="b.py"),
                ],
            )
        ]
    )

    assert len(aggregation.findings) == 2


def test_unlocated_findings_merge_only_for_same_tool_source() -> None:
    pytest_finding = Finding(
        finding_id="PYTEST-0001",
        agent_name="Stage1Analyzer",
        category="test_failure",
        severity="medium",
        title="pytest failures",
        description="one",
        evidence="one",
        tool_evidence=[
            ToolEvidence(tool_name="pytest", raw_output_ref="a")
        ],
        recommendation="fix",
        confidence=0.5,
    )
    radon_finding_contract = Finding(
        finding_id="RADON-MI-0001",
        agent_name="Stage1Analyzer",
        category="test_failure",
        severity="medium",
        title="maintainability",
        description="two",
        evidence="two",
        tool_evidence=[
            ToolEvidence(tool_name="radon", raw_output_ref="b")
        ],
        recommendation="fix",
        confidence=0.5,
    )

    merged, duplicates = deduplicate_findings(
        [pytest_finding, radon_finding_contract]
    )

    assert len(merged) == 2
    assert duplicates == 0


def test_unlocated_findings_with_same_tool_are_merged() -> None:
    first = Finding(
        finding_id="PYTEST-0001",
        agent_name="Stage1Analyzer",
        category="test_failure",
        severity="medium",
        title="first",
        description="one",
        evidence="one",
        tool_evidence=[ToolEvidence(tool_name="pytest", raw_output_ref="a")],
        recommendation="fix",
        confidence=0.5,
    )
    second = Finding(
        finding_id="PYTEST-0002",
        agent_name="Stage1Analyzer",
        category="test_failure",
        severity="low",
        title="second",
        description="two",
        evidence="two",
        tool_evidence=[ToolEvidence(tool_name="pytest", raw_output_ref="b")],
        recommendation="fix",
        confidence=0.6,
    )

    merged, duplicates = deduplicate_findings([first, second])

    assert len(merged) == 1
    assert duplicates == 1
    assert merged[0].merged_from == ["PYTEST-0002"]


def test_sensitive_values_in_tool_output_are_redacted() -> None:
    aggregation = aggregate_review_results(
        [
            tool_result(
                "bandit",
                [
                    bandit_finding(
                        rule_id="B105",
                        message='password = "super-secret-value"',
                        severity="LOW",
                    )
                ],
            )
        ]
    )

    finding = aggregation.findings[0]
    assert "super-secret-value" not in finding.title
    assert "super-secret-value" not in finding.description
    assert "super-secret-value" not in finding.evidence
    assert "[REDACTED]" in finding.evidence


def test_tool_status_counts_and_duplicate_count() -> None:
    error = ErrorInfo(
        error_type="ToolExecutionError",
        message="tool failed",
        retryable=False,
    )
    aggregation = aggregate_review_results(
        [
            tool_result("ruff", [], status=ToolExecutionStatus.FAILED, error=error),
            tool_result("bandit", [], status=ToolExecutionStatus.PARTIAL),
            tool_result("radon", [], status=ToolExecutionStatus.SUCCESS),
        ]
    )

    assert aggregation.stats.tool_failure_count == 1
    assert aggregation.stats.partial_tool_count == 1
    assert aggregation.findings == ()
    assert [summary.execution_status for summary in aggregation.tool_summaries] == [
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.PARTIAL,
        ToolExecutionStatus.SUCCESS,
    ]


def test_raw_output_prefix_is_normalized() -> None:
    aggregation = aggregate_review_results(
        [tool_result("ruff", [ruff_finding()])],
        raw_output_prefix="static_analysis.json#",
    )

    assert aggregation.raw_output_prefix == "static_analysis.json"
    assert (
        aggregation.findings[0].tool_evidence[0].raw_output_ref
        == "static_analysis.json#/tools/ruff/findings/0"
    )


def test_long_tool_text_is_capped_to_contract_limits() -> None:
    aggregation = aggregate_review_results(
        [
            tool_result(
                "ruff",
                [ruff_finding(rule_id="F401", message="x" * 5_000)],
            )
        ]
    )

    finding = aggregation.findings[0]
    assert len(finding.title) <= 200
    assert len(finding.description) <= 4_000
    assert len(finding.evidence) <= 4_000


def test_aggregation_is_deterministic() -> None:
    results = [
        tool_result("ruff", [ruff_finding()]),
        tool_result("bandit", [bandit_finding()]),
    ]

    first = aggregate_review_results(results)
    second = aggregate_review_results(results)

    assert [item.finding_id for item in first.findings] == [
        item.finding_id for item in second.findings
    ]
    assert first.stats == second.stats


def test_all_mapped_findings_remain_unverified() -> None:
    aggregation = aggregate_review_results(
        [
            tool_result("ruff", [ruff_finding()]),
            tool_result("bandit", [bandit_finding()]),
            tool_result("radon", [radon_finding("RADON_CC", "D")]),
        ]
    )

    assert aggregation.findings
    assert all(
        finding.agent_name == "Stage1Analyzer"
        for finding in aggregation.findings
    )
    assert all(
        finding.verification_status == "unverified"
        for finding in aggregation.findings
    )
