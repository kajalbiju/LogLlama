from __future__ import annotations

from typing import Any

import pytest

import logllama
import logllama.openai as logllama_openai
import logllama.provider_instrumentation as instrumentation
from logllama.redaction import REDACTED, redact_text


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


class _FailingMessages:
    def create(self, **_: Any) -> Any:
        raise RuntimeError("Incorrect API key provided: =sk-proj-abcdef1234567890wxyz. Check yours.")


class _FailingAnthropic:
    def __init__(self) -> None:
        self.messages = _FailingMessages()


class _FailingCompletions:
    def create(self, **_: Any) -> Any:
        raise RuntimeError("Incorrect API key provided: sk-proj-abcdef1234567890wxyz")


class _FailingOpenAI:
    def __init__(self) -> None:
        self.chat = type("Chat", (), {"completions": _FailingCompletions()})()


def test_anthropic_error_text_is_redacted_before_capture(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(instrumentation, "post_event_async", lambda _config, event: events.append(event))
    client = logllama.wrap_anthropic(_FailingAnthropic(), api_key="logllama-key", capture_otel=False)

    with pytest.raises(RuntimeError):
        client.messages.create(model="claude-test", max_tokens=5, messages=[{"role": "user", "content": "hi"}])

    assert events[0]["status"] == "error"
    assert "abcdef1234567890" not in events[0]["error"]["message"]
    assert REDACTED in events[0]["error"]["message"]


def test_openai_error_text_is_redacted_before_capture(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(logllama_openai, "post_event_async", lambda _config, event: events.append(event))
    client = logllama.wrap_openai(_FailingOpenAI(), api_key="logllama-key", capture_otel=False)

    with pytest.raises(RuntimeError):
        client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])

    assert events[0]["status"] == "error"
    assert "abcdef1234567890" not in events[0]["error"]["message"]
    assert REDACTED in events[0]["error"]["message"]
