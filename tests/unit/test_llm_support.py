"""Stage 2 LLM 安全投影、JSON 解析与 usage 汇总测试。"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from code_review.agents.llm_support import (
    PROMPT_INJECTION_NOTICE,
    LLMProjectionError,
    LLMResponseError,
    LLMUsageError,
    PromptProjection,
    UsageAccumulator,
    build_prompt_projection,
    build_user_prompt,
    describe_llm_error,
    load_agent_prompt,
    parse_json_object,
    request_json,
    validate_json_fields,
)
from tests.stage2_helpers import (
    COMMIT_SHA,
    REVIEW_ID,
    FakeLLMClient,
    make_agent_task,
    make_dispatch,
    make_worker_runtime,
)


def _projection_kwargs(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "agent_name": "SecurityAgent",
        "task_id": "task-security",
        "task_type": "security_review",
        "review_id": REVIEW_ID,
        "commit_sha": COMMIT_SHA,
        "language": "python",
        "task_description": "Review security issues.",
    }
    payload.update(overrides)
    return payload


class TestPromptFiles:
    @pytest.mark.parametrize(
        "agent_name", ["security", "quality", "performance", "testing"]
    )
    def test_loads_all_four_prompts(self, agent_name: str) -> None:
        text = load_agent_prompt(agent_name)
        assert text.strip()
        assert "Agent" in text

    def test_unknown_prompt_is_rejected(self) -> None:
        with pytest.raises(LLMProjectionError):
            load_agent_prompt("manager")
        with pytest.raises(LLMProjectionError):
            load_agent_prompt("../security")

    def test_prompts_include_injection_and_unverified_rules(self) -> None:
        for name in ("security", "quality", "performance", "testing"):
            text = load_agent_prompt(name)
            assert "不可信" in text or "提示注入" in text
            assert "unverified" in text or "verified" in text


class TestPromptProjection:
    def test_valid_projection_and_payload(self) -> None:
        projection = PromptProjection(**_projection_kwargs())
        payload = projection.to_payload()
        assert payload["agent_name"] == "SecurityAgent"
        assert payload["commit_sha"] == COMMIT_SHA
        assert projection.task_description == "Review security issues."
        assert isinstance(projection.source_files, MappingProxyType)

    @pytest.mark.parametrize(
        "field",
        [
            "agent_name",
            "task_id",
            "task_type",
            "review_id",
            "commit_sha",
            "language",
            "task_description",
        ],
    )
    def test_rejects_empty_fields(self, field: str) -> None:
        with pytest.raises(LLMProjectionError):
            PromptProjection(**_projection_kwargs(**{field: ""}))

    def test_rejects_invalid_commit(self) -> None:
        with pytest.raises(LLMProjectionError):
            PromptProjection(
                **_projection_kwargs(commit_sha="A" * 40)
            )

    def test_rules_are_deeply_read_only(self) -> None:
        projection = PromptProjection(
            **_projection_kwargs(
                rules={"nested": {"value": 1}, "items": [1, 2]}
            )
        )
        with pytest.raises(TypeError):
            projection.rules["nested"] = {}  # type: ignore[index]
        with pytest.raises(TypeError):
            projection.rules["nested"]["value"] = 2  # type: ignore[index]
        assert isinstance(projection.rules["items"], tuple)

    def test_projection_is_frozen(self) -> None:
        projection = PromptProjection(**_projection_kwargs())
        with pytest.raises(FrozenInstanceError):
            projection.task_id = "other"  # type: ignore[misc]

    def test_rejects_unsafe_source_path(self) -> None:
        with pytest.raises(LLMProjectionError):
            PromptProjection(
                **_projection_kwargs(
                    source_files={"../secret.py": "x"}
                )
            )

    def test_rejects_unsafe_allowed_path(self) -> None:
        with pytest.raises(LLMProjectionError):
            PromptProjection(
                **_projection_kwargs(
                    allowed_files=("C:/repo/app.py",)
                )
            )

    def test_rejects_non_mapping_rules(self) -> None:
        with pytest.raises(LLMProjectionError):
            PromptProjection(**_projection_kwargs(rules="rules"))

    def test_to_payload_does_not_expose_internal_mappings(self) -> None:
        projection = PromptProjection(
            **_projection_kwargs(
                source_files={"pkg/app.py": "print('x')"},
                rules={"values": [1]},
            )
        )
        payload = projection.to_payload()
        payload["source_files"]["pkg/app.py"] = "changed"
        payload["rules"]["values"].append(2)
        assert projection.source_files["pkg/app.py"] == "print('x')"
        assert projection.rules["values"] == (1,)


class TestBuildProjection:
    def test_projects_only_allowed_files(self, tmp_path: Path) -> None:
        task = make_agent_task(
            description="Review this repository.",
            input_data={"super_secret_token": "should-not-leak"},
        )
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=("pkg/app.py",),
            review_id=task.review_id,
        )
        dispatch = make_dispatch(task=task, runtime=runtime)
        projection = build_prompt_projection(
            dispatch,
            source_files={"pkg/app.py": "print('hello')"},
            tool_outputs={"bandit": "{}"},
        )
        prompt = build_user_prompt(projection)
        assert "print('hello')" in prompt
        assert "super_secret_token" not in prompt
        assert '"input_data"' not in prompt
        assert PROMPT_INJECTION_NOTICE in prompt

    def test_rejects_source_outside_allowed_files(
        self, tmp_path: Path
    ) -> None:
        dispatch = make_dispatch(
            workspace_path=tmp_path,
            task=make_agent_task(input_data={}),
        )
        with pytest.raises(LLMProjectionError):
            build_prompt_projection(
                dispatch,
                source_files={"pkg/other.py": "x"},
            )

    def test_reads_allowed_files_from_workspace(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "pkg"
        source.mkdir()
        (source / "app.py").write_text(
            "password = 'hunter2'\nprint('ok')\n",
            encoding="utf-8",
        )
        task = make_agent_task()
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=("pkg/app.py",),
            review_id=task.review_id,
        )
        projection = build_prompt_projection(
            make_dispatch(task=task, runtime=runtime)
        )
        assert "print('ok')" in projection.source_files["pkg/app.py"]
        assert "hunter2" not in projection.source_files["pkg/app.py"]
        assert "[REDACTED]" in projection.source_files["pkg/app.py"]

    def test_missing_file_is_a_warning(self, tmp_path: Path) -> None:
        task = make_agent_task()
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=("pkg/missing.py",),
            review_id=task.review_id,
        )
        projection = build_prompt_projection(
            make_dispatch(task=task, runtime=runtime)
        )
        assert projection.source_files == {}
        assert any("unavailable" in item for item in projection.warnings)

    def test_source_limit_truncates_and_warns(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "app.py").write_text(
            "x" * 50, encoding="utf-8"
        )
        task = make_agent_task()
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=("pkg/app.py",),
            review_id=task.review_id,
        )
        projection = build_prompt_projection(
            make_dispatch(task=task, runtime=runtime),
            max_source_chars=10,
        )
        assert len(projection.source_files["pkg/app.py"]) == 10
        assert any("truncated" in item for item in projection.warnings)

    def test_workspace_paths_are_replaced(self, tmp_path: Path) -> None:
        task = make_agent_task(
            description=f"Look at {tmp_path / 'pkg' / 'app.py'}",
        )
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=("pkg/app.py",),
            review_id=task.review_id,
        )
        projection = build_prompt_projection(
            make_dispatch(task=task, runtime=runtime),
            source_files={
                "pkg/app.py": f"open('{tmp_path / 'pkg' / 'app.py'}')"
            },
        )
        assert "<workspace>" in projection.task_description
        assert "<workspace>" in projection.source_files["pkg/app.py"]
        assert str(tmp_path) not in projection.task_description

    def test_tool_output_is_bounded(self, tmp_path: Path) -> None:
        task = make_agent_task()
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=(),
            review_id=task.review_id,
        )
        projection = build_prompt_projection(
            make_dispatch(task=task, runtime=runtime),
            tool_outputs={"bandit": "x" * 100},
            max_tool_output_chars=10,
        )
        assert len(projection.tool_outputs["bandit"]) == 10

    def test_too_many_tool_outputs_rejected(self, tmp_path: Path) -> None:
        task = make_agent_task()
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=(),
            review_id=task.review_id,
        )
        with pytest.raises(LLMProjectionError):
            build_prompt_projection(
                make_dispatch(task=task, runtime=runtime),
                tool_outputs={f"tool-{index}": "x" for index in range(11)},
            )

    def test_empty_source_and_tool_values_are_allowed(
        self, tmp_path: Path
    ) -> None:
        task = make_agent_task()
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=("pkg/empty.py",),
            review_id=task.review_id,
        )
        projection = build_prompt_projection(
            make_dispatch(task=task, runtime=runtime),
            source_files={"pkg/empty.py": ""},
            tool_outputs={"bandit": ""},
        )
        assert projection.source_files["pkg/empty.py"] == ""
        assert projection.tool_outputs["bandit"] == ""

    def test_rules_can_be_excluded(self, tmp_path: Path) -> None:
        task = make_agent_task()
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=(),
            review_id=task.review_id,
        )
        projection = build_prompt_projection(
            make_dispatch(task=task, runtime=runtime),
            include_rules=False,
        )
        assert projection.rules == {}

    def test_prompt_budget_omits_trailing_sources(
        self, tmp_path: Path
    ) -> None:
        task = make_agent_task()
        allowed = ("pkg/a.py", "pkg/b.py", "pkg/c.py")
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=allowed,
            review_id=task.review_id,
        )
        projection = build_prompt_projection(
            make_dispatch(task=task, runtime=runtime),
            source_files={
                "pkg/a.py": "a" * 800,
                "pkg/b.py": "b" * 800,
                "pkg/c.py": "c" * 800,
            },
            include_rules=False,
            max_prompt_chars=2000,
        )

        assert len(projection.source_files) < len(allowed)
        assert any(
            "prompt budget" in warning for warning in projection.warnings
        )
        assert len(build_user_prompt(projection, max_chars=2000)) <= 2000

    def test_prompt_budget_too_small_raises(
        self, tmp_path: Path
    ) -> None:
        task = make_agent_task()
        runtime = make_worker_runtime(
            tmp_path,
            allowed_files=("pkg/a.py",),
            review_id=task.review_id,
        )
        with pytest.raises(LLMProjectionError, match="exceeds"):
            build_prompt_projection(
                make_dispatch(task=task, runtime=runtime),
                source_files={"pkg/a.py": "x" * 800},
                include_rules=False,
                max_prompt_chars=100,
            )

    def test_invalid_limits_rejected(self, tmp_path: Path) -> None:
        dispatch = make_dispatch(workspace_path=tmp_path)
        with pytest.raises(LLMProjectionError):
            build_prompt_projection(dispatch, max_source_files=-1)
        with pytest.raises(LLMProjectionError):
            build_prompt_projection(dispatch, max_source_chars=0)
        with pytest.raises(LLMProjectionError):
            build_prompt_projection(dispatch, max_tool_output_chars=0)
        with pytest.raises(LLMProjectionError):
            build_prompt_projection(dispatch, max_prompt_chars=0)


class TestUserPrompt:
    def test_oversized_prompt_is_rejected(self) -> None:
        projection = PromptProjection(
            **_projection_kwargs(
                source_files={"pkg/app.py": "x" * 100},
            )
        )
        with pytest.raises(LLMProjectionError):
            build_user_prompt(projection, max_chars=50)

    def test_invalid_projection_rejected(self) -> None:
        with pytest.raises(LLMProjectionError):
            build_user_prompt("not-a-projection")  # type: ignore[arg-type]


class TestDescribeLLMError:
    def test_project_error_detail_is_reported(self) -> None:
        summary = describe_llm_error(
            LLMProjectionError("user prompt exceeds 100 characters")
        )
        assert summary == (
            "LLMProjectionError: user prompt exceeds 100 characters"
        )

    def test_unknown_exception_only_reports_type(self) -> None:
        summary = describe_llm_error(
            RuntimeError("network disabled for sk-abcdefghijklmnopqrstuvwx")
        )
        assert summary == "RuntimeError"
        assert "sk-" not in summary

    def test_safe_exception_message_is_redacted(self) -> None:
        summary = describe_llm_error(
            LLMResponseError("provider echoed sk-abcdefghijklmnopqrstuvwx")
        )
        assert "[REDACTED]" in summary
        assert "sk-" not in summary


class TestJsonParsing:
    def test_parses_object(self) -> None:
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_parses_json_fence(self) -> None:
        assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    @pytest.mark.parametrize(
        "content",
        [
            "",
            "not-json",
            "[]",
            '{"a": NaN}',
            '{"a": Infinity}',
            "```python\n{}\n```",
        ],
    )
    def test_rejects_invalid_content(self, content: str) -> None:
        with pytest.raises(LLMResponseError):
            parse_json_object(content)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(LLMResponseError):
            parse_json_object(1)  # type: ignore[arg-type]

    def test_rejects_oversized_content(self) -> None:
        with pytest.raises(LLMResponseError):
            parse_json_object('{"a": 1}', max_chars=3)

    def test_rejects_too_deep_content(self) -> None:
        with pytest.raises(LLMResponseError):
            parse_json_object('{"a": {"b": {"c": 1}}}', max_depth=2)

    def test_field_validation(self) -> None:
        assert validate_json_fields(
            {"a": 1, "b": 2}, required={"a"}, optional={"b"}
        ) == {"a": 1, "b": 2}
        with pytest.raises(LLMResponseError):
            validate_json_fields({"a": 1}, required={"a", "c"})
        with pytest.raises(LLMResponseError):
            validate_json_fields({"a": 1, "c": 2}, required={"a"})
        with pytest.raises(LLMResponseError):
            validate_json_fields([], required=set())  # type: ignore[arg-type]


class TestUsageAccumulator:
    def test_no_usage_does_not_fabricate_tokens(self) -> None:
        tracker = UsageAccumulator()
        result = tracker.record_completion(
            type("Completion", (), {"usage": None})()
        )
        assert result.llm_calls == 1
        assert result.reported_usage_calls == 0
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    def test_real_usage_is_accumulated(self) -> None:
        tracker = UsageAccumulator()
        completion = type(
            "Completion",
            (),
            {
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                }
            },
        )()
        tracker.record_completion(completion)
        tracker.record_completion(completion)
        snapshot = tracker.snapshot()
        assert snapshot.llm_calls == 2
        assert snapshot.reported_usage_calls == 2
        assert snapshot.input_tokens == 20
        assert snapshot.output_tokens == 8
        assert snapshot.total_tokens == 28

    def test_usage_without_split_is_not_counted(self) -> None:
        tracker = UsageAccumulator()
        tracker.record_completion(
            type("Completion", (), {"usage": {"total_tokens": 10}})()
        )
        snapshot = tracker.snapshot()
        assert snapshot.llm_calls == 1
        assert snapshot.reported_usage_calls == 0
        assert snapshot.total_tokens == 0

    @pytest.mark.parametrize(
        "usage",
        [
            {"prompt_tokens": -1, "completion_tokens": 1},
            {"prompt_tokens": True, "completion_tokens": 1},
            {"prompt_tokens": 1, "completion_tokens": "1"},
            "not-a-mapping",
        ],
    )
    def test_invalid_usage_is_rejected(self, usage: object) -> None:
        tracker = UsageAccumulator()
        with pytest.raises(LLMUsageError):
            tracker.record_completion(
                type("Completion", (), {"usage": usage})()
            )

    def test_failed_call_is_counted_without_usage(self) -> None:
        tracker = UsageAccumulator()
        snapshot = tracker.record_failed_call()
        assert snapshot.llm_calls == 1
        assert snapshot.reported_usage_calls == 0
        assert snapshot.total_tokens == 0


class TestRequestJson:
    def test_successful_fake_call_and_usage(self) -> None:
        client = FakeLLMClient(
            content='{"findings": [], "summary": "ok"}',
            usage={"prompt_tokens": 3, "completion_tokens": 2},
        )
        result = request_json(
            client,
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=100,
            temperature=0.0,
            timeout_seconds=5.0,
        )
        assert result.payload == {"findings": [], "summary": "ok"}
        assert result.usage.llm_calls == 1
        assert result.usage.reported_usage_calls == 1
        assert result.usage.total_tokens == 5
        assert client.calls[0]["system_prompt"] == "system"
        assert client.calls[0]["user_prompt"] == "user"

    def test_invalid_json_records_call(self) -> None:
        client = FakeLLMClient(content="not-json")
        tracker = UsageAccumulator()
        with pytest.raises(LLMResponseError):
            request_json(
                client,
                system_prompt="system",
                user_prompt="user",
                max_output_tokens=100,
                temperature=0.0,
                timeout_seconds=5.0,
                accumulator=tracker,
            )
        assert tracker.snapshot().llm_calls == 1
        assert len(client.calls) == 1

    def test_client_error_records_failed_call(self) -> None:
        client = FakeLLMClient(error=RuntimeError("network disabled"))
        tracker = UsageAccumulator()
        with pytest.raises(RuntimeError):
            request_json(
                client,
                system_prompt="system",
                user_prompt="user",
                max_output_tokens=100,
                temperature=0.0,
                timeout_seconds=5.0,
                accumulator=tracker,
            )
        assert tracker.snapshot().llm_calls == 1
        assert tracker.snapshot().reported_usage_calls == 0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"system_prompt": ""},
            {"user_prompt": ""},
            {"max_output_tokens": 0},
            {"temperature": math.inf},
            {"timeout_seconds": 0},
        ],
    )
    def test_invalid_request_parameters_do_not_call(
        self, kwargs: dict[str, object]
    ) -> None:
        client = FakeLLMClient()
        params: dict[str, object] = {
            "system_prompt": "system",
            "user_prompt": "user",
            "max_output_tokens": 100,
            "temperature": 0.0,
            "timeout_seconds": 5.0,
        }
        params.update(kwargs)
        with pytest.raises(LLMProjectionError):
            request_json(client, **params)  # type: ignore[arg-type]
        assert client.calls == []

    def test_client_without_complete_is_rejected(self) -> None:
        with pytest.raises(LLMProjectionError):
            request_json(
                object(),  # type: ignore[arg-type]
                system_prompt="system",
                user_prompt="user",
                max_output_tokens=100,
                temperature=0.0,
                timeout_seconds=5.0,
            )

    def test_finish_reason_and_content_are_preserved(self) -> None:
        client = FakeLLMClient(
            content='{"ok": true}',
            finish_reason="length",
        )
        result = request_json(
            client,
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=100,
            temperature=0.0,
            timeout_seconds=5.0,
        )
        assert result.finish_reason == "length"
        assert result.content == '{"ok": true}'
