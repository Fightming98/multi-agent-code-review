"""Stage 1.6 测试辅助：构造审查结果、产物输入与可控替身。

本模块只提供测试数据与 Fake，不访问网络、不调用真实 LLM，也不修改项目
自维护的可信 Fixture。所有时间统一使用带时区的 UTC 时间。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.code_review.reporting.report_generator import (
    InventorySummary,
    ReviewArtifactInput,
)
from src.code_review.schemas.report import TestSummary
from src.code_review.schemas.result import Finding, ToolEvidence
from src.code_review.schemas.task import ErrorInfo
from src.code_review.services.finding_aggregator import (
    AggregationResult,
    AggregationStats,
    ToolAggregateSummary,
)
from src.code_review.services.llm_analyzer import (
    LLMAnalysisResult,
    LLMAnalysisStatus,
)
from src.code_review.tools.base import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolFinding,
)
from src.code_review.tools.test_runner import (
    CoverageFileReport,
    TestExecutionResult,
    TestExecutionStatus,
    TestRecord,
)

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
COMMIT_SHA = "a" * 40
OTHER_COMMIT_SHA = "b" * 40
FIXTURE_MANIFEST_SHA = "c" * 64
STAGE1_AGENT_NAME = "Stage1Analyzer"


def make_tool_finding(
    *,
    tool_name: str = "ruff",
    rule_id: str = "F401",
    file_path: str = "pkg/app.py",
    message: str = "unused import",
    line: int = 1,
) -> ToolFinding:
    """构造工具层原始发现。"""

    return ToolFinding(
        tool_name=tool_name,
        rule_id=rule_id,
        file_path=file_path,
        message=message,
        line=line,
        end_line=line,
        column=1,
        severity="low",
        confidence="high",
    )


def make_tool_result(
    tool_name: str = "ruff",
    *,
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCESS,
    findings: tuple[ToolFinding, ...] = (),
    tool_version: str | None = "0.9.0",
    exit_code: int | None = 0,
    error: ErrorInfo | None = None,
    stdout: str = "",
    stderr: str = "",
    analyzed_file_count: int = 1,
    truncated: bool = False,
) -> ToolExecutionResult:
    """构造工具执行结果。"""

    return ToolExecutionResult(
        tool_name=tool_name,
        tool_version=tool_version,
        execution_status=status,
        exit_code=exit_code,
        started_at=NOW,
        finished_at=NOW,
        duration_ms=12,
        stdout=stdout,
        stderr=stderr,
        findings=findings,
        error=error,
        analyzed_file_count=analyzed_file_count,
        stdout_truncated=truncated,
    )


def make_finding(
    finding_id: str = "RUFF-0001",
    *,
    category: str = "style_violation",
    severity: str = "low",
    title: str = "Unused import",
    description: str = "The imported name is never used.",
    file_path: str | None = "pkg/app.py",
    start_line: int | None = 1,
    end_line: int | None = None,
    evidence: str = "import os",
    tool_evidence: list[ToolEvidence] | None = None,
    recommendation: str = "Remove the unused import.",
    confidence: float = 0.9,
    agent_name: str = STAGE1_AGENT_NAME,
    verification_status: str = "unverified",
    merged_from: list[str] | None = None,
) -> Finding:
    """构造合同 Finding；默认带真实风格的 Ruff 工具证据。"""

    if tool_evidence is None:
        tool_evidence = [
            ToolEvidence(
                tool_name="ruff",
                rule_id="F401",
                tool_version="0.9.0",
                raw_output_ref="static_analysis.json#/tools/ruff/findings/0",
            )
        ]
    return Finding(
        finding_id=finding_id,
        agent_name=agent_name,
        category=category,
        severity=severity,
        title=title,
        description=description,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        evidence=evidence,
        tool_evidence=tool_evidence,
        recommendation=recommendation,
        confidence=confidence,
        verification_status=verification_status,
        merged_from=merged_from or [],
    )


def make_test_result(
    status: TestExecutionStatus = TestExecutionStatus.NOT_EXECUTED,
    *,
    trusted_fixture: bool = False,
    reason: str | None = None,
    passed: int | None = None,
    failed: int | None = None,
    skipped: int | None = None,
    coverage: float | None = None,
    collected: int | None = None,
    records: tuple[TestRecord, ...] = (),
    coverage_files: tuple[CoverageFileReport, ...] = (),
    read_only_verified: bool | None = None,
    error: ErrorInfo | None = None,
) -> TestExecutionResult:
    """构造测试执行结果，并保持 not_executed 的 null 语义。"""

    if status is TestExecutionStatus.NOT_EXECUTED:
        summary = TestSummary(
            execution_status="not_executed",
            passed=None,
            failed=None,
            skipped=None,
            coverage=None,
            source="pytest",
            reason=reason or "external repository tests are not executed",
        )
        collected = None
        records = ()
        coverage_files = ()
    elif status is TestExecutionStatus.EXECUTED:
        summary = TestSummary(
            execution_status="executed",
            passed=3 if passed is None else passed,
            failed=0 if failed is None else failed,
            skipped=1 if skipped is None else skipped,
            coverage=87.5 if coverage is None else coverage,
            source="pytest",
        )
        collected = 4 if collected is None else collected
    else:
        summary = TestSummary(
            execution_status="failed",
            passed=None,
            failed=None,
            skipped=None,
            coverage=None,
            source="pytest",
            reason=reason or "test execution failed",
        )
        collected = None

    return TestExecutionResult(
        status=status,
        summary=summary,
        fixture_name="trusted_fixture_v1" if trusted_fixture else None,
        fixture_version="1.0.0" if trusted_fixture else None,
        fixture_manifest_sha256=(
            FIXTURE_MANIFEST_SHA if trusted_fixture else None
        ),
        collected_tests=collected,
        test_records=records,
        test_records_truncated=False,
        coverage_files=coverage_files,
        coverage_files_truncated=False,
        read_only_verified=read_only_verified,
        modified_paths=(),
        pytest_version="8.0.0",
        coverage_version="7.4.0",
        exit_code=0 if status is TestExecutionStatus.EXECUTED else None,
        coverage_exit_code=(
            0 if status is TestExecutionStatus.EXECUTED else None
        ),
        test_duration_seconds=(
            1.5 if status is TestExecutionStatus.EXECUTED else None
        ),
        started_at=NOW,
        finished_at=NOW,
        duration_ms=1500,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        error=error,
    )


def make_aggregation(
    tool_results: tuple[ToolExecutionResult, ...],
    findings: tuple[Finding, ...] = (),
    *,
    test_result: TestExecutionResult | None = None,
    warnings: tuple[str, ...] = (),
    stats: AggregationStats | None = None,
) -> AggregationResult:
    """构造确定性聚合结果。"""

    if stats is None:
        stats = AggregationStats(
            source_finding_count=sum(
                len(result.findings) for result in tool_results
            ),
            mapped_finding_count=len(findings),
            final_finding_count=len(findings),
            duplicate_count=0,
            skipped_finding_count=0,
            test_failure_finding_count=0,
            tool_failure_count=sum(
                1
                for result in tool_results
                if result.execution_status
                not in {
                    ToolExecutionStatus.SUCCESS,
                    ToolExecutionStatus.FINDINGS,
                }
            ),
            partial_tool_count=sum(
                1
                for result in tool_results
                if result.execution_status is ToolExecutionStatus.PARTIAL
            ),
        )
    summaries = tuple(
        ToolAggregateSummary(
            tool_name=result.tool_name,
            tool_version=result.tool_version,
            execution_status=result.execution_status,
            finding_count=len(result.findings),
            analyzed_file_count=result.analyzed_file_count,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
            error=result.error,
        )
        for result in tool_results
    )
    return AggregationResult(
        tool_results=tool_results,
        test_result=test_result,
        tool_summaries=summaries,
        findings=findings,
        stats=stats,
        raw_output_prefix="static_analysis.json",
        warnings=warnings,
    )


def make_llm_result(
    findings: tuple[Finding, ...] = (),
    *,
    status: LLMAnalysisStatus = LLMAnalysisStatus.COMPLETED,
    reason: str | None = None,
    model: str | None = "fake-model",
) -> LLMAnalysisResult:
    """构造 LLM 辅助分析结果。"""

    if status is not LLMAnalysisStatus.COMPLETED and reason is None:
        reason = f"LLM analysis status is {status.value}"
    return LLMAnalysisResult(
        status=status,
        findings=findings,
        accepted=(),
        rejected=(),
        explanations=(),
        model=model,
        usage={"prompt_tokens": 10, "completion_tokens": 5} if model else None,
        duration_ms=20,
        call_count=1,
        input_chars=100,
        proposal_count=0,
        context_finding_count=len(findings),
        context_snippet_count=0,
        reason=reason,
    )


def make_inventory_summary(
    *,
    total_files: int = 3,
    python_source_files: int = 2,
    python_test_files: int = 1,
    is_partial: bool = False,
    partial_reason: str | None = None,
) -> InventorySummary:
    """构造报告用扫描摘要。"""

    return InventorySummary(
        total_files=total_files,
        python_source_files=python_source_files,
        python_test_files=python_test_files,
        filtered_files=0,
        excluded_directories=0,
        total_size_bytes=300,
        scanned_bytes=300,
        total_line_count=30,
        is_partial=is_partial,
        partial_reason=partial_reason,
    )


def make_review_input(
    *,
    review_id: str = "stage1-test-review",
    workspace_path: Path | None = None,
    tool_results: tuple[ToolExecutionResult, ...] | None = None,
    test_result: TestExecutionResult | None = None,
    aggregation: AggregationResult | None = None,
    llm_analysis: LLMAnalysisResult | None = None,
    source_type: str = "github_repository",
    repository_url: str = "https://github.com/example/project",
    repository_name: str = "example/project",
    branch: str = "main",
    commit_sha: str | None = COMMIT_SHA,
    fixture_manifest_sha256: str | None = None,
    review_status: str = "completed",
    reviewed_at: datetime = NOW,
    inventory: InventorySummary | None = None,
    warnings: tuple[str, ...] = (),
) -> ReviewArtifactInput:
    """构造报告生成输入；三份结构化产物由真实生成器构建。"""

    if tool_results is None:
        tool_results = (
            make_tool_result(
                "ruff",
                findings=(make_tool_finding(),),
            ),
            make_tool_result("bandit"),
            make_tool_result("radon"),
        )
    if test_result is None:
        test_result = make_test_result()
    if aggregation is None:
        aggregation = make_aggregation(
            tool_results,
            (make_finding(),),
            test_result=test_result,
        )
    if llm_analysis is None:
        llm_analysis = make_llm_result(aggregation.findings)
    if inventory is None:
        inventory = make_inventory_summary()

    return ReviewArtifactInput(
        review_id=review_id,
        repository_url=repository_url,
        repository_name=repository_name,
        branch=branch,
        commit_sha=commit_sha,
        review_status=review_status,  # type: ignore[arg-type]
        reviewed_at=reviewed_at,
        project_language="python",
        discovered_file_count=inventory.total_files,
        analyzed_file_count=inventory.python_source_files,
        inventory=inventory,
        tool_results=tool_results,
        test_result=test_result,
        aggregation=aggregation,
        llm_analysis=llm_analysis,
        review_duration_seconds=1.25,
        warnings=warnings,
        workspace_path=workspace_path,
        source_type=source_type,
        fixture_manifest_sha256=fixture_manifest_sha256,
    )


@dataclass
class FakeRepositoryManager:
    """返回固定快照并记录清理调用的仓库管理器替身。"""

    snapshot: object
    clone_error: Exception | None = None
    clone_calls: list[dict[str, object]] = field(default_factory=list)
    cleanup_calls: list[object] = field(default_factory=list)
    cleanup_all_calls: int = 0

    def clone(
        self,
        repository_url: str,
        *,
        branch: str | None = None,
        commit_sha: str | None = None,
    ) -> object:
        self.clone_calls.append(
            {
                "repository_url": repository_url,
                "branch": branch,
                "commit_sha": commit_sha,
            }
        )
        if self.clone_error is not None:
            raise self.clone_error
        return self.snapshot

    def cleanup(self, snapshot: object) -> None:
        self.cleanup_calls.append(snapshot)

    def cleanup_all(self) -> None:
        self.cleanup_all_calls += 1


@dataclass
class FakeTool:
    """记录调用参数的静态分析工具替身。"""

    tool_name: str
    result: ToolExecutionResult | None = None
    error: Exception | None = None
    calls: list[tuple[Path, list[str]]] = field(default_factory=list)

    def run(self, workspace_path: Path, files: list[str]) -> ToolExecutionResult:
        self.calls.append((workspace_path, list(files)))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@dataclass
class FakeTestRunner:
    """记录 trusted_fixture 参数并返回固定结果的测试执行器替身。"""

    result: TestExecutionResult | None = None
    error: Exception | None = None
    calls: list[str | None] = field(default_factory=list)

    def execute(self, *, trusted_fixture: str | None = None) -> TestExecutionResult:
        self.calls.append(trusted_fixture)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


@dataclass
class FakeLLMAnalyzer:
    """返回固定 LLM 结果并记录调用参数的替身。"""

    result: LLMAnalysisResult | None = None
    error: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    def analyze(
        self,
        aggregation: AggregationResult,
        *,
        workspace_path: Path,
        allowed_files: list[str],
    ) -> LLMAnalysisResult:
        self.calls.append(
            {
                "aggregation": aggregation,
                "workspace_path": workspace_path,
                "allowed_files": list(allowed_files),
            }
        )
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result
