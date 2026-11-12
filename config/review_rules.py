"""Stage 2 评分、阈值与严重级别规则加载。

规则只从 ``config/review_rules.yaml`` 读取。加载失败、字段缺失、权重非法或
严重级别映射非法时必须明确报错；不得静默归一化、修正或使用代码内默认值覆盖。
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

DEFAULT_RULES_PATH = Path(__file__).with_name("review_rules.yaml")

DIMENSIONS: tuple[str, ...] = ("security", "quality", "performance", "testing")
DEDUCTION_LEVELS: tuple[str, ...] = (
    "critical",
    "high",
    "medium",
    "low",
    "info",
)
SEVERITIES = frozenset(DEDUCTION_LEVELS)
COMPLEXITY_RANKS = frozenset({"A", "B", "C", "D", "E", "F"})
REQUIRED_SEVERITY_TOOLS = frozenset({"bandit", "radon", "testing"})
WEIGHT_TOLERANCE = 1e-6


class ReviewRulesError(ValueError):
    """规则文件无法安全加载或校验失败。"""


@dataclass(frozen=True)
class ReviewRules:
    """不可变的 Stage 2 规则对象。"""

    schema_version: str
    weights: Mapping[str, float]
    deductions: Mapping[str, int]
    approve_min_score: float
    request_changes_below: float
    min_coverage_percent: float
    high_complexity_rank: str
    very_high_complexity_rank: str
    severity_mapping: Mapping[str, Mapping[str, str]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "weights",
            MappingProxyType(
                {key: float(value) for key, value in self.weights.items()}
            ),
        )
        object.__setattr__(
            self,
            "deductions",
            MappingProxyType(
                {key: int(value) for key, value in self.deductions.items()}
            ),
        )
        object.__setattr__(
            self,
            "severity_mapping",
            MappingProxyType(
                {
                    tool: MappingProxyType(dict(mapping))
                    for tool, mapping in self.severity_mapping.items()
                }
            ),
        )

    @property
    def dimensions(self) -> tuple[str, ...]:
        return DIMENSIONS

    @property
    def weight_total(self) -> float:
        return sum(self.weights.values())

    def weight_for(self, dimension: str) -> float:
        try:
            return self.weights[dimension]
        except KeyError as exc:
            raise KeyError(f"unknown dimension: {dimension}") from exc

    def deduction_for(self, severity: str) -> int:
        try:
            return self.deductions[severity]
        except KeyError as exc:
            raise KeyError(f"unknown severity: {severity}") from exc

    def map_severity(self, tool: str, source_severity: str) -> str:
        """按工具原始严重级别映射 Finding 严重级别。"""
        try:
            tool_mapping = self.severity_mapping[tool]
        except KeyError as exc:
            raise KeyError(f"no severity mapping for tool: {tool}") from exc
        try:
            return tool_mapping[source_severity]
        except KeyError as exc:
            raise KeyError(
                f"no severity mapping for {tool}.{source_severity}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        """返回可序列化的深拷贝，避免调用方修改内部只读映射。"""
        return {
            "schema_version": self.schema_version,
            "weights": dict(self.weights),
            "deductions": dict(self.deductions),
            "approve_min_score": self.approve_min_score,
            "request_changes_below": self.request_changes_below,
            "min_coverage_percent": self.min_coverage_percent,
            "high_complexity_rank": self.high_complexity_rank,
            "very_high_complexity_rank": self.very_high_complexity_rank,
            "severity_mapping": {
                tool: dict(mapping)
                for tool, mapping in self.severity_mapping.items()
            },
        }


def load_review_rules(
    path: str | Path | None = None,
) -> ReviewRules:
    """加载并严格校验规则文件。"""
    rules_path = Path(path) if path is not None else DEFAULT_RULES_PATH
    try:
        raw_text = rules_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReviewRulesError(
            f"cannot read review rules file: {rules_path.name}"
        ) from exc

    try:
        payload = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ReviewRulesError("review rules YAML is invalid") from exc

    if not isinstance(payload, Mapping):
        raise ReviewRulesError("review rules root must be a mapping")

    _require_exact_keys(
        payload,
        {
            "schema_version",
            "weights",
            "deductions",
            "verdict",
            "testing",
            "complexity",
            "severity_mapping",
        },
        "root",
    )

    schema_version = _as_nonempty_str(
        payload["schema_version"], "schema_version"
    )
    if schema_version != "1.0":
        raise ReviewRulesError("schema_version must be '1.0'")

    weights = _parse_weights(payload["weights"])
    deductions = _parse_deductions(payload["deductions"])
    approve_min_score, request_changes_below = _parse_verdict(
        payload["verdict"]
    )
    min_coverage_percent = _parse_testing(payload["testing"])
    high_rank, very_high_rank = _parse_complexity(payload["complexity"])
    severity_mapping = _parse_severity_mapping(payload["severity_mapping"])

    return ReviewRules(
        schema_version=schema_version,
        weights=weights,
        deductions=deductions,
        approve_min_score=approve_min_score,
        request_changes_below=request_changes_below,
        min_coverage_percent=min_coverage_percent,
        high_complexity_rank=high_rank,
        very_high_complexity_rank=very_high_rank,
        severity_mapping=severity_mapping,
    )


def _parse_weights(value: Any) -> dict[str, float]:
    mapping = _require_mapping(value, "weights")
    _require_exact_keys(mapping, set(DIMENSIONS), "weights")
    weights: dict[str, float] = {}
    for dimension in DIMENSIONS:
        weight = _as_float(mapping[dimension], f"weights.{dimension}")
        if not 0 < weight <= 1:
            raise ReviewRulesError(
                f"weights.{dimension} must satisfy 0 < w <= 1"
            )
        weights[dimension] = weight
    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        raise ReviewRulesError(
            "weights must sum to 1.0; missing or invalid values are not "
            "normalized automatically"
        )
    return weights


def _parse_deductions(value: Any) -> dict[str, int]:
    mapping = _require_mapping(value, "deductions")
    _require_exact_keys(mapping, set(DEDUCTION_LEVELS), "deductions")
    deductions: dict[str, int] = {}
    for level in DEDUCTION_LEVELS:
        amount = _as_int(mapping[level], f"deductions.{level}")
        if amount < 0:
            raise ReviewRulesError(
                f"deductions.{level} must be a non-negative integer"
            )
        deductions[level] = amount
    return deductions


def _parse_verdict(value: Any) -> tuple[float, float]:
    mapping = _require_mapping(value, "verdict")
    _require_exact_keys(
        mapping,
        {"approve_min_score", "request_changes_below"},
        "verdict",
    )
    approve = _as_float(
        mapping["approve_min_score"], "verdict.approve_min_score"
    )
    request = _as_float(
        mapping["request_changes_below"], "verdict.request_changes_below"
    )
    _require_percentage(approve, "verdict.approve_min_score")
    _require_percentage(request, "verdict.request_changes_below")
    if request > approve:
        raise ReviewRulesError(
            "verdict.request_changes_below must not exceed "
            "verdict.approve_min_score"
        )
    return approve, request


def _parse_testing(value: Any) -> float:
    mapping = _require_mapping(value, "testing")
    _require_exact_keys(mapping, {"min_coverage_percent"}, "testing")
    percent = _as_float(
        mapping["min_coverage_percent"],
        "testing.min_coverage_percent",
    )
    _require_percentage(percent, "testing.min_coverage_percent")
    return percent


def _parse_complexity(value: Any) -> tuple[str, str]:
    mapping = _require_mapping(value, "complexity")
    _require_exact_keys(
        mapping,
        {"high_rank", "very_high_rank"},
        "complexity",
    )
    high = _as_nonempty_str(mapping["high_rank"], "complexity.high_rank")
    very_high = _as_nonempty_str(
        mapping["very_high_rank"], "complexity.very_high_rank"
    )
    if high not in COMPLEXITY_RANKS:
        raise ReviewRulesError("complexity.high_rank must be one of A-F")
    if very_high not in COMPLEXITY_RANKS:
        raise ReviewRulesError(
            "complexity.very_high_rank must be one of A-F"
        )
    if high == very_high:
        raise ReviewRulesError(
            "complexity.high_rank and very_high_rank must differ"
        )
    return high, very_high


def _parse_severity_mapping(
    value: Any,
) -> dict[str, dict[str, str]]:
    mapping = _require_mapping(value, "severity_mapping")
    missing_tools = REQUIRED_SEVERITY_TOOLS - set(mapping)
    if missing_tools:
        joined = ", ".join(sorted(missing_tools))
        raise ReviewRulesError(
            f"severity_mapping is missing required tools: {joined}"
        )

    result: dict[str, dict[str, str]] = {}
    for tool, raw_tool_mapping in mapping.items():
        tool_name = _as_nonempty_str(tool, "severity_mapping tool")
        tool_mapping = _require_mapping(
            raw_tool_mapping, f"severity_mapping.{tool_name}"
        )
        if not tool_mapping:
            raise ReviewRulesError(
                f"severity_mapping.{tool_name} must not be empty"
            )
        parsed: dict[str, str] = {}
        for source, raw_severity in tool_mapping.items():
            source_key = _as_nonempty_str(
                source, f"severity_mapping.{tool_name} source"
            )
            severity = _as_nonempty_str(
                raw_severity,
                f"severity_mapping.{tool_name}.{source_key}",
            )
            if severity not in SEVERITIES:
                raise ReviewRulesError(
                    f"severity_mapping.{tool_name}.{source_key} has "
                    f"unsupported severity: {severity}"
                )
            parsed[source_key] = severity
        result[tool_name] = parsed
    return result


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewRulesError(f"{path} must be a mapping")
    for key in value:
        if not isinstance(key, str) or not key:
            raise ReviewRulesError(f"{path} keys must be non-empty strings")
    return value


def _require_exact_keys(
    mapping: Mapping[str, Any], expected: set[str], path: str
) -> None:
    actual = set(mapping)
    missing = expected - actual
    extra = actual - expected
    if missing:
        raise ReviewRulesError(
            f"{path} is missing keys: {', '.join(sorted(missing))}"
        )
    if extra:
        raise ReviewRulesError(
            f"{path} has unknown keys: {', '.join(sorted(extra))}"
        )


def _as_nonempty_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewRulesError(f"{path} must be a non-empty string")
    return value


def _as_float(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ReviewRulesError(f"{path} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ReviewRulesError(f"{path} must be finite")
    return number


def _as_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ReviewRulesError(f"{path} must be an integer")
    return int(value)


def _require_percentage(value: float, path: str) -> None:
    if not 0 <= value <= 100:
        raise ReviewRulesError(f"{path} must be between 0 and 100")
