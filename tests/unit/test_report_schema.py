"""阶段 0 最终报告合同单元测试。

覆盖 docs/task_contracts.md 中属于 Schema 层的规则：
RP-01, RP-02, RP-03, RP-04, RP-05, RP-06, RP-07, RP-08, RP-09, RP-10,
RP-11, RP-12, RP-13, RP-14, RP-15, RP-16, RP-17, RP-18, RP-19, RP-20。
"""

from __future__ import annotations

import json
import pathlib
import re
from datetime import timedelta

import pytest
from pydantic import ValidationError

from src.code_review.schemas import ReviewReport
from src.code_review.schemas import TestSummary as TestSummaryModel
from src.code_review.schemas.report import DimensionScore

COMMIT_SHA = "9fceb02d0ae598e95dc970b74767f19372d61af8"
OTHER_COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"

CORE_DIMENSIONS = ("security", "quality", "performance", "testing")
WEIGHTS = {
    "security": 0.35,
    "quality": 0.25,
    "performance": 0.20,
    "testing": 0.20,
}
AGENT_NAMES = {
    "security": "SecurityAgent",
    "quality": "QualityAgent",
    "performance": "PerformanceAgent",
    "testing": "TestingAgent",
}

_DOC_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "docs"
    / "task_contracts.md"
)


def _load_doc_json_blocks():
    text = _DOC_PATH.read_text(encoding="utf-8")
    return [
        json.loads(block)
        for block in re.findall(r"```json\s*\n(.*?)```", text, re.S)
    ]


def _doc_reports():
    return [
        block
        for block in _load_doc_json_blocks()
        if "report_status" in block
    ]


def _doc_test_summary():
    return next(
        block
        for block in _load_doc_json_blocks()
        if "execution_status" in block
    )


def make_dimension(
    score=100.0,
    weight=0.35,
    status="completed",
    reason=None,
    finding_count=0,
):
    return {
        "score": score,
        "weight": weight,
        "finding_count": finding_count,
        "status": status,
        "reason": reason,
    }


def make_dimension_scores():
    return {
        "security": make_dimension(100.0, WEIGHTS["security"]),
        "quality": make_dimension(100.0, WEIGHTS["quality"]),
        "performance": make_dimension(100.0, WEIGHTS["performance"]),
        "testing": make_dimension(100.0, WEIGHTS["testing"]),
    }


def make_agent_result(
    agent_name="SecurityAgent",
    status="completed",
    error_type="timeout",
    **overrides,
):
    data = {
        "task_id": f"task-{agent_name}",
        "review_id": "review-001",
        "agent_name": agent_name,
        "status": status,
        "commit_sha": COMMIT_SHA,
        "summary": "执行完成。",
        "execution_time": 1.0,
    }
    if status in {"partial", "failed"}:
        data["error"] = {
            "error_type": error_type,
            "message": "测试错误",
            "retryable": status == "failed",
        }
    data.update(overrides)
    return data


def make_agent_results():
    return {
        key: make_agent_result(AGENT_NAMES[key])
        for key in CORE_DIMENSIONS
    }


def make_report_finding(**overrides):
    data = {
        "finding_id": "QUA-001",
        "agent_name": "QualityAgent",
        "category": "high_complexity",
        "severity": "medium",
        "title": "函数圈复杂度过高",
        "description": "process_order 的圈复杂度为 18，超过阈值 10。",
        "file_path": "src/service.py",
        "start_line": 85,
        "end_line": 142,
        "evidence": "def process_order(order, user, inventory, coupons):",
        "recommendation": "拆分为多个职责单一的函数。",
        "confidence": 1.0,
        "verification_status": "verified",
    }
    data.update(overrides)
    return data


