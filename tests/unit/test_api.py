"""阶段 1 FastAPI 受控同步入口测试。

API 只做参数校验、并发限流与响应转换；本测试注入 Fake ReviewService，
不执行真实审查、不联网、不调用真实 LLM。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import code_review.api.app as api_app
from code_review.api.app import create_app
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
        review_status="completed",
        repository_name="example/project",
        commit_sha=COMMIT_SHA,
        report_dir=report_dir,
        metadata_path=report_dir / "metadata.json",
        static_analysis_path=report_dir / "static_analysis.json",
        test_report_path=report_dir / "test_report.json",
        markdown_path=report_dir / "report.md",
        finding_count=1,
        severity_counts={"medium": 1},
        test_status="not_executed",
        llm_status="completed",
        warnings=(),
        duration_seconds=0.5,
    )


def make_stage2_outcome(tmp_path: Path) -> ReviewOutcome:
    review_id = "stage2-test-review"
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
        report_json_path=report_dir / "report.json",
        finding_count=2,
        severity_counts={"medium": 2},
        test_status="not_executed",
        llm_status="not_configured",
        warnings=("tests not executed",),
        duration_seconds=1.5,
        review_stage="stage_2",
        overall_verdict="COMMENT",
        overall_score=93.75,
        dimension_scores={
            "security": 100.0,
            "quality": 95.0,
            "performance": 90.0,
            "testing": None,
        },
    )


class FakeService:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.requests: list[ReviewRequest] = []
        self.error: Exception | None = None
        self.outcome: ReviewOutcome | None = None
        self.closed = False
        self.started: threading.Event | None = None
        self.release: threading.Event | None = None

    def review(self, request: ReviewRequest) -> ReviewOutcome:
        self.requests.append(request)
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=5)
        if self.error is not None:
            raise self.error
        if self.outcome is not None:
            return self.outcome
        return make_outcome(self.tmp_path)

    def close(self) -> None:
        self.closed = True


def make_client(tmp_path: Path, service: FakeService) -> TestClient:
    settings = Settings(_env_file=None, review_output_root="reports")
    return TestClient(create_app(settings, service=service))


def test_post_review_returns_summary_and_uses_service(
    tmp_path: Path,
) -> None:
    service = FakeService(tmp_path)
    with make_client(tmp_path, service) as client:
        response = client.post(
            "/api/reviews",
            json={
                "repository_url": URL,
                "branch": "main",
                "commit_sha": COMMIT_SHA,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_id"] == "stage1-test-review"
    assert payload["review_status"] == "completed"
    assert payload["repository_name"] == "example/project"
    assert payload["commit_sha"] == COMMIT_SHA
    assert payload["report_path"] == "reports/stage1-test-review"
    assert payload["finding_count"] == 1
    assert payload["severity_counts"] == {"medium": 1}
    assert payload["test_status"] == "not_executed"
    assert payload["llm_status"] == "completed"
    assert service.requests == [
        ReviewRequest(
            repository_url=URL,
            branch="main",
            commit_sha=COMMIT_SHA,
            output_root=None,
        )
    ]
    assert service.closed is False


def test_post_review_returns_stage2_fields_without_host_paths(
    tmp_path: Path,
) -> None:
    service = FakeService(tmp_path)
    service.outcome = make_stage2_outcome(tmp_path)
    with make_client(tmp_path, service) as client:
        response = client.post(
            "/api/reviews", json={"repository_url": URL}
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_stage"] == "stage_2"
    assert payload["review_status"] == "partial"
    assert payload["overall_verdict"] == "COMMENT"
    assert payload["overall_score"] == 93.75
    assert payload["dimension_scores"] == {
        "security": 100.0,
        "quality": 95.0,
        "performance": 90.0,
        "testing": None,
    }
    assert payload["report_path"] == "reports/stage2-test-review"
    assert (
        payload["report_json_path"]
        == "reports/stage2-test-review/report.json"
    )
    assert payload["llm_status"] == "not_configured"
    assert str(tmp_path) not in response.text
    assert "\\" not in payload["report_json_path"]


def test_api_rejects_extra_fields_and_missing_url(tmp_path: Path) -> None:
    service = FakeService(tmp_path)
    with make_client(tmp_path, service) as client:
        extra = client.post(
            "/api/reviews",
            json={"repository_url": URL, "output_root": "/tmp/other"},
        )
        missing = client.post("/api/reviews", json={})
        wrong_method = client.get("/api/reviews")

    assert extra.status_code == 422
    assert missing.status_code == 422
    assert wrong_method.status_code == 405
    assert service.requests == []


@pytest.mark.parametrize(
    ("stage", "status_code"),
    [
        ("validation", 400),
        ("fixture", 400),
        ("repository", 502),
        ("inspection", 500),
        ("graph", 500),
        ("aggregation", 500),
        ("reporting", 500),
        ("internal", 500),
        ("unknown-stage", 500),
    ],
)
def test_service_errors_map_to_http_status(
    tmp_path: Path, stage: str, status_code: int
) -> None:
    service = FakeService(tmp_path)
    service.error = ReviewServiceError(
        "safe failure message",
        stage=stage,
        error_type="test_error",
        retryable=True,
        review_id="stage1-test-review",
    )
    with make_client(tmp_path, service) as client:
        response = client.post("/api/reviews", json={"repository_url": URL})

    assert response.status_code == status_code
    detail = response.json()["detail"]
    assert detail["message"] == "safe failure message"
    assert detail["stage"] == stage
    assert detail["error_type"] == "test_error"
    assert detail["retryable"] is True
    assert detail["review_id"] == "stage1-test-review"


def test_unexpected_error_is_not_leaked(tmp_path: Path) -> None:
    service = FakeService(tmp_path)
    service.error = RuntimeError("secret internal detail")
    with make_client(tmp_path, service) as client:
        response = client.post("/api/reviews", json={"repository_url": URL})

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["message"] == "review failed unexpectedly"
    assert detail["error_type"] == "RuntimeError"
    assert "secret internal detail" not in response.text


def test_second_concurrent_review_is_rejected_with_429(
    tmp_path: Path,
) -> None:
    service = FakeService(tmp_path)
    service.started = threading.Event()
    service.release = threading.Event()
    app = create_app(
        Settings(_env_file=None, review_output_root="reports"),
        service=service,
    )

    def first_request():
        with TestClient(app) as client:
            return client.post("/api/reviews", json={"repository_url": URL})

    def second_request():
        with TestClient(app) as client:
            return client.post("/api/reviews", json={"repository_url": URL})

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_request)
        assert service.started.wait(timeout=5)
        second = executor.submit(second_request)
        second_response = second.result(timeout=5)
        service.release.set()
        first_response = first.result(timeout=5)

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["detail"]["error_type"] == "review_slot_busy"
    assert len(service.requests) == 1


def test_owned_service_is_closed_on_lifespan_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[object] = []

    class OwnedService:
        def __init__(self, settings: object) -> None:
            self.closed = False
            created.append(self)

        def review(self, request: ReviewRequest) -> ReviewOutcome:
            return make_outcome(tmp_path)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(api_app, "ReviewService", OwnedService)
    app = create_app(Settings(_env_file=None, review_output_root="reports"))

    with TestClient(app) as client:
        response = client.post("/api/reviews", json={"repository_url": URL})

    assert response.status_code == 200
    assert len(created) == 1
    assert created[0].closed is True
