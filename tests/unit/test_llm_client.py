"""OpenAI 兼容 LLM 客户端的单元测试（不访问网络）。"""

from __future__ import annotations

import json

import httpx
import pytest

from src.code_review.services.llm_client import (
    LLMClientError,
    OpenAICompatibleClient,
)

API_KEY = "test-api-key-should-not-leak"


def make_client(
    handler: httpx.MockTransport,
    *,
    base_url: str = "https://api.example.com/v1",
    max_response_bytes: int = 2 * 1024 * 1024,
) -> OpenAICompatibleClient:
    http_client = httpx.Client(transport=handler)
    return OpenAICompatibleClient(
        base_url=base_url,
        api_key=API_KEY,
        model="test-model",
        http_client=http_client,
        max_response_bytes=max_response_bytes,
    )


def success_response(
    content: str = "hello",
    *,
    finish_reason: str = "stop",
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "test-model",
            "choices": [
                {
                    "message": {"content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 4,
                "total_tokens": 7,
            },
        },
    )


def test_successful_completion_sends_expected_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return success_response()

    client = make_client(httpx.MockTransport(handler))

    result = client.complete(
        system_prompt="system",
        user_prompt="user",
        max_output_tokens=123,
        temperature=0.0,
        timeout_seconds=5,
    )

    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    headers = captured["headers"]
    assert headers["authorization"] == f"Bearer {API_KEY}"
    body = captured["body"]
    assert body["model"] == "test-model"
    assert body["max_tokens"] == 123
    assert body["temperature"] == 0.0
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert result.content == "hello"
    assert result.model == "test-model"
    assert result.finish_reason == "stop"
    assert result.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }


def test_timeout_is_reported_as_timed_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    client = make_client(httpx.MockTransport(handler))

    with pytest.raises(LLMClientError) as excinfo:
        client.complete(
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=10,
            temperature=0.0,
            timeout_seconds=1,
        )

    assert excinfo.value.timed_out is True
    assert excinfo.value.reason == "model request timed out"


def test_http_error_does_not_include_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text="upstream secret: should-not-appear",
        )

    client = make_client(httpx.MockTransport(handler))

    with pytest.raises(LLMClientError) as excinfo:
        client.complete(
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=10,
            temperature=0.0,
            timeout_seconds=1,
        )

    assert "status 500" in excinfo.value.reason
    assert "should-not-appear" not in excinfo.value.reason


def test_redirect_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.example"})

    client = make_client(httpx.MockTransport(handler))

    with pytest.raises(LLMClientError, match="redirected"):
        client.complete(
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=10,
            temperature=0.0,
            timeout_seconds=1,
        )


def test_invalid_json_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client = make_client(httpx.MockTransport(handler))

    with pytest.raises(LLMClientError, match="valid JSON"):
        client.complete(
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=10,
            temperature=0.0,
            timeout_seconds=1,
        )


def test_oversized_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return success_response("x" * 100)

    client = make_client(httpx.MockTransport(handler), max_response_bytes=10)

    with pytest.raises(LLMClientError, match="size limit"):
        client.complete(
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=10,
            temperature=0.0,
            timeout_seconds=1,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": None}}]},
    ],
)
def test_missing_or_empty_content_is_rejected(payload: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = make_client(httpx.MockTransport(handler))

    with pytest.raises(LLMClientError):
        client.complete(
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=10,
            temperature=0.0,
            timeout_seconds=1,
        )


def test_usage_values_are_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": -1,
                    "total_tokens": "bad",
                    "unexpected": 9,
                },
            },
        )

    client = make_client(httpx.MockTransport(handler))

    result = client.complete(
        system_prompt="system",
        user_prompt="user",
        max_output_tokens=10,
        temperature=0.0,
        timeout_seconds=1,
    )

    assert result.usage == {"prompt_tokens": 1}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"base_url": "ftp://example.com"}, "http"),
        ({"base_url": "https://user:pass@example.com"}, "credentials"),
        ({"base_url": "https://example.com?q=1"}, "query"),
        ({"api_key": ""}, "api_key"),
        ({"model": ""}, "model"),
        ({"timeout_seconds": 0}, "timeout"),
    ],
)
def test_invalid_configuration_is_rejected(
    kwargs: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "base_url": "https://api.example.com",
        "api_key": API_KEY,
        "model": "test-model",
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        OpenAICompatibleClient(**values)  # type: ignore[arg-type]


def test_context_manager_closes_owned_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return success_response()

    with make_client(httpx.MockTransport(handler)) as client:
        assert client.complete(
            system_prompt="system",
            user_prompt="user",
            max_output_tokens=10,
            temperature=0.0,
            timeout_seconds=1,
        ).content == "hello"
