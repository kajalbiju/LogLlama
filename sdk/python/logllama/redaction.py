from __future__ import annotations

import re


REDACTED = "[REDACTED]"

# Secret-shaped values. The `*` is included so masked forms such as "sk-proj*******abcd" are also removed.
_SECRET_PATTERNS = (
    # OpenAI and Anthropic secret keys.
    re.compile(r"\bsk-[A-Za-z0-9_*\-]{6,}"),
    # Google API keys.
    re.compile(r"\bAIza[0-9A-Za-z_*\-]{8,}"),
    # LogLlama ingest and runtime keys.
    re.compile(r"\b(?:llm|llrt)_[A-Za-z0-9_*\-]{8,}"),
    # Bearer tokens.
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=*\-]{8,}"),
)

# Assignments to sensitive names. The name and separator are kept so the message still reads naturally.
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret)(\s*[:=]\s*)(['\"]?)[^\s'\",;&]+"
)


def redact_text(value: str) -> str:
    """Remove key-shaped values from free text, such as provider error messages, before they are recorded."""
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return _ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED}", redacted)
