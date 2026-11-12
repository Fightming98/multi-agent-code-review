"""Stage 2 评分规则加载器单元测试。"""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from config.review_rules import (
    DEFAULT_RULES_PATH,
    DIMENSIONS,
    ReviewRules,
    ReviewRulesError,
    load_review_rules,
)

BASE_RULES = {
    "schema_version": "1.0",
    "weights": {
        "security": 0.35,
        "quality": 0.25,
        "performance": 0.20,
        "testing": 0.20,
    },
    "deductions": {
        "critical": 25,
        "high": 15,
        "medium": 5,
        "low": 2,
        "info": 0,
    },
    "verdict": {
        "approve_min_score": 80,
        "request_changes_below": 60,
    },
    "testing": {"min_coverage_percent": 80},
    "complexity": {"high_rank": "D", "very_high_rank": "E"},
    "severity_mapping": {
        "bandit": {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"},
        "radon": {"A": "info", "B": "info", "C": "low", "D": "medium", "E": "high", "F": "high"},
        "testing": {
            "test_failure": "medium",
            "low_coverage": "medium",
            "missing_tests": "low",
        },
    },
}


def _write_rules(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _mutated(**updates: object) -> dict[str, object]:
    payload = copy.deepcopy(BASE_RULES)
    payload.update(updates)
    return payload


class TestDefaultRules:
    def test_loads_default_file(self) -> None:
        rules = load_review_rules()
        assert isinstance(rules, ReviewRules)
        assert rules.schema_version == "1.0"
        assert rules.dimensions == DIMENSIONS
        assert rules.weight_total == pytest.approx(1.0)

    def test_expected_weights_and_thresholds(self) -> None:
        rules = load_review_rules(DEFAULT_RULES_PATH)
        assert rules.weights["security"] == pytest.approx(0.35)
        assert rules.weights["quality"] == pytest.approx(0.25)
        assert rules.weights["performance"] == pytest.approx(0.20)
        assert rules.weights["testing"] == pytest.approx(0.20)
        assert rules.approve_min_score == 80
        assert rules.request_changes_below == 60
        assert rules.min_coverage_percent == 80
        assert rules.high_complexity_rank == "D"
        assert rules.very_high_complexity_rank == "E"

    def test_severity_mapping_does_not_preset_rule_ids(self) -> None:
        rules = load_review_rules()
        assert rules.map_severity("bandit", "HIGH") == "high"
        assert rules.map_severity("bandit", "MEDIUM") == "medium"
        assert rules.map_severity("bandit", "LOW") == "low"
        assert "B107" not in rules.severity_mapping["bandit"]
        assert "B608" not in rules.severity_mapping["bandit"]
        assert all(
            severity != "critical"
            for mapping in rules.severity_mapping.values()
            for severity in mapping.values()
        )

    def test_weight_and_deduction_helpers(self) -> None:
        rules = load_review_rules()
        assert rules.weight_for("security") == pytest.approx(0.35)
        assert rules.deduction_for("critical") == 25
        with pytest.raises(KeyError):
            rules.weight_for("unknown")
        with pytest.raises(KeyError):
            rules.deduction_for("unknown")

    def test_to_dict_is_independent_copy(self) -> None:
        rules = load_review_rules()
        copied = rules.to_dict()
        copied["weights"]["security"] = 0.99
        copied["severity_mapping"]["bandit"]["HIGH"] = "critical"
        assert rules.weights["security"] == pytest.approx(0.35)
        assert rules.severity_mapping["bandit"]["HIGH"] == "high"

    def test_rules_and_nested_mappings_are_read_only(self) -> None:
        rules = load_review_rules()
        with pytest.raises(FrozenInstanceError):
            rules.approve_min_score = 1  # type: ignore[misc]
        with pytest.raises(TypeError):
            rules.weights["security"] = 0.1  # type: ignore[index]
        with pytest.raises(TypeError):
            rules.severity_mapping["bandit"]["HIGH"] = "critical"  # type: ignore[index]

    def test_unknown_severity_lookup_raises(self) -> None:
        rules = load_review_rules()
        with pytest.raises(KeyError):
            rules.map_severity("unknown", "HIGH")
        with pytest.raises(KeyError):
            rules.map_severity("bandit", "CRITICAL")


class TestLoadFailures:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ReviewRulesError):
            load_review_rules(tmp_path / "missing.yaml")

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("weights: [unclosed", encoding="utf-8")
        with pytest.raises(ReviewRulesError):
            load_review_rules(path)

    @pytest.mark.parametrize("payload", [[], "text", 42, None])
    def test_root_must_be_mapping(
        self, tmp_path: Path, payload: object
    ) -> None:
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    def test_missing_root_key(self, tmp_path: Path) -> None:
        payload = copy.deepcopy(BASE_RULES)
        del payload["weights"]
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    def test_unknown_root_key(self, tmp_path: Path) -> None:
        payload = _mutated(extra=True)
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    def test_schema_version(self, tmp_path: Path) -> None:
        payload = _mutated(schema_version="2.0")
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    @pytest.mark.parametrize(
        "weights",
        [
            {"security": 0.35, "quality": 0.25, "performance": 0.20},
            {
                "security": 0.35,
                "quality": 0.25,
                "performance": 0.20,
                "testing": 0.20,
                "extra": 0.0,
            },
            {"security": 0, "quality": 0.25, "performance": 0.20, "testing": 0.55},
            {"security": -0.1, "quality": 0.25, "performance": 0.20, "testing": 0.65},
            {"security": 0.35, "quality": 0.25, "performance": 0.20, "testing": 0.30},
            {"security": True, "quality": 0.25, "performance": 0.20, "testing": 0.55},
            {"security": "0.35", "quality": 0.25, "performance": 0.20, "testing": 0.20},
            "not-a-mapping",
        ],
    )
    def test_invalid_weights(
        self, tmp_path: Path, weights: object
    ) -> None:
        payload = _mutated(weights=weights)
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    @pytest.mark.parametrize(
        "deductions",
        [
            {"critical": 25, "high": 15, "medium": 5, "low": 2},
            {
                "critical": 25,
                "high": 15,
                "medium": 5,
                "low": 2,
                "info": 0,
                "extra": 1,
            },
            {"critical": -1, "high": 15, "medium": 5, "low": 2, "info": 0},
            {"critical": 1.5, "high": 15, "medium": 5, "low": 2, "info": 0},
            {"critical": True, "high": 15, "medium": 5, "low": 2, "info": 0},
            "not-a-mapping",
        ],
    )
    def test_invalid_deductions(
        self, tmp_path: Path, deductions: object
    ) -> None:
        payload = _mutated(deductions=deductions)
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    @pytest.mark.parametrize(
        "verdict",
        [
            {"approve_min_score": 80},
            {"approve_min_score": 80, "request_changes_below": 60, "extra": 1},
            {"approve_min_score": 101, "request_changes_below": 60},
            {"approve_min_score": 80, "request_changes_below": -1},
            {"approve_min_score": 60, "request_changes_below": 80},
            {"approve_min_score": True, "request_changes_below": 60},
            "not-a-mapping",
        ],
    )
    def test_invalid_verdict(
        self, tmp_path: Path, verdict: object
    ) -> None:
        payload = _mutated(verdict=verdict)
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    @pytest.mark.parametrize(
        "testing",
        [
            {},
            {"min_coverage_percent": 80, "extra": 1},
            {"min_coverage_percent": -1},
            {"min_coverage_percent": 101},
            {"min_coverage_percent": "80"},
            "not-a-mapping",
        ],
    )
    def test_invalid_testing_threshold(
        self, tmp_path: Path, testing: object
    ) -> None:
        payload = _mutated(testing=testing)
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    @pytest.mark.parametrize(
        "complexity",
        [
            {"high_rank": "D"},
            {"high_rank": "D", "very_high_rank": "E", "extra": 1},
            {"high_rank": "G", "very_high_rank": "E"},
            {"high_rank": "D", "very_high_rank": "d"},
            {"high_rank": "D", "very_high_rank": "D"},
            "not-a-mapping",
        ],
    )
    def test_invalid_complexity(
        self, tmp_path: Path, complexity: object
    ) -> None:
        payload = _mutated(complexity=complexity)
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    def test_missing_required_severity_tool(self, tmp_path: Path) -> None:
        payload = copy.deepcopy(BASE_RULES)
        del payload["severity_mapping"]["testing"]
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    def test_empty_severity_tool_mapping(self, tmp_path: Path) -> None:
        payload = copy.deepcopy(BASE_RULES)
        payload["severity_mapping"]["bandit"] = {}
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    @pytest.mark.parametrize("severity", ["CRITICAL", "unknown", ""])
    def test_unsupported_severity_value(
        self, tmp_path: Path, severity: str
    ) -> None:
        payload = copy.deepcopy(BASE_RULES)
        payload["severity_mapping"]["bandit"]["HIGH"] = severity
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    def test_severity_mapping_must_be_mapping(self, tmp_path: Path) -> None:
        payload = _mutated(severity_mapping={"bandit": "high"})
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))

    def test_optional_extra_tool_mapping_is_accepted(
        self, tmp_path: Path
    ) -> None:
        payload = copy.deepcopy(BASE_RULES)
        payload["severity_mapping"]["ruff"] = {"warning": "low"}
        rules = load_review_rules(_write_rules(tmp_path, payload))
        assert rules.map_severity("ruff", "warning") == "low"

    def test_tolerance_accepts_float_rounding(self, tmp_path: Path) -> None:
        payload = _mutated(
            weights={
                "security": 0.1,
                "quality": 0.2,
                "performance": 0.3,
                "testing": 0.4,
            }
        )
        rules = load_review_rules(_write_rules(tmp_path, payload))
        assert rules.weight_total == pytest.approx(1.0)

    def test_tolerance_does_not_silently_normalize(
        self, tmp_path: Path
    ) -> None:
        payload = _mutated(
            weights={
                "security": 0.35,
                "quality": 0.25,
                "performance": 0.20,
                "testing": 0.21,
            }
        )
        with pytest.raises(ReviewRulesError):
            load_review_rules(_write_rules(tmp_path, payload))
