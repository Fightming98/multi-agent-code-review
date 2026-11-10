"""Stage 1.6 端到端集成测试。

- 外部样例仓库使用真实 Ruff / Bandit / Radon / RepositoryInspector，但
  仓库获取使用 Fake；测试执行必须保持 ``not_executed``，不运行样例代码。
- 项目自维护可信 Fixture 使用真实 Pytest / Coverage（受控例外）。
- LLM 使用 Fake，不访问网络。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.code_review.reporting.report_generator import ReportGenerator
from src.code_review.services.finding_aggregator import AggregationResult
from src.code_review.services.llm_analyzer import LLMAnalysisResult
from src.code_review.services.review_service import (
    ReviewRequest,
    ReviewService,
)
from src.code_review.tools.bandit_tool import BanditTool
from src.code_review.tools.radon_tool import RadonTool
from src.code_review.tools.repository_inspector import RepositoryInspector
from src.code_review.tools.repository_manager import RepositorySnapshot
from src.code_review.tools.ruff_tool import RuffTool
from src.code_review.tools.test_runner import TestRunner as PytestRunner
from config.settings import Settings
from tests.stage1_helpers import (
    COMMIT_SHA,
    FakeRepositoryManager,
    make_llm_result,
)

URL = "https://github.com/example/project"
SAMPLE_APP = """import sys

import os


def run_command(value):
    return os.system("echo " + value)