def make_report(**overrides):
    data = {
        "schema_version": "1.0",
        "review_id": "review-001",
        "trace_id": None,
        "repository": "owner/demo-project",
        "repository_url": "https://github.com/owner/demo-project",
        "branch": "main",
        "commit_sha": COMMIT_SHA,
        "language": "python",
        "report_status": "completed",
        "overall_verdict": "APPROVE",
        "verdict_reasons": [],
        "overall_score": 100.0,
        "dimension_scores": make_dimension_scores(),
        "summary": "未发现需要阻断合并的问题。",
        "agent_results": make_agent_results(),
        "external_agent_results": {},
        "findings": [],
        "rejected_findings": [],
        "test_summary": {
            "execution_status": "executed",
            "passed": 10,
            "failed": 0,
            "skipped": 0,
            "coverage": 90.0,
            "source": "pytest+coverage",
            "reason": None,
        },
        "execution_summary": {
            "total_tasks": 4,
            "completed_tasks": 4,
            "partial_tasks": 0,
            "failed_tasks": 0,
            "cancelled_tasks": 0,
            "duration_seconds": 1.0,
        },
    }
    data.update(overrides)
    return data


def make_partial_report():
    data = make_report()
    data["agent_results"]["security"] = make_agent_result(
        "SecurityAgent", status="partial"
    )
    data["dimension_scores"]["security"] = make_dimension(
        score=None,
        weight=WEIGHTS["security"],
        status="partial",
        reason="部分结果缺失",
    )
    data["overall_score"] = 100.0
    data["report_status"] = "partial"
    data["overall_verdict"] = "COMMENT"
    data["execution_summary"] = {
        "total_tasks": 4,
        "completed_tasks": 3,
        "partial_tasks": 1,
        "failed_tasks": 0,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }
    return data


def make_failed_report():
    data = make_report()
    data["agent_results"]["security"] = make_agent_result(
        "SecurityAgent", status="failed", error_type="timeout"
    )
    data["dimension_scores"]["security"] = make_dimension(
        score=None,
        weight=WEIGHTS["security"],
        status="failed",
        reason="SecurityAgent 执行超时",
    )
    data["overall_score"] = 100.0
    data["report_status"] = "partial"
    data["overall_verdict"] = "COMMENT"
    data["execution_summary"] = {
        "total_tasks": 4,
        "completed_tasks": 3,
        "partial_tasks": 0,
        "failed_tasks": 1,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }
    return data


def make_all_null_report():
    data = make_report()
    failures = {
        "security": ("timeout", "SecurityAgent 执行超时"),
        "quality": ("tool_error", "Ruff 工具执行失败"),
        "performance": ("rate_limit", "模型接口限流，重试后仍失败"),
        "testing": ("cancelled", "任务被取消，未执行"),
    }
    for key, (error_type, reason) in failures.items():
        data["agent_results"][key] = make_agent_result(
            AGENT_NAMES[key], status="failed", error_type=error_type
        )
        data["dimension_scores"][key] = make_dimension(
            score=None,
            weight=WEIGHTS[key],
            status="failed",
            reason=reason,
        )

    data["overall_score"] = None
    data["report_status"] = "partial"
    data["overall_verdict"] = "COMMENT"
    data["verdict_reasons"] = [
        "四个维度均没有可用的审查结果，无法给出综合评分"
    ]
    data["test_summary"] = {
        "execution_status": "not_executed",
        "passed": None,
        "failed": None,
        "skipped": None,
        "coverage": None,
        "source": None,
        "reason": "Testing 任务被取消，未执行测试",
    }
    data["execution_summary"] = {
        "total_tasks": 4,
        "completed_tasks": 0,
        "partial_tasks": 0,
        "failed_tasks": 3,
        "cancelled_tasks": 1,
        "duration_seconds": 1.0,
    }
    return data


def test_report_defaults_and_cost_summary():
    report = ReviewReport.model_validate(make_report())

    assert report.language == "python"
    assert report.trace_id is None
    assert report.verdict_reasons == []
    assert report.findings == []
    assert report.rejected_findings == []
    assert report.external_agent_results == {}
    assert report.cost_summary.total_input_tokens == 0
    assert report.cost_summary.total_output_tokens == 0
    assert report.cost_summary.estimated_cost == 0
    assert report.cost_summary.currency == "CNY"
    assert report.generated_at.tzinfo is not None
    assert report.generated_at.utcoffset() == timedelta(0)


