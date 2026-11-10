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

import src.code_review.services.review_service as review_service_module
from src.code_review.reporting.report_generator import ReportGenerationError
from src.code_review.services.llm_analyzer import LLMAnalysisStatus
from src.code_review.services.review_service import (
    ReviewRequest,
    ReviewService,
    ReviewServiceError,
)
from src.code_review.tools.file_filters import FileCategory
from src.code_review.tools.repository_inspector import (
    RepositoryFile,
    RepositoryInventory,
)
from src.code_review.tools.repository_manager import (
    CloneError,
    GitNotFoundError,
    RepositorySnapshot,
)
from src.code_review.tools.test_runner import TestExecutionStatus as ExecutionStatus
from config.settings import Settings
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
