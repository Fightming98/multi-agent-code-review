"""阶段 1 统一审查业务入口。

``ReviewService`` 是 CLI、FastAPI 与后续 Worker 的唯一业务入口。阶段 1 的
执行顺序固定为：

参数校验 → 仓库获取与 Commit 固定 → 文件扫描 → 静态分析 → 测试执行决策
→ 结果聚合 → LLM 辅助分析 → 报告生成 → 资源清理。

单个工具、测试或 LLM 的失败会被隔离为对应的失败结果，并保留其他确定性
结果；仓库获取、扫描与报告生成失败属于本次审查不可继续的阶段错误。所有
错误信息都经过安全收敛，不包含 API Key、仓库内容、宿主机绝对路径或本地
工作区路径。
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self
from uuid import uuid4

import structlog

from code_review.reporting.artifact_models import ReviewStatus
from code_review.reporting.report_generator import (
    InventorySummary,
    ReportArtifacts,
    ReportGenerationError,
    ReportGenerator,
    ReviewArtifactInput,
)
from code_review.schemas.report import TestSummary
from code_review.schemas.task import ErrorInfo
from code_review.tools.bandit_tool import BanditTool
from code_review.tools.base import (
    AnalysisTool,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from code_review.tools.radon_tool import RadonTool
from code_review.tools.repository_inspector import (
    RepositoryInspectionError,
    RepositoryInspector,
    RepositoryInventory,
)
from code_review.tools.repository_manager import (
    CloneError,
    CommitResolutionError,
    GitNotFoundError,
    GitTimeoutError,
    RepositoryError,
    RepositoryManager,
    RepositorySnapshot,
    ResourceLimitExceededError,
)
from code_review.tools.ruff_tool import RuffTool
from code_review.tools.test_runner import (
    TestExecutionResult,
    TestExecutionStatus,
    TestRunner,
)
from code_review.tools.trusted_fixture import (
    APPROVED_TRUSTED_FIXTURE_NAMES,
    DEFAULT_TRUSTED_FIXTURE_ROOT,
    TrustedFixtureError,
    verify_trusted_fixture,
)
from code_review.tools.url_validator import (
    GitHubRepository,
    URLValidationError,
    normalize_commit_sha,
    validate_branch_name,
    validate_github_url,
)
from config.settings import Settings

from .finding_aggregator import AggregationResult, aggregate_review_results
from .llm_analyzer import (
    LLMAnalysisResult,
    LLMAnalysisStatus,
    LLMAnalyzer,
)

_LOGGER = structlog.get_logger(__name__)
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_WARNING_CHARS = 500


class ReviewServiceError(RuntimeError):
    """本次审查无法继续；``message`` 必须可以安全展示给调用方。"""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        error_type: str,
        retryable: bool = False,
        review_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.error_type = error_type
        self.retryable = retryable
        self.review_id = review_id


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    """CLI / API 提交给 ReviewService 的审查请求。"""

    repository_url: str
    branch: str | None = None
    commit_sha: str | None = None
    output_root: Path | str | None = None


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    """一次成功完成的审查（状态可能为 completed 或 partial）。"""

    review_id: str
    review_status: ReviewStatus
    repository_name: str
    commit_sha: str | None
    report_dir: Path
    metadata_path: Path
    static_analysis_path: Path
    test_report_path: Path
    markdown_path: Path
    finding_count: int
    severity_counts: dict[str, int]
    test_status: str
    llm_status: str
    warnings: tuple[str, ...]
    duration_seconds: float

    @property
    def artifact_paths(self) -> tuple[Path, Path, Path, Path]:
        return (
            self.metadata_path,
            self.static_analysis_path,
            self.test_report_path,
            self.markdown_path,
        )


@dataclass(frozen=True)
class _WorkspaceInfo:
    """一次审查实际使用的仓库工作区及其来源元数据。"""

    path: Path
    repository_url: str
    repository_name: str
    branch: str
    commit_sha: str | None
    source_type: str
    oversized_files: tuple[str, ...] = ()
    fixture_name: str | None = None
    fixture_version: str | None = None
    fixture_manifest_sha256: str | None = None

    @property
    def trusted_fixture(self) -> bool:
        return self.source_type == "trusted_fixture"


class ReviewService:
    """串联仓库获取、确定性分析、LLM 辅助分析与报告生成。"""

    def __init__(
        self,
        settings: Settings,
        *,
        repository_manager: RepositoryManager | None = None,
        inspector: RepositoryInspector | None = None,
        tools: Sequence[AnalysisTool] | None = None,
        test_runner: TestRunner | None = None,
        llm_analyzer: LLMAnalyzer | None = None,
        report_generator: ReportGenerator | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[datetime], str] | None = None,
        allow_trusted_fixture_review: bool = False,
    ) -> None:
        self.settings = settings
        self._owns_repository_manager = repository_manager is None
        self._repository_manager = repository_manager or RepositoryManager(settings)
        self._inspector = inspector or RepositoryInspector(settings)
        self._tools = tuple(
            tools
            if tools is not None
            else (
                RuffTool(settings),
                BanditTool(settings),
                RadonTool(settings),
            )
        )
        if not self._tools:
            raise ValueError("at least one analysis tool is required")
        names = [tool.tool_name for tool in self._tools]
        if len(set(names)) != len(names):
            raise ValueError("analysis tool names must be unique")
        self._test_runner = test_runner or TestRunner(settings)
        self._owns_llm_analyzer = llm_analyzer is None
        self._llm_analyzer = llm_analyzer or LLMAnalyzer.from_settings(settings)
        self._report_generator = report_generator or ReportGenerator()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or self._default_review_id
        self._allow_trusted_fixture_review = allow_trusted_fixture_review

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    def review(self, request: ReviewRequest) -> ReviewOutcome:
        """审查一个 GitHub 仓库；外部仓库的测试永远不会被执行。"""

        repository = self._validate_request(request)
        started_at = self._now()
        review_id = self._new_review_id(started_at)
        output_root = self._resolve_output_root(request.output_root)
        _LOGGER.info(
            "review_started",
            review_id=review_id,
            source_type="github_repository",
            branch=request.branch,
            has_commit=request.commit_sha is not None,
        )

        snapshot: RepositorySnapshot | None = None
        try:
            snapshot = self._acquire_repository(repository, request, review_id)
            workspace = _WorkspaceInfo(
                path=snapshot.workspace_path,
                repository_url=snapshot.repository_url,
                repository_name=snapshot.full_name,
                branch=snapshot.branch,
                commit_sha=snapshot.commit_sha,
                source_type="github_repository",
                oversized_files=tuple(snapshot.oversized_files),
            )
            self._ensure_output_outside_workspace(output_root, workspace.path, review_id)
            outcome = self._run_review(
                workspace,
                review_id=review_id,
                started_at=started_at,
                output_root=output_root,
            )
            _LOGGER.info(
                "review_completed",
                review_id=review_id,
                review_status=outcome.review_status,
                finding_count=outcome.finding_count,
                test_status=outcome.test_status,
                llm_status=outcome.llm_status,
                duration_seconds=outcome.duration_seconds,
            )
            return outcome
        except ReviewServiceError as exc:
            _LOGGER.error(
                "review_failed",
                review_id=review_id,
                stage=exc.stage,
                error_type=exc.error_type,
                retryable=exc.retryable,
            )
            if exc.review_id is None:
                exc.review_id = review_id
            raise
        except Exception as exc:
            _LOGGER.error(
                "review_failed",
                review_id=review_id,
                stage="internal",
                error_type=type(exc).__name__,
            )
            raise ReviewServiceError(
                "review failed unexpectedly",
                stage="internal",
                error_type=type(exc).__name__,
                review_id=review_id,
            ) from exc
        finally:
            if snapshot is not None:
                self._cleanup_snapshot(snapshot)

    def review_trusted_fixture(
        self,
        *,
        output_root: Path | str | None = None,
    ) -> ReviewOutcome:
        """审查项目自维护的可信 Fixture。

        该入口只用于阶段 1 的受控集成测试与验收，不通过 CLI / FastAPI 暴露。
        调用方必须在构造服务时显式开启 ``allow_trusted_fixture_review``。
        """

        if not self._allow_trusted_fixture_review:
            raise ReviewServiceError(
                "trusted fixture review is not enabled",
                stage="validation",
                error_type="trusted_fixture_disabled",
            )
        started_at = self._now()
        review_id = self._new_review_id(started_at)
        resolved_output_root = self._resolve_output_root(output_root)
        try:
            verified = verify_trusted_fixture(
                expected_name=self.settings.trusted_fixture_name
            )
        except TrustedFixtureError as exc:
            raise ReviewServiceError(
                "trusted fixture verification failed",
                stage="fixture",
                error_type="fixture_integrity_failure",
                review_id=review_id,
            ) from exc

        if verified.name not in APPROVED_TRUSTED_FIXTURE_NAMES:
            raise ReviewServiceError(
                "trusted fixture is not approved",
                stage="fixture",
                error_type="fixture_not_approved",
                review_id=review_id,
            )

        # 生产路径只允许默认 Fixture；即使构造参数被误用也不执行其他目录。
        expected_root = DEFAULT_TRUSTED_FIXTURE_ROOT.resolve()
        if verified.root.resolve() != expected_root:
            raise ReviewServiceError(
                "trusted fixture root is not the approved fixture",
                stage="fixture",
                error_type="fixture_root_not_approved",
                review_id=review_id,
            )

        workspace = _WorkspaceInfo(
            path=verified.root,
            repository_url=f"fixture://{verified.name}",
            repository_name=verified.name,
            branch="fixture",
            commit_sha=None,
            source_type="trusted_fixture",
            fixture_name=verified.name,
            fixture_version=verified.version,
            fixture_manifest_sha256=verified.manifest_sha256,
        )
        self._ensure_output_outside_workspace(
            resolved_output_root, workspace.path, review_id
        )
        _LOGGER.info(
            "review_started",
            review_id=review_id,
            source_type="trusted_fixture",
            branch="fixture",
            has_commit=False,
        )
        try:
            outcome = self._run_review(
                workspace,
                review_id=review_id,
                started_at=started_at,
                output_root=resolved_output_root,
            )
            _LOGGER.info(
                "review_completed",
                review_id=review_id,
                review_status=outcome.review_status,
                finding_count=outcome.finding_count,
                test_status=outcome.test_status,
                llm_status=outcome.llm_status,
                duration_seconds=outcome.duration_seconds,
            )
            return outcome
        except ReviewServiceError as exc:
            _LOGGER.error(
                "review_failed",
                review_id=review_id,
                stage=exc.stage,
                error_type=exc.error_type,
                retryable=exc.retryable,
            )
            if exc.review_id is None:
                exc.review_id = review_id
            raise
        except Exception as exc:
            _LOGGER.error(
                "review_failed",
                review_id=review_id,
                stage="internal",
                error_type=type(exc).__name__,
            )
            raise ReviewServiceError(
                "review failed unexpectedly",
                stage="internal",
                error_type=type(exc).__name__,
                review_id=review_id,
            ) from exc

    def close(self) -> None:
        """释放服务持有的 HTTP 客户端与工作区资源。"""

        if self._owns_llm_analyzer:
            client = getattr(self._llm_analyzer, "client", None)
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - 关闭失败不影响退出
                    _LOGGER.warning("llm_client_close_failed")
        if self._owns_repository_manager:
            cleanup_all = getattr(self._repository_manager, "cleanup_all", None)
            if callable(cleanup_all):
                try:
                    cleanup_all()
                except Exception:  # noqa: BLE001 - 清理失败不影响退出
                    _LOGGER.warning("repository_cleanup_failed")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 请求校验与仓库获取
    # ------------------------------------------------------------------
    def _validate_request(self, request: ReviewRequest) -> GitHubRepository:
        if not isinstance(request, ReviewRequest):
            raise ReviewServiceError(
                "review request is invalid",
                stage="validation",
                error_type="invalid_request",
            )
        try:
            repository = validate_github_url(request.repository_url)
        except URLValidationError as exc:
            raise ReviewServiceError(
                "repository URL is invalid",
                stage="validation",
                error_type="invalid_repository_url",
            ) from exc
        try:
            if request.branch is not None:
                validate_branch_name(request.branch)
            if request.commit_sha is not None:
                normalize_commit_sha(request.commit_sha)
        except URLValidationError as exc:
            raise ReviewServiceError(
                "branch or commit SHA is invalid",
                stage="validation",
                error_type="invalid_revision",
            ) from exc
        return repository

    def _acquire_repository(
        self,
        repository: GitHubRepository,
        request: ReviewRequest,
        review_id: str,
    ) -> RepositorySnapshot:
        try:
            snapshot = self._repository_manager.clone(
                repository.canonical_url,
                branch=request.branch,
                commit_sha=request.commit_sha,
            )
        except GitNotFoundError as exc:
            raise ReviewServiceError(
                "git executable is not available",
                stage="repository",
                error_type="git_not_found",
                review_id=review_id,
            ) from exc
        except GitTimeoutError as exc:
            raise ReviewServiceError(
                "repository acquisition timed out",
                stage="repository",
                error_type="clone_timeout",
                retryable=True,
                review_id=review_id,
            ) from exc
        except ResourceLimitExceededError as exc:
            raise ReviewServiceError(
                "repository resource limit exceeded",
                stage="repository",
                error_type="resource_limit_exceeded",
                review_id=review_id,
            ) from exc
        except CloneError as exc:
            raise ReviewServiceError(
                "repository clone failed",
                stage="repository",
                error_type="clone_failed",
                retryable=True,
                review_id=review_id,
            ) from exc
        except CommitResolutionError as exc:
            raise ReviewServiceError(
                "commit SHA could not be resolved",
                stage="repository",
                error_type="commit_resolution_failed",
                review_id=review_id,
            ) from exc
        except RepositoryError as exc:
            raise ReviewServiceError(
                "repository acquisition failed",
                stage="repository",
                error_type="repository_error",
                review_id=review_id,
            ) from exc
        except Exception as exc:
            raise ReviewServiceError(
                "repository acquisition failed unexpectedly",
                stage="repository",
                error_type=type(exc).__name__,
                review_id=review_id,
            ) from exc

        if not isinstance(snapshot.commit_sha, str) or not _COMMIT_SHA_RE.fullmatch(
            snapshot.commit_sha
        ):
            raise ReviewServiceError(
                "repository snapshot does not contain a fixed commit SHA",
                stage="repository",
                error_type="invalid_snapshot",
                review_id=review_id,
            )
        if not snapshot.workspace_path.is_dir():
            raise ReviewServiceError(
                "repository workspace is unavailable",
                stage="repository",
                error_type="invalid_snapshot",
                review_id=review_id,
            )
        return snapshot

    def _cleanup_snapshot(self, snapshot: RepositorySnapshot) -> None:
        try:
            self._repository_manager.cleanup(snapshot)
        except Exception as exc:  # noqa: BLE001 - 清理失败不能覆盖审查结果
            _LOGGER.warning(
                "workspace_cleanup_failed",
                error_type=type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # 核心流水线
    # ------------------------------------------------------------------
    def _run_review(
        self,
        workspace: _WorkspaceInfo,
        *,
        review_id: str,
        started_at: datetime,
        output_root: Path,
    ) -> ReviewOutcome:
        started_clock = time.perf_counter()
        inventory = self._inspect(workspace.path, review_id)
        python_files = [file.path for file in inventory.python_files]
        _LOGGER.info(
            "inventory_completed",
            review_id=review_id,
            total_files=inventory.statistics.total_files,
            python_files=len(python_files),
            partial=inventory.is_partial,
        )

        tool_results = self._run_tools(
            workspace.path, python_files, review_id
        )
        test_result = self._run_tests(workspace, review_id)
        try:
            aggregation = aggregate_review_results(
                tool_results,
                test_result,
                raw_output_prefix="static_analysis.json",
            )
        except Exception as exc:
            raise ReviewServiceError(
                "finding aggregation failed",
                stage="aggregation",
                error_type=type(exc).__name__,
                review_id=review_id,
            ) from exc

        llm_analysis = self._run_llm(
            aggregation,
            workspace_path=workspace.path,
            allowed_files=python_files,
            review_id=review_id,
        )
        warnings = self._build_warnings(
            workspace, inventory, tool_results, test_result, llm_analysis
        )
        review_status = self._review_status(
            inventory=inventory,
            tool_results=tool_results,
            test_result=test_result,
            llm_analysis=llm_analysis,
            warnings=warnings,
        )
        duration_seconds = round(time.perf_counter() - started_clock, 3)

        source = ReviewArtifactInput(
            review_id=review_id,
            repository_url=workspace.repository_url,
            repository_name=workspace.repository_name,
            branch=workspace.branch,
            commit_sha=workspace.commit_sha,
            review_status=review_status,
            reviewed_at=started_at,
            project_language="python",
            discovered_file_count=inventory.statistics.total_files,
            analyzed_file_count=len(python_files),
            inventory=self._inventory_summary(inventory),
            tool_results=tool_results,
            test_result=test_result,
            aggregation=aggregation,
            llm_analysis=llm_analysis,
            review_duration_seconds=duration_seconds,
            warnings=warnings,
            workspace_path=workspace.path,
            source_type=workspace.source_type,
            fixture_manifest_sha256=workspace.fixture_manifest_sha256,
        )
        try:
            artifacts = self._report_generator.generate(source, output_root)
        except ReportGenerationError as exc:
            raise ReviewServiceError(
                "report generation failed",
                stage="reporting",
                error_type="report_generation_failed",
                review_id=review_id,
            ) from exc

        _LOGGER.info(
            "report_generated",
            review_id=review_id,
            review_status=review_status,
            finding_count=len(llm_analysis.findings),
            test_status=test_result.status.value,
            llm_status=llm_analysis.status.value,
        )
        return self._outcome(
            artifacts,
            workspace=workspace,
            review_status=review_status,
            test_result=test_result,
            llm_analysis=llm_analysis,
            warnings=warnings,
            duration_seconds=duration_seconds,
        )

    def _inspect(self, workspace_path: Path, review_id: str) -> RepositoryInventory:
        try:
            return self._inspector.inspect(workspace_path)
        except RepositoryInspectionError as exc:
            raise ReviewServiceError(
                "repository inspection failed",
                stage="inspection",
                error_type="inspection_failed",
                review_id=review_id,
            ) from exc
        except Exception as exc:
            raise ReviewServiceError(
                "repository inspection failed unexpectedly",
                stage="inspection",
                error_type=type(exc).__name__,
                review_id=review_id,
            ) from exc

    def _run_tools(
        self,
        workspace_path: Path,
        files: Sequence[str],
        review_id: str,
    ) -> tuple[ToolExecutionResult, ...]:
        results: list[ToolExecutionResult] = []
        for tool in self._tools:
            started = self._now()
            started_clock = time.perf_counter()
            try:
                result = tool.run(workspace_path, list(files))
                if not isinstance(result, ToolExecutionResult):
                    raise TypeError("tool returned an invalid result")
            except Exception as exc:  # noqa: BLE001 - 单工具失败不终止审查
                finished = self._now()
                result = ToolExecutionResult(
                    tool_name=tool.tool_name,
                    tool_version=None,
                    execution_status=ToolExecutionStatus.FAILED,
                    exit_code=None,
                    started_at=started,
                    finished_at=finished,
                    duration_ms=int(
                        (time.perf_counter() - started_clock) * 1000
                    ),
                    stdout="",
                    stderr="",
                    findings=(),
                    error=ErrorInfo(
                        error_type="tool_exception",
                        message=(
                            f"{tool.tool_name} raised "
                            f"{type(exc).__name__}"
                        ),
                        retryable=False,
                        details={"tool": tool.tool_name},
                    ),
                )
                _LOGGER.warning(
                    "tool_failed",
                    review_id=review_id,
                    tool=tool.tool_name,
                    error_type=type(exc).__name__,
                )
            results.append(result)
            _LOGGER.info(
                "tool_completed",
                review_id=review_id,
                tool=result.tool_name,
                status=result.execution_status.value,
                finding_count=len(result.findings),
                duration_ms=result.duration_ms,
            )
        return tuple(results)

    def _run_tests(
        self,
        workspace: _WorkspaceInfo,
        review_id: str,
    ) -> TestExecutionResult:
        trusted_name = (
            workspace.fixture_name if workspace.trusted_fixture else None
        )
        started = self._now()
        started_clock = time.perf_counter()
        try:
            result = self._test_runner.execute(trusted_fixture=trusted_name)
            if not isinstance(result, TestExecutionResult):
                raise TypeError("test runner returned an invalid result")
        except Exception as exc:  # noqa: BLE001 - 测试失败仍生成报告
            result = self._failed_test_result(
                trusted_name=trusted_name,
                fixture_version=workspace.fixture_version,
                fixture_manifest_sha256=workspace.fixture_manifest_sha256,
                started=started,
                duration_ms=int((time.perf_counter() - started_clock) * 1000),
                error=ErrorInfo(
                    error_type="test_exception",
                    message=f"test execution raised {type(exc).__name__}",
                    retryable=False,
                ),
            )
            _LOGGER.warning(
                "tests_failed",
                review_id=review_id,
                error_type=type(exc).__name__,
            )
        _LOGGER.info(
            "tests_completed",
            review_id=review_id,
            status=result.status.value,
            executed_on=("trusted_fixture" if trusted_name else "none"),
        )
        return result

    def _run_llm(
        self,
        aggregation: AggregationResult,
        *,
        workspace_path: Path,
        allowed_files: Sequence[str],
        review_id: str,
    ) -> LLMAnalysisResult:
        try:
            result = self._llm_analyzer.analyze(
                aggregation,
                workspace_path=workspace_path,
                allowed_files=list(allowed_files),
            )
            if not isinstance(result, LLMAnalysisResult):
                raise TypeError("LLM analyzer returned an invalid result")
            return result
        except Exception as exc:  # noqa: BLE001 - LLM 失败保留确定性结果
            _LOGGER.warning(
                "llm_analysis_failed",
                review_id=review_id,
                error_type=type(exc).__name__,
            )
            return LLMAnalysisResult(
                status=LLMAnalysisStatus.FAILED,
                findings=aggregation.findings,
                accepted=(),
                rejected=(),
                explanations=(),
                reason=f"LLM analysis raised {type(exc).__name__}",
            )

    # ------------------------------------------------------------------
    # 状态、警告与结果
    # ------------------------------------------------------------------
    @staticmethod
    def _failed_test_result(
        *,
        trusted_name: str | None,
        fixture_version: str | None,
        fixture_manifest_sha256: str | None,
        started: datetime,
        duration_ms: int,
        error: ErrorInfo,
    ) -> TestExecutionResult:
        summary = TestSummary(
            execution_status="failed",
            passed=None,
            failed=None,
            skipped=None,
            coverage=None,
            source="pytest",
            reason="test execution did not complete",
        )
        return TestExecutionResult(
            status=TestExecutionStatus.FAILED,
            summary=summary,
            fixture_name=trusted_name,
            fixture_version=fixture_version,
            fixture_manifest_sha256=fixture_manifest_sha256,
            collected_tests=None,
            test_records=(),
            test_records_truncated=False,
            coverage_files=(),
            coverage_files_truncated=False,
            read_only_verified=None,
            modified_paths=(),
            pytest_version=None,
            coverage_version=None,
            exit_code=None,
            coverage_exit_code=None,
            test_duration_seconds=None,
            started_at=started,
            finished_at=started,
            duration_ms=duration_ms,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            error=error,
        )

    @staticmethod
    def _inventory_summary(
        inventory: RepositoryInventory,
    ) -> InventorySummary:
        stats = inventory.statistics
        return InventorySummary(
            total_files=stats.total_files,
            python_source_files=stats.python_source_files,
            python_test_files=stats.python_test_files,
            filtered_files=stats.filtered_files,
            excluded_directories=stats.excluded_directories,
            total_size_bytes=stats.total_size_bytes,
            scanned_bytes=stats.scanned_bytes,
            total_line_count=stats.total_line_count,
            is_partial=inventory.is_partial,
            partial_reason=inventory.partial_reason,
        )

    @staticmethod
    def _build_warnings(
        workspace: _WorkspaceInfo,
        inventory: RepositoryInventory,
        tool_results: Sequence[ToolExecutionResult],
        test_result: TestExecutionResult,
        llm_analysis: LLMAnalysisResult,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if inventory.is_partial:
            warnings.append(
                "repository scan was partial: "
                f"{inventory.partial_reason or 'scan limit reached'}"
            )
        if workspace.oversized_files:
            warnings.append(
                f"{len(workspace.oversized_files)} oversized source files "
                "were skipped"
            )
        for result in tool_results:
            if result.execution_status not in {
                ToolExecutionStatus.SUCCESS,
                ToolExecutionStatus.FINDINGS,
            }:
                warnings.append(
                    f"{result.tool_name} finished with status "
                    f"{result.execution_status.value}"
                )
            if result.truncated:
                warnings.append(
                    f"{result.tool_name} output was truncated"
                )
        if workspace.trusted_fixture:
            if test_result.status is not TestExecutionStatus.EXECUTED:
                warnings.append(
                    f"trusted fixture tests finished with status "
                    f"{test_result.status.value}"
                )
        elif test_result.status is not TestExecutionStatus.NOT_EXECUTED:
            warnings.append(
                f"external repository tests returned unexpected status "
                f"{test_result.status.value}"
            )
        if test_result.status in {
            TestExecutionStatus.FAILED,
            TestExecutionStatus.TIMEOUT,
        }:
            reason = test_result.summary.reason or "test execution failed"
            warnings.append(f"tests failed: {reason}")
        if test_result.read_only_verified is False:
            warnings.append("test execution modified the fixture workspace")
        if test_result.truncated:
            warnings.append("test output was truncated")
        if llm_analysis.status is not LLMAnalysisStatus.COMPLETED:
            warnings.append(
                f"LLM analysis finished with status "
                f"{llm_analysis.status.value}"
            )
        return tuple(_shorten(item) for item in warnings)

    @staticmethod
    def _review_status(
        *,
        inventory: RepositoryInventory,
        tool_results: Sequence[ToolExecutionResult],
        test_result: TestExecutionResult,
        llm_analysis: LLMAnalysisResult,
        warnings: Sequence[str],
    ) -> ReviewStatus:
        if inventory.is_partial or warnings:
            return "partial"
        if any(
            result.execution_status
            not in {ToolExecutionStatus.SUCCESS, ToolExecutionStatus.FINDINGS}
            or result.truncated
            for result in tool_results
        ):
            return "partial"
        if test_result.status in {
            TestExecutionStatus.FAILED,
            TestExecutionStatus.TIMEOUT,
        }:
            return "partial"
        if test_result.read_only_verified is False:
            return "partial"
        if llm_analysis.status is not LLMAnalysisStatus.COMPLETED:
            return "partial"
        return "completed"

    @staticmethod
    def _outcome(
        artifacts: ReportArtifacts,
        *,
        workspace: _WorkspaceInfo,
        review_status: ReviewStatus,
        test_result: TestExecutionResult,
        llm_analysis: LLMAnalysisResult,
        warnings: Sequence[str],
        duration_seconds: float,
    ) -> ReviewOutcome:
        severity_counts: dict[str, int] = {}
        for finding in llm_analysis.findings:
            severity_counts[finding.severity] = (
                severity_counts.get(finding.severity, 0) + 1
            )
        return ReviewOutcome(
            review_id=artifacts.review_id,
            review_status=review_status,
            repository_name=workspace.repository_name,
            commit_sha=workspace.commit_sha,
            report_dir=artifacts.report_dir,
            metadata_path=artifacts.metadata_path,
            static_analysis_path=artifacts.static_analysis_path,
            test_report_path=artifacts.test_report_path,
            markdown_path=artifacts.markdown_path,
            finding_count=len(llm_analysis.findings),
            severity_counts=dict(sorted(severity_counts.items())),
            test_status=test_result.status.value,
            llm_status=llm_analysis.status.value,
            warnings=tuple(warnings),
            duration_seconds=duration_seconds,
        )

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
        ):
            raise ReviewServiceError(
                "review clock must return a timezone-aware UTC datetime",
                stage="internal",
                error_type="invalid_clock",
            )
        return value.astimezone(UTC)

    def _new_review_id(self, started_at: datetime) -> str:
        value = self._id_factory(started_at)
        if not isinstance(value, str) or not value.strip():
            raise ReviewServiceError(
                "review id is invalid",
                stage="internal",
                error_type="invalid_review_id",
            )
        return value

    @staticmethod
    def _default_review_id(started_at: datetime) -> str:
        stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        return f"stage1-{stamp}-{uuid4().hex[:8]}"

    def _resolve_output_root(self, value: Path | str | None) -> Path:
        raw = value if value is not None else self.settings.review_output_root
        if not isinstance(raw, (str, Path)) or not str(raw).strip():
            raise ReviewServiceError(
                "report output root is invalid",
                stage="validation",
                error_type="invalid_output_root",
            )
        return Path(raw)

    @staticmethod
    def _ensure_output_outside_workspace(
        output_root: Path,
        workspace_path: Path,
        review_id: str,
    ) -> None:
        try:
            resolved_output = output_root.expanduser().resolve()
            resolved_workspace = workspace_path.expanduser().resolve()
        except OSError as exc:
            raise ReviewServiceError(
                "report output root is invalid",
                stage="validation",
                error_type="invalid_output_root",
                review_id=review_id,
            ) from exc
        if resolved_output == resolved_workspace or resolved_output.is_relative_to(
            resolved_workspace
        ):
            raise ReviewServiceError(
                "report output root must be outside the review workspace",
                stage="validation",
                error_type="output_inside_workspace",
                review_id=review_id,
            )


def _shorten(value: str) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= _MAX_WARNING_CHARS else text[:_MAX_WARNING_CHARS]