def test_overall_score_is_required():
    data = make_report()
    del data["overall_score"]

    with pytest.raises(ValidationError, match="overall_score"):
        ReviewReport.model_validate(data)


@pytest.mark.parametrize("score", [-0.1, 100.1, 101])
def test_overall_score_bounds_RP_01(score):
    with pytest.raises(ValidationError):
        ReviewReport.model_validate(make_report(overall_score=score))


@pytest.mark.parametrize("verdict", ["MERGE", "approve", "REJECT"])
def test_invalid_verdict_rejected_RP_02(verdict):
    with pytest.raises(ValidationError):
        ReviewReport.model_validate(make_report(overall_verdict=verdict))


def test_execution_task_counts_must_sum_RP_03():
    data = make_report()
    data["execution_summary"]["completed_tasks"] = 3

    with pytest.raises(ValidationError, match="counts must sum"):
        ReviewReport.model_validate(data)


def test_completed_report_requires_all_results_completed_RP_04():
    data = make_report()
    data["agent_results"]["security"] = make_agent_result(
        "SecurityAgent", status="partial"
    )
    data["dimension_scores"]["security"] = make_dimension(
        score=None,
        weight=WEIGHTS["security"],
        status="partial",
        reason="部分结果缺失",
    )
    data["overall_verdict"] = "COMMENT"

    with pytest.raises(ValidationError, match="report_status 'completed'"):
        ReviewReport.model_validate(data)


def test_completed_report_requires_all_dimension_scores_RP_04():
    data = make_report()
    data["dimension_scores"]["testing"]["score"] = None
    data["dimension_scores"]["testing"]["reason"] = "测试未执行"
    data["overall_verdict"] = "COMMENT"

    with pytest.raises(ValidationError, match="report_status 'completed'"):
        ReviewReport.model_validate(data)


def test_completed_report_requires_external_results_completed_RP_04():
    data = make_report()
    data["external_agent_results"] = {
        "architecture": make_agent_result(
            "ExternalArchitectureReviewAgent", status="partial"
        )
    }
    data["execution_summary"] = {
        "total_tasks": 5,
        "completed_tasks": 4,
        "partial_tasks": 1,
        "failed_tasks": 0,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }

    with pytest.raises(ValidationError, match="report_status 'completed'"):
        ReviewReport.model_validate(data)


def test_partial_report_with_partial_result_is_valid_RP_04():
    report = ReviewReport.model_validate(make_partial_report())
    assert report.report_status == "partial"


def test_partial_report_when_everything_completed_rejected_RP_04():
    data = make_report(
        report_status="partial",
        overall_verdict="COMMENT",
    )

    with pytest.raises(ValidationError, match="must be 'completed'"):
        ReviewReport.model_validate(data)


def test_partial_report_must_not_approve_RP_05():
    data = make_report()
    data["agent_results"]["security"] = make_agent_result(
        "SecurityAgent", status="partial"
    )
    data["dimension_scores"]["security"] = make_dimension(
        score=100.0,
        weight=WEIGHTS["security"],
        status="partial",
    )
    data["report_status"] = "partial"
    data["overall_verdict"] = "APPROVE"
    data["overall_score"] = 100.0
    data["execution_summary"] = {
        "total_tasks": 4,
        "completed_tasks": 3,
        "partial_tasks": 1,
        "failed_tasks": 0,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }

    with pytest.raises(ValidationError, match="partial report"):
        ReviewReport.model_validate(data)


