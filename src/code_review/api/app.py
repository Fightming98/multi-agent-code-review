"""阶段 1 FastAPI 受控同步入口。

API 只负责 HTTP 参数校验、并发限流与响应转换；实际审查全部交给同一个
``ReviewService``。阶段 1 不引入 Redis / ARQ，HTTP 请求在受控的
单进程、单并发槽位内同步执行。
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from code_review.services.review_service import (
    ReviewOutcome,
    ReviewRequest,
    ReviewService,
    ReviewServiceError,
)
from config.settings import Settings


class ReviewRequestModel(BaseModel):
    """HTTP 审查请求；不接受输出目录等服务器端参数。"""

    model_config = ConfigDict(extra="forbid")

    repository_url: str = Field(min_length=1, max_length=2048)
    branch: str | None = Field(default=None, min_length=1, max_length=255)
    commit_sha: str | None = Field(default=None, min_length=1, max_length=64)


class ReviewResponseModel(BaseModel):
    """HTTP 审查响应摘要。"""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    review_status: str
    repository_name: str
    commit_sha: str | None
    report_path: str
    finding_count: int
    severity_counts: dict[str, int]
    test_status: str
    llm_status: str
    warnings: list[str]
    duration_seconds: float


def create_app(
    settings: Settings | None = None,
    *,
    service: ReviewService | None = None,
) -> FastAPI:
    """创建 API 应用；测试可注入与 CLI 相同的 ReviewService。"""

    resolved_settings = settings or Settings()
    owns_service = service is None
    review_service = service or ReviewService(resolved_settings)
    review_slot = threading.BoundedSemaphore(1)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owns_service:
                review_service.close()

    app = FastAPI(
        title="Multi-Agent Code Review (Stage 1)",
        version="0.1.0",
        description=(
            "阶段 1 受控同步入口：只做参数校验与响应转换，"
            "审查逻辑由 ReviewService 承担。"
        ),
        lifespan=lifespan,
    )

    @app.post(
        "/api/reviews",
        response_model=ReviewResponseModel,
        status_code=200,
        responses={
            400: {"description": "请求参数无效"},
            429: {"description": "当前审查槽位忙碌"},
            502: {"description": "仓库获取失败"},
            500: {"description": "审查内部失败"},
        },
    )
    def create_review(request: ReviewRequestModel) -> ReviewResponseModel:
        if not review_slot.acquire(blocking=False):
            raise HTTPException(
                status_code=429,
                detail={
                    "message": "a review is already running; retry later",
                    "stage": "capacity",
                    "error_type": "review_slot_busy",
                },
            )
        try:
            try:
                outcome = review_service.review(
                    ReviewRequest(
                        repository_url=request.repository_url,
                        branch=request.branch,
                        commit_sha=request.commit_sha,
                    )
                )
            except ReviewServiceError as exc:
                raise _to_http_exception(exc) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "message": "review failed unexpectedly",
                        "stage": "internal",
                        "error_type": type(exc).__name__,
                    },
                ) from exc
            return _to_response(outcome, resolved_settings)
        finally:
            review_slot.release()

    return app


def _to_response(
    outcome: ReviewOutcome,
    settings: Settings,
) -> ReviewResponseModel:
    return ReviewResponseModel(
        review_id=outcome.review_id,
        review_status=outcome.review_status,
        repository_name=outcome.repository_name,
        commit_sha=outcome.commit_sha,
        report_path=_report_reference(settings, outcome.review_id),
        finding_count=outcome.finding_count,
        severity_counts=outcome.severity_counts,
        test_status=outcome.test_status,
        llm_status=outcome.llm_status,
        warnings=list(outcome.warnings),
        duration_seconds=outcome.duration_seconds,
    )


def _report_reference(settings: Settings, review_id: str) -> str:
    """返回相对于配置输出根的引用；不主动暴露额外宿主机路径。"""

    root = str(settings.review_output_root).replace("\\", "/").rstrip("/")
    if root in {"", "."}:
        return review_id
    return f"{root}/{review_id}"


def _to_http_exception(exc: ReviewServiceError) -> HTTPException:
    status_by_stage = {
        "validation": 400,
        "fixture": 400,
        "repository": 502,
        "inspection": 500,
        "aggregation": 500,
        "reporting": 500,
        "internal": 500,
    }
    return HTTPException(
        status_code=status_by_stage.get(exc.stage, 500),
        detail={
            "message": str(exc),
            "stage": exc.stage,
            "error_type": exc.error_type,
            "retryable": exc.retryable,
            "review_id": exc.review_id,
        },
    )


app = create_app()
