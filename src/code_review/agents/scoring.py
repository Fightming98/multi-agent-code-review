"""Stage 2 Final Reviewer 评分：维度分、综合分与 verdict。

规则来源 ``docs/workflow.md``、``docs/acceptance.md`` 与 Stage 2.4 提示词
§八～§十一，所有阈值与权重来自 ``config/review_rules.yaml``，本模块不
硬编码：

- 维度分：``max(0, 100 - Σ扣分)``，只统计非 rejected Findings；
- 维度不可用（失败 / 未执行 / 证据不可靠）：``score = None`` 并给出 reason；
- 综合分：只对有效维度计算 ``Σ(wᵢ × Sᵢ) / Σwᵢ``；0 个有效维度为 None；
- ``DimensionScore.weight`` 始终保留配置权重，重归一化只发生在公式内部；
- verdict 阈值比较使用**精确值**，展示层才四舍五入到一位小数（B-2）。

本模块是纯函数集合：不调用 LLM、不访问网络、不写文件。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from code_review.schemas.report import DimensionScore, Verdict
from code_review.schemas.result import Finding
from config.review_rules import ReviewRules

__all__ = [
    "DIMENSION_ORDER",
    "DimensionScoring",
    "VerdictDecision",
    "build_dimension_score",
    "compute_overall_score",
    "decide_verdict",
    "format_score",
    "score_findings",
    "to_schema_dimension",
]

DIMENSION_ORDER: tuple[str, ...] = (
    "security",
    "quality",
    "performance",
    "testing",
)

_SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")


@dataclass(frozen=True)
class DimensionScoring:
    """单个维度的评分结果（内部模型，不是 Schema）。"""

    dimension: str
    score: float | None
    weight: float
    status: Literal["completed", "partial", "failed"]
    finding_count: int
    reason: str | None = None
    deductions: tuple[tuple[str, float], ...] = ()

    @property
    def available(self) -> bool:
        return self.score is not None

    @property
    def total_deduction(self) -> float:
        return sum(points for _, points in self.deductions)


def score_findings(
    findings: Sequence[Finding],
    *,
    rules: ReviewRules,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    """按严重级别扣分并返回维度分；rejected Findings 不参与计算。"""

    deductions: list[tuple[str, float]] = []
    for finding in findings:
        if finding.verification_status == "rejected":
            continue
        if finding.severity not in _SEVERITY_ORDER:
            raise ValueError(
                f"unsupported finding severity: {finding.severity}"
            )
        points = float(rules.deduction_for(finding.severity))
        if points:
            deductions.append((finding.severity, points))
    total = sum(points for _, points in deductions)
    return max(0.0, 100.0 - total), tuple(deductions)


def build_dimension_score(
    *,
    dimension: str,
    findings: Sequence[Finding],
    status: Literal["completed", "partial", "failed"],
    rules: ReviewRules,
    unavailable_reason: str | None = None,
) -> DimensionScoring:
    """构造维度评分。

    ``unavailable_reason`` 非空时维度分为 None（例如 Agent 失败、外部
    测试未执行、工具证据不可靠），并原样作为 ``reason`` 保存。
    """

    if dimension not in DIMENSION_ORDER:
        raise ValueError(f"unknown dimension: {dimension}")
    weight = float(rules.weight_for(dimension))
    counted = [
        finding
        for finding in findings
        if finding.verification_status != "rejected"
    ]
    finding_count = len(counted)
    if unavailable_reason is not None:
        reason = unavailable_reason.strip()
        if not reason:
            raise ValueError("unavailable_reason must be non-empty")
        return DimensionScoring(
            dimension=dimension,
            score=None,
            weight=weight,
            status=status,
            finding_count=finding_count,
            reason=reason,
        )
    score, deductions = score_findings(counted, rules=rules)
    return DimensionScoring(
        dimension=dimension,
        score=score,
        weight=weight,
        status=status,
        finding_count=finding_count,
        deductions=deductions,
    )


def to_schema_dimension(scoring: DimensionScoring) -> DimensionScore:
    """转换为冻结 Schema；权重保持配置值，不写回归一化权重。"""

    return DimensionScore(
        score=scoring.score,
        weight=scoring.weight,
        finding_count=scoring.finding_count,
        status=scoring.status,
        reason=scoring.reason,
    )


def compute_overall_score(
    scorings: Sequence[DimensionScoring],
) -> float | None:
    """只对有效维度计算加权平均；有效权重之和为 0 时返回 None。"""

    available = [item for item in scorings if item.score is not None]
    if not available:
        return None
    total_weight = sum(item.weight for item in available)
    if total_weight <= 0:
        return None
    weighted = sum(
        item.weight * float(item.score) for item in available
    )
    return weighted / total_weight


def format_score(value: float | None) -> str:
    """展示层格式化：None → ``N/A``，其余保留一位小数（B-2）。"""

    if value is None:
        return "N/A"
    return f"{value:.1f}"


@dataclass(frozen=True)
class VerdictDecision:
    verdict: Verdict
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.reasons or not any(
            reason.strip() for reason in self.reasons
        ):
            raise ValueError("verdict_reasons must not be empty")


def _verified(findings: Sequence[Finding], severity: str) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.verification_status == "verified"
        and finding.severity == severity
    ]


def _blocking(findings: Sequence[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.verification_status != "rejected"
        and finding.severity in {"critical", "high"}
    ]


def decide_verdict(
    *,
    scorings: Sequence[DimensionScoring],
    findings: Sequence[Finding],
    overall_score: float | None,
    rules: ReviewRules,
    report_status: str | None = None,
) -> VerdictDecision:
    """按 Stage 2.4 §十一 的优先级决定 verdict；比较使用精确分值。

    ``report_status="partial"`` 时不得 APPROVE：冻结 Schema 明确禁止
    partial 报告使用 APPROVE，即使四个维度都已有分数。
    """

    verified_critical = _verified(findings, "critical")
    if verified_critical:
        return VerdictDecision(
            verdict="REQUEST_CHANGES",
            reasons=tuple(
                f"verified critical finding {finding.finding_id} "
                f"({finding.category}) in {finding.agent_name}"
                for finding in verified_critical
            ),
        )

    verified_high = _verified(findings, "high")
    if verified_high:
        return VerdictDecision(
            verdict="REQUEST_CHANGES",
            reasons=tuple(
                f"verified high finding {finding.finding_id} "
                f"({finding.category}) in {finding.agent_name}"
                for finding in verified_high
            ),
        )

    threshold = float(rules.request_changes_below)
    if overall_score is not None and overall_score < threshold:
        return VerdictDecision(
            verdict="REQUEST_CHANGES",
            reasons=(
                (
                    "overall score "
                    f"{format_score(overall_score)} is below the "
                    f"request-changes threshold {threshold:g}"
                ),
                f"exact overall score: {overall_score!r}",
            ),
        )

    scored = [item for item in scorings if item.score is not None]
    missing = [
        item.dimension for item in scorings if item.score is None
    ]
    blocking = _blocking(findings)
    approve_min = float(rules.approve_min_score)

    if (
        len(scored) == len(DIMENSION_ORDER)
        and not blocking
        and overall_score is not None
        and overall_score >= approve_min
        and report_status != "partial"
    ):
        return VerdictDecision(
            verdict="APPROVE",
            reasons=(
                (
                    "all four dimensions are scored, no non-rejected "
                    "critical/high finding remains, and the exact overall "
                    f"score {format_score(overall_score)} is not below the "
                    f"approve threshold {approve_min:g}"
                ),
            ),
        )

    reasons: list[str] = []
    if not scored:
        reasons.append(
            "no dimension score is available; no verified critical "
            "finding was found"
        )
    else:
        if missing:
            reasons.append(
                "dimension scores are unavailable for: "
                + ", ".join(missing)
            )
        if blocking:
            reasons.append(
                "critical/high findings are not fully verified: "
                + ", ".join(
                    f"{finding.finding_id} ({finding.severity}, "
                    f"{finding.verification_status})"
                    for finding in blocking
                )
            )
        if overall_score is None:
            reasons.append(
                "overall score is unavailable because no dimension could "
                "be scored"
            )
        elif (
            overall_score < approve_min
            and overall_score >= threshold
        ):
            reasons.append(
                "exact overall score "
                f"{format_score(overall_score)} is below the approve "
                f"threshold {approve_min:g}"
            )
        if report_status == "partial":
            reasons.append(
                "report status is partial because at least one agent "
                "result did not complete; APPROVE is not allowed"
            )
    return VerdictDecision(verdict="COMMENT", reasons=tuple(reasons))
