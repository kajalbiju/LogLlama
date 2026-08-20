from __future__ import annotations

import asyncio
from enum import Enum
from types import SimpleNamespace
from typing import Any

import pytest

import logllama
import logllama.cursor as logllama_cursor
import logllama.provider_instrumentation as instrumentation


class _Messages:
    received: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.received = kwargs
        return SimpleNamespace(
            _request_id="anthropic-request-123",
            retries_taken=1,
            model=kwargs["model"],
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        )


class _Anthropic:
    def __init__(self) -> None:
        self.messages = _Messages()


class _Models:
    received: dict[str, Any] | None = None

    def generate_content(self, **kwargs: Any) -> Any:
        self.received = kwargs
        return SimpleNamespace(
            text="ok",
            response_id="gemini-request-123",
            model_version="gemini-test-001",
            sdk_http_response=SimpleNamespace(
                headers={"grpc-previous-rpc-attempts": "2"},
            ),
            usage_metadata=SimpleNamespace(
                prompt_token_count=3,
                candidates_token_count=2,
                total_token_count=5,
            ),
        )


class _AsyncModels:
    received: dict[str, Any] | None = None

    async def generate_content(self, **kwargs: Any) -> Any:
        self.received = kwargs
        return SimpleNamespace(
            text="async ok",
            response_id="gemini-async-request-123",
            model_version="gemini-test-async-001",
            usage_metadata=SimpleNamespace(
                prompt_token_count=4,
                candidates_token_count=1,
                total_token_count=5,
            ),
        )


class _GenerateConfig:
    def model_dump(self) -> dict[str, Any]:
        return {
            "temperature": 0.2,
            "top_p": 0.8,
            "top_k": 20,
            "max_output_tokens": 16,
            "thinking_config": {"thinking_level": _ThinkingLevel.MINIMAL},
            "api_key": "must-not-be-captured",
        }


class _ThinkingLevel(str, Enum):
    MINIMAL = "MINIMAL"


class _Gemini:
    def __init__(self) -> None:
        self.models = _Models()
        self.aio = SimpleNamespace(models=_AsyncModels())


class _Interactions:
    received: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.received = kwargs
        return SimpleNamespace(
            id="gemini-interaction-123",
            model=kwargs["model"],
            output_text="ok",
            usage=SimpleNamespace(
                total_input_tokens=2,
                total_output_tokens=1,
                total_tokens=3,
            ),
        )


class _InteractionsGemini:
    def __init__(self) -> None:
        self.interactions = _Interactions()


class _GeminiError(RuntimeError):
    request_id = "gemini-error-request-123"
    retries_taken = 3


class _FailingModels:
    def generate_content(self, **_: Any) -> Any:
        raise _GeminiError("provider unavailable")


class _FailingGemini:
    def __init__(self) -> None:
        self.models = _FailingModels()


class _CursorRun:
    def wait(self) -> Any:
        return SimpleNamespace(
            id="cursor-run-123",
            model=SimpleNamespace(id="composer-test"),
            result="cursor response",
            status="completed",
            usage=SimpleNamespace(input_tokens=7, output_tokens=3, total_tokens=10),
        )


class _Cursor:
    def __init__(self) -> None:
        self.model = SimpleNamespace(id="composer-default")
        self.received: tuple[Any, ...] | None = None

    def send(self, *args: Any, **kwargs: Any) -> _CursorRun:
        self.received = args
        assert not kwargs
        return _CursorRun()


