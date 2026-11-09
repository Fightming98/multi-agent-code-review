"""阶段 0 任务合同单元测试。

覆盖 docs/task_contracts.md 中属于 Schema 层的规则：
TK-01, TK-02, TK-03, TK-04, TK-05, TK-06, TK-07, TK-08, TK-09, TK-10,
TK-11, TK-12, TK-13；ST-01, ST-02, ST-03, ST-05。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from code_review.schemas import AgentTask, ErrorInfo, is_transition_allowed

COMMIT_SHA = "9fceb02d0ae598e95dc970b74767f19372d61af8"
CREATED_AT = "2026-11-08T10:00:00Z"
STARTED_AT = "2026-11-08T10:00:01Z"
FINISHED_AT = "2026-11-08T10:00:02Z"

RETRYABLE_ERROR = {
    "error_type": "timeout",
    "message": "执行超时",
    "retryable": True,
}
FINAL_ERROR = {
    "error_type": "invalid_input",
    "message": "输入非法",
    "retryable": False,
}


def make_task(**overrides):
    """构造最小合法任务，可按需覆盖字段。"""

    data = {
        "review_id": "review-001",
        "agent_name": "SecurityAgent",
        "task_type": "security_review",
        "description": "检查仓库是否存在安全漏洞",
        "input_data": {
            "repository_path": "/workspace/review-001/repo",
            "commit_sha": COMMIT_SHA,
            "language": "python",
        },
        "expected_output": {
            "result_schema": "AgentResult",
            "must_include_evidence": True,
        },
    }
    data.update(overrides)
    return AgentTask.model_validate(data)


# docs/task_contracts.md §4.6 的三个完整示例。
_DOC_TASK_EXAMPLES = [
    {
        "schema_version": "1.0",
        "task_id": "task-main-001",
        "parent_task_id": None,
        "review_id": "review-001",
        "agent_name": "ManagerAgent",
        "task_type": "review_orchestration",
        "description": "编排 review-001 的完整代码审查流程",
        "input_data": {
            "repository_url": "https://github.com/owner/demo-project",
            "branch": "main",
            "commit_sha": COMMIT_SHA,
            "repository_path": "/workspace/review-001/repo",
            "language": "python",
        },
        "expected_output": {"deliverable": "task_plan"},
        "priority": "medium",
        "required": True,
        "status": "running",
        "retry_count": 0,
        "max_retries": 0,
        "timeout_seconds": None,
        "created_at": "2026-11-08T10:00:00Z",
        "started_at": "2026-11-08T10:00:01Z",
        "finished_at": None,
        "last_error": None,
    },
    {
        "schema_version": "1.0",
        "task_id": "task-security-001",
        "parent_task_id": "task-main-001",
        "review_id": "review-001",
        "agent_name": "SecurityAgent",
        "task_type": "security_review",
        "description": "检查仓库是否存在安全漏洞，包括注入风险与硬编码凭证",
        "input_data": {
            "repository_path": "/workspace/review-001/repo",
            "commit_sha": COMMIT_SHA,
            "language": "python",
            "target_files": ["src/auth.py", "src/database.py", "src/config.py"],
            "rules": {},
        },
        "expected_output": {
            "result_schema": "AgentResult",
            "must_include_evidence": True,
            "finding_categories": [
                "sql_injection",
                "hardcoded_secret",
                "command_injection",
            ],
        },
        "priority": "high",
        "required": True,
        "status": "pending",
        "retry_count": 0,
        "max_retries": 2,
        "timeout_seconds": 120,
        "created_at": "2026-11-08T10:00:02Z",
        "started_at": None,
        "finished_at": None,
        "last_error": None,
    },
    {
        "schema_version": "1.0",
        "task_id": "task-security-001-02",
        "parent_task_id": "task-security-001",
        "review_id": "review-001",
        "agent_name": "SecretScannerSubAgent",
        "task_type": "secret_scan",
        "description": "扫描仓库中的硬编码密钥与凭证",
        "input_data": {
            "repository_path": "/workspace/review-001/repo",
            "commit_sha": COMMIT_SHA,
            "language": "python",
        },
        "expected_output": {
            "result_schema": "AgentResult",
            "must_include_evidence": True,
            "finding_categories": ["hardcoded_secret"],
        },
        "priority": "high",
        "required": True,
        "status": "failed",
        "retry_count": 2,
        "max_retries": 2,
        "timeout_seconds": 60,
        "created_at": "2026-11-08T10:00:05Z",
        "started_at": "2026-11-08T10:01:10Z",
        "finished_at": "2026-11-08T10:02:10Z",
        "last_error": {
            "error_type": "timeout",
            "message": "密钥扫描工具执行超过 60 秒",
            "retryable": True,
            "occurred_at": "2026-11-08T10:02:10Z",
            "details": {},
        },
    },
]


def test_minimal_task_defaults_and_unique_ids_TK_08():
    first = make_task()
    second = make_task()

    assert first.status == "pending"
    assert first.priority == "medium"
    assert first.required is True
    assert first.retry_count == 0
    assert first.max_retries == 2
    assert first.timeout_seconds is None
    assert first.parent_task_id is None
    assert first.last_error is None
    assert first.created_at.tzinfo is not None
    assert first.created_at.utcoffset() == timedelta(0)
    assert first.task_id != second.task_id


def test_parent_task_id_null_and_value():
    root = make_task()
    child = make_task(parent_task_id="task-main-001")

    assert root.parent_task_id is None
    assert child.parent_task_id == "task-main-001"


def test_depth_two_subtask_record_is_valid_TK_02():
    """合同允许深度 2 的子任务记录；真实深度需由任务树上下文校验。"""

    task = make_task(
        task_id="task-security-001-01",
        parent_task_id="task-security-001",
    )
    assert task.parent_task_id == "task-security-001"


def test_parent_task_id_cannot_reference_itself_TK_02():
    with pytest.raises(ValidationError, match="parent_task_id"):
        make_task(task_id="task-security-001", parent_task_id="task-security-001")


@pytest.mark.parametrize("status", ["queued", "done", "retrying", "FAILED"])
def test_invalid_status_rejected_TK_03(status):
    with pytest.raises(ValidationError):
        make_task(status=status)


@pytest.mark.parametrize("priority", ["urgent", "critical", "HIGH"])
def test_invalid_priority_rejected_TK_04(priority):
    with pytest.raises(ValidationError):
        make_task(priority=priority)


def test_retry_count_must_not_exceed_max_retries_TK_05():
    with pytest.raises(ValidationError, match="retry_count"):
        make_task(retry_count=3, max_retries=2)


@pytest.mark.parametrize(
    ("retry_count", "max_retries"),
    [(-1, 2), (0, -1), (-1, -1)],
)
def test_negative_retry_fields_rejected_TK_05(retry_count, max_retries):
    with pytest.raises(ValidationError):
        make_task(retry_count=retry_count, max_retries=max_retries)


@pytest.mark.parametrize("timeout", [0, -1, -0.5])
def test_timeout_must_be_positive_TK_06(timeout):
    with pytest.raises(ValidationError):
        make_task(timeout_seconds=timeout)


def test_timeout_accepts_positive_or_null_TK_06():
    assert make_task(timeout_seconds=None).timeout_seconds is None
    assert make_task(timeout_seconds=1.5).timeout_seconds == 1.5


@pytest.mark.parametrize(
    "field",
    ["task_id", "review_id", "agent_name", "task_type", "description"],
)
def test_empty_required_strings_rejected_TK_01(field):
    with pytest.raises(ValidationError):
        make_task(**{field: ""})

    with pytest.raises(ValidationError):
        make_task(**{field: "   "})


def test_description_length_limit_JS_11():
    with pytest.raises(ValidationError):
        make_task(description="x" * 4001)

    assert len(make_task(description="x" * 4000).description) == 4000


def test_failed_status_requires_last_error_TK_09():
    with pytest.raises(ValidationError, match="last_error"):
        make_task(status="failed")

    task = make_task(
        status="failed",
        last_error=RETRYABLE_ERROR,
    )
    assert task.last_error is not None
    assert task.last_error.error_type == "timeout"


def test_extra_fields_rejected_TK_11():
    data = make_task().model_dump()
    data["unexpected_field"] = True

    with pytest.raises(ValidationError, match="unexpected_field"):
        AgentTask.model_validate(data)


@pytest.mark.parametrize(
    "created_at",
    [
        datetime(2026, 11, 8, 10, 0, 0),
        datetime(
            2026,
            11,
            8,
            10,
            0,
            0,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    ],
)
def test_created_at_must_be_utc_TK_10(created_at):
    with pytest.raises(ValidationError):
        make_task(created_at=created_at)


def test_finished_at_must_not_precede_created_at_TK_10():
    with pytest.raises(ValidationError, match="finished_at"):
        make_task(
            status="completed",
            created_at="2026-11-08T10:00:00Z",
            started_at="2026-11-08T10:00:01Z",
            finished_at="2026-11-08T09:59:59Z",
        )


def test_finished_at_must_not_precede_started_at_TK_10():
    with pytest.raises(ValidationError, match="started_at"):
        make_task(
            status="completed",
            created_at="2026-11-08T10:00:00Z",
            started_at="2026-11-08T10:00:05Z",
            finished_at="2026-11-08T10:00:04Z",
        )


def test_error_info_occurred_at_must_be_utc():
    with pytest.raises(ValidationError):
        ErrorInfo.model_validate(
            {
                "error_type": "timeout",
                "message": "执行超时",
                "retryable": True,
                "occurred_at": datetime(2026, 11, 8, 10, 0, 0),
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("input_data", []), ("expected_output", "not-a-dict")],
)
def test_input_and_expected_output_must_be_dicts_TK_07(field, value):
    with pytest.raises(ValidationError):
        make_task(**{field: value})


def test_json_roundtrip_TK_12():
    task = make_task(
        status="failed",
        last_error=RETRYABLE_ERROR,
    )

    restored = AgentTask.model_validate_json(task.model_dump_json())
    assert restored == task


def test_document_task_examples_validate():
    for example in _DOC_TASK_EXAMPLES:
        task = AgentTask.model_validate(example)
        assert task.task_id == example["task_id"]


@pytest.mark.parametrize(
    ("current", "new_status", "expected"),
    [
        ("pending", "running", True),
        ("pending", "cancelled", True),
        ("pending", "completed", False),
        ("pending", "failed", False),
        ("running", "completed", True),
        ("running", "failed", True),
        ("running", "cancelled", True),
        ("running", "pending", False),
        ("completed", "running", False),
        ("completed", "pending", False),
        ("completed", "cancelled", False),
        ("cancelled", "pending", False),
        ("cancelled", "running", False),
        ("failed", "running", False),
        ("failed", "completed", False),
        ("failed", "cancelled", False),
        ("unknown", "pending", False),
    ],
)
def test_status_transition_matrix_ST_01_ST_02(current, new_status, expected):
    assert (
        is_transition_allowed(
            current,
            new_status,
            retry_count=0,
            max_retries=2,
            retryable=True,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("retryable", "retry_count", "max_retries", "expected"),
    [
        (True, 0, 2, True),
        (True, 1, 2, True),
        (True, 2, 2, False),
        (False, 0, 2, False),
    ],
)
def test_failed_to_pending_requires_retryable_and_quota_ST_03(
    retryable, retry_count, max_retries, expected
):
    assert (
        is_transition_allowed(
            "failed",
            "pending",
            retry_count=retry_count,
            max_retries=max_retries,
            retryable=retryable,
        )
        is expected
    )


def test_task_can_transition_to_uses_last_error_ST_03():
    retryable_task = make_task(
        status="failed",
        retry_count=1,
        max_retries=2,
        last_error=RETRYABLE_ERROR,
    )
    non_retryable_task = make_task(
        status="failed",
        created_at=CREATED_AT,
        finished_at=FINISHED_AT,
        last_error=FINAL_ERROR,
    )
    completed_task = make_task(
        status="completed",
        created_at=CREATED_AT,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
    )

    assert retryable_task.can_transition_to("pending") is True
    assert non_retryable_task.can_transition_to("pending") is False
    assert completed_task.can_transition_to("running") is False


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        ("pending", {}),
        ("running", {"started_at": STARTED_AT}),
        (
            "completed",
            {"started_at": STARTED_AT, "finished_at": FINISHED_AT},
        ),
        ("cancelled", {"finished_at": FINISHED_AT}),
        (
            "failed",
            {"started_at": STARTED_AT, "last_error": RETRYABLE_ERROR},
        ),
        (
            "failed",
            {
                "started_at": STARTED_AT,
                "finished_at": FINISHED_AT,
                "last_error": FINAL_ERROR,
            },
        ),
        (
            "failed",
            {
                "started_at": STARTED_AT,
                "finished_at": FINISHED_AT,
                "retry_count": 2,
                "max_retries": 2,
                "last_error": RETRYABLE_ERROR,
            },
        ),
    ],
)
def test_status_timestamp_consistency_valid_TK_13(status, extra):
    task = make_task(
        status=status,
        created_at=CREATED_AT,
        **extra,
    )
    assert task.status == status


@pytest.mark.parametrize(
    ("status", "extra", "match"),
    [
        (
            "pending",
            {"finished_at": FINISHED_AT},
            "pending",
        ),
        ("running", {}, "started_at"),
        (
            "running",
            {"started_at": STARTED_AT, "finished_at": FINISHED_AT},
            "running",
        ),
        ("completed", {}, "finished_at"),
        ("cancelled", {}, "finished_at"),
        (
            "failed",
            {
                "started_at": STARTED_AT,
                "finished_at": FINISHED_AT,
                "last_error": RETRYABLE_ERROR,
            },
            "retryable failed",
        ),
        (
            "failed",
            {"started_at": STARTED_AT, "last_error": FINAL_ERROR},
            "final failed",
        ),
    ],
)
def test_status_timestamp_consistency_invalid_TK_13(
    status, extra, match
):
    with pytest.raises(ValidationError, match=match):
        make_task(status=status, created_at=CREATED_AT, **extra)


def test_retry_after_failure_clears_finished_at_TK_13():
    """重试回到 pending 时：保留 started_at，finished_at 必须为空。"""

    task = make_task(
        status="pending",
        retry_count=1,
        max_retries=2,
        created_at=CREATED_AT,
        started_at=STARTED_AT,
        finished_at=None,
        last_error=RETRYABLE_ERROR,
    )

    assert task.started_at is not None
    assert task.finished_at is None
    assert task.last_error is not None


def test_is_transition_allowed_is_pure_function_ST_05():
    """ST-05：状态迁移合法性由模块级纯函数提供，可独立于任务实例测试。"""

    import inspect

    # 纯函数签名：模块级函数，不依赖 self / cls 或任务实例状态。
    assert inspect.isfunction(is_transition_allowed)
    parameters = inspect.signature(is_transition_allowed).parameters
    assert "self" not in parameters
    assert "cls" not in parameters

    kwargs = {"retry_count": 1, "max_retries": 2, "retryable": True}
    snapshot = dict(kwargs)

    # 相同输入重复调用结果一致，且不修改调用方传入的参数。
    first = is_transition_allowed("failed", "pending", **kwargs)
    second = is_transition_allowed("failed", "pending", **kwargs)
    assert first is True
    assert second is True
    assert isinstance(first, bool)
    assert kwargs == snapshot

    # 迁移条件完全由显式参数决定，不读取 AgentTask 实例或全局可变状态。
    assert (
        is_transition_allowed(
            "failed",
            "pending",
            retry_count=2,
            max_retries=2,
            retryable=True,
        )
        is False
    )
    assert (
        is_transition_allowed(
            "failed",
            "pending",
            retry_count=0,
            max_retries=2,
            retryable=False,
        )
        is False
    )