def test_verified_critical_requires_request_changes_RP_06():
    critical = make_report_finding(
        finding_id="SEC-001",
        agent_name="SecurityAgent",
        category="sql_injection",
        severity="critical",
        title="Potential SQL Injection",
        description="SQL 查询直接拼接用户输入。",
        evidence="query = f'SELECT * FROM users WHERE id={user_id}'",
        verification_status="verified",
    )

    with pytest.raises(ValidationError, match="verified critical"):
        ReviewReport.model_validate(
            make_report(
                overall_verdict="COMMENT",
                findings=[critical],
            )
        )

    report = ReviewReport.model_validate(
        make_report(
            overall_verdict="REQUEST_CHANGES",
            findings=[critical],
        )
    )
    assert report.overall_verdict == "REQUEST_CHANGES"


def test_rejected_findings_only_in_rejected_list_RP_07():
    rejected = make_report_finding(verification_status="rejected")

    with pytest.raises(ValidationError, match="rejected findings"):
        ReviewReport.model_validate(
            make_report(findings=[rejected])
        )

    with pytest.raises(ValidationError, match="rejected_findings"):
        ReviewReport.model_validate(
            make_report(rejected_findings=[make_report_finding()])
        )

    report = ReviewReport.model_validate(
        make_report(rejected_findings=[rejected])
    )
    assert report.rejected_findings[0].verification_status == "rejected"


def test_duplicate_finding_ids_rejected_RP_08():
    first = make_report_finding(finding_id="QUA-001")
    second = make_report_finding(finding_id="QUA-001", title="重复编号")

    with pytest.raises(ValidationError, match="finding_id"):
        ReviewReport.model_validate(
            make_report(findings=[first, second])
        )


def test_not_executed_summary_rejects_test_numbers_RP_09():
    with pytest.raises(ValidationError, match="not_executed"):
        TestSummaryModel.model_validate(
            {
                "execution_status": "not_executed",
                "passed": 1,
                "reason": "未执行",
            }
        )


def test_not_executed_summary_requires_reason_RP_09():
    with pytest.raises(ValidationError, match="reason"):
        TestSummaryModel.model_validate(
            {"execution_status": "not_executed"}
        )


def test_failed_test_summary_requires_reason():
    with pytest.raises(ValidationError, match="reason"):
        TestSummaryModel.model_validate(
            {"execution_status": "failed"}
        )


def test_coverage_requires_source_RP_10():
    data = make_report()
    data["test_summary"]["source"] = None

    with pytest.raises(ValidationError, match="source"):
        ReviewReport.model_validate(data)


def test_coverage_bounds_RP_10():
    with pytest.raises(ValidationError):
        TestSummaryModel.model_validate(
            {
                "execution_status": "executed",
                "coverage": 100.1,
                "source": "coverage",
            }
        )


@pytest.mark.parametrize("weight", [0, -0.1, 1.1, 2])
def test_dimension_weight_bounds_RP_11(weight):
    data = make_report()
    data["dimension_scores"]["security"]["weight"] = weight

    with pytest.raises(ValidationError):
        ReviewReport.model_validate(data)


def test_dimension_weights_must_sum_to_one_RP_11():
    data = make_report()
    data["dimension_scores"]["testing"]["weight"] = 0.19

    with pytest.raises(ValidationError, match="sum to 1"):
        ReviewReport.model_validate(data)


def test_dimension_weights_accept_tolerance_RP_11():
    data = make_report()
    data["dimension_scores"]["testing"]["weight"] = 0.2000005

    report = ReviewReport.model_validate(data)
    assert report.dimension_scores["testing"].weight == 0.2000005


def test_agent_commit_sha_must_match_report_RP_12():
    data = make_report()
    data["agent_results"]["quality"]["commit_sha"] = OTHER_COMMIT_SHA

    with pytest.raises(ValidationError, match="commit_sha"):
        ReviewReport.model_validate(data)


