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
    """阶段 0 配置项。

    默认值必须安全：不包含真实 API Key、模型地址或任何凭据。
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

    @field_validator(
        "llm_base_url",
        "llm_api_key",
        "llm_model",
        mode="before",
    )
    @classmethod
    def _empty_string_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("app_name", "app_env", "llm_provider")
    @classmethod
    def _required_non_empty(cls, value: str, info: Any) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
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
