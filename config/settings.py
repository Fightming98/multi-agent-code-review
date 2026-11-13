"""项目配置（pydantic-settings）。

环境变量与 .env 均可覆盖默认值；密钥只允许通过环境变量注入。
对应 docs/acceptance.md AC-0-11 / AC-0-12。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    """阶段 0/1 配置项。

    默认值必须安全：不包含真实 API Key、模型地址或任何凭据。
    阶段 1 的仓库与工具阈值集中在本次配置中，见 docs/acceptance.md §4.7。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "multi-agent-code-review"
    app_env: str = "development"
    debug: bool = False

    llm_provider: str = "openai_compatible"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None

    log_level: str = "INFO"

    max_concurrent_agents: int = Field(default=4, ge=1, le=64)
    max_retry_attempts: int = Field(default=2, ge=0, le=10)

    # 阶段 1：仓库获取与资源限制（docs/acceptance.md §4.7）
    github_allowed_host: str = "github.com"
    github_allowed_port: int = Field(default=443, ge=1, le=65535)
    git_executable: str = "git"
    git_clone_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    git_command_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_repository_size_mb: int = Field(default=200, ge=1, le=10_240)
    max_file_count: int = Field(default=5_000, ge=1, le=1_000_000)
    max_single_file_size_mb: int = Field(default=2, ge=1, le=1_024)
    max_total_scan_size_mb: int = Field(default=50, ge=1, le=10_240)
    static_tool_timeout_seconds: int = Field(default=120, ge=1, le=3600)
    static_tool_output_limit_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    max_tool_findings: int = Field(default=1_000, ge=1, le=1_000_000)
    pytest_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    coverage_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_test_output_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    max_test_records: int = Field(default=100, ge=1, le=10_000)
    max_coverage_files: int = Field(default=1_000, ge=1, le=100_000)
    llm_timeout_seconds: int = Field(default=60, ge=1, le=600)
    llm_max_input_chars: int = Field(default=60_000, ge=1)
    llm_max_output_tokens: int = Field(default=8_000, ge=1, le=100_000)
    llm_max_findings_per_call: int = Field(default=15, ge=15, le=20)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_max_finding_proposals: int = Field(default=50, ge=1, le=10_000)
    trusted_fixture_name: str = "trusted_fixture_v1"
    review_rules_path: str | None = None
    review_output_root: str = "reports"
    keep_workspace_on_failure: bool = False
    workspace_root: str | None = None

    @field_validator(
        "llm_base_url",
        "llm_api_key",
        "llm_model",
        "workspace_root",
        "review_rules_path",
        mode="before",
    )
    @classmethod
    def _empty_string_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "app_name",
        "app_env",
        "llm_provider",
        "github_allowed_host",
        "git_executable",
        "trusted_fixture_name",
        "review_output_root",
    )
    @classmethod
    def _required_non_empty(cls, value: str, info: Any) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @field_validator("github_allowed_host")
    @classmethod
    def _only_github_host(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "github.com":
            raise ValueError("github_allowed_host must be exactly 'github.com'")
        return normalized

    @field_validator("github_allowed_port")
    @classmethod
    def _only_https_port(cls, value: int) -> int:
        if value != 443:
            raise ValueError("github_allowed_port must be 443")
        return value

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"log_level must be one of {sorted(_VALID_LOG_LEVELS)}"
            )
        return normalized
