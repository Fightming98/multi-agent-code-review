"""阶段 1 产物 Pydantic 合同测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.code_review.reporting.artifact_models import (
    CoverageArtifact,
    ExecutionEnvironmentArtifact,
    FixtureArtifact,
    InventorySummaryArtifact,
    LLMAnalysisArtifact,
    MetadataArtifact,
    RawToolFindingArtifact,
    StaticAnalysisArtifact,
    StaticAnalysisStatisticsArtifact,
    ToolRunArtifact,
)
from src.code_review.reporting.artifact_models import (
    TestCountsArtifact as CountsArtifact,
)
from src.code_review.reporting.artifact_models import (
    TestReferenceArtifact as ReferenceArtifact,
)
from src.code_review.reporting.artifact_models import (
    TestReferenceEntryArtifact as ReferenceEntryArtifact,
)
from src.code_review.reporting.artifact_models import (
    TestReportArtifact as ReportArtifact,
)
from tests.stage1_helpers import (
    COMMIT_SHA,
    FIXTURE_MANIFEST_SHA,
    NOW,
    make_finding,
)

ENVIRONMENT = ExecutionEnvironmentArtifact(
    python_version="3.12.16",
    python_implementation="CPython",
    platform_system="Windows",
    platform_release="11",
    platform_machine="AMD64",
)


def github_metadata(**overrides: object) -> MetadataArtifact:
    payload: dict[str, object] = {
        "review_id": "stage1-20260102T030405Z-abcdef12",
        "repository_url": "https://github.com/example/project",
        "repository_name": "example/project",
        "branch": "main",
        "commit_sha": COMMIT_SHA,
        "review_status": "completed",
        "reviewed_at": NOW,
        "discovered_file_count": 3,
        "analyzed_file_count": 2,
        "tool_versions": {"ruff": "0.9.0"},
        "execution_environment": ENVIRONMENT,
        "review_duration_seconds": 1.25,
    }
    payload.update(overrides)
    return MetadataArtifact(**payload)


def fixture_metadata(**overrides: object) -> MetadataArtifact:
    payload: dict[str, object] = {
        "source_type": "trusted_fixture",
        "review_id": "stage1-fixture-review",
        "repository_url": "fixture://trusted_fixture_v1",
        "repository_name": "trusted_fixture_v1",
        "branch": "fixture",
        "commit_sha": None,
        "fixture_manifest_sha256": FIXTURE_MANIFEST_SHA,
        "review_status": "partial",
        "reviewed_at": NOW,
        "discovered_file_count": 4,
        "analyzed_file_count": 3,
        "tool_versions": {"pytest": "8.0.0"},
        "execution_environment": ENVIRONMENT,
        "review_duration_seconds": 2.0,
    }
    payload.update(overrides)
    return MetadataArtifact(**payload)


def tool_run(**overrides: object) -> ToolRunArtifact:
    payload: dict[str, object] = {
        "tool_name": "ruff",
        "tool_version": "0.9.0",
        "execution_status": "findings",
        "exit_code": 1,
        "started_at": NOW,
        "finished_at": NOW,
        "duration_ms": 10,
        "analyzed_file_count": 2,
        "findings": [
            RawToolFindingArtifact(
                tool_name="ruff",
                rule_id="F401",
                file_path="pkg/app.py",
                message="unused import",
                line=1,
            )
        ],
        "finding_count": 1,
    }
    payload.update(overrides)
    return ToolRunArtifact(**payload)


def statistics() -> StaticAnalysisStatisticsArtifact:
    return StaticAnalysisStatisticsArtifact(
        source_finding_count=1,
        mapped_finding_count=1,
        deterministic_finding_count=1,
        final_finding_count=1,
        semantic_finding_count=0,
        duplicate_count=0,
        skipped_finding_count=0,
        test_failure_finding_count=0,
        tool_failure_count=0,
        partial_tool_count=0,
        severity_counts={"low": 1},
        category_counts={"style_violation": 1},
    )


def static_analysis(**overrides: object) -> StaticAnalysisArtifact:
    payload: dict[str, object] = {
        "review_id": "stage1-20260102T030405Z-abcdef12",
        "commit_sha": COMMIT_SHA,
        "generated_at": NOW,
        "tools": {"ruff": tool_run()},
        "tests": ReferenceArtifact(
            pytest=ReferenceEntryArtifact(
                execution_status="not_executed",
                reason="external repository tests are not executed",
            )
        ),
        "findings": [make_finding()],
        "statistics": statistics(),
        "llm_analysis": LLMAnalysisArtifact(
            status="not_configured",
            reason="LLM is not configured",
        ),
    }
    payload.update(overrides)
    return StaticAnalysisArtifact(**payload)


def make_test_report(**overrides: object) -> ReportArtifact:
    payload: dict[str, object] = {
        "review_id": "stage1-20260102T030405Z-abcdef12",
        "commit_sha": COMMIT_SHA,
        "generated_at": NOW,
        "execution_status": "not_executed",
        "data_source": "external_repository",
        "trusted_fixture": False,
        "counts": CountsArtifact(),
        "coverage": CoverageArtifact(),
        "reason": "external repository tests are not executed",
        "duration_ms": 0,
    }
    payload.update(overrides)
    return ReportArtifact(**payload)


def test_metadata_accepts_github_repository_with_fixed_commit() -> None:
    metadata = github_metadata()

    assert metadata.schema_version == "1.0"
    assert metadata.stage == "stage_1"
    assert metadata.source_type == "github_repository"
    assert metadata.commit_sha == COMMIT_SHA
    assert metadata.fixture_manifest_sha256 is None


def test_metadata_accepts_trusted_fixture_without_fake_commit() -> None:
    metadata = fixture_metadata()

    assert metadata.source_type == "trusted_fixture"
    assert metadata.repository_url == "fixture://trusted_fixture_v1"
    assert metadata.commit_sha is None
    assert metadata.fixture_manifest_sha256 == FIXTURE_MANIFEST_SHA


def test_metadata_rejects_github_repository_without_commit() -> None:
    with pytest.raises(ValidationError, match="commit_sha is required"):
        github_metadata(commit_sha=None)


def test_metadata_rejects_non_github_or_credentialed_url() -> None:
    with pytest.raises(ValidationError, match="https://github.com"):
        github_metadata(repository_url="https://gitlab.com/example/project")
    with pytest.raises(ValidationError):
        github_metadata(
            repository_url="https://user:token@github.com/example/project"
        )


def test_metadata_rejects_fixture_commit_or_missing_manifest() -> None:
    with pytest.raises(ValidationError, match="must not claim a Git commit"):
        fixture_metadata(commit_sha=COMMIT_SHA)
    with pytest.raises(ValidationError, match="fixture_manifest_sha256"):
        fixture_metadata(fixture_manifest_sha256=None)


def test_metadata_rejects_unsafe_review_id() -> None:
    for review_id in ("../escape", "a/b", "a..b", ""):
        with pytest.raises(ValidationError):
            github_metadata(review_id=review_id)


def test_metadata_rejects_non_utc_reviewed_at() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        github_metadata(reviewed_at=datetime(2026, 1, 2, 3, 4, 5))
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        github_metadata(
            reviewed_at=datetime(
                2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=8))
            )
        )


def test_inventory_partial_semantics() -> None:
    baseline = InventorySummaryArtifact(
        total_files=1,
        python_source_files=1,
        python_test_files=0,
        filtered_files=0,
        excluded_directories=0,
        total_size_bytes=10,
        scanned_bytes=10,
        total_line_count=1,
    )
    assert baseline.is_partial is False
    with pytest.raises(ValidationError, match="partial_reason is required"):
        InventorySummaryArtifact(**{**baseline.model_dump(), "is_partial": True})
    with pytest.raises(ValidationError, match="partial_reason must be null"):
        InventorySummaryArtifact(
            **{**baseline.model_dump(), "partial_reason": "limit reached"}
        )
    partial = InventorySummaryArtifact(
        **{
            **baseline.model_dump(),
            "is_partial": True,
            "partial_reason": "total_scan_size_limit",
        }
    )
    assert partial.is_partial is True


def test_tool_run_requires_utc_and_safe_paths() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        tool_run(started_at=datetime(2026, 1, 2, 3, 4, 5))
    with pytest.raises(ValidationError, match="safe POSIX"):
        tool_run(
            findings=[
                RawToolFindingArtifact(
                    tool_name="ruff",
                    file_path="../escape.py",
                    message="bad path",
                )
            ]
        )


def test_static_analysis_enforces_stage1_findings() -> None:
    with pytest.raises(ValidationError, match="Stage1Analyzer"):
        static_analysis(findings=[make_finding(agent_name="SecurityAgent")])
    with pytest.raises(ValidationError, match="remain unverified"):
        static_analysis(findings=[make_finding(verification_status="verified")])


def test_static_analysis_requires_tools_and_valid_commit() -> None:
    with pytest.raises(ValidationError):
        static_analysis(tools={})
    with pytest.raises(ValidationError, match="40-character"):
        static_analysis(commit_sha="abc")


def test_static_analysis_allows_null_commit_for_trusted_fixture() -> None:
    artifact = static_analysis(commit_sha=None)
    assert artifact.commit_sha is None


def test_llm_analysis_requires_reason_for_failure_statuses() -> None:
    with pytest.raises(ValidationError, match="reason is required"):
        LLMAnalysisArtifact(status="not_configured")
    with pytest.raises(ValidationError, match="reason is required"):
        LLMAnalysisArtifact(status="timeout")
    completed = LLMAnalysisArtifact(status="completed")
    assert completed.reason is None


def test_test_report_not_executed_requires_null_counts_and_reason() -> None:
    report = make_test_report()
    assert report.counts.passed is None
    assert report.coverage.percent_covered is None

    with pytest.raises(ValidationError, match="must not report counts"):
        make_test_report(
            counts=CountsArtifact(passed=1),
        )
    with pytest.raises(ValidationError, match="must not report coverage"):
        make_test_report(coverage=CoverageArtifact(percent_covered=80.0))
    with pytest.raises(ValidationError, match="must include a reason"):
        make_test_report(reason=None)


def test_test_report_executed_requires_counts_and_coverage() -> None:
    executed = make_test_report(
        execution_status="executed",
        counts=CountsArtifact(
            collected=2,
            passed=2,
            failed=0,
            skipped=0,
            errors=0,
        ),
        coverage=CoverageArtifact(percent_covered=80.0),
        reason=None,
    )
    assert executed.counts.collected == 2
    assert executed.coverage.percent_covered == 80.0

    with pytest.raises(ValidationError, match="all counts"):
        make_test_report(
            execution_status="executed",
            counts=CountsArtifact(collected=1),
            coverage=CoverageArtifact(percent_covered=80.0),
            reason=None,
        )
    with pytest.raises(ValidationError, match="must report coverage"):
        make_test_report(
            execution_status="executed",
            counts=CountsArtifact(
                collected=1,
                passed=1,
                failed=0,
                skipped=0,
                errors=0,
            ),
            reason=None,
        )


def test_test_report_requires_fixture_metadata_and_no_commit() -> None:
    fixture = make_test_report(
        review_id="stage1-fixture-review",
        commit_sha=None,
        execution_status="executed",
        data_source="trusted_fixture",
        trusted_fixture=True,
        fixture=FixtureArtifact(
            name="trusted_fixture_v1",
            version="1.0.0",
            manifest_sha256=FIXTURE_MANIFEST_SHA,
        ),
        counts=CountsArtifact(
            collected=1,
            passed=1,
            failed=0,
            skipped=0,
            errors=0,
        ),
        coverage=CoverageArtifact(percent_covered=100.0),
        reason=None,
    )
    assert fixture.trusted_fixture is True
    assert fixture.commit_sha is None

    with pytest.raises(ValidationError, match="fixture metadata is required"):
        make_test_report(
            commit_sha=None,
            data_source="trusted_fixture",
            trusted_fixture=True,
        )
    with pytest.raises(ValidationError, match="must match data_source"):
        make_test_report(data_source="trusted_fixture", trusted_fixture=False)


def test_test_report_external_requires_commit() -> None:
    with pytest.raises(ValidationError, match="commit_sha is required"):
        make_test_report(commit_sha=None)


def test_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        github_metadata(unexpected="value")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ToolRunArtifact(
            **{
                **tool_run().model_dump(),
                "raw_findings": [],
            }
        )
