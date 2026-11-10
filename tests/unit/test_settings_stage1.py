"""阶段 1 配置项（阈值与安全主机约束）的单元测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import Settings


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_stage1_threshold_defaults_match_acceptance_document() -> None:
    settings = make_settings()

    assert settings.github_allowed_host == "github.com"
    assert settings.github_allowed_port == 443
    assert settings.git_executable == "git"
    assert settings.git_clone_timeout_seconds == 300
    assert settings.git_command_timeout_seconds == 300
    assert settings.max_repository_size_mb == 200
    assert settings.max_file_count == 5_000
    assert settings.max_single_file_size_mb == 2
    assert settings.max_total_scan_size_mb == 50
    assert settings.static_tool_timeout_seconds == 120
    assert settings.static_tool_output_limit_bytes == 5 * 1024 * 1024
    assert settings.max_tool_findings == 1_000
    assert settings.pytest_timeout_seconds == 300
    assert settings.coverage_timeout_seconds == 300
    assert settings.max_test_output_bytes == 5 * 1024 * 1024
    assert settings.max_test_records == 100
    assert settings.max_coverage_files == 1_000
    assert settings.llm_timeout_seconds == 60
    assert settings.llm_max_input_chars == 60_000
    assert settings.llm_max_output_tokens == 2_000
    assert settings.llm_temperature == 0.0
    assert settings.llm_max_finding_proposals == 50
    assert settings.trusted_fixture_name == "trusted_fixture_v1"
    assert settings.keep_workspace_on_failure is False
    assert settings.workspace_root is None


def test_github_host_is_normalized() -> None:
    settings = make_settings(github_allowed_host="  GitHub.COM  ")

    assert settings.github_allowed_host == "github.com"


@pytest.mark.parametrize(
    "host",
    ["gitlab.com", "github.com.evil.com", "evilgithub.com", "127.0.0.1", ""],
)
def test_non_github_host_is_rejected(host: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(github_allowed_host=host)


@pytest.mark.parametrize("port", [80, 8443, 0])
def test_non_443_port_is_rejected(port: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(github_allowed_port=port)


@pytest.mark.parametrize(
    "field",
    ["git_executable", "trusted_fixture_name"],
)
def test_required_stage1_strings_must_not_be_empty(field: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: "   "})


def test_blank_workspace_root_becomes_none() -> None:
    assert make_settings(workspace_root="   ").workspace_root is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_repository_size_mb", 0),
        ("max_file_count", 0),
        ("max_single_file_size_mb", 0),
        ("max_total_scan_size_mb", 0),
        ("git_clone_timeout_seconds", 0),
        ("llm_timeout_seconds", 0),
        ("max_test_output_bytes", 1023),
        ("max_test_records", 0),
        ("max_coverage_files", 0),
        ("llm_temperature", -0.1),
        ("llm_temperature", 2.1),
    ],
)
def test_out_of_range_thresholds_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})