def test_external_commit_sha_must_match_report_RP_12():
    data = make_report()
    data["external_agent_results"] = {
        "architecture": make_agent_result(
            "ExternalArchitectureReviewAgent",
            commit_sha=OTHER_COMMIT_SHA,
        )
    }
    data["execution_summary"] = {
        "total_tasks": 5,
        "completed_tasks": 5,
        "partial_tasks": 0,
        "failed_tasks": 0,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }

    with pytest.raises(ValidationError, match="commit_sha"):
        ReviewReport.model_validate(data)


def test_report_json_roundtrip_RP_13():
    report = ReviewReport.model_validate(
        make_report(findings=[make_report_finding()])
    )

    restored = ReviewReport.model_validate_json(report.model_dump_json())
    assert restored == report


def test_missing_dimension_score_must_not_approve_RP_14():
    data = make_report()
    data["dimension_scores"]["performance"]["score"] = None
    data["dimension_scores"]["performance"]["reason"] = "性能分析失败"

    with pytest.raises(ValidationError, match="dimension scores"):
        ReviewReport.model_validate(data)

    data["overall_verdict"] = "COMMENT"
    data["report_status"] = "partial"
    data["overall_score"] = 100.0

    report = ReviewReport.model_validate(data)
    assert report.dimension_scores["performance"].score is None


def test_dimension_scores_missing_key_rejected_RP_15():
    data = make_report()
    del data["dimension_scores"]["testing"]

    with pytest.raises(ValidationError, match="dimension_scores"):
        ReviewReport.model_validate(data)


def test_dimension_scores_unknown_key_rejected_RP_15():
    data = make_report()
    data["dimension_scores"]["architecture"] = make_dimension()

    with pytest.raises(ValidationError, match="dimension_scores"):
        ReviewReport.model_validate(data)


def test_empty_dimension_scores_rejected_RP_15():
    data = make_report()
    data["dimension_scores"] = {}

    with pytest.raises(ValidationError, match="dimension_scores"):
        ReviewReport.model_validate(data)


def test_agent_results_keys_must_match_RP_15():
    data = make_report()
    del data["agent_results"]["testing"]

    with pytest.raises(ValidationError, match="agent_results"):
        ReviewReport.model_validate(data)


def test_failed_agent_result_is_retained_RP_15():
    report = ReviewReport.model_validate(make_failed_report())

    assert report.agent_results["security"].status == "failed"
    assert report.dimension_scores["security"].status == "failed"


def test_all_dimensions_null_report_valid_RP_16():
    report = ReviewReport.model_validate(make_all_null_report())

    assert report.overall_score is None
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    assert report.verdict_reasons


def test_all_dimensions_null_requires_null_overall_RP_16():
    data = make_all_null_report()
    data["overall_score"] = 0.0

    with pytest.raises(ValidationError, match="all dimension scores"):
        ReviewReport.model_validate(data)


def test_all_dimensions_null_must_not_approve_RP_16():
    data = make_all_null_report()
    data["overall_verdict"] = "APPROVE"

    with pytest.raises(ValidationError, match="APPROVE"):
        ReviewReport.model_validate(data)


def test_all_dimensions_null_requires_reasons_RP_16():
    data = make_all_null_report()
    data["verdict_reasons"] = []

    with pytest.raises(ValidationError, match="verdict_reasons"):
        ReviewReport.model_validate(data)


def test_partial_dimensions_require_renormalized_overall_RP_16():
    data = make_partial_report()
    data["overall_score"] = 80.0

    with pytest.raises(ValidationError, match="renormalized"):
        ReviewReport.model_validate(data)


def test_partial_dimensions_require_non_null_overall_RP_16():
    data = make_partial_report()
    data["overall_score"] = None

    with pytest.raises(ValidationError, match="must not be null"):
        ReviewReport.model_validate(data)


