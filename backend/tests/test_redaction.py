import pytest

from app.services.redaction import REDACTED, redact_text


@pytest.mark.parametrize(
    ("raw", "leaked"),
    [
        ("Incorrect API key provided: =sk-proj*****************************xpkA. You can find", "sk-proj"),
        ("rejected sk-ant-api03-abcdefghijklmnop", "abcdefghijklmnop"),
        ("google said AIzaSyD-1234567890abcdef", "AIzaSyD"),
        ("LogLlama rejected llm_ABCDEFGH12345678", "llm_ABCDEFGH"),
        ("runtime llrt_ZYXWVUTS98765432 is invalid", "llrt_ZYXW"),
        ("Authorization: Bearer abc.def.ghi-123456", "abc.def"),
        ("api_key=supersecret123", "supersecret123"),
        ("password: hunter2-long", "hunter2-long"),
    ],
)
def test_secret_values_are_removed(raw: str, leaked: str) -> None:
    redacted = redact_text(raw)

    assert leaked not in redacted
    assert REDACTED in redacted


@pytest.mark.parametrize(
    "text",
    [
        "task-manager requires review",
        "tokens used: 13",
        "rate limit exceeded, retry after 20 seconds",
    ],
)
def test_ordinary_error_text_is_unchanged(text: str) -> None:
    assert redact_text(text) == text