"""


@dataclass
class EchoLLM:
    """不联网的 LLM 替身：保留全部确定性 Finding。"""

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
                "finding_count": len(aggregation.findings),
                "workspace_path": workspace_path,
                "allowed_files": list(allowed_files),
            }
        )
        return make_llm_result(
            aggregation.findings,
            model="fake-offline-model",
        )


def make_sample_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "sample_repo"
    package = workspace / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.py").write_text(SAMPLE_APP, encoding="utf-8")
    (workspace / ".env").write_text(
        "API_KEY=integration-secret-value\n", encoding="utf-8"
    )
    return workspace


def make_snapshot(workspace: Path) -> RepositorySnapshot:
    return RepositorySnapshot(
        owner="example",
        name="project",
        repository_url=URL,
        branch="main",
        commit_sha=COMMIT_SHA,
        workspace_path=workspace,
        cloned_at=datetime(2026, 1, 2, tzinfo=UTC),
        size_bytes=100,
        file_count=3,
        git_version="2.40.0",
    )


def build_external_service(
    tmp_path: Path,
    workspace: Path,
) -> tuple[ReviewService, FakeRepositoryManager, EchoLLM]:
    settings = Settings(
        _env_file=None,
        review_output_root=str(tmp_path / "reports"),
        static_tool_timeout_seconds=120,
    )
    manager = FakeRepositoryManager(make_snapshot(workspace))
    llm = EchoLLM()
    service = ReviewService(
        settings,
        repository_manager=manager,
        inspector=RepositoryInspector(settings),
        tools=[RuffTool(settings), BanditTool(settings), RadonTool(settings)],
        test_runner=PytestRunner(settings),
        llm_analyzer=llm,
        report_generator=ReportGenerator(),
    )
    return service, manager, llm


def test_external_repository_review_generates_four_artifacts_without_execution(
    tmp_path: Path,
) -> None:
    workspace = make_sample_workspace(tmp_path)
    service, manager, llm = build_external_service(tmp_path, workspace)

    outcome = service.review(ReviewRequest(URL, branch="main"))

    assert outcome.review_status == "completed"
    assert outcome.test_status == "not_executed"
    assert outcome.llm_status == "completed"
    assert outcome.commit_sha == COMMIT_SHA
    assert outcome.finding_count >= 2
    assert manager.clone_calls == [
        {"repository_url": URL, "branch": "main", "commit_sha": None}
    ]
    assert manager.cleanup_calls
    assert manager.cleanup_calls[0] is manager.snapshot
    assert llm.calls and llm.calls[0]["allowed_files"] == [
        "pkg/__init__.py",
        "pkg/app.py",
    ]

    report_dir = outcome.report_dir
    assert {path.name for path in report_dir.iterdir()} == {
        "metadata.json",
        "static_analysis.json",
        "test_report.json",
        "report.md",
    }
    assert not (report_dir / "report.json").exists()

    metadata = json.loads((report_dir / "metadata.json").read_text("utf-8"))
    static = json.loads(
        (report_dir / "static_analysis.json").read_text("utf-8")
    )
    tests = json.loads((report_dir / "test_report.json").read_text("utf-8"))
    report = (report_dir / "report.md").read_text("utf-8")

    assert metadata["source_type"] == "github_repository"
    assert metadata["commit_sha"] == COMMIT_SHA
    assert set(static["tools"]) == {"ruff", "bandit", "radon"}
    assert static["findings"]
    assert tests["execution_status"] == "not_executed"
    assert tests["trusted_fixture"] is False
    for key in ("collected", "passed", "failed", "skipped", "errors"):
        assert tests["counts"][key] is None
    assert tests["coverage"]["percent_covered"] is None
    assert "## 7. 测试与覆盖率" in report
    assert "不代表测试通过" in report

    # 外部仓库的样例代码不得被执行，也不得在仓库中留下缓存或字节码。
    assert not (workspace / "__pycache__").exists()
    assert not (workspace / ".pytest_cache").exists()
    assert not any(workspace.rglob("*.pyc"))

    artifacts_text = "\n".join(
        path.read_text("utf-8")
        for path in (
            outcome.metadata_path,
            outcome.static_analysis_path,
            outcome.test_report_path,
            outcome.markdown_path,
        )
    )
    assert str(workspace) not in artifacts_text
    assert "integration-secret-value" not in artifacts_text


def test_trusted_fixture_review_executes_tests_and_marks_source(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        review_output_root=str(tmp_path / "reports"),
        static_tool_timeout_seconds=120,
    )
    service = ReviewService(
        settings,
        inspector=RepositoryInspector(settings),
        tools=[RuffTool(settings), BanditTool(settings), RadonTool(settings)],
        test_runner=PytestRunner(settings),
        llm_analyzer=EchoLLM(),
        report_generator=ReportGenerator(),
        allow_trusted_fixture_review=True,
    )

    outcome = service.review_trusted_fixture()

    assert outcome.review_status == "completed"
    assert outcome.test_status == "executed"
    assert outcome.commit_sha is None
    assert outcome.repository_name == "trusted_fixture_v1"
    assert {path.name for path in outcome.report_dir.iterdir()} == {
        "metadata.json",
        "static_analysis.json",
        "test_report.json",
        "report.md",
    }

    metadata = json.loads(
        outcome.metadata_path.read_text(encoding="utf-8")
    )
    tests = json.loads(
        outcome.test_report_path.read_text(encoding="utf-8")
    )
    report = outcome.markdown_path.read_text(encoding="utf-8")

    assert metadata["source_type"] == "trusted_fixture"
    assert metadata["repository_url"] == "fixture://trusted_fixture_v1"
    assert metadata["commit_sha"] is None
    assert len(metadata["fixture_manifest_sha256"]) == 64
    assert tests["trusted_fixture"] is True
    assert tests["data_source"] == "trusted_fixture"
    assert tests["execution_status"] == "executed"
    assert tests["counts"]["passed"] + tests["counts"]["failed"] > 0
    assert tests["coverage"]["percent_covered"] is not None
    assert tests["read_only_verified"] is True
    assert "不伪造 Git Commit" in report
    assert "不代表对外部仓库执行了测试" in report

    from src.code_review.tools.trusted_fixture import DEFAULT_TRUSTED_FIXTURE_ROOT

    fixture = DEFAULT_TRUSTED_FIXTURE_ROOT
    assert not any(
        path.name in {".pytest_cache", "__pycache__"}
        for path in fixture.rglob("*")
    )
    assert not any(fixture.rglob("*.pyc"))


def test_cli_and_api_import_the_same_review_service() -> None:
    import src.code_review.api.app as api_app
    from src.code_review import cli
    from src.code_review.services.review_service import ReviewService

    assert cli.ReviewService is ReviewService
    assert api_app.ReviewService is ReviewService

    cli_source = Path(cli.__file__).read_text(encoding="utf-8")
    api_source = Path(api_app.__file__).read_text(encoding="utf-8")
    for source in (cli_source, api_source):
        assert "RuffTool" not in source
        assert "BanditTool" not in source
        assert "RadonTool" not in source
        assert "aggregate_review_results" not in source
        assert "LLMAnalyzer" not in source
