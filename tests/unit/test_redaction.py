"""敏感文本脱敏的单元测试。"""

from __future__ import annotations

from code_review.services.redaction import REDACTED, redact_sensitive_text


def test_quoted_secret_is_redacted_and_key_name_is_kept() -> None:
    text = 'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz"'

    result = redact_sensitive_text(text)

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in result
    assert "API_KEY" in result
    assert REDACTED in result
    assert result == 'API_KEY = "[REDACTED]"'


def test_unquoted_password_is_redacted() -> None:
    result = redact_sensitive_text("password=super-secret-value")

    assert result == "password=[REDACTED]"


def test_private_key_block_is_redacted() -> None:
    text = (
        "before\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA\n"
        "-----END RSA PRIVATE KEY-----\n"
        "after"
    )

    result = redact_sensitive_text(text)

    assert "MIIEowIBAAKCAQEA" not in result
    assert "BEGIN RSA PRIVATE KEY" not in result
    assert result.startswith("before")
    assert result.endswith("after")


def test_bearer_token_is_redacted() -> None:
    result = redact_sensitive_text("Authorization: Bearer abcdefghijklmnop123")

    assert "abcdefghijklmnop123" not in result
    assert "Bearer [REDACTED]" in result


def test_known_key_prefixes_are_redacted() -> None:
    values = [
        "sk-abcdefghijklmnop123456",
        "AKIAABCDEFGHIJKLMNOP",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "glpat-abcdefghijklmnopqrst",
    ]

    for value in values:
        result = redact_sensitive_text(f"token {value} end")
        assert value not in result
        assert REDACTED in result


def test_url_credentials_are_redacted_without_leaking_username() -> None:
    result = redact_sensitive_text(
        "clone https://user:secret@example.com/owner/repo.git"
    )

    assert "user" not in result
    assert "secret" not in result
    assert result == "clone https://[REDACTED]@example.com/owner/repo.git"


def test_clean_text_is_unchanged() -> None:
    text = "def add(a, b):\n    return a + b\n"

    assert redact_sensitive_text(text) == text


def test_max_chars_truncates_after_redaction() -> None:
    result = redact_sensitive_text(
        'password = "super-secret-value"',
        max_chars=10,
    )

    assert len(result) == 10
    assert "super-secret-value" not in result


def test_non_string_input_returns_empty_string() -> None:
    assert redact_sensitive_text(None) == ""  # type: ignore[arg-type]
    assert redact_sensitive_text(123) == ""  # type: ignore[arg-type]
