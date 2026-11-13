"""Stage 2.4：维度评分、综合评分、B-2 精确值与 verdict 测试。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from code_review.agents.scoring import (
    DIMENSION_ORDER,
    DimensionScoring,
    build_dimension_score,
    compute_overall_score,
    decide_verdict,
    format_score,
    score_findings,
    to_schema_dimension,
)
from code_review.schemas.report import DimensionScore
from tests.stage2_helpers import make_finding, make_review_rules

WEIGHTS = {
    "security": 0.35,
    "quality": 0.25,
    "performance": 0.20,
    "testing": 0.20,
}

RULES = make_review_rules()


def scoring(
    dimension: str,
    score: float | None,
    *,
    weight: float | None = None,
    status: str = "completed",
) -> DimensionScoring:
    return DimensionScoring(
        dimension=dimension,
        score=score,
        weight=weight if weight is not None else WEIGHTS[dimension],
        status=status,
        finding_count=0,
        reason="test fixture" if score is None else None,
    )


def all_scored(value: float = 100.0) -> list[DimensionScoring]:
    return [scoring(dimension, value) for dimension in DIMENSION_ORDER]


def make_severity_finding(severity: str, status: str = "unverified"):
    return make_finding(
        finding_id=f"F-{severity}",
        severity=severity,
        verification_status=status,
    )


# ----------------------------------------------------------------------
# 权重与扣分


def test_weights_come_from_configuration() -> None:
    for dimension in DIMENSION_ORDER:
        assert RULES.weight_for(dimension) == pytest.approx(
            WEIGHTS[dimension]
        )
    assert RULES.weight_total == pytest.approx(1.0)


def test_configured_deductions_are_applied() -> None:
    findings = [
        make_severity_finding("critical"),
        make_severity_finding("high"),
        make_severity_finding("medium"),
        make_severity_finding("low"),
        make_severity_finding("info"),
    ]

    score, deductions = score_findings(findings, rules=RULES)

    assert score == pytest.approx(53.0)
    assert sum(points for _, points in deductions) == pytest.approx(47.0)


def test_rejected_findings_do_not_deduct() -> None:
    findings = [
        make_severity_finding("critical", status="rejected"),
        make_severity_finding("info"),
    ]

    score, deductions = score_findings(findings, rules=RULES)

    assert score == pytest.approx(100.0)
    assert deductions == ()


def test_score_is_clamped_at_zero() -> None:
    findings = [
        make_severity_finding("critical") for _ in range(4)
    ]
    for index, finding in enumerate(findings):
        findings[index] = finding.model_copy(
            update={"finding_id": f"F-{index}"}
        )

    score, _ = score_findings(findings, rules=RULES)

    assert score == 0.0


def test_unavailable_dimension_is_null_with_reason() -> None:
    result = build_dimension_score(
        dimension="security",
        findings=[],
        status="failed",
        rules=RULES,
        unavailable_reason="SecurityAgent failed (agent_execution_error)",
    )

    assert result.score is None
    assert result.reason is not None
    schema = to_schema_dimension(result)
    assert isinstance(schema, DimensionScore)
    assert schema.score is None
    assert schema.weight == pytest.approx(0.35)


def test_dimension_weight_is_never_renormalized() -> None:
    partial = [
        scoring("security", 91.0),
        scoring("quality", 90.0),
        scoring("performance", 80.0),
        scoring("testing", None),
    ]

    assert compute_overall_score(partial) is not None
    assert to_schema_dimension(partial[3]).weight == pytest.approx(0.20)


# ----------------------------------------------------------------------
# 综合分与 B-2


def test_overall_uses_full_weights_for_four_dimensions() -> None:
    scores = [
        scoring("security", 91.0),
        scoring("quality", 90.0),
        scoring("performance", 80.0),
        scoring("testing", 70.0),
    ]

    assert compute_overall_score(scores) == pytest.approx(84.35)


def test_overall_renormalizes_missing_dimension_only_in_formula() -> None:
    scores = [
        scoring("security", 91.0),
        scoring("quality", 90.0),
        scoring("performance", 80.0),
        scoring("testing", None),
    ]

    overall = compute_overall_score(scores)

    # (0.35×91 + 0.25×90 + 0.20×80) / 0.80 = 87.9375
    assert overall == pytest.approx(87.9375, abs=1e-9)
    assert format_score(overall) == "87.9"
    assert scores[0].weight == pytest.approx(0.35)
    assert scores[3].weight == pytest.approx(0.20)


def test_single_available_dimension_uses_its_own_score() -> None:
    scores = [
        scoring("security", 91.0),
        scoring("quality", None),
        scoring("performance", None),
        scoring("testing", None),
    ]

    assert compute_overall_score(scores) == pytest.approx(91.0)


def test_no_available_dimension_returns_null() -> None:
    scores = [scoring(dimension, None) for dimension in DIMENSION_ORDER]

    assert compute_overall_score(scores) is None


def test_format_score_uses_one_decimal_for_display_only() -> None:
    assert format_score(87.9375) == "87.9"
    assert format_score(79.96) == "80.0"
    assert format_score(100.0) == "100.0"
    assert format_score(None) == "N/A"


def test_b2_exact_value_is_not_rounded_before_verdict() -> None:
    scores = all_scored(79.96)
    overall = compute_overall_score(scores)

    assert format_score(overall) == "80.0"
    assert overall is not None and overall < 80

    decision = decide_verdict(
        scorings=scores,
        findings=[],
        overall_score=overall,
        rules=RULES,
    )

    assert decision.verdict == "COMMENT"


# ----------------------------------------------------------------------
# verdict


def test_verified_critical_forces_request_changes() -> None:
    decision = decide_verdict(
        scorings=all_scored(100.0),
        findings=[make_severity_finding("critical", status="verified")],
        overall_score=100.0,
        rules=RULES,
    )

    assert decision.verdict == "REQUEST_CHANGES"
    assert decision.reasons


def test_verified_high_forces_request_changes() -> None:
    decision = decide_verdict(
        scorings=all_scored(100.0),
        findings=[make_severity_finding("high", status="verified")],
        overall_score=100.0,
        rules=RULES,
    )

    assert decision.verdict == "REQUEST_CHANGES"


def test_exact_score_below_request_changes_threshold() -> None:
    scores = all_scored(59.99)
    overall = compute_overall_score(scores)

    decision = decide_verdict(
        scorings=scores,
        findings=[],
        overall_score=overall,
        rules=RULES,
    )

    assert decision.verdict == "REQUEST_CHANGES"
    assert any("60" in reason for reason in decision.reasons)


def test_approve_requires_all_four_scores_and_threshold() -> None:
    decision = decide_verdict(
        scorings=all_scored(100.0),
        findings=[],
        overall_score=100.0,
        rules=RULES,
    )

    assert decision.verdict == "APPROVE"
    assert decision.reasons


def test_three_scored_dimensions_cannot_approve() -> None:
    scores = [
        scoring("security", 100.0),
        scoring("quality", 100.0),
        scoring("performance", 100.0),
        scoring("testing", None),
    ]

    decision = decide_verdict(
        scorings=scores,
        findings=[],
        overall_score=100.0,
        rules=RULES,
    )

    assert decision.verdict == "COMMENT"
    assert any("testing" in reason for reason in decision.reasons)


def test_partial_report_cannot_approve() -> None:
    decision = decide_verdict(
        scorings=all_scored(100.0),
        findings=[],
        overall_score=100.0,
        rules=RULES,
        report_status="partial",
    )

    assert decision.verdict == "COMMENT"
    assert any("partial" in reason for reason in decision.reasons)


def test_all_null_scores_produce_comment_with_reasons() -> None:
    scores = [scoring(dimension, None) for dimension in DIMENSION_ORDER]

    decision = decide_verdict(
        scorings=scores,
        findings=[],
        overall_score=None,
        rules=RULES,
    )

    assert decision.verdict == "COMMENT"
    assert decision.reasons


def test_unverified_high_blocks_approve_but_not_request_changes() -> None:
    decision = decide_verdict(
        scorings=all_scored(95.0),
        findings=[make_severity_finding("high", status="unverified")],
        overall_score=95.0,
        rules=RULES,
    )

    assert decision.verdict == "COMMENT"
    assert any("unverified" in reason for reason in decision.reasons)


def test_rejected_critical_does_not_block_approve() -> None:
    decision = decide_verdict(
        scorings=all_scored(100.0),
        findings=[make_severity_finding("critical", status="rejected")],
        overall_score=100.0,
        rules=RULES,
    )

    assert decision.verdict == "APPROVE"


def test_every_verdict_has_reasons() -> None:
    cases = [
        ([], [make_severity_finding("critical", status="verified")], 100.0),
        ([], [make_severity_finding("high", status="verified")], 100.0),
        ([], [], 10.0),
        ([], [], 100.0),
        ([], [make_severity_finding("high")], 95.0),
    ]
    for scores, findings, overall in cases:
        resolved = scores or all_scored(100.0)
        decision = decide_verdict(
            scorings=resolved,
            findings=findings,
            overall_score=overall,
            rules=RULES,
        )
        assert decision.reasons
        assert all(reason.strip() for reason in decision.reasons)


# ----------------------------------------------------------------------
# 配置校验


def test_invalid_weights_are_rejected_by_loader(tmp_path: Path) -> None:
    from config.review_rules import (
        DEFAULT_RULES_PATH,
        ReviewRulesError,
        load_review_rules,
    )

    payload = yaml.safe_load(
        DEFAULT_RULES_PATH.read_text(encoding="utf-8")
    )
    payload["weights"] = {
        "security": 0.35,
        "quality": 0.25,
        "performance": 0.20,
        "testing": 0.10,
    }
    invalid = tmp_path / "review_rules.yaml"
    invalid.write_text(
        yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8"
    )

    with pytest.raises(ReviewRulesError):
        load_review_rules(invalid)


def test_float_noise_does_not_change_threshold_decision() -> None:
    # 精确值 80 本身满足阈值；任何舍入都不参与比较。
    scores = all_scored(80.0)
    overall = compute_overall_score(scores)
    assert overall is not None and math.isclose(overall, 80.0, abs_tol=1e-9)
    decision = decide_verdict(
        scorings=scores,
        findings=[],
        overall_score=overall,
        rules=RULES,
    )
    assert decision.verdict == "APPROVE"
