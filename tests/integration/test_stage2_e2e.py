"""Stage 2.6 端到端验收测试：真实工具 + 自有 Fixture + 五件产物。

本测试使用 ``tests/fixtures/stage2_sample_repo/`` 构建真实临时 Git 仓库，
并用真实 Ruff / Bandit / Radon / Pytest / Coverage 执行 Stage 2 工作流。
默认路径不调用真实 LLM；GT-4/GT-7 的受控 Fake LLM 路径单独验证，且不会
生成五件产物（O-1 成本语义未解决）。

测试不联网、不访问 GitHub、不执行外部仓库代码。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from code_review.agents.contracts import ArtifactData
from code_review.agents.evidence import (
    CHECK_IDS,
    STATUS_UNVERIFIED,
    Stage2EvidenceValidator,
)
from code_review.agents.manager import DIMENSIONS
from code_review.agents.reviewer import FinalReviewError
from code_review.graph.state import RepositoryContext, build_initial_state
from code_review.graph.workflow import build_review_graph
from code_review.reporting.report_generator import InventorySummary
from code_review.reporting.stage2_models import (
    STAGE2_CORE_DIMENSIONS,
    Stage2MetadataArtifact,
    Stage2StaticAnalysisArtifact,
    Stage2TestReportArtifact,
)
from code_review.reporting.stage2_report_generator import (
    Stage2ArtifactInput,
    Stage2ReportGenerator,
)
from code_review.schemas.report import ReviewReport
from code_review.services.review_service import (
    ReviewOutcome,
    ReviewService,
    ReviewServiceError,
)
from code_review.services.stage2_factory import (
    Stage2FactoryContext,
    build_stage2_dependencies,
)
from code_review.tools.bandit_tool import BanditTool
from code_review.tools.radon_tool import RadonTool
from code_review.tools.repository_inspector import (
    RepositoryInspector,
    RepositoryInventory,
)
from code_review.tools.ruff_tool import RuffTool
from code_review.tools.stage2_fixture import (
    STAGE2_FIXTURE_NAME,
    STAGE2_FIXTURE_ROOT,
    Stage2FixtureBuild,
    build_stage2_fixture_repository,
)
from code_review.tools.test_runner import TestRunner as FixtureTestRunner
from code_review.tools.trusted_fixture import (
    APPROVED_TRUSTED_FIXTURE_NAMES,
    TrustedFixtureError,
    verify_trusted_fixture,
)
from config.llm_pricing import ModelPricing
from config.settings import Settings
from tests.stage2_helpers import (
    PERFORMANCE_PROMPT_MARKER,
    QUALITY_PROMPT_MARKER,
    RoutedFakeLLMClient,
    find_source_line,
    make_llm_finding_proposal,
    resolve_disk_pointer,
    source_line_text,
)

FIXTURE_TOKEN = "stage2-demo-token"
SOURCE_APP = "sample_app"
PROCESSOR = "sample_app/processor.py"
REPOSITORY = "sample_app/repository.py"
CLIENT_DEFAULTS = "sample_app/client_defaults.py"

OPEN_NEEDLE = 'with open(path, encoding="utf-8") as handle:'
NESTED_LOOP_NEEDLE = "for right in records[index + 1:]:"
SQL_NEEDLE = 'query = "SELECT id, name FROM users WHERE name = \'"'


@dataclass(frozen=True)
class Stage2E2EFixture:
    """一次真实 Stage 2 服务级审查的完整内存与磁盘上下文。"""

    base: Path
    build: Stage2FixtureBuild
    settings: Settings
    inventory: RepositoryInventory
    allowed_files: tuple[str, ...]
    outcome: ReviewOutcome
    source: Stage2ArtifactInput
    report: ReviewReport
    service: ReviewService


class CapturingStage2ReportGenerator(Stage2ReportGenerator):
    """记录生成器输入，并在写盘前断言报告目录尚不存在。

    Final Reviewer 必须只校验内存 ``ArtifactData``。如果它依赖磁盘产物，
    ``generate`` 被调用时报告目录为空这一事实就会暴露问题。
    """

    def __init__(self) -> None:
        self.sources: list[Stage2ArtifactInput] = []

    def generate(self, source: Stage2ArtifactInput, output_root: Path):
        review_dir = Path(output_root) / source.report.review_id
        assert not review_dir.exists(), (
            "Final Reviewer must not depend on on-disk artifacts"
        )
        self.sources.append(source)
        return super().generate(source, output_root)


class FailingBanditTool:
    """模拟 Bandit 进程异常，用于验证 failed AgentResult 的保留。"""

    tool_name = "bandit"

    def run(self, workspace_path: Path, files: list[str]) -> Any:
        raise RuntimeError("simulated bandit failure")


def _make_settings() -> Settings:
    return Settings(
        _env_file=None,
        trusted_fixture_name=STAGE2_FIXTURE_NAME,
        static_tool_timeout_seconds=60,
    )


def _make_test_runner(settings: Settings) -> FixtureTestRunner:
    return FixtureTestRunner(
        settings,
        fixture_root=STAGE2_FIXTURE_ROOT,
        allow_custom_fixture_root=True,
    )


def _make_service(
    settings: Settings,
    *,
    generator: Stage2ReportGenerator,
    tools: tuple[Any, ...] | None = None,
) -> ReviewService:
    return ReviewService(
        settings,
        tools=tools,
        test_runner=_make_test_runner(settings),
        allow_trusted_fixture_review=True,
        multi_agent=True,
        stage2_report_generator=generator,
    )


def _inventory_summary(inventory: RepositoryInventory) -> InventorySummary:
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


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_one(report: ReviewReport, category: str) -> Any:
    matches = [
        finding for finding in report.findings if finding.category == category
    ]
    assert len(matches) == 1, (
        f"expected exactly one {category} finding, got {len(matches)}"
    )
    return matches[0]


def _resolve(source: Stage2ArtifactInput, pointer: str) -> Any:
    return source.artifact_data.resolve(pointer)


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    """分母为 0 时返回 null；不把 0/0 伪造成 0。"""

    if denominator == 0:
        return None
    return numerator / denominator


def _git(
    workspace: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        shell=False,
    )


@pytest.fixture(scope="module")
def stage2_e2e(
    tmp_path_factory: pytest.TempPathFactory,
) -> Stage2E2EFixture:
    base = tmp_path_factory.mktemp("stage2-e2e")
    try:
        build = build_stage2_fixture_repository(base / "repo")
        settings = _make_settings()
        inventory = RepositoryInspector(settings).inspect(
            build.workspace_path
        )
        allowed_files = tuple(
            item.path for item in inventory.python_files
        )
        generator = CapturingStage2ReportGenerator()
        service = _make_service(settings, generator=generator)
        outcome = service.review_stage2_fixture(
            workspace_path=build.workspace_path,
            commit_sha=build.commit_sha,
            trusted_fixture=STAGE2_FIXTURE_NAME,
            output_root=base / "reports",
            fixture_manifest_sha256=build.fixture_manifest_sha256,
        )
        assert len(generator.sources) == 1
        source = generator.sources[0]
        fixture = Stage2E2EFixture(
            base=base,
            build=build,
            settings=settings,
            inventory=inventory,
            allowed_files=allowed_files,
            outcome=outcome,
            source=source,
            report=source.report,
            service=service,
        )
        yield fixture
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ----------------------------------------------------------------------
# Fixture determinism and approval boundary


def test_fixture_commit_sha_is_repeatable_and_backed_by_git(
    tmp_path: Path,
) -> None:
    first = build_stage2_fixture_repository(tmp_path / "first")
    second = build_stage2_fixture_repository(tmp_path / "second")

    assert first.commit_sha == second.commit_sha
    assert re.fullmatch(r"[0-9a-f]{40}", first.commit_sha)
    assert first.commit_sha == _git(
        first.workspace_path, "rev-parse", "--verify", "HEAD^{commit}"
    ).stdout.strip()
    assert _git(
        first.workspace_path, "cat-file", "-t", first.commit_sha
    ).stdout.strip() == "commit"
    assert _git(
        first.workspace_path, "status", "--porcelain"
    ).stdout.strip() == ""

    assert first.commit_message == "stage2 sample fixture"
    assert first.commit_time == "2026-01-01T00:00:00+0000"
    assert first.author_name == "Stage 2 Fixture Builder"
    assert first.author_email == "stage2-fixture@example.invalid"
    assert first.git_version.startswith("git version ")

    assert first.fixture_manifest_sha256 == second.fixture_manifest_sha256
    assert first.file_hashes == second.file_hashes
    assert first.file_count == 11
    manifest_path = first.workspace_path / "FIXTURE_MANIFEST.json"
    assert (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        == first.fixture_manifest_sha256
    )
    for relative, digest in first.file_hashes.items():
        payload = first.workspace_path.joinpath(
            *relative.split("/")
        ).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digest

    source = verify_trusted_fixture(
        STAGE2_FIXTURE_ROOT, expected_name=STAGE2_FIXTURE_NAME
    )
    assert source.manifest_sha256 == first.fixture_manifest_sha256


def test_fixture_approval_is_explicit_and_narrow(
    stage2_e2e: Stage2E2EFixture,
    tmp_path: Path,
) -> None:
    assert set(APPROVED_TRUSTED_FIXTURE_NAMES) == {
        "trusted_fixture_v1",
        STAGE2_FIXTURE_NAME,
    }
    assert verify_trusted_fixture(
        STAGE2_FIXTURE_ROOT, expected_name=STAGE2_FIXTURE_NAME
    ).name == STAGE2_FIXTURE_NAME
    with pytest.raises(TrustedFixtureError):
        verify_trusted_fixture(
            STAGE2_FIXTURE_ROOT, expected_name="trusted_fixture_v1"
        )

    output_root = tmp_path / "reports"
    with pytest.raises(ReviewServiceError) as unapproved:
        stage2_e2e.service.review_stage2_fixture(
            workspace_path=stage2_e2e.build.workspace_path,
            commit_sha=stage2_e2e.build.commit_sha,
            trusted_fixture="unapproved_fixture",
            output_root=output_root,
        )
    assert unapproved.value.error_type == "fixture_not_approved"

    with pytest.raises(ReviewServiceError) as mismatch:
        stage2_e2e.service.review_stage2_fixture(
            workspace_path=stage2_e2e.build.workspace_path,
            commit_sha=stage2_e2e.build.commit_sha,
            trusted_fixture="trusted_fixture_v1",
            output_root=output_root,
        )
    assert mismatch.value.error_type == "fixture_name_mismatch"
    assert not output_root.exists()


# ----------------------------------------------------------------------
# Full service pipeline and five artifacts


def test_service_pipeline_uses_real_tools_and_writes_five_artifacts(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    report = stage2_e2e.report
    outcome = stage2_e2e.outcome
    source = stage2_e2e.source

    assert outcome.review_stage == "stage_2"
    assert outcome.review_status == "completed"
    assert outcome.finding_count == 5
    assert outcome.test_status == "executed"
    assert outcome.llm_status == "not_configured"
    assert outcome.commit_sha == stage2_e2e.build.commit_sha
    assert outcome.report_dir.name == outcome.review_id

    assert report.report_status == "completed"
    assert report.overall_verdict == "APPROVE"
    assert report.overall_score == pytest.approx(94.3)
    assert report.findings and len(report.findings) == 5
    assert report.rejected_findings == []
    assert report.external_agent_results == {}
    assert set(report.dimension_scores) == set(DIMENSIONS)
    assert set(report.agent_results) == set(DIMENSIONS)
    for dimension in DIMENSIONS:
        assert report.agent_results[dimension].status == "completed"
        assert report.agent_results[dimension].execution_time > 0
    assert report.dimension_scores["security"].score == pytest.approx(93.0)
    assert report.dimension_scores["quality"].score == pytest.approx(95.0)
    assert report.dimension_scores["performance"].score == pytest.approx(100.0)
    assert report.dimension_scores["testing"].score == pytest.approx(90.0)
    assert report.dimension_scores["security"].weight == pytest.approx(0.35)
    assert report.dimension_scores["quality"].weight == pytest.approx(0.25)
    assert report.dimension_scores["performance"].weight == pytest.approx(0.20)
    assert report.dimension_scores["testing"].weight == pytest.approx(0.20)

    assert source.usage_summary.llm_calls == 0
    assert source.usage_summary.reported_usage_calls == 0
    assert source.usage_summary.input_tokens == 0
    assert source.usage_summary.output_tokens == 0
    assert report.cost_summary.total_input_tokens == 0
    assert report.cost_summary.total_output_tokens == 0
    assert report.cost_summary.estimated_cost == 0.0

    assert set(outcome.artifact_paths) == {
        outcome.metadata_path,
        outcome.static_analysis_path,
        outcome.test_report_path,
        outcome.report_json_path,
        outcome.markdown_path,
    }
    assert sorted(path.name for path in outcome.report_dir.iterdir()) == [
        "metadata.json",
        "report.json",
        "report.md",
        "static_analysis.json",
        "test_report.json",
    ]

    metadata = Stage2MetadataArtifact.model_validate_json(
        outcome.metadata_path.read_text(encoding="utf-8")
    )
    assert metadata.stage == "stage_2"
    assert metadata.source_type == "trusted_fixture"
    assert metadata.review_id == report.review_id
    assert metadata.repository_url == f"fixture://{STAGE2_FIXTURE_NAME}"
    assert metadata.repository_name == STAGE2_FIXTURE_NAME
    assert metadata.branch == "fixture"
    assert metadata.commit_sha == stage2_e2e.build.commit_sha
    assert re.fullmatch(r"[0-9a-f]{40}", metadata.commit_sha)
    assert (
        metadata.fixture_manifest_sha256
        == stage2_e2e.build.fixture_manifest_sha256
    )
    assert metadata.review_status == "completed"
    assert metadata.discovered_file_count == 12
    # analyzed_file_count 只统计被静态分析的 Python 源文件；3 个测试文件
    # 由 TestingAgent 执行，不计入该字段。
    assert metadata.analyzed_file_count == 6
    assert metadata.inventory is not None
    assert metadata.inventory.total_files == 12
    assert metadata.execution_environment.python_version.startswith("3.12")
    assert {"ruff", "bandit", "radon"} <= set(metadata.tool_versions)
    assert all(
        value is not None and value.strip()
        for key, value in metadata.tool_versions.items()
        if key in {"ruff", "bandit", "radon"}
    )

    static_payload = _read_json(outcome.static_analysis_path)
    static_artifact = Stage2StaticAnalysisArtifact.model_validate(
        static_payload
    )
    assert set(static_artifact.agents) == set(STAGE2_CORE_DIMENSIONS)
    assert static_payload == _thaw(source.artifact_data.static_analysis)

    test_payload = _read_json(outcome.test_report_path)
    test_artifact = Stage2TestReportArtifact.model_validate(test_payload)
    assert test_payload == _thaw(source.artifact_data.test_report)
    assert test_artifact.agent_name == "TestingAgent"
    assert test_artifact.result_status == "completed"

    roundtrip = ReviewReport.model_validate_json(
        outcome.report_json_path.read_text(encoding="utf-8")
    )
    assert roundtrip == report


def test_five_artifacts_match_in_memory_evidence(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    outcome = stage2_e2e.outcome
    source = stage2_e2e.source
    report = stage2_e2e.report
    assert isinstance(source.artifact_data, ArtifactData)

    static_payload = _read_json(outcome.static_analysis_path)
    test_payload = _read_json(outcome.test_report_path)
    assert static_payload == _thaw(source.artifact_data.static_analysis)
    assert test_payload == _thaw(source.artifact_data.test_report)

    documents = {
        "static_analysis.json": static_payload,
        "test_report.json": test_payload,
    }
    pointers = 0
    for finding in (*report.findings, *report.rejected_findings):
        for evidence in finding.tool_evidence:
            pointer = evidence.raw_output_ref
            file_name = pointer.split("#", 1)[0]
            assert file_name in documents
            memory_value = source.artifact_data.resolve(pointer)
            disk_value = resolve_disk_pointer(documents[file_name], pointer)
            assert memory_value == disk_value
            pointers += 1
    # B107 + B608 + Radon（quality/performance 两条证据）+ 两个项目级证据
    assert pointers == 6

    metadata = Stage2MetadataArtifact.model_validate_json(
        outcome.metadata_path.read_text(encoding="utf-8")
    )
    assert metadata.reviewed_at.utcoffset().total_seconds() == 0
    assert metadata.review_duration_seconds >= 0


def test_ground_truth_findings_have_real_evidence(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    report = stage2_e2e.report
    source = stage2_e2e.source
    root = stage2_e2e.build.workspace_path

    gt1_line = find_source_line(root, CLIENT_DEFAULTS, "def build_client(")
    gt2_line = find_source_line(root, REPOSITORY, SQL_NEEDLE)
    gt3_line = find_source_line(root, PROCESSOR, "def classify_record(")
    gt4_line = find_source_line(root, PROCESSOR, OPEN_NEEDLE)
    gt7_line = find_source_line(root, PROCESSOR, NESTED_LOOP_NEEDLE)

    hardcoded = _find_one(report, "hardcoded_secret")
    assert hardcoded.agent_name == "SecurityAgent"
    assert hardcoded.severity == "low"
    assert hardcoded.file_path == CLIENT_DEFAULTS
    assert hardcoded.start_line == gt1_line
    assert hardcoded.verification_status == "verified"
    assert hardcoded.tool_evidence
    assert hardcoded.tool_evidence[0].rule_id == "B107"
    record = _resolve(
        source, hardcoded.tool_evidence[0].raw_output_ref
    )
    assert record["rule_id"] == "B107"
    assert record["severity"] == "LOW"
    assert record["file_path"] == CLIENT_DEFAULTS
    assert record["line"] == gt1_line
    assert FIXTURE_TOKEN not in json.dumps(record, ensure_ascii=False)

    sql = _find_one(report, "sql_injection")
    assert sql.agent_name == "SecurityAgent"
    assert sql.severity == "medium"
    assert sql.file_path == REPOSITORY
    assert sql.start_line == gt2_line
    assert sql.verification_status == "verified"
    assert sql.tool_evidence[0].rule_id == "B608"
    record = _resolve(source, sql.tool_evidence[0].raw_output_ref)
    assert record["rule_id"] == "B608"
    assert record["severity"] == "MEDIUM"
    assert record["line"] == gt2_line

    complexity = _find_one(report, "high_complexity")
    assert complexity.agent_name == "QualityAgent"
    assert complexity.severity == "medium"
    assert complexity.file_path == PROCESSOR
    assert complexity.start_line == gt3_line
    assert complexity.end_line is not None
    assert complexity.end_line > complexity.start_line
    assert complexity.verification_status == "verified"
    assert "PERF-RADON-0004" in complexity.merged_from
    assert len(complexity.tool_evidence) == 2
    pointers = {
        evidence.raw_output_ref for evidence in complexity.tool_evidence
    }
    assert len(pointers) == 2
    for pointer in pointers:
        assert pointer.startswith(
            "static_analysis.json#/agents/"
        ) and "/tools/radon/findings/" in pointer
        record = _resolve(source, pointer)
        assert record["rule_id"] == "RADON_CC"
        assert record["file_path"] == PROCESSOR
        assert record["line"] == gt3_line
        assert record["metadata"]["complexity"] == 22
        assert record["metadata"]["rank"] == "D"
    assert not any(
        finding.agent_name == "PerformanceAgent"
        and finding.category == "high_complexity"
        for finding in report.findings
    )

    test_failure = _find_one(report, "test_failure")
    assert test_failure.agent_name == "TestingAgent"
    assert test_failure.severity == "medium"
    assert test_failure.file_path is None
    assert test_failure.start_line is None
    assert test_failure.end_line is None
    assert test_failure.verification_status == "verified"
    assert [item.raw_output_ref for item in test_failure.tool_evidence] == [
        "test_report.json#/counts"
    ]
    counts = _resolve(source, "test_report.json#/counts")
    assert counts["failed"] == 1
    assert counts["total"] == 8

    low_coverage = _find_one(report, "low_coverage")
    assert low_coverage.agent_name == "TestingAgent"
    assert low_coverage.severity == "medium"
    assert low_coverage.file_path is None
    assert low_coverage.start_line is None
    assert low_coverage.end_line is None
    assert low_coverage.verification_status == "verified"
    assert [
        item.raw_output_ref for item in low_coverage.tool_evidence
    ] == ["test_report.json#/coverage"]
    coverage = _resolve(source, "test_report.json#/coverage")
    assert coverage == pytest.approx(40.48)
    assert coverage < 80

    # GT-4 / GT-7 只能由 Fake LLM 提出；五件产物路径不包含它们。
    assert gt4_line == 54
    assert gt7_line == 63
    assert not any(
        finding.category in {"error_handling", "algorithmic_complexity"}
        for finding in report.findings
    )

    assert all(
        finding.verification_status == "verified"
        for finding in report.findings
    )
    assert not any(
        finding.severity in {"critical", "high"}
        for finding in report.findings
    )
    locations = [
        (finding.category, finding.file_path, finding.start_line)
        for finding in report.findings
    ]
    assert len(locations) == len(set(locations))


def test_testing_results_come_from_real_pytest_and_coverage(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    report = stage2_e2e.report
    test = report.test_summary
    assert test.execution_status == "executed"
    assert test.passed == 7
    assert test.failed == 1
    assert test.skipped == 0
    assert test.coverage == pytest.approx(40.48)
    assert test.source == "pytest+coverage"
    assert test.reason is None

    test_artifact = Stage2TestReportArtifact.model_validate_json(
        stage2_e2e.outcome.test_report_path.read_text(encoding="utf-8")
    )
    assert test_artifact.counts == {
        "total": 8,
        "passed": 7,
        "failed": 1,
        "skipped": 0,
    }
    assert test_artifact.coverage == pytest.approx(40.48)
    assert test_artifact.source == "pytest+coverage"
    assert test_artifact.reason is None
    assert test_artifact.read_only_verified is True
    assert test_artifact.modified_paths == []
    assert test_artifact.fixture == {
        "name": STAGE2_FIXTURE_NAME,
        "version": "1.0.0",
        "manifest_sha256": stage2_e2e.build.fixture_manifest_sha256,
    }
    assert test_artifact.tool_versions["pytest"]
    assert test_artifact.tool_versions["coverage"]

    failed_records = [
        record
        for record in test_artifact.records
        if record["outcome"] == "failed"
    ]
    assert len(failed_records) == 1
    assert failed_records[0]["name"].endswith(
        "test_low_stock_uses_exclusive_threshold"
    )
    assert "AssertionError" in (failed_records[0]["message"] or "")

    covered_files = {
        item["file_path"] for item in test_artifact.coverage_files
    }
    assert {
        "sample_app/inventory.py",
        PROCESSOR,
        REPOSITORY,
        "sample_app/reporting.py",
    } <= covered_files
    assert test_artifact.coverage_files_truncated is False


def test_report_markdown_matches_json_key_fields(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    report = stage2_e2e.report
    markdown = stage2_e2e.outcome.markdown_path.read_text(encoding="utf-8")
    payload = _read_json(stage2_e2e.outcome.report_json_path)

    assert markdown.startswith("# Stage 2 代码审查报告")
    assert f"- Review ID：`{report.review_id}`" in markdown
    assert f"- Commit SHA：`{report.commit_sha}`" in markdown
    assert f"- 结论：**{report.overall_verdict}**" in markdown
    assert "报告状态：`completed`" in markdown
    assert f"综合分：{report.overall_score:.1f}" in markdown
    assert payload["overall_score"] == pytest.approx(report.overall_score)
    assert payload["overall_verdict"] == report.overall_verdict
    assert payload["report_status"] == report.report_status

    for dimension in DIMENSIONS:
        assert dimension in markdown
        assert f"{report.dimension_scores[dimension].weight:.0%}" in markdown
    for finding in report.findings:
        assert f"- 类别：{finding.category}" in markdown

    assert "- 通过：7" in markdown
    assert "- 失败：1" in markdown
    assert "- 覆盖率：40.5%" in markdown
    assert payload["test_summary"]["coverage"] == pytest.approx(40.48)
    assert payload["test_summary"]["execution_status"] == "executed"


def test_artifacts_are_sanitized(stage2_e2e: Stage2E2EFixture) -> None:
    texts = {
        path.name: path.read_text(encoding="utf-8", errors="ignore")
        for path in stage2_e2e.outcome.report_dir.iterdir()
    }
    assert set(texts) == {
        "metadata.json",
        "report.json",
        "report.md",
        "static_analysis.json",
        "test_report.json",
    }
    for name, text in texts.items():
        assert FIXTURE_TOKEN not in text, name
        assert str(stage2_e2e.build.workspace_path) not in text, name
        assert str(stage2_e2e.base) not in text, name
        assert str(Path.home()) not in text, name
    assert "[REDACTED]" in texts["static_analysis.json"]
    assert "[REDACTED]" in texts["report.json"]


def test_failed_agent_result_is_retained_in_report_and_artifacts(
    stage2_e2e: Stage2E2EFixture,
    tmp_path: Path,
) -> None:
    settings = stage2_e2e.settings
    generator = CapturingStage2ReportGenerator()
    service = _make_service(
        settings,
        generator=generator,
        tools=(
            FailingBanditTool(),
            RuffTool(settings),
            RadonTool(settings),
        ),
    )
    outcome = service.review_stage2_fixture(
        workspace_path=stage2_e2e.build.workspace_path,
        commit_sha=stage2_e2e.build.commit_sha,
        trusted_fixture=STAGE2_FIXTURE_NAME,
        output_root=tmp_path / "reports",
        fixture_manifest_sha256=stage2_e2e.build.fixture_manifest_sha256,
    )
    report = generator.sources[0].report

    assert outcome.review_status == "partial"
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    assert report.overall_score is not None
    security = report.agent_results["security"]
    assert security.status == "failed"
    assert security.error is not None
    assert security.error.error_type == "tool_execution_error"
    assert security.findings == []
    assert report.dimension_scores["security"].status == "failed"
    assert report.dimension_scores["security"].score is None
    assert report.dimension_scores["security"].reason
    assert report.dimension_scores["quality"].score is not None
    assert report.dimension_scores["performance"].score is not None
    assert report.dimension_scores["testing"].score is not None
    assert outcome.finding_count == len(report.findings)

    static_payload = _read_json(outcome.static_analysis_path)
    security_block = static_payload["agents"]["security"]
    assert security_block["result_status"] == "failed"
    assert security_block["tools"]["bandit"]["execution_status"] == "failed"
    assert security_block["tools"]["bandit"]["findings"] == []
    assert security_block["tools"]["bandit"]["error"] is not None

    payload = _read_json(outcome.report_json_path)
    assert payload["agent_results"]["security"]["status"] == "failed"
    assert payload["agent_results"]["security"]["error"] is not None
    assert payload["dimension_scores"]["security"]["score"] is None
    assert payload["report_status"] == "partial"
    markdown = outcome.markdown_path.read_text(encoding="utf-8")
    assert "报告状态：`partial`" in markdown
    assert "结论：**COMMENT**" in markdown
    assert sorted(path.name for path in outcome.report_dir.iterdir()) == [
        "metadata.json",
        "report.json",
        "report.md",
        "static_analysis.json",
        "test_report.json",
    ]


# ----------------------------------------------------------------------
# Baseline metrics


def test_baseline_metrics_are_measured_without_thresholds(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    report = stage2_e2e.report
    root = stage2_e2e.build.workspace_path
    gt1 = find_source_line(root, CLIENT_DEFAULTS, "def build_client(")
    gt2 = find_source_line(root, REPOSITORY, SQL_NEEDLE)
    gt3 = find_source_line(root, PROCESSOR, "def classify_record(")
    gt4 = find_source_line(root, PROCESSOR, OPEN_NEEDLE)
    gt7 = find_source_line(root, PROCESSOR, NESTED_LOOP_NEEDLE)
    ground_truth = (
        ("GT-1", "hardcoded_secret", CLIENT_DEFAULTS, gt1),
        ("GT-2", "sql_injection", REPOSITORY, gt2),
        ("GT-3", "high_complexity", PROCESSOR, gt3),
        ("GT-4", "error_handling", PROCESSOR, gt4),
        ("GT-5", "test_failure", None, None),
        ("GT-6", "low_coverage", None, None),
        ("GT-7", "algorithmic_complexity", PROCESSOR, gt7),
    )

    matched: set[str] = set()
    used_findings: set[str] = set()
    for gt_id, category, file_path, line in ground_truth:
        for finding in report.findings:
            if finding.finding_id in used_findings:
                continue
            if finding.category != category:
                continue
            if file_path is not None and finding.file_path != file_path:
                continue
            if line is not None and finding.start_line != line:
                continue
            matched.add(gt_id)
            used_findings.add(finding.finding_id)
            break

    true_positives = len(matched)
    false_negatives = len(ground_truth) - true_positives
    false_positives = len(report.findings) - true_positives
    precision = _safe_ratio(true_positives, true_positives + false_positives)
    recall = _safe_ratio(true_positives, true_positives + false_negatives)
    false_discovery_rate = _safe_ratio(
        false_positives, true_positives + false_positives
    )

    assert matched == {"GT-1", "GT-2", "GT-3", "GT-5", "GT-6"}
    assert true_positives == 5
    assert false_positives == 0
    assert false_negatives == 2
    assert precision == 1.0
    assert recall == pytest.approx(5 / 7)
    assert false_discovery_rate == 0.0
    assert _safe_ratio(0, 0) is None
    assert _safe_ratio(0, 5) == 0.0

    assert stage2_e2e.outcome.duration_seconds > 0
    assert report.execution_summary.duration_seconds > 0
    assert report.execution_summary.total_tasks == 4
    assert report.execution_summary.completed_tasks == 4
    assert (
        report.execution_summary.duration_seconds
        <= stage2_e2e.outcome.duration_seconds + 0.1
    )
    for dimension in DIMENSIONS:
        assert report.agent_results[dimension].execution_time > 0
    assert report.cost_summary.estimated_cost == 0.0


# ----------------------------------------------------------------------
# Controlled Fake LLM paths (GT-4/GT-7 and O-1)


def test_fake_llm_ground_truth_is_detected_but_unverified(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    settings = stage2_e2e.settings
    root = stage2_e2e.build.workspace_path
    quality_line = find_source_line(root, PROCESSOR, OPEN_NEEDLE)
    performance_line = find_source_line(root, PROCESSOR, NESTED_LOOP_NEEDLE)

    fake = RoutedFakeLLMClient(
        {
            QUALITY_PROMPT_MARKER: [
                make_llm_finding_proposal(
                    category="error_handling",
                    severity="medium",
                    title="File read has no error handling",
                    description=(
                        "read_records does not handle missing or unreadable "
                        "files."
                    ),
                    file_path=PROCESSOR,
                    start_line=quality_line,
                    end_line=quality_line,
                    evidence=source_line_text(
                        root, PROCESSOR, quality_line
                    ).strip(),
                    recommendation=(
                        "Handle OSError and UnicodeDecodeError explicitly."
                    ),
                    confidence=0.6,
                )
            ],
            PERFORMANCE_PROMPT_MARKER: [
                make_llm_finding_proposal(
                    category="algorithmic_complexity",
                    severity="medium",
                    title="Nested scan is quadratic",
                    description=(
                        "find_duplicates compares every pair of records."
                    ),
                    file_path=PROCESSOR,
                    start_line=performance_line,
                    end_line=performance_line,
                    evidence=source_line_text(
                        root, PROCESSOR, performance_line
                    ).strip(),
                    recommendation=(
                        "Use a set or counter to detect duplicates in "
                        "linear time."
                    ),
                    confidence=0.6,
                )
            ],
        }
    )
    deps = build_stage2_dependencies(
        Stage2FactoryContext(
            settings=settings,
            tools=(RuffTool(settings), BanditTool(settings), RadonTool(settings)),
            test_runner=_make_test_runner(settings),
            trusted_fixture=STAGE2_FIXTURE_NAME,
        ),
        llm_client=fake,
    )
    plan = deps.manager.plan(
        review_id="review-stage2-fake-llm",
        commit_sha=stage2_e2e.build.commit_sha,
    )
    from tests.stage2_helpers import make_dispatch, make_worker_runtime

    quality_task = plan.task_for("quality")
    performance_task = plan.task_for("performance")
    quality_runtime = make_worker_runtime(
        root,
        allowed_files=stage2_e2e.allowed_files,
        commit_sha=stage2_e2e.build.commit_sha,
        review_id=quality_task.review_id,
        rules=deps.rules,
    )
    performance_runtime = make_worker_runtime(
        root,
        allowed_files=stage2_e2e.allowed_files,
        commit_sha=stage2_e2e.build.commit_sha,
        review_id=performance_task.review_id,
        rules=deps.rules,
    )
    quality_output = asyncio.run(
        deps.graph.agent_for("quality").execute(
            make_dispatch(task=quality_task, runtime=quality_runtime)
        )
    )
    performance_output = asyncio.run(
        deps.graph.agent_for("performance").execute(
            make_dispatch(task=performance_task, runtime=performance_runtime)
        )
    )

    assert fake.markers == [QUALITY_PROMPT_MARKER, PERFORMANCE_PROMPT_MARKER]
    assert quality_output.evidence.usage.llm_calls == 1
    assert quality_output.evidence.usage.reported_usage_calls == 0
    assert quality_output.evidence.usage.input_tokens == 0
    assert quality_output.evidence.usage.output_tokens == 0
    assert performance_output.evidence.usage.llm_calls == 1

    quality_findings = {
        finding.category: finding for finding in quality_output.result.findings
    }
    performance_findings = {
        finding.category: finding
        for finding in performance_output.result.findings
    }
    gt4 = quality_findings["error_handling"]
    gt7 = performance_findings["algorithmic_complexity"]
    assert gt4.file_path == PROCESSOR
    assert gt4.start_line == quality_line
    assert gt4.verification_status == "unverified"
    assert gt4.tool_evidence == []
    assert gt7.file_path == PROCESSOR
    assert gt7.start_line == performance_line
    assert gt7.verification_status == "unverified"
    assert gt7.tool_evidence == []

    validator = Stage2EvidenceValidator(
        workspace_path=root,
        allowed_files=stage2_e2e.allowed_files,
        artifact_data=stage2_e2e.source.artifact_data,
        rules=deps.rules,
    )
    for finding in (gt4, gt7):
        validation = validator.validate(finding)
        assert validation.status == STATUS_UNVERIFIED
        assert validation.evidence_kind == "code_location"
        assert any(
            reason.startswith("V5") and "no tool evidence" in reason
            for reason in validation.reasons
        )
        checks = {check.check_id: check for check in validation.checks}
        # 无工具证据时 V5/V7 不做结构化检查，而是在 reasons 中给出结论。
        assert set(checks) == {"V1", "V2", "V3", "V4", "V6"}
        assert set(checks) <= set(CHECK_IDS)
        for check_id in ("V1", "V2", "V3", "V4"):
            assert checks[check_id].passed, check_id


def test_fake_llm_full_graph_without_pricing_is_blocked(
    stage2_e2e: Stage2E2EFixture,
    tmp_path: Path,
) -> None:
    settings = stage2_e2e.settings
    fake = RoutedFakeLLMClient(
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        }
    )
    deps = build_stage2_dependencies(
        Stage2FactoryContext(
            settings=settings,
            tools=(RuffTool(settings), BanditTool(settings), RadonTool(settings)),
            test_runner=FixtureTestRunner(settings),
            trusted_fixture=None,
        ),
        llm_client=fake,
    )
    state = build_initial_state(
        review_id="review-stage2-o1",
        commit_sha=stage2_e2e.build.commit_sha,
        repository=RepositoryContext(
            repository_url="https://github.com/acme/stage2-fixture",
            repository_name="acme/stage2-fixture",
            branch="main",
            source_type="github_repository",
        ),
        workspace_path=stage2_e2e.build.workspace_path,
        allowed_files=stage2_e2e.allowed_files,
        inventory=_inventory_summary(stage2_e2e.inventory),
        rules=deps.rules,
    )
    output_root = tmp_path / "reports"
    with pytest.raises(FinalReviewError, match="pricing is required"):
        asyncio.run(build_review_graph(deps.graph).ainvoke(state))
    assert set(fake.markers) == {
        QUALITY_PROMPT_MARKER,
        PERFORMANCE_PROMPT_MARKER,
        "# SecurityAgent Prompt",
    }
    assert len(fake.markers) == 3
    assert not output_root.exists()


def test_fake_llm_full_graph_prices_real_usage(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    settings = stage2_e2e.settings
    fake = RoutedFakeLLMClient(
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        }
    )
    pricing = ModelPricing(
        model="fake-model",
        input_per_million_tokens=Decimal("0.25"),
        output_per_million_tokens=Decimal("1.00"),
        currency="USD",
        source_url="https://example.invalid/pricing",
        retrieved_at="2026-11-13",
    )
    deps = build_stage2_dependencies(
        Stage2FactoryContext(
            settings=settings,
            tools=(RuffTool(settings), BanditTool(settings), RadonTool(settings)),
            test_runner=FixtureTestRunner(settings),
            trusted_fixture=None,
        ),
        llm_client=fake,
        model_pricing=pricing,
    )
    state = build_initial_state(
        review_id="review-stage2-o1-priced",
        commit_sha=stage2_e2e.build.commit_sha,
        repository=RepositoryContext(
            repository_url="https://github.com/acme/stage2-fixture",
            repository_name="acme/stage2-fixture",
            branch="main",
            source_type="github_repository",
        ),
        workspace_path=stage2_e2e.build.workspace_path,
        allowed_files=stage2_e2e.allowed_files,
        inventory=_inventory_summary(stage2_e2e.inventory),
        rules=deps.rules,
    )
    output = asyncio.run(build_review_graph(deps.graph).ainvoke(state))
    report = output["review_report"]
    usage = output["usage_summary"]

    assert len(fake.markers) == 3
    assert usage.llm_calls == 3
    assert usage.reported_usage_calls == 3
    assert usage.input_tokens == 300
    assert usage.output_tokens == 60
    assert report.cost_summary.total_input_tokens == 300
    assert report.cost_summary.total_output_tokens == 60
    assert report.cost_summary.currency == "USD"
    assert report.cost_summary.estimated_cost == pytest.approx(
        float(
            (
                Decimal(300) * Decimal("0.25")
                + Decimal(60) * Decimal("1.00")
            )
            / Decimal(1_000_000)
        )
    )


def test_external_testing_not_executed_is_completed(
    stage2_e2e: Stage2E2EFixture,
) -> None:
    settings = stage2_e2e.settings
    deps = build_stage2_dependencies(
        Stage2FactoryContext(
            settings=settings,
            tools=(RuffTool(settings), BanditTool(settings), RadonTool(settings)),
            test_runner=FixtureTestRunner(settings),
            trusted_fixture=None,
        )
    )
    state = build_initial_state(
        review_id="review-stage2-external",
        commit_sha=stage2_e2e.build.commit_sha,
        repository=RepositoryContext(
            repository_url="https://github.com/acme/stage2-fixture",
            repository_name="acme/stage2-fixture",
            branch="main",
            source_type="github_repository",
        ),
        workspace_path=stage2_e2e.build.workspace_path,
        allowed_files=stage2_e2e.allowed_files,
        inventory=_inventory_summary(stage2_e2e.inventory),
        rules=deps.rules,
    )
    output = asyncio.run(build_review_graph(deps.graph).ainvoke(state))
    report = output["review_report"]
    testing = output["testing_result"]

    assert testing.status == "completed"
    assert testing.findings == []
    assert testing.score is None
    assert testing.error is None
    assert report.test_summary.execution_status == "not_executed"
    assert report.test_summary.passed is None
    assert report.test_summary.failed is None
    assert report.test_summary.skipped is None
    assert report.test_summary.coverage is None
    assert report.test_summary.reason
    assert report.dimension_scores["testing"].score is None
    assert report.dimension_scores["testing"].reason
    assert report.report_status == "partial"
    assert report.overall_verdict == "COMMENT"
    assert report.overall_score is not None
    # 图中的 review_status 是 Final Reviewer 节点执行状态，恒为 completed；
    # 报告状态以 report.report_status 为准（ReviewService 同样如此转换）。
    assert output["review_status"] == "completed"
    assert output["review_status"] != report.report_status