def test_anthropic_wrapper_captures_and_removes_logllama_metadata(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(instrumentation, "post_event_async", lambda _config, event: events.append(event))
    client = logllama.wrap_anthropic(
        _Anthropic(),
        api_key="logllama-key",
        capture_otel=False,
    )

    client.messages.create(
        model="claude-test",
        max_tokens=10,
        messages=[{"role": "user", "content": "hello"}],
        logllama_metadata={"tenant_id": "tenant-test"},
    )

    assert client.messages.received is not None
    assert "logllama_metadata" not in client.messages.received
    assert events[0]["provider"] == "anthropic"
    assert events[0]["tenant_id"] == "tenant-test"
    assert events[0]["usage"]["total_tokens"] == 3
    assert events[0]["provider_request_id"] == "anthropic-request-123"
    assert events[0]["retry_count"] == 1
    assert events[0]["model_parameters"] == {"max_tokens": 10}


def test_cursor_wrapper_captures_completed_run_and_removes_metadata(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(logllama_cursor, "post_event_async", lambda _config, event: events.append(event))
    client = logllama.wrap_cursor(_Cursor(), api_key="logllama-key", capture_otel=False)

    result = client.send(
        "hello",
        {"model": "composer-test", "logllama_metadata": {"tenant_id": "tenant-test"}},
    ).wait()

    assert result.result == "cursor response"
    assert client.received == ("hello", {"model": "composer-test"})
    assert events[0]["provider"] == "cursor"
    assert events[0]["operation"] == "agents.send"
    assert events[0]["model"] == "composer-test"
    assert events[0]["tenant_id"] == "tenant-test"
    assert events[0]["provider_request_id"] == "cursor-run-123"
    assert events[0]["usage"] == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    assert events[0]["response"]["result"] == "cursor response"


def test_gemini_wrapper_captures_usage_parameters_request_id_and_retries(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(instrumentation, "post_event_async", lambda _config, event: events.append(event))
    client = logllama.wrap_gemini(
        _Gemini(),
        api_key="logllama-key",
        capture_otel=False,
    )

    client.models.generate_content(
        model="gemini-test",
        contents="hello",
        logllama_metadata={"comparison_id": "cmp-test"},
        config=_GenerateConfig(),
    )

    assert client.models.received is not None
    assert "logllama_metadata" not in client.models.received
    assert events[0]["provider"] == "gemini"
    assert events[0]["model"] == "gemini-test-001"
    assert events[0]["usage"] == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    assert events[0]["provider_request_id"] == "gemini-request-123"
    assert events[0]["retry_count"] == 2
    assert events[0]["model_parameters"] == {
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 20,
        "max_output_tokens": 16,
        "thinking_config": {"thinking_level": "MINIMAL"},
    }
    assert events[0]["custom_metadata"]["comparison_id"] == "cmp-test"


def test_gemini_interactions_uses_response_id_as_provider_request_id(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(instrumentation, "post_event_async", lambda _config, event: events.append(event))
    client = logllama.wrap_gemini(
        _InteractionsGemini(),
        api_key="logllama-key",
        capture_otel=False,
    )

    client.interactions.create(
        model="gemini-test",
        input="hello",
        logllama_metadata={"request_id": "application-request-123"},
    )

    assert client.interactions.received is not None
    assert "logllama_metadata" not in client.interactions.received
    assert events[0]["operation"] == "interactions.create"
    assert events[0]["provider_request_id"] == "gemini-interaction-123"
    assert events[0]["usage"] == {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}


def test_gemini_async_wrapper_captures_explicit_application_retry(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(instrumentation, "post_event_async", lambda _config, event: events.append(event))
    client = logllama.wrap_gemini(
        _Gemini(),
        api_key="logllama-key",
        capture_otel=False,
    )

    response = asyncio.run(
        client.aio.models.generate_content(
            model="gemini-test",
            contents="hello",
            config={"temperature": 0},
            logllama_metadata={
                "request_id": "application-request-123",
                "retry_count": 1,
            },
        )
    )

    assert response.text == "async ok"
    assert events[0]["provider_request_id"] == "gemini-async-request-123"
    assert events[0]["retry_count"] == 1
    assert events[0]["request_id"] == "application-request-123"
    assert events[0]["model_parameters"] == {"temperature": 0}
    assert "retry_count" not in events[0]["custom_metadata"]


def test_gemini_error_captures_request_id_retry_count_and_parameters(monkeypatch) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(instrumentation, "post_event_async", lambda _config, event: events.append(event))
    client = logllama.wrap_gemini(
        _FailingGemini(),
        api_key="logllama-key",
        capture_otel=False,
    )

    with pytest.raises(_GeminiError):
        client.models.generate_content(
            model="gemini-test",
            contents="hello",
            config={"temperature": 0.4, "max_output_tokens": 8},
        )

    assert events[0]["status"] == "error"
    assert events[0]["provider_request_id"] == "gemini-error-request-123"
    assert events[0]["retry_count"] == 3
    assert events[0]["model_parameters"] == {
        "temperature": 0.4,
        "max_output_tokens": 8,
    }
