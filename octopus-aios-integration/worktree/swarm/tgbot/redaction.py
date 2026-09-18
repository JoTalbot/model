"""Central value-free runtime error redaction."""

from __future__ import annotations

import re

_PATTERNS = (
    # Telegram Bot API embeds the token in the URL path.
    (
        re.compile(r"(?i)(?:bot|file/bot)\d{5,}:[A-Za-z0-9_-]{20,}"),
        "bot[token-redacted]",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}"), "Bearer [redacted]"),
    (re.compile(r"(?i)(token|api[_-]?key|secret)=([^&\s]+)"), r"\1=[redacted]"),
    # Telegram user/chat identifiers are privacy metadata in this subsystem.
    (re.compile(r"(?<![A-Za-z0-9])-?\d{7,16}(?![A-Za-z0-9])"), "[identifier-redacted]"),
)


def redact_runtime_text(value: object, *, limit: int = 300) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text[: max(0, int(limit))]


def safe_error(error: BaseException) -> str:
    detail = redact_runtime_text(error)
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__
