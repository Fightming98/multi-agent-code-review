"""真实模型调用冒烟测试（TC-1-06）。

默认不运行；只有显式设置 ``RUN_LLM_SMOKE=1`` 且本地配置了完整
``LLM_BASE_URL`` / ``LLM_API_KEY`` / ``LLM_MODEL`` 时才访问真实模型服务。
本测试只验证一次最小结构化输出与 usage，不写入 API Key，不纳入常规单元测试。
"""

from __future__ import annotations

import os
import time

import pytest

from code_review.services.llm_analyzer import _extract_json_object
from code_review.services.llm_client import OpenAICompatibleClient
from config.settings import Settings

RUN_LLM_SMOKE = os.environ.get("RUN_LLM_SMOKE") == "1"

pytestmark = [
    pytest.mark.llm_smoke,
    pytest.mark.skipif(
        not RUN_LLM_SMOKE,
        reason="set RUN_LLM_SMOKE=1 to run the real LLM smoke test",
    ),
]


def test_real_llm_call_returns_structured_output_and_usage() -> None:
    settings = Settings()
    if (
        not settings.llm_base_url
        or not settings.llm_api_key
        or not settings.llm_model
    ):
        pytest.skip("LLM_BASE_URL / LLM_API_KEY / LLM_MODEL are not configured")

    started = time.perf_counter()
    with OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    ) as client:
        completion = client.complete(
            system_prompt=(
                "You are a smoke-test responder. Return only a compact JSON "
                "object and no markdown fences."
            ),
            user_prompt='Return exactly this JSON object: {"ok": true, "stage": 1}',
            max_output_tokens=128,
            temperature=0.0,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    latency_ms = int((time.perf_counter() - started) * 1000)

    assert completion.content.strip()
    assert completion.model
    assert completion.usage is not None
    assert completion.usage.get("total_tokens", 0) > 0

    payload = _extract_json_object(completion.content)
    assert payload == {"ok": True, "stage": 1}

    print(
        "LLM_SMOKE "
        f"configured_model={settings.llm_model} "
        f"response_model={completion.model} "
        f"finish_reason={completion.finish_reason} "
        f"usage={completion.usage} "
        f"latency_ms={latency_ms}"
    )