def test_partial_dimensions_renormalized_average_RP_16():
    data = make_report()
    data["dimension_scores"]["security"]["score"] = 75.0
    data["dimension_scores"]["quality"]["score"] = 95.0
    data["dimension_scores"]["performance"]["score"] = 100.0
    data["dimension_scores"]["testing"] = make_dimension(
        score=None,
        weight=WEIGHTS["testing"],
        status="completed",
        reason="测试结果缺失",
    )
    data["report_status"] = "partial"
    data["overall_verdict"] = "COMMENT"
    data["overall_score"] = 87.5

    report = ReviewReport.model_validate(data)
    assert report.overall_score == 87.5


def test_all_dimensions_scored_reject_null_overall_RP_16():
    data = make_report(overall_score=None)

    with pytest.raises(ValidationError, match="must not be null"):
        ReviewReport.model_validate(data)


def test_execution_summary_total_tasks_mismatch_RP_17():
    data = make_report()
    data["execution_summary"] = {
        "total_tasks": 3,
        "completed_tasks": 3,
        "partial_tasks": 0,
        "failed_tasks": 0,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }

    with pytest.raises(ValidationError, match="total_tasks"):
        ReviewReport.model_validate(data)


def test_execution_summary_completed_mismatch_RP_17():
    data = make_report()
    data["execution_summary"] = {
        "total_tasks": 4,
        "completed_tasks": 3,
        "partial_tasks": 0,
        "failed_tasks": 1,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }

    with pytest.raises(ValidationError, match="completed_tasks"):
        ReviewReport.model_validate(data)


def test_execution_summary_cancelled_rule_RP_17():
    data = make_all_null_report()
    data["execution_summary"]["cancelled_tasks"] = 0
    data["execution_summary"]["failed_tasks"] = 4

    with pytest.raises(ValidationError, match="cancelled_tasks"):
        ReviewReport.model_validate(data)


def test_execution_summary_includes_external_tasks_RP_17():
    data = make_report()
    data["external_agent_results"] = {
        "architecture": make_agent_result(
            "ExternalArchitectureReviewAgent"
        )
    }

    with pytest.raises(ValidationError, match="total_tasks"):
        ReviewReport.model_validate(data)


def test_dimension_null_score_requires_reason_RP_18():
    with pytest.raises(ValidationError, match="reason"):
        DimensionScore.model_validate(
            {
                "score": None,
                "weight": 0.25,
                "finding_count": 0,
                "status": "completed",
            }
        )


def test_failed_dimension_must_not_have_score_RP_18():
    with pytest.raises(ValidationError, match="failed dimension"):
        DimensionScore.model_validate(
            {
                "score": 50.0,
                "weight": 0.25,
                "finding_count": 0,
                "status": "failed",
                "reason": "工具失败",
            }
        )


def test_dimension_null_score_with_reason_valid_RP_18():
    dimension = DimensionScore.model_validate(
        {
            "score": None,
            "weight": 0.25,
            "finding_count": 0,
            "status": "partial",
            "reason": "部分结果缺失",
        }
    )
    assert dimension.score is None


def test_dimension_status_must_match_agent_result_RP_19():
    data = make_report()
    data["dimension_scores"]["security"]["status"] = "partial"

    with pytest.raises(ValidationError, match="status must match"):
        ReviewReport.model_validate(data)


def test_external_result_key_must_not_reuse_core_dimension_RP_20():
    data = make_report()
    data["external_agent_results"] = {
        "security": make_agent_result("SecurityAgent")
    }

    with pytest.raises(ValidationError, match="external_agent_results"):
        ReviewReport.model_validate(data)


def test_external_result_key_must_not_be_empty_RP_20():
    data = make_report()
    data["external_agent_results"] = {
        " ": make_agent_result("ExternalArchitectureReviewAgent")
    }

    with pytest.raises(ValidationError, match="external_agent_results"):
        ReviewReport.model_validate(data)


def test_external_agent_result_valid_RP_20():
    data = make_report()
    data["external_agent_results"] = {
        "architecture": make_agent_result(
            "ExternalArchitectureReviewAgent"
        )
    }
    data["execution_summary"] = {
        "total_tasks": 5,
        "completed_tasks": 5,
        "partial_tasks": 0,
        "failed_tasks": 0,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }

    report = ReviewReport.model_validate(data)
    assert "architecture" in report.external_agent_results
    assert set(report.dimension_scores) == set(CORE_DIMENSIONS)


