"""真实 LLM 价格表加载与成本估算测试（不联网）。"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from config.llm_pricing import (
    DEFAULT_PRICING_PATH,
    LLMPricingError,
    load_model_pricing,
)


def test_default_pricing_contains_configured_model() -> None:
    pricing = load_model_pricing("deepseek-ai/DeepSeek-V3")

    assert pricing.model == "deepseek-ai/DeepSeek-V3"
    assert pricing.input_per_million_tokens == Decimal("0.25")
    assert pricing.output_per_million_tokens == Decimal("1.00")
    assert pricing.currency == "USD"
    assert pricing.source_url.startswith("https://")
    assert pricing.retrieved_at == "2026-11-13"


def test_estimate_uses_exact_token_prices() -> None:
    pricing = load_model_pricing("deepseek-ai/DeepSeek-V3")

    assert pricing.estimate(39, 15) == Decimal("0.00002475")
    assert pricing.estimate(0, 0) == Decimal(0)


def test_pricing_requires_exact_model_match() -> None:
    with pytest.raises(LLMPricingError, match="no pricing entry"):
        load_model_pricing("deepseek-ai/DeepSeek-V3-unknown")


def test_pricing_requires_a_model_id() -> None:
    with pytest.raises(LLMPricingError, match="model id"):
        load_model_pricing(None)


def test_pricing_path_can_be_overridden(tmp_path: Path) -> None:
    path = tmp_path / "pricing.yaml"
    path.write_text(
        'schema_version: "1.0"\n'
        "models:\n"
        "  test-model:\n"
        "    input_per_million_tokens: 1.5\n"
        "    output_per_million_tokens: 3\n"
        '    currency: "CNY"\n'
        '    source_url: "https://example.invalid/pricing"\n'
        '    retrieved_at: "2026-11-13"\n',
        encoding="utf-8",
    )

    pricing = load_model_pricing("test-model", path)

    assert pricing.input_per_million_tokens == Decimal("1.5")
    assert pricing.output_per_million_tokens == Decimal(3)
    assert pricing.currency == "CNY"


@pytest.mark.parametrize(
    "entry",
    [
        (
            "    input_per_million_tokens: 0\n"
            "    output_per_million_tokens: 1\n"
            '    currency: "USD"\n'
            '    source_url: "https://example.invalid/pricing"\n'
            '    retrieved_at: "2026-11-13"'
        ),
        (
            "    input_per_million_tokens: 1\n"
            "    output_per_million_tokens: 1\n"
            '    currency: "EUR"\n'
            '    source_url: "https://example.invalid/pricing"\n'
            '    retrieved_at: "2026-11-13"'
        ),
        (
            "    input_per_million_tokens: 1\n"
            "    output_per_million_tokens: 1\n"
            '    currency: "USD"\n'
            '    retrieved_at: "2026-11-13"'
        ),
    ],
)
def test_invalid_pricing_entries_are_rejected(
    tmp_path: Path,
    entry: str,
) -> None:
    path = tmp_path / "pricing.yaml"
    path.write_text(
        'schema_version: "1.0"\nmodels:\n  test-model:\n' + entry + "\n",
        encoding="utf-8",
    )

    with pytest.raises(LLMPricingError):
        load_model_pricing("test-model", path)


def test_default_pricing_path_exists() -> None:
    assert DEFAULT_PRICING_PATH.is_file()


def test_model_pricing_rejects_invalid_tokens() -> None:
    pricing = load_model_pricing("deepseek-ai/DeepSeek-V3")

    with pytest.raises(LLMPricingError, match="non-negative integer"):
        pricing.estimate(-1, 0)
    with pytest.raises(LLMPricingError, match="non-negative integer"):
        pricing.estimate(0, True)
