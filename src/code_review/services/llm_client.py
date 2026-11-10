"""兼容 OpenAI Chat Completions API 的最小 LLM 客户端。

阶段 1 不引入额外 SDK；客户端只使用已安装的 ``httpx``。实现遵循以下约束：

- API Key 只从配置注入，不写入日志、异常或结果对象；
- 不跟随重定向，避免凭据被转发到其他主机；
- 超时、HTTP 错误、非 JSON 响应与超长响应统一转换为安全错误；
- 只读取 ``choices[0].message.content`` 与受限的 usage 字段。

真实模型调用属于 Stage 1.7 的可选冒烟测试；单元测试必须注入 Fake 客户端，
不得访问网络。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Self
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


class LLMClientError(RuntimeError):
    """模型请求失败；``reason`` 不包含响应正文或凭据。"""

    def __init__(self, reason: str, *, timed_out: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.timed_out = timed_out


@dataclass(frozen=True)
class LLMCompletion:
    """一次模型补全结果。"""

    content: str
    model: str | None
    finish_reason: str | None
    usage: dict[str, int] | None


class LLMClient(Protocol):
    """可替换的模型客户端接口（测试使用 Fake）。"""

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float,
        timeout_seconds: float,
    ) -> LLMCompletion:
        """发送一次非流式补全请求。"""


class OpenAICompatibleClient:
    """兼容 OpenAI Chat Completions 的客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | SecretStr,
        model: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.Client | None = None,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("llm base_url must not be empty")
        parsed = urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("llm base_url must be an http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("llm base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("llm base_url must not contain a query or fragment")

        secret = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        if not secret.get_secret_value().strip():
            raise ValueError("llm api_key must not be empty")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("llm model must not be empty")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("llm timeout_seconds must be positive")
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")

        self._base_url = base_url.strip().rstrip("/")
        self._api_key = secret
        self.model = model.strip()
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._http_client = http_client or httpx.Client(
            follow_redirects=False,
            timeout=self._timeout_seconds,
        )
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float,
        timeout_seconds: float,
    ) -> LLMCompletion:
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ValueError("user_prompt must not be empty")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(temperature),
            "max_tokens": int(max_output_tokens),
            "stream": False,
        }
        try:
            response = self._http_client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=float(timeout_seconds),
            )
        except httpx.TimeoutException as exc:
            raise LLMClientError("model request timed out", timed_out=True) from exc
        except httpx.HTTPError as exc:
            raise LLMClientError("model request failed") from exc

        if 300 <= response.status_code < 400:
            raise LLMClientError("model request was redirected")
        if response.status_code >= 400:
            raise LLMClientError(
                f"model request failed with status {response.status_code}"
            )
        if len(response.content) > self._max_response_bytes:
            raise LLMClientError("model response exceeds the size limit")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMClientError("model response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise LLMClientError("model response must be a JSON object")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMClientError("model response did not contain a choice")
        first = choices[0]
        if not isinstance(first, dict):
            raise LLMClientError("model response choice is invalid")
        message = first.get("message")
        if not isinstance(message, dict):
            raise LLMClientError("model response message is invalid")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("model response did not contain text")

        response_model = data.get("model")
        finish_reason = first.get("finish_reason")
        usage = _sanitize_usage(data.get("usage"))
        return LLMCompletion(
            content=content,
            model=response_model if isinstance(response_model, str) else self.model,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            usage=usage,
        )


def _sanitize_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    usage: dict[str, int] = {}
    for key in _USAGE_KEYS:
        raw = value.get(key)
        if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
            usage[key] = raw
    return usage or None
