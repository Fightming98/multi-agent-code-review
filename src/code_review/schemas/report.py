"""最终审查报告合同：ReviewReport 及其子模型。

对应 docs/task_contracts.md §9。本模块依赖 result.py，不得反向依赖。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .result import AgentResult, Finding
from .task import _require_non_empty, _require_utc, utc_now

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_CORE_DIMENSIONS = frozenset(
    {"security", "quality", "performance", "testing"}
)
_WEIGHT_TOLERANCE = 1e-6
_SCORE_TOLERANCE = 1e-6

Verdict = Literal["APPROVE", "COMMENT", "REQUEST_CHANGES"]
ReportStatus = Literal["completed", "partial"]
DimensionStatus = Literal["completed", "partial", "failed"]


class DimensionScore(BaseModel):
    """单个维度的评分（docs/task_contracts.md §9.2）。"""

    model_config = ConfigDict(extra="forbid")

    score: float | None = Field(default=None, ge=0, le=100)
    weight: float = Field(gt=0, le=1)
    finding_count: int = Field(ge=0)
    status: DimensionStatus
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, "reason")

    @model_validator(mode="after")
    def _check_consistency(self) -> "DimensionScore":
        # RP-18：评分为 null 时必须说明原因；failed 维度不得带评分。
        if self.score is None and self.reason is None:
            raise ValueError("score = null requires a non-empty reason")
        if self.status == "failed" and self.score is not None:
            raise ValueError("failed dimension requires score = null")
        return self


class TestSummary(BaseModel):
    """测试执行摘要（docs/task_contracts.md §9.2）。

    未执行的测试不得伪造通过数或覆盖率。
    """

    # 类名以 Test 开头，标记为非 pytest 测试类，避免收集警告。
    __test__: ClassVar[bool] = False

    model_config = ConfigDict(extra="forbid")

    execution_status: Literal["executed", "not_executed", "failed"]
    passed: int | None = Field(default=None, ge=0)
    failed: int | None = Field(default=None, ge=0)
    skipped: int | None = Field(default=None, ge=0)
    coverage: float | None = Field(default=None, ge=0, le=100)
    source: str | None = None
    reason: str | None = None

    @field_validator("source", "reason")
    @classmethod
    def _optional_non_empty(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, info.field_name)

    @model_validator(mode="after")
    def _check_consistency(self) -> "TestSummary":
        counts = (self.passed, self.failed, self.skipped, self.coverage)

        # RP-09：not_executed 时测试数字必须全部为空，且说明原因。
        if self.execution_status == "not_executed":
            if any(value is not None for value in counts):
                raise ValueError(
                    "not_executed test summary must not contain test counts "
                    "or coverage"
                )
            if self.reason is None:
                raise ValueError(
                    "not_executed test summary requires a reason"
                )

        # §9.2：failed 同样必须说明原因。
        if self.execution_status == "failed" and self.reason is None:
            raise ValueError("failed test summary requires a reason")

        # RP-10：覆盖率必须来自真实工具，因此必须有来源。
        if self.coverage is not None and self.source is None:
            raise ValueError("coverage requires a non-empty source")

        return self


class ExecutionSummary(BaseModel):
    """执行统计（docs/task_contracts.md §9.2）。"""

    model_config = ConfigDict(extra="forbid")

    total_tasks: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    partial_tasks: int = Field(default=0, ge=0)
    failed_tasks: int = Field(ge=0)
    cancelled_tasks: int = Field(default=0, ge=0)
    duration_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def _check_task_counts(self) -> "ExecutionSummary":
        # RP-03：各状态任务数之和必须等于总任务数。
        total = (
            self.completed_tasks
            + self.partial_tasks
            + self.failed_tasks
            + self.cancelled_tasks
        )
        if total != self.total_tasks:
            raise ValueError(
                "completed/partial/failed/cancelled task counts must sum "
                "to total_tasks"
            )
        return self


class CostSummary(BaseModel):
    """成本统计（docs/task_contracts.md §9.2）。"""

    model_config = ConfigDict(extra="forbid")

    total_input_tokens: int = Field(default=0, ge=0)
    total_output_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0, ge=0)
    currency: Literal["CNY", "USD"] = "CNY"


class ReviewReport(BaseModel):
    """最终审查报告（docs/task_contracts.md §9.1）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    review_id: str
    trace_id: str | None = None
    repository: str
    repository_url: str
    branch: str
    commit_sha: str
    language: str = "python"
    report_status: ReportStatus
    overall_verdict: Verdict
    verdict_reasons: list[str] = Field(default_factory=list)
    overall_score: float | None = Field(ge=0, le=100)
    dimension_scores: dict[str, DimensionScore]
    summary: str = Field(max_length=4000)
    agent_results: dict[str, AgentResult]
    external_agent_results: dict[str, AgentResult] = Field(
        default_factory=dict
    )
    findings: list[Finding] = Field(default_factory=list)
    rejected_findings: list[Finding] = Field(default_factory=list)
    test_summary: TestSummary
    execution_summary: ExecutionSummary
    cost_summary: CostSummary = Field(default_factory=CostSummary)
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "schema_version",
        "review_id",
        "repository",
        "repository_url",
        "branch",
        "language",
        "summary",
    )
    @classmethod
    def _required_non_empty(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("trace_id")
    @classmethod
    def _trace_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, "trace_id")

    @field_validator("commit_sha")
    @classmethod
    def _valid_commit_sha(cls, value: str) -> str:
        if not _COMMIT_SHA_RE.match(value):
            raise ValueError(
                "commit_sha must be 40 lowercase hexadecimal characters"
            )
        return value

    @field_validator("generated_at")
    @classmethod
    def _utc_generated_at(cls, value: datetime) -> datetime:
        return _require_utc(value, "generated_at")

    @model_validator(mode="after")
    def _check_consistency(self) -> "ReviewReport":
        self._check_dimension_keys()
        self._check_external_results()
        self._check_weights()
        self._check_dimension_statuses()
        self._check_findings()
        self._check_commit_shas()
        self._check_verdict_rules()
        self._check_report_status()
        self._check_score_semantics()
        self._check_execution_summary()
        return self

    def _check_dimension_keys(self) -> None:
        """RP-15：四个核心维度必须且只能完整出现。"""

        dimension_keys = set(self.dimension_scores)
        agent_keys = set(self.agent_results)

        if dimension_keys != _CORE_DIMENSIONS:
            missing = sorted(_CORE_DIMENSIONS - dimension_keys)
            unknown = sorted(dimension_keys - _CORE_DIMENSIONS)
            raise ValueError(
                "dimension_scores must contain exactly the four core "
                f"dimensions; missing={missing}, unknown={unknown}"
            )
        if agent_keys != _CORE_DIMENSIONS:
            missing = sorted(_CORE_DIMENSIONS - agent_keys)
            unknown = sorted(agent_keys - _CORE_DIMENSIONS)
            raise ValueError(
                "agent_results must contain exactly the four core "
                f"dimensions; missing={missing}, unknown={unknown}"
            )

    def _check_external_results(self) -> None:
        """RP-20：外部结果键不得为空，也不得占用核心维度键。"""

        for key in self.external_agent_results:
            if not key.strip():
                raise ValueError(
                    "external_agent_results keys must not be empty"
                )
            if key in _CORE_DIMENSIONS:
                raise ValueError(
                    "external_agent_results must not reuse core dimension "
                    f"key '{key}'"
                )

    def _check_weights(self) -> None:
        """RP-11：四个配置权重均大于 0，且总和为 1。"""

        total = sum(
            dimension.weight
            for dimension in self.dimension_scores.values()
        )
        if not math.isclose(total, 1.0, abs_tol=_WEIGHT_TOLERANCE):
            raise ValueError(
                "dimension weights must sum to 1 within 1e-6"
            )

    def _check_dimension_statuses(self) -> None:
        """RP-19：维度状态必须与对应 Agent 结果状态一致。"""

        for key in sorted(_CORE_DIMENSIONS):
            dimension_status = self.dimension_scores[key].status
            result_status = self.agent_results[key].status
            if dimension_status != result_status:
                raise ValueError(
                    f"dimension_scores[{key}].status must match "
                    f"agent_results[{key}].status"
                )

    def _check_findings(self) -> None:
        """RP-07、RP-08：核验状态归位，且 finding_id 唯一。"""

        if any(
            finding.verification_status == "rejected"
            for finding in self.findings
        ):
            raise ValueError(
                "findings must not contain rejected findings"
            )
        if any(
            finding.verification_status != "rejected"
            for finding in self.rejected_findings
        ):
            raise ValueError(
                "rejected_findings must all have verification_status rejected"
            )

        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding_id must be unique in findings")

    def _check_commit_shas(self) -> None:
        """RP-12：报告、核心结果与外部结果的 commit_sha 必须一致。"""

        for name, result in self.agent_results.items():
            if result.commit_sha != self.commit_sha:
                raise ValueError(
                    f"agent_results[{name}].commit_sha must match "
                    "ReviewReport.commit_sha"
                )
        for name, result in self.external_agent_results.items():
            if result.commit_sha != self.commit_sha:
                raise ValueError(
                    f"external_agent_results[{name}].commit_sha must match "
                    "ReviewReport.commit_sha"
                )

    def _check_verdict_rules(self) -> None:
        """RP-05、RP-06、RP-14：结论的硬性约束。"""

        has_verified_critical = any(
            finding.verification_status == "verified"
            and finding.severity == "critical"
            for finding in self.findings
        )
        if (
            has_verified_critical
            and self.overall_verdict != "REQUEST_CHANGES"
        ):
            raise ValueError(
                "verified critical finding requires overall_verdict "
                "REQUEST_CHANGES"
            )

        if (
            self.report_status == "partial"
            and self.overall_verdict == "APPROVE"
        ):
            raise ValueError(
                "partial report must not have overall_verdict APPROVE"
            )

        if (
            any(
                dimension.score is None
                for dimension in self.dimension_scores.values()
            )
            and self.overall_verdict == "APPROVE"
        ):
            raise ValueError(
                "overall_verdict APPROVE requires all dimension scores"
            )

    def _check_report_status(self) -> None:
        """RP-04：completed 当且仅当所有维度有分且所有结果 completed。"""

        all_scored = all(
            dimension.score is not None
            for dimension in self.dimension_scores.values()
        )
        all_completed = all(
            result.status == "completed"
            for result in self.agent_results.values()
        ) and all(
            result.status == "completed"
            for result in self.external_agent_results.values()
        )
        should_be_completed = all_scored and all_completed

        if self.report_status == "completed" and not should_be_completed:
            raise ValueError(
                "report_status 'completed' requires all four dimension "
                "scores and all agent results to be completed"
            )
        if self.report_status == "partial" and should_be_completed:
            raise ValueError(
                "report_status must be 'completed' when all dimension "
                "scores and all agent results are completed"
            )

    def _check_score_semantics(self) -> None:
        """RP-16：overall_score 的空值语义与权重重新归一化。"""

        scored_dimensions = [
            dimension
            for dimension in self.dimension_scores.values()
            if dimension.score is not None
        ]

        if not scored_dimensions:
            if self.overall_score is not None:
                raise ValueError(
                    "overall_score must be null when all dimension scores "
                    "are null"
                )
            if self.report_status != "partial":
                raise ValueError(
                    "report_status must be 'partial' when all dimension "
                    "scores are null"
                )
            if self.overall_verdict not in {"COMMENT", "REQUEST_CHANGES"}:
                raise ValueError(
                    "overall_verdict must be COMMENT when all dimension "
                    "scores are null"
                )
            if not any(
                reason.strip() for reason in self.verdict_reasons
            ):
                raise ValueError(
                    "verdict_reasons must explain why no dimension score "
                    "is available"
                )
            return

        if len(scored_dimensions) < len(_CORE_DIMENSIONS):
            if self.overall_score is None:
                raise ValueError(
                    "overall_score must not be null when at least one "
                    "dimension score is available"
                )
            total_weight = sum(
                dimension.weight for dimension in scored_dimensions
            )
            expected = (
                sum(
                    dimension.weight * dimension.score
                    for dimension in scored_dimensions
                )
                / total_weight
            )
            if not math.isclose(
                self.overall_score,
                expected,
                abs_tol=_SCORE_TOLERANCE,
            ):
                raise ValueError(
                    "overall_score must equal the renormalized weighted "
                    f"average of available dimensions ({expected})"
                )
            if self.report_status != "partial":
                raise ValueError(
                    "report_status must be 'partial' when some dimension "
                    "scores are null"
                )
            if self.overall_verdict == "APPROVE":
                raise ValueError(
                    "overall_verdict must not be APPROVE when some "
                    "dimension scores are null"
                )
            return

        if self.overall_score is None:
            raise ValueError(
                "overall_score must not be null when all dimension scores "
                "are available"
            )

    def _check_execution_summary(self) -> None:
        """RP-17：执行统计必须与 Agent 结果集合一致。"""

        results = list(self.agent_results.values()) + list(
            self.external_agent_results.values()
        )
        total_tasks = len(results)
        completed_tasks = sum(
            result.status == "completed" for result in results
        )
        partial_tasks = sum(
            result.status == "partial" for result in results
        )
        cancelled_tasks = sum(
            result.status == "failed"
            and result.error is not None
            and result.error.error_type == "cancelled"
            for result in results
        )
        failed_tasks = (
            sum(result.status == "failed" for result in results)
            - cancelled_tasks
        )

        # cancelled 是 failed 的子集，先比较 cancelled，避免 cancelled
        # 计数错误被 failed 的差值掩盖。
        expected = {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "partial_tasks": partial_tasks,
            "cancelled_tasks": cancelled_tasks,
            "failed_tasks": failed_tasks,
        }
        actual = {
            "total_tasks": self.execution_summary.total_tasks,
            "completed_tasks": self.execution_summary.completed_tasks,
            "partial_tasks": self.execution_summary.partial_tasks,
            "cancelled_tasks": self.execution_summary.cancelled_tasks,
            "failed_tasks": self.execution_summary.failed_tasks,
        }
        for field_name, expected_value in expected.items():
            if actual[field_name] != expected_value:
                raise ValueError(
                    f"execution_summary.{field_name} must be "
                    f"{expected_value}, got {actual[field_name]}"
                )
