"""Stage 2 五件报告产物生成器测试。

全部输入来自内存 ``ReviewReport`` 与 ``ArtifactData``，不联网、不调用真实
LLM、不执行被评审仓库代码。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from code_review.agents.contracts import UsageSummary
from code_review.agents.reviewer import FinalReviewer
from code_review.reporting.stage2_models import (
    Stage2MetadataArtifact,
    Stage2StaticAnalysisArtifact,
    Stage2TestReportArtifact,
)
from code_review.reporting.stage2_report_generator import (
    Stage2ArtifactInput,
    Stage2ReportGenerationError,
    Stage2ReportGenerator,
)
from code_review.schemas.report import ReviewReport
from code_review.schemas.result import ToolEvidence
from tests.stage2_helpers import (
    COMMIT_SHA,
    NOW,
    make_dimension_result,
    make_final_review_request,
    make_finding,
    make_inventory_summary,
    make_stage24_artifact_data,
)

APP_SOURCE = '''"""Stage 2 report generator sample module."""

import os

def build_query(user_input):
    return "SELECT * FROM users WHERE name = " + user_input

def run(user_input):
    os.system("echo " + user_input)

# padding line 11
# padding line 12
# padding line 13'''

CONFIRMED_FINDING = make_finding(evidence="sample tool finding")
REVIEWED_AT = NOW


def make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "sample_repo"
    package = workspace / "pkg"
    package.mkdir(parents=True)
    (package / "app.py").write_text(APP_SOURCE, encoding="utf-8")
    return workspace


def build_inputs(
    tmp_path: Path,
    *,
    warnings: tuple[str, ...] = (),
) -> tuple[Stage2ArtifactInput, ReviewReport]:
    workspace = make_workspace(tmp_path)
    artifact_data = make_stage24_artifact_data()
    request = make_final_review_request(
        workspace,
        results={
            "security": make_dimension_result(
                "security",
                findings=[CONFIRMED_FINDING],
            )
        },
        artifact_data=artifact_data,
    )
    report = FinalReviewer().review(request).report
    assert report.findings, "the sample finding must be verified for this test"
    source = Stage2ArtifactInput(
        report=report,
        artifact_data=artifact_data,
        usage_summary=UsageSummary(),
        source_type="github_repository",
        reviewed_at=REVIEWED_AT,
        inventory=make_inventory_summary(),
        review_duration_seconds=1.25,
        warnings=warnings,
        workspace_path=workspace,
    )
    return source, report


def test_generator_writes_five_consistent_artifacts(tmp_path: Path) -> None:
    source, report = build_inputs(tmp_path)

    artifacts = Stage2ReportGenerator().generate(
        source, tmp_path / "reports"
    )

    names = sorted(path.name for path in artifacts.report_dir.iterdir())
    assert names == [
        "metadata.json",
        "report.json",
        "report.md",
        "static_analysis.json",
        "test_report.json",
    ]
    assert artifacts.report_json_path == (
        artifacts.report_dir / "report.json"
    )
    assert artifacts.markdown_path == artifacts.report_dir / "report.md"

    # report.json 必须是冻结 Schema 认可的精确保留值。
    on_disk = ReviewReport.model_validate_json(
        artifacts.report_json_path.read_text(encoding="utf-8")
    )
    assert on_disk == report
    assert on_disk.findings[0].verification_status == "verified"

    metadata = Stage2MetadataArtifact.model_validate_json(
        artifacts.metadata_path.read_text(encoding="utf-8")
    )
    assert metadata.stage == "stage_2"
    assert metadata.source_type == "github_repository"
    assert metadata.commit_sha == COMMIT_SHA
    assert metadata.review_status == report.report_status

    static_payload = json.loads(
        artifacts.static_analysis_path.read_text(encoding="utf-8")
    )
    assert static_payload == thaw(source.artifact_data.static_analysis)
    test_payload = json.loads(
        artifacts.test_report_path.read_text(encoding="utf-8")
    )
    assert test_payload["execution_status"] == "executed"
    Stage2StaticAnalysisArtifact.model_validate(static_payload)
    Stage2TestReportArtifact.model_validate(test_payload)

    markdown = artifacts.markdown_path.read_text(encoding="utf-8")
    assert "Stage 2 代码审查报告" in markdown
    assert report.overall_verdict in markdown
    assert "## 2. 维度评分" in markdown

    # 内存 Pointer 与落盘 Pointer 必须解析到相同记录。
    static_model = Stage2StaticAnalysisArtifact.model_validate(static_payload)
    test_model = Stage2TestReportArtifact.model_validate(test_payload)
    for finding in (*report.findings, *report.rejected_findings):
        for evidence in finding.tool_evidence:
            assert resolve_disk_pointer(
                evidence.raw_output_ref, static_model, test_model
            ) == source.artifact_data.resolve(evidence.raw_output_ref)


def thaw(value):
    """把 ArtifactData 的只读容器转换为可比较的普通 JSON 结构。"""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(item) for item in value]
    return value


def resolve_disk_pointer(pointer: str, static, test):
    file_name, fragment = pointer.split("#", 1)
    node = (
        static.model_dump(mode="json")
        if file_name == "static_analysis.json"
        else test.model_dump(mode="json")
    )
    for token in fragment.strip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def test_markdown_shows_one_decimal_while_json_keeps_exact_score(
    tmp_path: Path,
) -> None:
    source, report = build_inputs(tmp_path)
    source = Stage2ArtifactInput(
        report=report.model_copy(update={"overall_score": 93.75}),
        artifact_data=source.artifact_data,
        usage_summary=source.usage_summary,
        source_type=source.source_type,
        reviewed_at=source.reviewed_at,
        inventory=source.inventory,
        review_duration_seconds=source.review_duration_seconds,
        warnings=source.warnings,
        workspace_path=source.workspace_path,
    )

    artifacts = Stage2ReportGenerator().generate(
        source, tmp_path / "reports"
    )

    report_json = json.loads(
        artifacts.report_json_path.read_text(encoding="utf-8")
    )
    markdown = artifacts.markdown_path.read_text(encoding="utf-8")
    assert report_json["overall_score"] == 93.75
    assert "综合分：93.8" in markdown


def test_generator_refuses_real_llm_usage_without_cost_semantics(
    tmp_path: Path,
) -> None:
    source, _ = build_inputs(tmp_path)
    source = Stage2ArtifactInput(
        report=source.report,
        artifact_data=source.artifact_data,
        usage_summary=UsageSummary(
            llm_calls=1,
            reported_usage_calls=1,
            input_tokens=100,
            output_tokens=20,
        ),
        source_type=source.source_type,
        reviewed_at=source.reviewed_at,
        inventory=source.inventory,
        review_duration_seconds=source.review_duration_seconds,
        warnings=source.warnings,
        workspace_path=source.workspace_path,
    )

    with pytest.raises(Stage2ReportGenerationError):
        Stage2ReportGenerator().generate(source, tmp_path / "reports")

    assert not (tmp_path / "reports" / source.report.review_id).exists()


def test_generator_refuses_existing_output_directory(tmp_path: Path) -> None:
    source, _ = build_inputs(tmp_path)
    existing = tmp_path / "reports" / source.report.review_id
    existing.mkdir(parents=True)

    with pytest.raises(Stage2ReportGenerationError):
        Stage2ReportGenerator().generate(source, tmp_path / "reports")

    assert list(existing.iterdir()) == []


def test_generator_refuses_pointer_missing_from_artifact_data(
    tmp_path: Path,
) -> None:
    source, report = build_inputs(tmp_path)
    broken = CONFIRMED_FINDING.model_copy(
        update={
            "tool_evidence": [
                ToolEvidence(
                    tool_name="bandit",
                    rule_id="B608",
                    tool_version="1.9.4",
                    raw_output_ref=(
                        "static_analysis.json#/agents/security/tools/"
                        "bandit/findings/9"
                    ),
                )
            ]
        }
    )
    source = Stage2ArtifactInput(
        report=report.model_copy(update={"findings": [broken]}),
        artifact_data=source.artifact_data,
        usage_summary=source.usage_summary,
        source_type=source.source_type,
        reviewed_at=source.reviewed_at,
        inventory=source.inventory,
        review_duration_seconds=source.review_duration_seconds,
        warnings=source.warnings,
        workspace_path=source.workspace_path,
    )

    with pytest.raises(Stage2ReportGenerationError):
        Stage2ReportGenerator().generate(source, tmp_path / "reports")

    assert not (tmp_path / "reports" / source.report.review_id).exists()


def test_new_report_fields_are_sanitized(tmp_path: Path) -> None:
    workspace = (tmp_path / "sample_repo").resolve()
    source, _ = build_inputs(
        tmp_path,
        warnings=(f"workspace located at {workspace}",),
    )

    artifacts = Stage2ReportGenerator().generate(
        source, tmp_path / "reports"
    )

    metadata_text = artifacts.metadata_path.read_text(encoding="utf-8")
    report_text = artifacts.report_json_path.read_text(encoding="utf-8")
    markdown = artifacts.markdown_path.read_text(encoding="utf-8")
    assert "<workspace>" in metadata_text
    assert str(workspace.resolve()) not in metadata_text
    assert str(workspace.resolve()) not in report_text
    assert str(workspace.resolve()) not in markdown
