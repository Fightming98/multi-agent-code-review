"""敏感文本脱敏。

阶段 1 的 Finding 证据、LLM 输入与错误信息都可能包含源码片段。本模块提供
一个确定性的保守脱敏函数：常见密钥、令牌、密码赋值、Bearer Token、私钥块
与 URL 凭据在写入结果或发送给模型前必须替换为 ``[REDACTED]``。
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_SECRET_NAME = (
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
    r"secret|password|passwd|pwd)"
)
_QUOTED_SECRET_RE = re.compile(
    rf'(?i)\b({_SECRET_NAME})\b(\s*[:=]\s*)(["\'])([^"\'\n]{{4,}})\3'
)
_UNQUOTED_SECRET_RE = re.compile(
    rf"(?i)\b({_SECRET_NAME})\b(\s*[:=]\s*)([A-Za-z0-9_./+=-]{{8,}})"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_KEY_PREFIX_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20,})"
)
_URL_CREDENTIAL_RE = re.compile(r"(?i)\b(https?://)([^/\s:@]+):([^/\s@]+)@")


def redact_sensitive_text(text: str, *, max_chars: int | None = None) -> str:
    """替换常见敏感值，并按需截断。

    ``max_chars`` 只限制返回长度，不改变脱敏顺序；截断点可能落在替换标记
    中间，因此先脱敏再截断。
    """

    if not isinstance(text, str):
        return ""

    result = _PRIVATE_KEY_RE.sub(REDACTED, text)
    result = _QUOTED_SECRET_RE.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}{match.group(3)}"
            f"{REDACTED}{match.group(3)}"
        ),
        result,
    )
    result = _UNQUOTED_SECRET_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        result,
    )
    result = _BEARER_RE.sub(f"Bearer {REDACTED}", result)
    result = _KEY_PREFIX_RE.sub(REDACTED, result)
    result = _URL_CREDENTIAL_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED}@",
        result,
    )
    if max_chars is not None and max_chars >= 0 and len(result) > max_chars:
        return result[:max_chars]
    return result
