"""ReviewService 统一业务入口测试。

所有外部依赖均使用 Fake：不联网、不克隆真实仓库、不调用真实 LLM、不在
可信 Fixture 之外执行任何仓库代码。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import code_review.services.review_service as review_service_module
from code_review.agents.contracts import UsageSummary
from code_review.agents.manager import ManagerAgent
from code_review.reporting.report_generator import ReportGenerationError
from code_review.reporting.stage2_models import (
    Stage2MetadataArtifact,
    Stage2StaticAnalysisArtifact,
    Stage2TestReportArtifact,
)
from code_review.reporting.stage2_report_generator import (
    Stage2ReportGenerationError,
)
from code_review.schemas.report import ReviewReport
from code_review.services.llm_analyzer import LLMAnalysisStatus
from code_review.services.review_service import (
    ReviewRequest,
    ReviewService,
    ReviewServiceError,
)
from code_review.services.stage2_factory import Stage2Dependencies
from code_review.tools.file_filters import FileCategory
from code_review.tools.repository_inspector import (
    RepositoryFile,
    RepositoryInventory,
)
from code_review.tools.repository_manager import (
    CloneError,
    GitNotFoundError,
    GitResult,
    RepositorySnapshot,
)
from code_review.tools.test_runner import TestExecutionStatus as ExecutionStatus
from config.settings import Settings
from tests import stage2_helpers as s2
from tests.stage1_helpers import (
    COMMIT_SHA,
    FIXTURE_MANIFEST_SHA,
    NOW,
    FakeLLMAnalyzer,
    FakeRepositoryManager,
    FakeTestRunner,
    FakeTool,
    make_finding,
    make_llm_result,
    make_test_result,
    make_tool_finding,
    make_tool_result,
)

URL = "https://github.com/example/project"


@dataclass
class FakeInspector:
    inventory: RepositoryInventory
    calls: list[Path] = field(default_factory=list)

    def inspect(self, root: Path) -> RepositoryInventory:
        self.calls.append(root)
        return self.inventory


class FailingReportGenerator:
    def generate(self, source: object, output_root: Path) -> object:
        raise ReportGenerationError("report failed")


def make_inventory(root: Path) -> RepositoryInventory:
    return RepositoryInventory(
        root=root,
        files=(
            RepositoryFile(
                path="pkg/app.py",
                category=FileCategory.PYTHON_SOURCE,
                language="python",
                line_count=10,
                size_bytes=100,
            ),
        ),
        filtered_files=(),
        excluded_directories=(),
        scanned_bytes=100,
        is_partial=False,
        partial_reason=None,
    )


def make_snapshot(
    workspace: Path,
    *,
    commit_sha: str = COMMIT_SHA,
) -> RepositorySnapshot:
    workspace.mkdir(parents=True, exist_ok=True)
    return RepositorySnapshot(
        owner="example",
        name="project",
        repository_url=URL,
        branch="main",
        commit_sha=commit_sha,
        workspace_path=workspace,
        cloned_at=NOW,
        size_bytes=100,
        file_count=1,
        git_version="2.40.0",
    )


@dataclass
class ServiceHarness:
    service: ReviewService
    manager: FakeRepositoryManager
    inspector: FakeInspector
    tools: list[FakeTool]
    test_runner: FakeTestRunner
    llm: FakeLLMAnalyzer
    snapshot: RepositorySnapshot
    workspace: Path
    settings: Settings


def make_harness(
    tmp_path: Path,
    *,
    tool_results: tuple | None = None,
    test_result=None,
    llm_result=None,
    inventory: RepositoryInventory | None = None,
    snapshot: RepositorySnapshot | None = None,
    allow_trusted_fixture_review: bool = False,
    clock=None,
    id_factory=None,
    report_generator=None,
    multi_agent: bool = False,
) -> ServiceHarness:
    workspace = tmp_path / "workspace"
    snapshot = snapshot or make_snapshot(workspace)
    workspace = snapshot.workspace_path
    if inventory is None:
        inventory = make_inventory(workspace)

    if tool_results is None:
        tool_results = (
            make_tool_result(
                "ruff", findings=(make_tool_finding(),)
            ),
            make_tool_result("bandit"),
            make_tool_result("radon"),
        )
    if test_result is None:
        test_result = make_test_result()
    if llm_result is None:
        llm_result = make_llm_result(
            (make_finding("LLM-0001", category="code_smell"),)
        )

    manager = FakeRepositoryManager(snapshot)
    inspector = FakeInspector(inventory)
    tools = [
        FakeTool(result.tool_name, result=result)
        for result in tool_results
    ]
    test_runner = FakeTestRunner(result=test_result)
    llm = FakeLLMAnalyzer(result=llm_result)
    settings = Settings(
        _env_file=None,
        review_output_root=str(tmp_path / "reports"),
        static_tool_timeout_seconds=60,
    )
    service = ReviewService(
        settings,
        repository_manager=manager,
        inspector=inspector,
        tools=tools,
        test_runner=test_runner,
        llm_analyzer=llm,
        report_generator=report_generator,
        clock=clock or (lambda: NOW),
        id_factory=id_factory or (lambda _: "stage1-test-review"),
        allow_trusted_fixture_review=allow_trusted_fixture_review,
        multi_agent=multi_agent,
    )
    return ServiceHarness(
        service=service,
        manager=manager,
        inspector=inspector,
        tools=tools,
        test_runner=test_runner,
        llm=llm,
        snapshot=snapshot,
        workspace=workspace,
        settings=settings,
    )


def test_review_runs_full_pipeline_and_writes_four_artifacts(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)

    outcome = harness.service.review(ReviewRequest(URL, branch="main"))

    assert outcome.review_id == "stage1-test-review"
    assert outcome.review_status == "completed"
    assert outcome.repository_name == "example/project"
    assert outcome.commit_sha == COMMIT_SHA
    assert outcome.finding_count == 1
    assert outcome.severity_counts == {"low": 1}
    assert outcome.test_status == "not_executed"
    assert outcome.llm_status == "completed"
    assert outcome.warnings == ()
    assert {path.name for path in outcome.artifact_paths} == {
        "metadata.json",
        "static_analysis.json",
        "test_report.json",
        "report.md",
    }

    assert harness.manager.clone_calls == [
        {
            "repository_url": URL,
            "branch": "main",
            "commit_sha": None,
        }
    ]
    assert harness.manager.cleanup_calls == [harness.snapshot]
    assert harness.inspector.calls == [harness.workspace]
    assert [tool.tool_name for tool in harness.tools] == [
        "ruff",
        "bandit",
        "radon",
    ]
    for tool in harness.tools:
        assert tool.calls == [(harness.workspace, ["pkg/app.py"])]
    assert harness.test_runner.calls == [None]
    assert harness.llm.calls[0]["allowed_files"] == ["pkg/app.py"]

    metadata = json.loads(
        outcome.metadata_path.read_text(encoding="utf-8")
    )
    tests = json.loads(
        outcome.test_report_path.read_text(encoding="utf-8")
    )
    assert metadata["source_type"] == "github_repository"
    assert metadata["commit_sha"] == COMMIT_SHA
    assert tests["execution_status"] == "not_executed"
    assert tests["trusted_fixture"] is False


def test_external_repository_tests_are_never_executed(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)

    harness.service.review(ReviewRequest(URL))

    assert harness.test_runner.calls == [None]


def test_invalid_url_is_rejected_before_repository_clone(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(ReviewRequest("https://gitlab.com/x/y"))

    assert caught.value.stage == "validation"
    assert caught.value.error_type == "invalid_repository_url"
    assert harness.manager.clone_calls == []
    assert not (tmp_path / "reports").exists()


def test_invalid_revision_is_rejected_before_clone(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)

    with pytest.raises(ReviewServiceError) as branch_error:
        harness.service.review(ReviewRequest(URL, branch="-bad"))
    assert branch_error.value.error_type == "invalid_revision"

    with pytest.raises(ReviewServiceError) as sha_error:
        harness.service.review(ReviewRequest(URL, commit_sha="not-a-sha"))
    assert sha_error.value.error_type == "invalid_revision"
    assert harness.manager.clone_calls == []


def test_clone_errors_are_mapped_to_safe_service_errors(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    harness.manager.clone_error = CloneError(
        r"clone failed at C:\Users\secret\workspace"
    )

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(ReviewRequest(URL))

    assert caught.value.stage == "repository"
    assert caught.value.error_type == "clone_failed"
    assert caught.value.retryable is True
    assert "C:\\Users" not in str(caught.value)
    assert "secret" not in str(caught.value)

    harness.manager.clone_error = GitNotFoundError("git missing")
    with pytest.raises(ReviewServiceError) as git_error:
        harness.service.review(ReviewRequest(URL))
    assert git_error.value.error_type == "git_not_found"
    assert git_error.value.retryable is False


def test_snapshot_must_have_full_commit(tmp_path: Path) -> None:
    snapshot = make_snapshot(tmp_path / "workspace", commit_sha="abc123")
    harness = make_harness(tmp_path, snapshot=snapshot)

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(ReviewRequest(URL))

    assert caught.value.stage == "repository"
    assert caught.value.error_type == "invalid_snapshot"
    assert harness.manager.cleanup_calls == []


def test_output_inside_workspace_is_rejected_and_cleaned_up(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(
            ReviewRequest(URL, output_root=harness.workspace / "reports")
        )

    assert caught.value.stage == "validation"
    assert caught.value.error_type == "output_inside_workspace"
    assert harness.manager.cleanup_calls == [harness.snapshot]
    assert not (harness.workspace / "reports").exists()


def test_tool_exception_is_isolated_and_reported(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    harness.tools[0].error = RuntimeError("ruff exploded")
    harness.tools[0].result = None

    outcome = harness.service.review(ReviewRequest(URL))

    assert outcome.review_status == "partial"
    assert any("ruff finished with status failed" in item for item in outcome.warnings)
    static = json.loads(
        outcome.static_analysis_path.read_text(encoding="utf-8")
    )
    assert static["tools"]["ruff"]["execution_status"] == "failed"
    assert static["error_summary"][0]["source"] == "ruff"
    assert "ruff exploded" not in json.dumps(static, ensure_ascii=False)


def test_test_runner_exception_becomes_failed_test_report(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    harness.test_runner.error = RuntimeError("pytest exploded")

    outcome = harness.service.review(ReviewRequest(URL))

    assert outcome.review_status == "partial"
    assert outcome.test_status == "failed"
    assert any("tests failed" in item for item in outcome.warnings)
    tests = json.loads(
        outcome.test_report_path.read_text(encoding="utf-8")
    )
    assert tests["execution_status"] == "failed"
    assert tests["counts"]["passed"] is None
    assert tests["reason"] == "test execution did not complete"


def test_llm_exception_keeps_deterministic_findings(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    harness.llm.error = RuntimeError("provider failed with sk-secret-value")

    outcome = harness.service.review(ReviewRequest(URL))

    assert outcome.review_status == "partial"
    assert outcome.llm_status == "failed"
    assert outcome.finding_count >= 1
    assert any("LLM analysis finished with status failed" in item for item in outcome.warnings)
    static = json.loads(
        outcome.static_analysis_path.read_text(encoding="utf-8")
    )
    assert static["llm_analysis"]["status"] == "failed"
    assert "provider failed" not in json.dumps(static, ensure_ascii=False)
    assert static["findings"]


def test_llm_not_configured_marks_review_partial(tmp_path: Path) -> None:
    harness = make_harness(
        tmp_path,
        llm_result=make_llm_result(
            (), status=LLMAnalysisStatus.NOT_CONFIGURED
        ),
    )

    outcome = harness.service.review(ReviewRequest(URL))

    assert outcome.review_status == "partial"
    assert outcome.llm_status == "not_configured"
    assert any(
        "LLM analysis finished with status not_configured" in item
        for item in outcome.warnings
    )
    static = json.loads(
        outcome.static_analysis_path.read_text(encoding="utf-8")
    )
    assert static["llm_analysis"]["reason"]


def test_invalid_clock_and_review_id_are_internal_errors(
    tmp_path: Path,
) -> None:
    harness = make_harness(
        tmp_path,
        clock=lambda: datetime(2026, 1, 2, 3, 4, 5),
    )
    with pytest.raises(ReviewServiceError) as clock_error:
        harness.service.review(ReviewRequest(URL))
    assert clock_error.value.stage == "internal"
    assert clock_error.value.error_type == "invalid_clock"

    harness = make_harness(tmp_path, id_factory=lambda _: "  ")
    with pytest.raises(ReviewServiceError) as id_error:
        harness.service.review(ReviewRequest(URL))
    assert id_error.value.stage == "internal"
    assert id_error.value.error_type == "invalid_review_id"


def test_report_failure_is_wrapped_and_workspace_is_cleaned(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path, report_generator=FailingReportGenerator())

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(ReviewRequest(URL))

    assert caught.value.stage == "reporting"
    assert caught.value.error_type == "report_generation_failed"
    assert harness.manager.cleanup_calls == [harness.snapshot]


def test_trusted_fixture_review_uses_fixture_tests_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    verified = SimpleNamespace(
        name="trusted_fixture_v1",
        root=fixture_root,
        version="1.0.0",
        manifest_sha256=FIXTURE_MANIFEST_SHA,
    )
    monkeypatch.setattr(
        review_service_module,
        "verify_trusted_fixture",
        lambda *, expected_name: verified,
    )
    monkeypatch.setattr(
        review_service_module,
        "DEFAULT_TRUSTED_FIXTURE_ROOT",
        fixture_root,
    )
    executed = make_test_result(
        ExecutionStatus.EXECUTED,
        trusted_fixture=True,
        read_only_verified=True,
    )
    harness = make_harness(
        tmp_path,
        test_result=executed,
        inventory=make_inventory(fixture_root),
        snapshot=make_snapshot(fixture_root),
        allow_trusted_fixture_review=True,
    )

    outcome = harness.service.review_trusted_fixture()

    assert outcome.review_status == "completed"
    assert harness.manager.clone_calls == []
    assert harness.test_runner.calls == ["trusted_fixture_v1"]
    assert harness.manager.cleanup_calls == []
    metadata = json.loads(
        outcome.metadata_path.read_text(encoding="utf-8")
    )
    tests = json.loads(
        outcome.test_report_path.read_text(encoding="utf-8")
    )
    assert metadata["source_type"] == "trusted_fixture"
    assert metadata["commit_sha"] is None
    assert metadata["repository_url"] == "fixture://trusted_fixture_v1"
    assert metadata["fixture_manifest_sha256"] == FIXTURE_MANIFEST_SHA
    assert tests["trusted_fixture"] is True
    assert tests["execution_status"] == "executed"


def test_trusted_fixture_review_is_disabled_by_default(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review_trusted_fixture()

    assert caught.value.stage == "validation"
    assert caught.value.error_type == "trusted_fixture_disabled"
    assert harness.test_runner.calls == []


def test_constructor_requires_unique_non_empty_tools(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(ValueError, match="at least one analysis tool"):
        ReviewService(
            settings,
            repository_manager=FakeRepositoryManager(None),
            tools=[],
            llm_analyzer=FakeLLMAnalyzer(result=make_llm_result(())),
        )

    with pytest.raises(ValueError, match="names must be unique"):
        ReviewService(
            settings,
            repository_manager=FakeRepositoryManager(None),
            tools=[
                FakeTool("ruff", result=make_tool_result("ruff")),
                FakeTool("ruff", result=make_tool_result("ruff")),
            ],
            llm_analyzer=FakeLLMAnalyzer(result=make_llm_result(())),
        )


def test_warnings_are_shortened(tmp_path: Path) -> None:
    harness = make_harness(
        tmp_path,
        test_result=make_test_result(
            ExecutionStatus.FAILED,
            reason="x" * 600,
        ),
    )

    outcome = harness.service.review(ReviewRequest(URL))

    assert any(item.startswith("tests failed:") for item in outcome.warnings)
    assert all(len(item) <= 500 for item in outcome.warnings)


# ----------------------------------------------------------------------
# Stage 2：多 Agent 工作流与五件产物


class FakeGitClient:
    """记录调用的 Fake Git 客户端；不启动任何真实进程。"""

    def __init__(
        self,
        *,
        head_sha: str = COMMIT_SHA,
        returncode: int = 0,
        error: Exception | None = None,
    ) -> None:
        self.head_sha = head_sha
        self.returncode = returncode
        self.error = error
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        args,
        *,
        cwd: Path | None = None,
        timeout: float = 300,
        size_guard=None,
        isolated_config=None,
    ) -> GitResult:
        self.calls.append(
            {"args": tuple(args), "cwd": cwd, "timeout": timeout}
        )
        if self.error is not None:
            raise self.error
        return GitResult(
            returncode=self.returncode,
            stdout=f"{self.head_sha}\n",
            stderr="",
        )


class FailingStage2ReportGenerator:
    def generate(self, source: object, output_root: Path) -> object:
        raise Stage2ReportGenerationError("stage 2 report failed")


class ExplodingManager(ManagerAgent):
    def plan(self, **kwargs: object) -> object:
        raise RuntimeError("manager planning exploded")


@dataclass
class Stage2Harness:
    service: ReviewService
    manager: FakeRepositoryManager
    inspector: FakeInspector
    tools: list
    test_runner: object
    snapshot: RepositorySnapshot
    workspace: Path
    settings: Settings
    git_client: FakeGitClient


STAGE2_ARTIFACT_NAMES = [
    "metadata.json",
    "report.json",
    "report.md",
    "static_analysis.json",
    "test_report.json",
]


def make_stage2_harness(
    tmp_path: Path,
    *,
    workspace: Path | None = None,
    test_result=None,
    git_client: FakeGitClient | None = None,
    stage2_factory=None,
    stage2_report_generator=None,
    multi_agent: bool = True,
    allow_trusted_fixture_review: bool = True,
    trusted_fixture_name: str | None = None,
    id_factory=None,
) -> Stage2Harness:
    resolved_workspace = workspace or (tmp_path / "workspace")
    package = resolved_workspace / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "app.py").write_text(
        '"""Stage 2 service sample module."""\n'
        "\n"
        "def run(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    snapshot = make_snapshot(resolved_workspace)
    inventory = make_inventory(resolved_workspace)
    if test_result is None:
        test_result = s2.make_test_execution_result(status="not_executed")

    manager = FakeRepositoryManager(snapshot)
    inspector = FakeInspector(inventory)
    tools = [
        s2.FakeAnalysisTool(
            tool_name=name, result=s2.make_tool_result(tool_name=name)
        )
        for name in ("ruff", "bandit", "radon")
    ]
    test_runner = s2.FakeTestRunner(result=test_result)
    settings_kwargs = {
        "review_output_root": str(tmp_path / "reports"),
        "static_tool_timeout_seconds": 60,
    }
    if trusted_fixture_name is not None:
        settings_kwargs["trusted_fixture_name"] = trusted_fixture_name
    settings = Settings(_env_file=None, **settings_kwargs)
    resolved_git = git_client or FakeGitClient()
    service = ReviewService(
        settings,
        repository_manager=manager,
        inspector=inspector,
        tools=tools,
        test_runner=test_runner,
        llm_analyzer=FakeLLMAnalyzer(result=make_llm_result(())),
        clock=lambda: NOW,
        id_factory=id_factory or (lambda _: "stage2-test-review"),
        allow_trusted_fixture_review=allow_trusted_fixture_review,
        multi_agent=multi_agent,
        stage2_factory=stage2_factory,
        stage2_report_generator=stage2_report_generator,
        git_client=resolved_git,
    )
    return Stage2Harness(
        service=service,
        manager=manager,
        inspector=inspector,
        tools=tools,
        test_runner=test_runner,
        snapshot=snapshot,
        workspace=resolved_workspace,
        settings=settings,
        git_client=resolved_git,
    )


def test_stage2_review_is_the_default_and_writes_five_artifacts(
    tmp_path: Path,
) -> None:
    harness = make_stage2_harness(tmp_path)

    outcome = harness.service.review(ReviewRequest(URL))

    assert outcome.review_stage == "stage_2"
    assert outcome.review_id == "stage2-test-review"
    names = sorted(path.name for path in outcome.report_dir.iterdir())
    assert names == STAGE2_ARTIFACT_NAMES
    assert outcome.artifact_paths == (
        outcome.metadata_path,
        outcome.static_analysis_path,
        outcome.test_report_path,
        outcome.report_json_path,
        outcome.markdown_path,
    )

    report = ReviewReport.model_validate_json(
        outcome.report_json_path.read_text(encoding="utf-8")
    )
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    assert report.overall_score == 100.0
    assert report.dimension_scores["testing"].score is None
    for dimension in ("security", "quality", "performance"):
        assert report.dimension_scores[dimension].score == 100.0
    assert outcome.overall_verdict == report.overall_verdict
    assert outcome.overall_score == report.overall_score
    assert outcome.dimension_scores["testing"] is None

    metadata = Stage2MetadataArtifact.model_validate_json(
        outcome.metadata_path.read_text(encoding="utf-8")
    )
    assert metadata.stage == "stage_2"
    assert metadata.source_type == "github_repository"
    assert metadata.commit_sha == COMMIT_SHA
    assert metadata.review_status == "partial"
    assert metadata.review_duration_seconds >= 0

    static = Stage2StaticAnalysisArtifact.model_validate_json(
        outcome.static_analysis_path.read_text(encoding="utf-8")
    )
    assert set(static.agents) == {
        "security",
        "quality",
        "performance",
        "testing",
    }
    tests = Stage2TestReportArtifact.model_validate_json(
        outcome.test_report_path.read_text(encoding="utf-8")
    )
    assert tests.execution_status == "not_executed"
    assert tests.counts["passed"] is None
    assert outcome.test_status == "not_executed"
    assert outcome.llm_status == "not_configured"

    markdown = outcome.markdown_path.read_text(encoding="utf-8")
    assert "Stage 2 代码审查报告" in markdown
    assert report.overall_verdict in markdown
    assert "综合分：100.0" in markdown
    assert "测试未执行" in markdown or "not_executed" in markdown

    # 外部仓库测试绝不执行；报告写出后才清理工作区。
    assert harness.test_runner.calls == [None]
    assert harness.manager.cleanup_calls == [harness.snapshot]


def test_stage2_factory_failure_is_reported_as_graph_setup_error(
    tmp_path: Path,
) -> None:
    def broken_factory(context: object) -> object:
        raise RuntimeError("factory exploded")

    harness = make_stage2_harness(tmp_path, stage2_factory=broken_factory)

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(ReviewRequest(URL))

    assert caught.value.stage == "graph"
    assert caught.value.error_type == "graph_setup_failed"
    assert not (tmp_path / "reports").exists()
    assert harness.manager.cleanup_calls == [harness.snapshot]


def test_stage2_graph_execution_failure_is_explicit(
    tmp_path: Path,
) -> None:
    graph = s2.make_graph_dependencies(manager=ExplodingManager())
    dependencies = Stage2Dependencies(
        manager=graph.manager,
        graph=graph,
        rules=s2.make_review_rules(),
    )
    harness = make_stage2_harness(
        tmp_path, stage2_factory=lambda context: dependencies
    )

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(ReviewRequest(URL))

    assert caught.value.stage == "graph"
    assert caught.value.error_type == "graph_execution_failed"
    assert not (tmp_path / "reports").exists()
    assert harness.manager.cleanup_calls == [harness.snapshot]


def test_stage2_report_generation_failure_is_mapped_to_reporting(
    tmp_path: Path,
) -> None:
    harness = make_stage2_harness(
        tmp_path,
        stage2_report_generator=FailingStage2ReportGenerator(),
    )

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(ReviewRequest(URL))

    assert caught.value.stage == "reporting"
    assert caught.value.error_type == "report_generation_failed"
    assert not (tmp_path / "reports").exists()
    assert harness.manager.cleanup_calls == [harness.snapshot]


def test_stage2_real_llm_usage_fails_instead_of_fake_zero_cost(
    tmp_path: Path,
) -> None:
    usage = UsageSummary(
        llm_calls=1,
        reported_usage_calls=1,
        input_tokens=100,
        output_tokens=20,
    )
    graph = s2.make_graph_dependencies(
        factories={
            "security": s2.make_dimension_factory("security", usage=usage)
        }
    )
    dependencies = Stage2Dependencies(
        manager=graph.manager,
        graph=graph,
        rules=s2.make_review_rules(),
    )
    harness = make_stage2_harness(
        tmp_path, stage2_factory=lambda context: dependencies
    )

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review(ReviewRequest(URL))

    # Final Reviewer 在成本语义未解决时拒绝伪造零成本，整次审查显式失败。
    assert caught.value.stage == "graph"
    assert caught.value.error_type == "graph_execution_failed"
    assert not (tmp_path / "reports").exists()
    assert harness.manager.cleanup_calls == [harness.snapshot]


def test_stage2_fixture_review_verifies_commit_and_executes_approved_tests(
    tmp_path: Path,
) -> None:
    fixture_workspace = tmp_path / "fixture_repo"
    git_client = FakeGitClient(head_sha=COMMIT_SHA)
    executed = s2.make_test_execution_result(
        fixture_name="trusted_fixture_v1",
        fixture_version="1.0.0",
        fixture_manifest_sha256=FIXTURE_MANIFEST_SHA,
    )
    harness = make_stage2_harness(
        tmp_path,
        workspace=fixture_workspace,
        test_result=executed,
        git_client=git_client,
    )

    outcome = harness.service.review_stage2_fixture(
        workspace_path=fixture_workspace,
        commit_sha=COMMIT_SHA,
        trusted_fixture="trusted_fixture_v1",
        fixture_manifest_sha256=FIXTURE_MANIFEST_SHA,
    )

    assert outcome.review_stage == "stage_2"
    assert outcome.commit_sha == COMMIT_SHA
    assert outcome.test_status == "executed"
    assert outcome.overall_verdict == "APPROVE"
    assert all(
        score == 100.0 for score in outcome.dimension_scores.values()
    )
    assert sorted(
        path.name for path in outcome.report_dir.iterdir()
    ) == STAGE2_ARTIFACT_NAMES
    assert git_client.calls == [
        {
            "args": ("rev-parse", "--verify", "HEAD^{commit}"),
            "cwd": fixture_workspace.resolve(),
            "timeout": harness.settings.git_command_timeout_seconds,
        }
    ]
    assert harness.test_runner.calls == ["trusted_fixture_v1"]

    metadata = Stage2MetadataArtifact.model_validate_json(
        outcome.metadata_path.read_text(encoding="utf-8")
    )
    assert metadata.source_type == "trusted_fixture"
    assert metadata.repository_url == "fixture://trusted_fixture_v1"
    assert metadata.commit_sha == COMMIT_SHA
    assert metadata.fixture_manifest_sha256 == FIXTURE_MANIFEST_SHA

    # Stage 2 Fixture 入口不清理调用方工作区。
    assert harness.manager.cleanup_calls == []
    assert fixture_workspace.is_dir()


def test_stage2_fixture_review_requires_multi_agent(tmp_path: Path) -> None:
    harness = make_stage2_harness(tmp_path, multi_agent=False)

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review_stage2_fixture(
            workspace_path=harness.workspace,
            commit_sha=COMMIT_SHA,
            trusted_fixture="trusted_fixture_v1",
        )

    assert caught.value.stage == "validation"
    assert caught.value.error_type == "stage2_review_disabled"
    assert harness.git_client.calls == []


def test_stage2_fixture_review_rejects_unapproved_and_mismatched_names(
    tmp_path: Path,
) -> None:
    harness = make_stage2_harness(tmp_path)

    with pytest.raises(ReviewServiceError) as unapproved:
        harness.service.review_stage2_fixture(
            workspace_path=harness.workspace,
            commit_sha=COMMIT_SHA,
            trusted_fixture="evil_fixture",
        )
    assert unapproved.value.error_type == "fixture_not_approved"

    mismatched = make_stage2_harness(
        tmp_path / "mismatch", trusted_fixture_name="other_fixture"
    )
    with pytest.raises(ReviewServiceError) as mismatch:
        mismatched.service.review_stage2_fixture(
            workspace_path=mismatched.workspace,
            commit_sha=COMMIT_SHA,
            trusted_fixture="trusted_fixture_v1",
        )
    assert mismatch.value.error_type == "fixture_name_mismatch"
    assert harness.git_client.calls == []
    assert mismatched.git_client.calls == []


def test_stage2_fixture_review_rejects_head_commit_mismatch(
    tmp_path: Path,
) -> None:
    harness = make_stage2_harness(
        tmp_path, git_client=FakeGitClient(head_sha="b" * 40)
    )

    with pytest.raises(ReviewServiceError) as caught:
        harness.service.review_stage2_fixture(
            workspace_path=harness.workspace,
            commit_sha=COMMIT_SHA,
            trusted_fixture="trusted_fixture_v1",
        )

    assert caught.value.stage == "fixture"
    assert caught.value.error_type == "fixture_commit_mismatch"
    assert not (tmp_path / "reports").exists()


def test_review_trusted_fixture_keeps_stage1_behavior_on_stage2_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    verified = SimpleNamespace(
        name="trusted_fixture_v1",
        root=fixture_root,
        version="1.0.0",
        manifest_sha256=FIXTURE_MANIFEST_SHA,
    )
    monkeypatch.setattr(
        review_service_module,
        "verify_trusted_fixture",
        lambda *, expected_name: verified,
    )
    monkeypatch.setattr(
        review_service_module,
        "DEFAULT_TRUSTED_FIXTURE_ROOT",
        fixture_root,
    )
    executed = make_test_result(
        ExecutionStatus.EXECUTED,
        trusted_fixture=True,
        read_only_verified=True,
    )
    harness = make_stage2_harness(
        tmp_path,
        workspace=fixture_root,
        test_result=executed,
        id_factory=lambda _: "stage1-test-review",
    )

    outcome = harness.service.review_trusted_fixture()

    assert outcome.review_stage == "stage_1"
    assert outcome.commit_sha is None
    assert outcome.report_json_path is None
    assert {path.name for path in outcome.report_dir.iterdir()} == {
        "metadata.json",
        "static_analysis.json",
        "test_report.json",
        "report.md",
    }
    metadata = json.loads(
        outcome.metadata_path.read_text(encoding="utf-8")
    )
    assert metadata["stage"] == "stage_1"
    assert metadata["commit_sha"] is None
    assert harness.test_runner.calls == ["trusted_fixture_v1"]
    assert harness.manager.cleanup_calls == []
