"""真实 LLM 成本估算的模型价格表加载。

价格只从 ``config/llm_pricing.yaml`` 读取，必须包含被调用模型的精确 ID、
币种、输入/输出单价与官方来源。不做汇率换算、不猜测价格、不对缺失模型
使用默认值；无法定价时必须显式失败。

O-1：冻结的 ``CostSummary`` 无法表达“未知成本”，因此真实 LLM 调用只有在
拿到真实 token usage 与匹配的价格条目时才允许写入成本。
"""

from __future__ import annotations

import numbers
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml

DEFAULT_PRICING_PATH = Path(__file__).with_name("llm_pricing.yaml")
CURRENCIES = frozenset({"CNY", "USD"})
TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)
_ENTRY_KEYS = frozenset(
    {
        "input_per_million_tokens",
        "output_per_million_tokens",
        "currency",
        "source_url",
        "retrieved_at",
    }
)


class LLMPricingError(ValueError):
    """价格表无法读取、字段非法或缺少被调用模型。"""


@dataclass(frozen=True)
class ModelPricing:
    """某个精确模型 ID 的输入/输出 token 单价。"""

    model: str
    input_per_million_tokens: Decimal
    output_per_million_tokens: Decimal
    currency: Literal["CNY", "USD"]
    source_url: str
    retrieved_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise LLMPricingError("pricing model must be a non-empty string")
        object.__setattr__(
            self,
            "input_per_million_tokens",
            _positive_decimal(
                self.input_per_million_tokens,
                "input_per_million_tokens",
            ),
        )
        object.__setattr__(
            self,
            "output_per_million_tokens",
            _positive_decimal(
                self.output_per_million_tokens,
                "output_per_million_tokens",
            ),
        )
        if self.currency not in CURRENCIES:
            raise LLMPricingError(
                f"pricing currency must be one of {sorted(CURRENCIES)}"
            )
        if not isinstance(self.source_url, str) or not self.source_url.strip():
            raise LLMPricingError("pricing source_url must not be empty")
        if (
            not isinstance(self.retrieved_at, str)
            or not self.retrieved_at.strip()
        ):
            raise LLMPricingError("pricing retrieved_at must not be empty")

    def estimate(self, input_tokens: int, output_tokens: int) -> Decimal:
        """按百万 token 单价计算估算成本；只接受真实非负 token 数。"""

        for name, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LLMPricingError(
                    f"{name} must be a non-negative integer"
                )
        return (
            Decimal(input_tokens) * self.input_per_million_tokens
            + Decimal(output_tokens) * self.output_per_million_tokens
        ) / TOKENS_PER_PRICE_UNIT


def load_model_pricing(
    model: str | None,
    path: str | Path | None = None,
) -> ModelPricing:
    """加载并校验 ``model`` 对应的价格条目。"""

    if not isinstance(model, str) or not model.strip():
        raise LLMPricingError(
            "a concrete model id is required to load LLM pricing"
        )
    resolved_path = (
        Path(path) if path is not None else DEFAULT_PRICING_PATH
    )
    try:
        text = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LLMPricingError(
            "cannot read LLM pricing configuration"
        ) from exc
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LLMPricingError(
            "LLM pricing configuration is not valid YAML"
        ) from exc
    if not isinstance(payload, Mapping):
        raise LLMPricingError(
            "LLM pricing configuration must be a mapping"
        )
    if payload.get("schema_version") != "1.0":
        raise LLMPricingError(
            "LLM pricing configuration schema_version must be '1.0'"
        )
    models = payload.get("models")
    if not isinstance(models, Mapping):
        raise LLMPricingError(
            "LLM pricing configuration must contain a models mapping"
        )
    normalized_model = model.strip()
    entry = models.get(normalized_model)
    if not isinstance(entry, Mapping):
        raise LLMPricingError(
            f"no pricing entry for model: {normalized_model}"
        )
    missing = _ENTRY_KEYS.difference(entry)
    unknown = set(entry).difference(_ENTRY_KEYS)
    if missing or unknown:
        raise LLMPricingError(
            "LLM pricing entry must contain exactly: "
            + ", ".join(sorted(_ENTRY_KEYS))
        )
    return ModelPricing(
        model=normalized_model,
        input_per_million_tokens=entry["input_per_million_tokens"],
        output_per_million_tokens=entry["output_per_million_tokens"],
        currency=entry["currency"],
        source_url=entry["source_url"],
        retrieved_at=entry["retrieved_at"],
    )


def _positive_decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(
        value, (numbers.Real, Decimal)
    ):
        raise LLMPricingError(f"{name} must be a positive number")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise LLMPricingError(f"{name} must be a positive number") from exc
    if not decimal_value.is_finite() or decimal_value <= 0:
        raise LLMPricingError(f"{name} must be a positive number")
    return decimal_value
