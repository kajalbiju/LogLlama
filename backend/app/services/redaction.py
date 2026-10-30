import re


REDACTED = "[REDACTED]"

# Same rules as the SDKs' redaction module. The backend applies them again so that events from any client are covered.
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_*\-]{6,}"),
    re.compile(r"\bAIza[0-9A-Za-z_*\-]{8,}"),
    re.compile(r"\b(?:llm|llrt)_[A-Za-z0-9_*\-]{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=*\-]{8,}"),
)

_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret)(\s*[:=]\s*)(['\"]?)[^\s'\",;&]+"
)


def redact_text(value: str) -> str:
    """Remove key-shaped values from free text before an error message is stored."""
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return _ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED}", redacted)