def test_external_failure_is_retained_RP_20():
    data = make_report()
    data["external_agent_results"] = {
        "architecture": make_agent_result(
            "ExternalArchitectureReviewAgent",
            status="failed",
            error_type="timeout",
        )
    }
    data["report_status"] = "partial"
    data["overall_verdict"] = "COMMENT"
    data["execution_summary"] = {
        "total_tasks": 5,
        "completed_tasks": 4,
        "partial_tasks": 0,
        "failed_tasks": 1,
        "cancelled_tasks": 0,
        "duration_seconds": 1.0,
    }

    report = ReviewReport.model_validate(data)
    assert report.external_agent_results["architecture"].status == "failed"
    assert report.report_status == "partial"


def test_invalid_currency_rejected():
    data = make_report()
    data["cost_summary"] = {"currency": "EUR"}

    with pytest.raises(ValidationError):
        ReviewReport.model_validate(data)


def test_dimension_score_bounds():
    data = make_report()
    data["dimension_scores"]["security"]["score"] = 100.1

    with pytest.raises(ValidationError):
        ReviewReport.model_validate(data)


def test_negative_duration_rejected():
    data = make_report()
    data["execution_summary"]["duration_seconds"] = -1.0

    with pytest.raises(ValidationError):
        ReviewReport.model_validate(data)


def test_summary_length_limit_JS_11():
    data = make_report(summary="x" * 4001)

    with pytest.raises(ValidationError):
        ReviewReport.model_validate(data)


def test_generated_at_must_be_utc():
    data = make_report(generated_at="2026-11-08T10:00:00")

    with pytest.raises(ValidationError):
        ReviewReport.model_validate(data)


@pytest.mark.parametrize(
    "commit_sha",
    ["abc123", "9FCEB02D0AE598E95DC970B74767F19372D61AF8", "z" * 40],
)
def test_report_commit_sha_format(commit_sha):
    data = make_report(commit_sha=commit_sha)

    with pytest.raises(ValidationError, match="commit_sha"):
        ReviewReport.model_validate(data)


def test_trace_id_must_not_be_blank():
    with pytest.raises(ValidationError):
        ReviewReport.model_validate(make_report(trace_id=" "))


def test_document_full_report_example_validates():
    full_report, _ = _doc_reports()
    report = ReviewReport.model_validate(full_report)

    assert report.review_id == "review-001"
    assert report.overall_verdict == "REQUEST_CHANGES"
    assert report.findings[0].verification_status == "verified"
    assert report.execution_summary.total_tasks == 4


def test_document_all_null_report_example_validates():
    _, all_null_report = _doc_reports()
    report = ReviewReport.model_validate(all_null_report)

    assert report.overall_score is None
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    assert report.execution_summary.cancelled_tasks == 1


def test_document_not_executed_test_summary_validates():
    example = _doc_test_summary()
    summary = TestSummaryModel.model_validate(example)

    assert summary.execution_status == "not_executed"
    assert summary.passed is None
    assert summary.reason


def test_all_contract_field_names_are_snake_case_JS_02():
    from src.code_review.schemas import (
        AgentResult,
        AgentTask,
        ErrorInfo,
        Finding,
        ToolEvidence,
    )
    from src.code_review.schemas.report import (
        CostSummary,
        ExecutionSummary,
    )

    models = [
        AgentTask,
        ErrorInfo,
        Finding,
        ToolEvidence,
        AgentResult,
        DimensionScore,
        TestSummaryModel,
        ExecutionSummary,
        CostSummary,
        ReviewReport,
    ]
    for model in models:
        for field_name in model.model_fields:
            assert re.fullmatch(r"[a-z][a-z0-9_]*", field_name), (
                model.__name__,
                field_name,
            )
