"""阶段 1 CLI 入口测试：只验证参数解析、委托与输出，不执行真实审查。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from src.code_review import cli
from src.code_review.services.review_service import (
    ReviewOutcome,
    ReviewRequest,
    ReviewServiceError,
)
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


class FakeService:
    instances: ClassVar[list[FakeService]] = []
    error: Exception | None = None

    def __init__(self, settings: object) -> None:
        self.settings = settings
        self.request: ReviewRequest | None = None
        self.closed = False
        FakeService.instances.append(self)

    def review(self, request: ReviewRequest) -> ReviewOutcome:
        self.request = request
        if FakeService.error is not None:
            raise FakeService.error
        return make_outcome(Path(self.settings))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    FakeService.instances = []
    FakeService.error = None
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
