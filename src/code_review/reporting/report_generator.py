"""阶段 1 JSON 报告产物生成。

生成顺序固定为：先构建并校验三份结构化产物，再写 JSON，最后仅依据这三份
已校验的数据渲染 ``report.md``。阶段 1 不生成 ``report.json``，也不构造
``ReviewReport``。

产物写入前统一执行两层净化：

- 把本次工作区、用户主目录与系统临时目录替换为占位符；
- 使用 ``redact_sensitive_text`` 替换常见密钥、令牌与凭据。

净化后重新通过 Pydantic 模型校验，确保 JSON 可重新解析且不携带敏感值。
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from code_review.reporting.artifact_models import (
    CoverageArtifact,
    CoverageFileArtifact,
    ErrorSummaryArtifact,
    ExecutionEnvironmentArtifact,
    FixtureArtifact,
    InventorySummaryArtifact,
    LLMAcceptedProposalArtifact,
    LLMAnalysisArtifact,
    LLMExplanationArtifact,
    LLMRejectedProposalArtifact,
    MetadataArtifact,
    RawToolFindingArtifact,
    ReviewStatus,
    StaticAnalysisArtifact,
    StaticAnalysisStatisticsArtifact,
    TestCountsArtifact,
    TestRecordArtifact,
    TestReferenceArtifact,
    TestReferenceEntryArtifact,
    TestReportArtifact,
    ToolRunArtifact,
)
from code_review.services.finding_aggregator import AggregationResult
from code_review.services.llm_analyzer import LLMAnalysisResult
from code_review.services.redaction import redact_sensitive_text
from code_review.tools.base import ToolExecutionResult
from code_review.tools.test_runner import TestExecutionResult, TestExecutionStatus

_SEVERITIES = ("critical", "high", "medium", "low", "info")
_MAX_WARNING_CHARS = 1_000


class ReportGenerationError(RuntimeError):
    """报告构建、序列化或校验失败。"""


class ReportOutputError(ReportGenerationError):
    """输出目录不可用或已存在。"""


@dataclass(frozen=True)
class InventorySummary:
    """服务层传入的报告用仓库扫描摘要（不含工作区绝对路径）。"""

    total_files: int
    python_source_files: int
    python_test_files: int
    filtered_files: int
    excluded_directories: int
    total_size_bytes: int
    scanned_bytes: int
    total_line_count: int
    is_partial: bool
    partial_reason: str | None


@dataclass(frozen=True)
class ReviewArtifactInput:
    """一次审查中生成报告所需的全部真实结果。"""

    review_id: str
    repository_url: str
    repository_name: str
    branch: str
    commit_sha: str | None
    review_status: ReviewStatus
    reviewed_at: datetime
    project_language: str
    discovered_file_count: int
    analyzed_file_count: int
    inventory: InventorySummary | None
    tool_results: Sequence[ToolExecutionResult]
    test_result: TestExecutionResult
    aggregation: AggregationResult
    llm_analysis: LLMAnalysisResult
    review_duration_seconds: float
    warnings: Sequence[str] = ()
    workspace_path: Path | None = None
    source_type: str = "github_repository"
    fixture_manifest_sha256: str | None = None


@dataclass(frozen=True)
class ReportArtifacts:
    """已写入磁盘的四件产物及其模型。"""

    review_id: str
    report_dir: Path
    metadata: MetadataArtifact
    static_analysis: StaticAnalysisArtifact
    test_report: TestReportArtifact
    metadata_path: Path
    static_analysis_path: Path
    test_report_path: Path
    markdown_path: Path


class ReportGenerator:
    """把一次审查结果写为三份 JSON 与一份 Markdown。"""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def generate(
        self,
        source: ReviewArtifactInput,
        output_root: Path,
    ) -> ReportArtifacts:
        generated_at = self._clock()
        metadata = self._build_metadata(source)
        static_analysis = self._build_static_analysis(
            source, generated_at=generated_at
        )
        test_report = self._build_test_report(source, generated_at=generated_at)

        metadata = _sanitize_model(metadata, source.workspace_path)
        static_analysis = _sanitize_model(
            static_analysis, source.workspace_path
        )
        test_report = _sanitize_model(test_report, source.workspace_path)

        try:
            root = Path(output_root).expanduser().resolve()
            report_dir = root / source.review_id
        except OSError as exc:
            raise ReportOutputError("report output directory is invalid") from exc
        if report_dir.exists():
            raise ReportOutputError(
                f"report directory already exists: {source.review_id}"
            )

        try:
            report_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise ReportOutputError(
                "report directory could not be created"
            ) from exc

        metadata_path = report_dir / "metadata.json"
        static_path = report_dir / "static_analysis.json"
        test_path = report_dir / "test_report.json"
        markdown_path = report_dir / "report.md"

        try:
            _write_json(metadata_path, metadata)
            _write_json(static_path, static_analysis)
            _write_json(test_path, test_report)

            # Markdown 必须由三份已校验的结构化数据渲染，不得读取运行时对象。
            from code_review.reporting.markdown_renderer import render_markdown

            markdown = render_markdown(metadata, static_analysis, test_report)
            _write_text(markdown_path, markdown)
        except ReportGenerationError:
            shutil.rmtree(report_dir, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(report_dir, ignore_errors=True)
            raise ReportGenerationError(
                "report artifacts could not be written"
            ) from exc
        except Exception as exc:
            shutil.rmtree(report_dir, ignore_errors=True)
            raise ReportGenerationError(
                "report artifacts could not be generated"
            ) from exc

        return ReportArtifacts(
            review_id=source.review_id,
            report_dir=report_dir,
            metadata=metadata,
            static_analysis=static_analysis,
            test_report=test_report,
            metadata_path=metadata_path,
            static_analysis_path=static_path,
            test_report_path=test_path,
            markdown_path=markdown_path,
        )

    def _build_metadata(self, source: ReviewArtifactInput) -> MetadataArtifact:
        tool_versions: dict[str, str | None] = {
            result.tool_name: result.tool_version
            for result in source.tool_results
        }
        tool_versions["pytest"] = source.test_result.pytest_version
        tool_versions["coverage"] = source.test_result.coverage_version
        if source.llm_analysis.model:
            tool_versions["llm"] = source.llm_analysis.model

        inventory = (
            InventorySummaryArtifact(
                total_files=source.inventory.total_files,
                python_source_files=source.inventory.python_source_files,
                python_test_files=source.inventory.python_test_files,
                filtered_files=source.inventory.filtered_files,
                excluded_directories=source.inventory.excluded_directories,
                total_size_bytes=source.inventory.total_size_bytes,
                scanned_bytes=source.inventory.scanned_bytes,
                total_line_count=source.inventory.total_line_count,
                is_partial=source.inventory.is_partial,
                partial_reason=source.inventory.partial_reason,
            )
            if source.inventory is not None
            else None
        )

        return MetadataArtifact(
            source_type=source.source_type,
            review_id=source.review_id,
            repository_url=source.repository_url,
            repository_name=source.repository_name,
            branch=source.branch,
            commit_sha=source.commit_sha,
            fixture_manifest_sha256=source.fixture_manifest_sha256,
            review_status=source.review_status,
            reviewed_at=source.reviewed_at,
            project_language=source.project_language,
            discovered_file_count=source.discovered_file_count,
            analyzed_file_count=source.analyzed_file_count,
            tool_versions=dict(sorted(tool_versions.items())),
            execution_environment=ExecutionEnvironmentArtifact(
                python_version=(
                    f"{sys.version_info.major}.{sys.version_info.minor}."
                    f"{sys.version_info.micro}"
                ),
                python_implementation=platform.python_implementation(),
                platform_system=platform.system() or "unknown",
                platform_release=platform.release() or "unknown",
                platform_machine=platform.machine() or "unknown",
            ),
            inventory=inventory,
            review_duration_seconds=round(source.review_duration_seconds, 3),
        )

    def _build_static_analysis(
        self,
        source: ReviewArtifactInput,
        *,
        generated_at: datetime,
    ) -> StaticAnalysisArtifact:
        tools: dict[str, ToolRunArtifact] = {}
        for result in source.tool_results:
            if result.tool_name in tools:
                raise ReportGenerationError(
                    f"duplicate tool result: {result.tool_name}"
                )
            tools[result.tool_name] = _tool_run_artifact(result)
        if not tools:
            raise ReportGenerationError("no static analysis tool results available")

        final_findings = list(source.llm_analysis.findings)
        severity_counts = {severity: 0 for severity in _SEVERITIES}
        for finding in final_findings:
            severity_counts[finding.severity] += 1
        category_counts = Counter(finding.category for finding in final_findings)
        semantic_count = sum(
            1 for finding in final_findings if finding.finding_id.startswith("LLM-")
        )

        summary = source.test_result.summary
        warnings = _unique_texts(
            [*source.warnings, *source.aggregation.warnings]
        )
        error_summary = _build_error_summary(source)

        return StaticAnalysisArtifact(
            review_id=source.review_id,
            commit_sha=source.commit_sha,
            generated_at=generated_at,
            tools=tools,
            tests=TestReferenceArtifact(
                pytest=TestReferenceEntryArtifact(
                    execution_status=summary.execution_status,
                    passed=summary.passed,
                    failed=summary.failed,
                    skipped=summary.skipped,
                    coverage=summary.coverage,
                    source=summary.source,
                    reason=summary.reason,
                )
            ),
            findings=final_findings,
            statistics=StaticAnalysisStatisticsArtifact(
                source_finding_count=source.aggregation.stats.source_finding_count,
                mapped_finding_count=source.aggregation.stats.mapped_finding_count,
                deterministic_finding_count=len(source.aggregation.findings),
                final_finding_count=len(final_findings),
                semantic_finding_count=semantic_count,
                duplicate_count=source.aggregation.stats.duplicate_count,
                skipped_finding_count=source.aggregation.stats.skipped_finding_count,
                test_failure_finding_count=(
                    source.aggregation.stats.test_failure_finding_count
                ),
                tool_failure_count=source.aggregation.stats.tool_failure_count,
                partial_tool_count=source.aggregation.stats.partial_tool_count,
                severity_counts=severity_counts,
                category_counts=dict(sorted(category_counts.items())),
            ),
            llm_analysis=_llm_analysis_artifact(source.llm_analysis),
            warnings=warnings,
            error_summary=error_summary,
        )

    def _build_test_report(
        self,
        source: ReviewArtifactInput,
        *,
        generated_at: datetime,
    ) -> TestReportArtifact:
        result = source.test_result
        summary = result.summary
        trusted = result.fixture_name is not None
        executed = result.status is TestExecutionStatus.EXECUTED

        counts = TestCountsArtifact(
            collected=result.collected_tests,
            passed=summary.passed,
            failed=summary.failed,
            skipped=summary.skipped,
            errors=(
                sum(
                    1
                    for record in result.test_records
                    if record.outcome == "error"
                )
                if executed
                else None
            ),
            errors_complete=not result.test_records_truncated,
        )
        coverage = CoverageArtifact(
            percent_covered=summary.coverage,
            files=[
                CoverageFileArtifact(
                    file_path=item.file_path,
                    percent_covered=item.percent_covered,
                    covered_lines=item.covered_lines,
                    num_statements=item.num_statements,
                    missing_lines=list(item.missing_lines),
                )
                for item in result.coverage_files
            ],
            files_truncated=result.coverage_files_truncated,
        )
        fixture = (
            FixtureArtifact(
                name=result.fixture_name,
                version=result.fixture_version,
                manifest_sha256=result.fixture_manifest_sha256,
            )
            if result.fixture_name is not None
            else None
        )

        return TestReportArtifact(
            review_id=source.review_id,
            commit_sha=source.commit_sha,
            generated_at=generated_at,
            execution_status=result.status.value,
            data_source="trusted_fixture" if trusted else "external_repository",
            trusted_fixture=trusted,
            fixture=fixture,
            counts=counts,
            coverage=coverage,
            reason=summary.reason,
            tool_versions={
                "pytest": result.pytest_version,
                "coverage": result.coverage_version,
            },
            started_at=result.started_at,
            finished_at=result.finished_at,
            duration_ms=result.duration_ms,
            test_duration_seconds=result.test_duration_seconds,
            exit_code=result.exit_code,
            coverage_exit_code=result.coverage_exit_code,
            read_only_verified=result.read_only_verified,
            modified_paths=list(result.modified_paths),
            records=[
                TestRecordArtifact(
                    name=record.name,
                    outcome=record.outcome,
                    file_path=record.file_path,
                    line=record.line,
                    duration_seconds=record.duration_seconds,
                    message=record.message,
                )
                for record in result.test_records
            ],
            records_truncated=result.test_records_truncated,
            stdout=result.stdout,
            stderr=result.stderr,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            error=result.error,
        )


def _tool_run_artifact(result: ToolExecutionResult) -> ToolRunArtifact:
    return ToolRunArtifact(
        tool_name=result.tool_name,
        tool_version=result.tool_version,
        execution_status=result.execution_status.value,
        exit_code=result.exit_code,
        started_at=result.started_at,
        finished_at=result.finished_at,
        duration_ms=result.duration_ms,
        analyzed_file_count=result.analyzed_file_count,
        stdout=result.stdout,
        stderr=result.stderr,
        stdout_truncated=result.stdout_truncated,
        stderr_truncated=result.stderr_truncated,
        findings_truncated=result.findings_truncated,
        findings=[
            RawToolFindingArtifact(
                tool_name=finding.tool_name,
                rule_id=finding.rule_id,
                file_path=finding.file_path,
                message=finding.message,
                line=finding.line,
                end_line=finding.end_line,
                column=finding.column,
                severity=finding.severity,
                confidence=finding.confidence,
                metadata=_json_mapping(finding.metadata),
            )
            for finding in result.findings
        ],
        finding_count=len(result.findings),
        error=result.error,
    )


def _llm_analysis_artifact(result: LLMAnalysisResult) -> LLMAnalysisArtifact:
    return LLMAnalysisArtifact(
        status=result.status.value,
        model=result.model,
        usage=dict(result.usage) if result.usage is not None else None,
        duration_ms=result.duration_ms,
        call_count=result.call_count,
        input_chars=result.input_chars,
        proposal_count=result.proposal_count,
        dropped_proposal_count=result.dropped_proposal_count,
        context_finding_count=result.context_finding_count,
        context_snippet_count=result.context_snippet_count,
        input_truncated=result.input_truncated,
        output_truncated=result.output_truncated,
        reason=result.reason,
        accepted=[
            LLMAcceptedProposalArtifact(
                finding_id=item.finding_id,
                proposal_index=item.proposal_index,
                source=item.source,
                related_finding_id=item.related_finding_id,
                merged=item.merged,
            )
            for item in result.accepted
        ],
        rejected=[
            LLMRejectedProposalArtifact(
                proposal_index=item.proposal_index,
                reason=item.reason,
                kind=item.kind,
                category=item.category,
                title=item.title,
                file_path=item.file_path,
                start_line=item.start_line,
            )
            for item in result.rejected
        ],
        explanations=[
            LLMExplanationArtifact(
                related_finding_id=item.related_finding_id,
                proposal_index=item.proposal_index,
                description=item.description,
            )
            for item in result.explanations
        ],
    )


def _build_error_summary(
    source: ReviewArtifactInput,
) -> list[ErrorSummaryArtifact]:
    errors: list[ErrorSummaryArtifact] = []
    for result in source.tool_results:
        if result.error is not None:
            errors.append(
                ErrorSummaryArtifact(
                    source=result.tool_name,
                    error_type=result.error.error_type,
                    message=result.error.message,
                    retryable=result.error.retryable,
                )
            )
    if source.test_result.error is not None:
        errors.append(
            ErrorSummaryArtifact(
                source="pytest",
                error_type=source.test_result.error.error_type,
                message=source.test_result.error.message,
                retryable=source.test_result.error.retryable,
            )
        )
    llm = source.llm_analysis
    if llm.status.value in {"not_configured", "timeout", "failed"} and llm.reason:
        errors.append(
            ErrorSummaryArtifact(
                source="llm",
                error_type=llm.status.value,
                message=llm.reason,
                retryable=llm.status.value == "timeout",
            )
        )
    if (
        source.inventory is not None
        and source.inventory.is_partial
        and source.inventory.partial_reason
    ):
        errors.append(
            ErrorSummaryArtifact(
                source="repository_scan",
                error_type="partial_scan",
                message=source.inventory.partial_reason,
                retryable=False,
            )
        )
    return errors


def _json_mapping(value: Mapping[str, object]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


def _unique_texts(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _truncate(str(value), _MAX_WARNING_CHARS)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]


def _write_json(path: Path, model: Any) -> None:
    text = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    )
    _write_text(path, text + "\n")
    try:
        type(model).model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReportGenerationError(
            f"report JSON failed validation: {path.name}"
        ) from exc


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _sanitize_model(model: Any, workspace_path: Path | None) -> Any:
    payload = model.model_dump(mode="json")
    sanitized = _sanitize_value(payload, workspace_path)
    try:
        return type(model).model_validate(sanitized)
    except Exception as exc:
        raise ReportGenerationError(
            f"sanitized artifact failed validation: {type(model).__name__}"
        ) from exc


def _sanitize_value(value: Any, workspace_path: Path | None) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value, workspace_path)
    if isinstance(value, list):
        return [_sanitize_value(item, workspace_path) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, workspace_path) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_value(item, workspace_path)
            for key, item in value.items()
        }
    return value


def _add_path_replacement(
    replacements: list[tuple[str, str]], raw: str, replacement: str
) -> None:
    """登记路径替换，同时覆盖 JSON 字符串中被转义的 Windows 路径。

    工具 stdout / stderr 往往是嵌套的 JSON 字符串；写入产物时主机路径会
    再次被转义，形成 ``C:\\\\Users\\\\...``。仅替换单反斜杠形式无法清除
    这类路径，因此按层补充转义变体。
    """
    if not raw:
        return
    variants = {raw}
    escaped = raw
    if "\\" in raw:
        for _ in range(3):
            escaped = escaped.replace("\\", "\\\\")
            variants.add(escaped)
    for variant in variants:
        replacements.append((variant, replacement))


def _sanitize_text(text: str, workspace_path: Path | None) -> str:
    replacements: list[tuple[str, str]] = []
    if workspace_path is not None:
        try:
            workspace = Path(workspace_path).expanduser().resolve()
        except OSError:
            workspace = Path(workspace_path)
        _add_path_replacement(replacements, str(workspace), "<workspace>")
        _add_path_replacement(
            replacements, workspace.as_posix(), "<workspace>"
        )
    try:
        _add_path_replacement(replacements, str(Path.home()), "<home>")
        _add_path_replacement(replacements, Path.home().as_posix(), "<home>")
    except (OSError, RuntimeError):
        pass
    try:
        _add_path_replacement(
            replacements, str(tempfile.gettempdir()), "<temp>"
        )
        _add_path_replacement(
            replacements, Path(tempfile.gettempdir()).as_posix(), "<temp>"
        )
    except (OSError, RuntimeError):
        pass

    result = text
    for raw, replacement in sorted(
        replacements, key=lambda item: len(item[0]), reverse=True
    ):
        if not raw:
            continue
        flags = re.IGNORECASE if os.name == "nt" else 0
        result = re.sub(re.escape(raw), replacement, result, flags=flags)
    return redact_sensitive_text(result)
