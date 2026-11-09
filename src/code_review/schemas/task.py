"""任务数据合同：AgentTask、ErrorInfo 与任务状态迁移。

对应 docs/task_contracts.md §4、§6、§7。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
TaskPriority = Literal["low", "medium", "high"]


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间（JS-03）。"""

    return datetime.now(timezone.utc)


def _require_non_empty(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be a timezone-aware UTC datetime"
        )
    return value.astimezone(timezone.utc)


class ErrorInfo(BaseModel):
    """失败信息（docs/task_contracts.md §7.1）。"""

    model_config = ConfigDict(extra="forbid")

    error_type: str
    message: str
    retryable: bool
    occurred_at: datetime = Field(default_factory=utc_now)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("error_type", "message")
    @classmethod
    def _non_empty(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("occurred_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "occurred_at")


class AgentTask(BaseModel):
    """任务定义（docs/task_contracts.md §4.1）。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_task_id: str | None = None
    review_id: str
    agent_name: str
    task_type: str
    description: str = Field(max_length=4000)
    input_data: dict[str, Any]
    expected_output: dict[str, Any]
    priority: TaskPriority = "medium"
    required: bool = True
    status: TaskStatus = "pending"
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=2, ge=0)
    timeout_seconds: float | None = Field(default=None, gt=0)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: ErrorInfo | None = None

    @field_validator(
        "schema_version",
        "task_id",
        "review_id",
        "agent_name",
        "task_type",
        "description",
    )
    @classmethod
    def _required_non_empty(cls, value: str, info: Any) -> str:
        return _require_non_empty(value, info.field_name)

    @field_validator("parent_task_id")
    @classmethod
    def _parent_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value, "parent_task_id")

    @field_validator("created_at", "started_at", "finished_at")
    @classmethod
    def _utc_datetimes(
        cls, value: datetime | None, info: Any
    ) -> datetime | None:
        if value is None:
            return None
        return _require_utc(value, info.field_name)

    @model_validator(mode="after")
    def _check_consistency(self) -> "AgentTask":
        if self.parent_task_id == self.task_id:
            raise ValueError("parent_task_id must not equal task_id")
        if self.retry_count > self.max_retries:
            raise ValueError("retry_count must be <= max_retries")
        if self.status == "failed" and self.last_error is None:
            raise ValueError("status 'failed' requires last_error")

        # TK-10：finished_at 不得早于 created_at 与 started_at。
        if self.finished_at is not None:
            if self.finished_at < self.created_at:
                raise ValueError(
                    "finished_at must not be earlier than created_at"
                )
            if (
                self.started_at is not None
                and self.finished_at < self.started_at
            ):
                raise ValueError(
                    "finished_at must not be earlier than started_at"
                )

        self._check_status_timestamps()
        return self

    def _check_status_timestamps(self) -> None:
        """TK-13：状态与时间戳必须一致。"""

        if self.status == "pending":
            if self.finished_at is not None:
                raise ValueError(
                    "pending status requires finished_at = null"
                )
            return

        if self.status == "running":
            if self.started_at is None:
                raise ValueError("running status requires started_at")
            if self.finished_at is not None:
                raise ValueError(
                    "running status requires finished_at = null"
                )
            return

        if self.status in {"completed", "cancelled"}:
            if self.finished_at is None:
                raise ValueError(
                    f"{self.status} status requires finished_at"
                )
            return

        # status == "failed"
        assert self.last_error is not None  # 前面已校验
        still_retryable = (
            self.last_error.retryable
            and self.retry_count < self.max_retries
        )
        if still_retryable:
            if self.finished_at is not None:
                raise ValueError(
                    "retryable failed status requires finished_at = null"
                )
        elif self.finished_at is None:
            raise ValueError(
                "final failed status requires finished_at"
            )

    def can_transition_to(self, new_status: TaskStatus) -> bool:
        """判断当前任务是否可以迁移到 new_status（ST-01～ST-03）。"""

        retryable = self.last_error is not None and self.last_error.retryable
        return is_transition_allowed(
            self.status,
            new_status,
            retry_count=self.retry_count,
            max_retries=self.max_retries,
            retryable=retryable,
        )


_ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"completed", "failed", "cancelled"}),
    "failed": frozenset({"pending"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


def is_transition_allowed(
    current: str,
    new_status: str,
    *,
    retry_count: int = 0,
    max_retries: int = 2,
    retryable: bool = False,
) -> bool:
    """纯函数：校验任务状态迁移是否合法（ST-01～ST-03）。

    ST-03 要求 failed → pending 仅在错误可重试且重试次数未用尽时成立。
    """

    if new_status not in _ALLOWED_STATUS_TRANSITIONS.get(current, frozenset()):
        return False
    if current == "failed" and new_status == "pending":
        return retryable and retry_count < max_retries
    return True
