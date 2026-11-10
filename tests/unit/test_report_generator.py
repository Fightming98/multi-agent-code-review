"""阶段 1 四件基础产物的生成与净化测试。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from code_review.reporting.artifact_models import (
    MetadataArtifact,
    StaticAnalysisArtifact,
)
from code_review.reporting.artifact_models import (
    TestReportArtifact as ReportArtifact,
)
from code_review.reporting.report_generator import (
    ReportGenerationError,
    ReportGenerator,
    ReportOutputError,
)
from code_review.schemas.task import ErrorInfo
from code_review.services.llm_analyzer import LLMAnalysisStatus
from code_review.tools.base import ToolExecutionStatus
from code_review.tools.test_runner import TestExecutionStatus as ExecutionStatus
from tests.stage1_helpers import (
    FIXTURE_MANIFEST_SHA,
    NOW,
    make_aggregation,
    make_finding,
    make_llm_result,
    make_review_input,
    make_test_result,
    make_tool_finding,
    make_tool_result,
)

SECRET = "supersecretvalue123"
ARTIFACT_NAMES = {
    "metadata.json",
    "static_analysis.json",
    "test_report.json",
    "report.md",
}


def generate(
    tmp_path: Path,
    workspace_path: Path | None = None,
    **overrides: object,
):
    generator = ReportGenerator(clock=lambda: NOW)
    source = make_review_input(
        workspace_path=workspace_path or tmp_path / "workspace",
        **overrides,
    )
    return generator.generate(source, tmp_path / "reports")


def test_generate_writes_exactly_four_artifacts(tmp_path: Path) -> None:
    artifacts = generate(tmp_path)

    names = {path.name for path in artifacts.report_dir.iterdir()}
    assert names == ARTIFACT_NAMES
    assert not (artifacts.report_dir / "report.json").exists()

    metadata = MetadataArtifact.model_validate_json(
        artifacts.metadata_path.read_text(encoding="utf-8")
    )
    static = StaticAnalysisArtifact.model_validate_json(
        artifacts.static_analysis_path.read_text(encoding="utf-8")
    )
    tests = ReportArtifact.model_validate_json(
        artifacts.test_report_path.read_text(encoding="utf-8")
    )
    assert metadata.review_id == artifacts.review_id
    assert static.review_id == artifacts.review_id
    assert tests.review_id == artifacts.review_id
    assert artifacts.markdown_path.read_text(encoding="utf-8").startswith(
        "# 代码审查基础报告"
    )


def test_metadata_records_repository_commit_and_tool_versions(
    tmp_path: Path,
) -> None:
    artifacts = generate(tmp_path)
    payload = json.loads(
        artifacts.metadata_path.read_text(encoding="utf-8")
    )

    assert payload["source_type"] == "github_repository"
    assert payload["repository_url"] == "https://github.com/example/project"
    assert payload["commit_sha"] == "a" * 40
    assert payload["fixture_manifest_sha256"] is None
    assert payload["tool_versions"]["ruff"] == "0.9.0"
    assert payload["tool_versions"]["pytest"] == "8.0.0"
    assert payload["tool_versions"]["coverage"] == "7.4.0"
    assert payload["tool_versions"]["llm"] == "fake-model"
    assert payload["inventory"]["total_files"] == 3


def test_trusted_fixture_metadata_does_not_fake_git_commit(
    tmp_path: Path,
) -> None:
    test_result = make_test_result(
        ExecutionStatus.EXECUTED,
        trusted_fixture=True,
        read_only_verified=True,
    )
    tool_results = (
        make_tool_result("ruff", findings=(make_tool_finding(),)),
        make_tool_result("bandit"),
        make_tool_result("radon"),
    )
    aggregation = make_aggregation(
        tool_results,
        (make_finding(),),
        test_result=test_result,
    )
    artifacts = generate(
        tmp_path,
        review_id="stage1-fixture-review",
        repository_url="fixture://trusted_fixture_v1",
        repository_name="trusted_fixture_v1",
        branch="fixture",
        commit_sha=None,
        fixture_manifest_sha256=FIXTURE_MANIFEST_SHA,
        source_type="trusted_fixture",
        test_result=test_result,
        tool_results=tool_results,
        aggregation=aggregation,
        llm_analysis=make_llm_result(aggregation.findings),
    )

    metadata = json.loads(
        artifacts.metadata_path.read_text(encoding="utf-8")
    )
    tests = json.loads(artifacts.test_report_path.read_text(encoding="utf-8"))
    static = json.loads(
        artifacts.static_analysis_path.read_text(encoding="utf-8")
    )
    report = artifacts.markdown_path.read_text(encoding="utf-8")

    assert metadata["source_type"] == "trusted_fixture"
    assert metadata["commit_sha"] is None
    assert metadata["fixture_manifest_sha256"] == FIXTURE_MANIFEST_SHA
    assert static["commit_sha"] is None
    assert tests["trusted_fixture"] is True
    assert tests["data_source"] == "trusted_fixture"
    assert tests["fixture"]["manifest_sha256"] == FIXTURE_MANIFEST_SHA
    assert "不伪造 Git Commit" in report
    assert FIXTURE_MANIFEST_SHA in report


def test_not_executed_report_keeps_null_counts_and_reason(
    tmp_path: Path,
) -> None:
    artifacts = generate(tmp_path)
    payload = json.loads(
        artifacts.test_report_path.read_text(encoding="utf-8")
    )

    assert payload["execution_status"] == "not_executed"
    assert payload["trusted_fixture"] is False
    assert payload["data_source"] == "external_repository"
    assert payload["reason"] == "external repository tests are not executed"
    for key in ("collected", "passed", "failed", "skipped", "errors"):
        assert payload["counts"][key] is None
    assert payload["coverage"]["percent_covered"] is None


def test_existing_report_directory_is_not_overwritten(tmp_path: Path) -> None:
    existing = tmp_path / "reports" / "stage1-test-review"
    existing.mkdir(parents=True)
    marker = existing / "keep.txt"
    marker.write_text("do not overwrite", encoding="utf-8")

    generator = ReportGenerator(clock=lambda: NOW)
    with pytest.raises(ReportOutputError, match="already exists"):
        generator.generate(
            make_review_input(workspace_path=tmp_path / "workspace"),
            tmp_path / "reports",
        )

    assert marker.read_text(encoding="utf-8") == "do not overwrite"


def test_artifacts_are_sanitized_for_paths_and_secrets(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    stdout = (
        f"workspace={workspace}\n"
        f"home={Path.home()}\n"
        f"temp={tempfile.gettempdir()}\n"
        f"API_KEY={SECRET}\n"
    )
    tool_results = (
        make_tool_result(
            "ruff",
            status=ToolExecutionStatus.FINDINGS,
            findings=(make_tool_finding(),),
            stdout=stdout,
        ),
        make_tool_result(
            "bandit",
            status=ToolExecutionStatus.FAILED,
            error=ErrorInfo(
                error_type="tool_error",
                message=f"failed in {workspace}: API_KEY={SECRET}",
                retryable=False,
            ),
        ),
        make_tool_result("radon"),
    )
    aggregation = make_aggregation(
        tool_results,
        (make_finding(evidence=f"api_key = \"{SECRET}\""),),
    )
    artifacts = generate(
        tmp_path,
        workspace_path=workspace,
        tool_results=tool_results,
        aggregation=aggregation,
        llm_analysis=make_llm_result(
            aggregation.findings,
            status=LLMAnalysisStatus.NOT_CONFIGURED,
        ),
    )

    texts = [
        artifacts.metadata_path.read_text(encoding="utf-8"),
        artifacts.static_analysis_path.read_text(encoding="utf-8"),
        artifacts.test_report_path.read_text(encoding="utf-8"),
        artifacts.markdown_path.read_text(encoding="utf-8"),
    ]
    for text in texts:
        assert SECRET not in text
        assert str(workspace) not in text
        assert str(Path.home()) not in text
        assert str(tempfile.gettempdir()) not in text
    static_text = texts[1]
    assert "<workspace>" in static_text
    assert "[REDACTED]" in static_text


def test_artifacts_sanitize_escaped_windows_paths_in_tool_output(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # 工具 stdout 通常是嵌套 JSON 字符串，写入产物后主机路径会被再次转义。
    nested_stdout = json.dumps(
        {
            "workspace_file": str(workspace / "pkg" / "app.py"),
            "home_file": str(Path.home() / "private" / "key.py"),
            "temp_file": str(Path(tempfile.gettempdir()) / "scratch.py"),
        }
    )
    tool_results = (
        make_tool_result(
            "ruff",
            status=ToolExecutionStatus.FINDINGS,
            findings=(make_tool_finding(),),
            stdout=nested_stdout,
        ),
        make_tool_result("bandit"),
        make_tool_result("radon"),
    )
    aggregation = make_aggregation(tool_results, (make_finding(),))
    artifacts = generate(
        tmp_path,
        workspace_path=workspace,
        tool_results=tool_results,
        aggregation=aggregation,
        llm_analysis=make_llm_result(aggregation.findings),
    )

    static_text = artifacts.static_analysis_path.read_text(encoding="utf-8")
    assert "<workspace>" in static_text
    assert "<home>" in static_text
    assert "<temp>" in static_text
    for leaked in (
        str(workspace),
        str(Path.home()),
        str(tempfile.gettempdir()),
    ):
        assert leaked not in static_text
        assert leaked.replace("\\", "\\\\") not in static_text


def test_finding_evidence_pointers_resolve_in_static_analysis(
    tmp_path: Path,
) -> None:
    artifacts = generate(tmp_path)
    payload = json.loads(
        artifacts.static_analysis_path.read_text(encoding="utf-8")
    )
    finding = payload["findings"][0]

    assert finding["tool_evidence"]
    for evidence in finding["tool_evidence"]:
        reference = evidence["raw_output_ref"]
        assert reference.startswith("static_analysis.json#/")
        node: object = payload
        for token in reference.split("#/", 1)[1].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, list):
                node = node[int(token)]
            else:
                assert isinstance(node, dict)
                node = node[token]
        assert isinstance(node, dict)
        assert node["rule_id"] == "F401"


def test_markdown_is_rendered_from_validated_models(tmp_path: Path) -> None:
    finding = make_finding(title="Unused import in module")
    tool_results = (
        make_tool_result("ruff", findings=(make_tool_finding(),)),
        make_tool_result("bandit"),
        make_tool_result("radon"),
    )
    aggregation = make_aggregation(tool_results, (finding,))
    artifacts = generate(
        tmp_path,
        tool_results=tool_results,
        aggregation=aggregation,
        llm_analysis=make_llm_result((finding,)),
    )

    report = artifacts.markdown_path.read_text(encoding="utf-8")
    assert "Unused import in module" in report
    assert "static_analysis.json#/tools/ruff/findings/0" in report
    assert "本次共产生 1 条 Finding" in report


def test_duplicate_or_missing_tool_results_are_rejected(tmp_path: Path) -> None:
    duplicate = (
        make_tool_result("ruff"),
        make_tool_result("ruff"),
    )
    aggregation = make_aggregation(duplicate, ())
    generator = ReportGenerator(clock=lambda: NOW)
    with pytest.raises(ReportGenerationError, match="duplicate tool result"):
        generator.generate(
            make_review_input(
                workspace_path=tmp_path / "workspace",
                tool_results=duplicate,
                aggregation=aggregation,
                llm_analysis=make_llm_result(()),
            ),
            tmp_path / "reports",
        )
    assert not (tmp_path / "reports" / "stage1-test-review").exists()

    empty_aggregation = make_aggregation((), ())
    with pytest.raises(
        ReportGenerationError, match="no static analysis tool results"
    ):
        generator.generate(
            make_review_input(
                workspace_path=tmp_path / "workspace",
                tool_results=(),
                aggregation=empty_aggregation,
                llm_analysis=make_llm_result(()),
            ),
            tmp_path / "reports",
        )


def test_failed_generation_removes_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> str:
        raise RuntimeError("render failed")

    monkeypatch.setattr(
        "code_review.reporting.markdown_renderer.render_markdown", boom
    )
    generator = ReportGenerator(clock=lambda: NOW)
    with pytest.raises(ReportGenerationError):
        generator.generate(
            make_review_input(workspace_path=tmp_path / "workspace"),
            tmp_path / "reports",
        )
    assert not (tmp_path / "reports" / "stage1-test-review").exists()


def test_review_id_cannot_escape_output_root(tmp_path: Path) -> None:
    generator = ReportGenerator(clock=lambda: NOW)
    source = make_review_input(
        review_id="../escape",
        workspace_path=tmp_path / "workspace",
    )
    with pytest.raises(ValidationError):
        generator.generate(source, tmp_path / "reports")
    assert not (tmp_path / "escape").exists()
