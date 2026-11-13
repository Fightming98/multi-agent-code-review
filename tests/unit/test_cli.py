"""阶段 1 CLI 入口测试：只验证参数解析、委托与输出，不执行真实审查。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from code_review import cli
from code_review.services.review_service import (
    ReviewOutcome,
    ReviewRequest,
    ReviewServiceError,
)
from config.settings import Settings
from tests.stage1_helpers import COMMIT_SHA

URL = "https://github.com/example/project"


def make_outcome(tmp_path: Path) -> ReviewOutcome:
    review_id = "stage1-test-review"
    report_dir = tmp_path / "reports" / review_id
    return ReviewOutcome(
        review_id=review_id,
        review_status="partial",
        repository_name="example/project",
        commit_sha=COMMIT_SHA,
        report_dir=report_dir,
        metadata_path=report_dir / "metadata.json",
        static_analysis_path=report_dir / "static_analysis.json",
        test_report_path=report_dir / "test_report.json",
        markdown_path=report_dir / "report.md",
        finding_count=2,
        severity_counts={"low": 2},
        test_status="not_executed",
        llm_status="completed",
        warnings=("LLM analysis finished with status completed",),
        duration_seconds=1.25,
    )


def make_stage2_outcome(tmp_path: Path) -> ReviewOutcome:
    review_id = "stage2-test-review"
    report_dir = tmp_path / "reports" / review_id
    return ReviewOutcome(
        review_id=review_id,
        review_status="completed",
        repository_name="example/project",
        commit_sha=COMMIT_SHA,
        report_dir=report_dir,
        metadata_path=report_dir / "metadata.json",
        static_analysis_path=report_dir / "static_analysis.json",
        test_report_path=report_dir / "test_report.json",
        markdown_path=report_dir / "report.md",
        report_json_path=report_dir / "report.json",
        finding_count=1,
        severity_counts={"medium": 1},
        test_status="executed",
        llm_status="not_configured",
        warnings=(),
        duration_seconds=0.5,
        review_stage="stage_2",
        overall_verdict="COMMENT",
        overall_score=93.75,
        dimension_scores={"security": 100.0, "testing": None},
    )


class FakeService:
    instances: ClassVar[list[FakeService]] = []
    error: Exception | None = None
    outcome: ReviewOutcome | None = None

    def __init__(self, settings: object) -> None:
        self.settings = settings
        self.request: ReviewRequest | None = None
        self.closed = False
        FakeService.instances.append(self)

    def review(self, request: ReviewRequest) -> ReviewOutcome:
        self.request = request
        if FakeService.error is not None:
            raise FakeService.error
        if FakeService.outcome is not None:
            return FakeService.outcome
        return make_outcome(Path(self.settings))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    FakeService.instances = []
    FakeService.error = None
    FakeService.outcome = None
    monkeypatch.setattr(cli, "Settings", lambda: tmp_path)
    monkeypatch.setattr(cli, "ReviewService", FakeService)
    return FakeService


def test_cli_requires_review_subcommand() -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main([])
    assert caught.value.code == 2

    with pytest.raises(SystemExit) as missing_url:
        cli.main(["review"])
    assert missing_url.value.code == 2


def test_cli_delegates_to_review_service(
    fake_cli, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main(
        [
            "review",
            URL,
            "--branch",
            "main",
            "--commit-sha",
            COMMIT_SHA,
            "--output-dir",
            str(tmp_path / "custom-output"),
        ]
    )

    assert exit_code == 0
    service = fake_cli.instances[-1]
    assert service.request == ReviewRequest(
        repository_url=URL,
        branch="main",
        commit_sha=COMMIT_SHA,
        output_root=str(tmp_path / "custom-output"),
    )
    assert service.closed is True

    output = capsys.readouterr().out
    assert "阶段 1 审查完成" in output
    assert "stage1-test-review" in output
    assert "metadata.json" in output
    assert "report.md" in output
    assert "not_executed" in output


def test_cli_real_llm_requires_complete_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeService.instances = []
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_base_url=None,
        llm_api_key=None,
        llm_model=None,
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "ReviewService", FakeService)

    exit_code = cli.main(["review", URL, "--real-llm"])

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "error[llm]" in error
    assert "LLM_BASE_URL" in error
    assert "sk-" not in error
    assert FakeService.instances == []


def test_cli_json_output_is_machine_readable(
    fake_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main(["review", URL, "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["review_id"] == "stage1-test-review"
    assert payload["review_status"] == "partial"
    assert payload["commit_sha"] == COMMIT_SHA
    assert [Path(item).name for item in payload["artifacts"]] == [
        "metadata.json",
        "static_analysis.json",
        "test_report.json",
        "report.md",
    ]
    assert payload["test_status"] == "not_executed"


def test_cli_reports_service_error_without_traceback(
    fake_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_cli.error = ReviewServiceError(
        "repository clone failed",
        stage="repository",
        error_type="clone_failed",
        review_id="stage1-test-review",
    )

    exit_code = cli.main(["review", URL])

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "error[repository]" in error
    assert "repository clone failed" in error
    assert "review_id=stage1-test-review" in error
    assert "Traceback" not in error
    assert fake_cli.instances[-1].closed is True


def test_cli_reports_unexpected_error_without_traceback(
    fake_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_cli.error = RuntimeError("boom")

    exit_code = cli.main(["review", URL])

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "review failed unexpectedly (RuntimeError)" in error
    assert "boom" not in error
    assert "Traceback" not in error
    assert fake_cli.instances[-1].closed is True


def test_cli_stage2_human_output_shows_verdict_and_scores(
    fake_cli, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_cli.outcome = make_stage2_outcome(tmp_path)

    exit_code = cli.main(["review", URL])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "阶段 2 审查完成" in output
    assert "审查结论       : COMMENT" in output
    # Markdown/CLI 显示一位小数；JSON 保留精确值。
    assert "综合分         : 93.8" in output
    assert "security=100.0" in output
    assert "testing=N/A" in output
    for name in (
        "metadata.json",
        "static_analysis.json",
        "test_report.json",
        "report.json",
        "report.md",
    ):
        assert name in output


def test_cli_stage2_json_output_keeps_exact_score_and_five_artifacts(
    fake_cli, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_cli.outcome = make_stage2_outcome(tmp_path)

    exit_code = cli.main(["review", URL, "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["review_stage"] == "stage_2"
    assert payload["overall_verdict"] == "COMMENT"
    assert payload["overall_score"] == 93.75
    assert payload["dimension_scores"] == {
        "security": 100.0,
        "testing": None,
    }
    assert Path(payload["report_json_path"]).name == "report.json"
    assert [Path(item).name for item in payload["artifacts"]] == [
        "metadata.json",
        "static_analysis.json",
        "test_report.json",
        "report.json",
        "report.md",
    ]
    assert payload["test_status"] == "executed"
    assert payload["llm_status"] == "not_configured"
