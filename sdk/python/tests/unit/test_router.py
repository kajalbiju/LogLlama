from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import logllama


class _OpenAIResponses:
    def __init__(self) -> None:
        self.received: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.received = kwargs
        return SimpleNamespace(
            output_text="openai response",
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=3, output_tokens=2, total_tokens=5),
            status="completed",
        )


class _OpenAIClient:
    def __init__(self) -> None:
        self.responses = _OpenAIResponses()


class _AnthropicMessages:
    def __init__(self) -> None:
        self.received: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.received = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="anthropic response")],
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=4, output_tokens=3),
            stop_reason="end_turn",
        )


class _AnthropicClient:
    def __init__(self) -> None:
        self.messages = _AnthropicMessages()


class _GeminiInteractions:
    def __init__(self) -> None:
        self.received: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.received = kwargs
        return SimpleNamespace(
            output_text="gemini response",
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=5, output_tokens=4, total_tokens=9),
            status="completed",
        )


class _GeminiClient:
    def __init__(self) -> None:
        self.interactions = _GeminiInteractions()


class _CursorRun:
    def wait(self) -> Any:
        return SimpleNamespace(
            id="cursor-run-123",
            model=SimpleNamespace(id="composer-test"),
            result="cursor response",
            status="completed",
            usage=SimpleNamespace(input_tokens=6, output_tokens=2, total_tokens=8),
        )


class _CursorClient:
    def __init__(self) -> None:
        self.model = SimpleNamespace(id="composer-test")

    def send(self, *_: Any) -> _CursorRun:
        return _CursorRun()


def _llm() -> logllama.LLM:
    return logllama.LLM(
        openai=_OpenAIClient(),
        anthropic=_AnthropicClient(),
        cursor=_CursorClient(),
        gemini=_GeminiClient(),
        models={
            "openai": "gpt-test",
            "anthropic": "claude-test",
            "cursor": "composer-test",
            "gemini": "gemini-test",
        },
        routes={"fast": {"provider": "gemini", "model": "gemini-fast"}},
        instrument=False,
    )


def test_generate_switches_providers_with_one_parameter() -> None:
    llm = _llm()

    openai_response = llm.generate("hello", provider="openai")
    anthropic_response = llm.generate("hello", provider="claude")
    gemini_response = llm.generate("hello", provider="gemini")
    cursor_response = llm.generate("hello", provider="cursor")

    assert openai_response.text == "openai response"
    assert anthropic_response.text == "anthropic response"
    assert anthropic_response.provider == "anthropic"
    assert gemini_response.usage.total_tokens == 9
    assert cursor_response.text == "cursor response"
    assert cursor_response.usage.total_tokens == 8


def test_route_resolves_provider_and_model() -> None:
    response = _llm().generate("hello", route="fast")

    assert response.provider == "gemini"
    assert response.model == "gemini-fast"


class _ApprovalClient:
    def request_test(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": "test-plan", "status": "pending", **kwargs}

    def get_test_plan(self, test_plan_id: str) -> dict[str, Any]:
        return {
            "id": test_plan_id,
            "status": "approved",
            "prompt": "same prompt",
            "system": None,
            "max_output_tokens": 16,
            "targets": [
                {"provider": "openai", "model": "gpt-test"},
                {"provider": "anthropic", "model": "claude-test"},
                {"provider": "gemini", "model": "gemini-test"},
            ],
            "expires_at": "2999-01-01T00:00:00+00:00",
        }

    def lease_test_plan(self, test_plan_id: str) -> dict[str, Any]:
        return self.get_test_plan(test_plan_id)


def test_compare_uses_only_approved_plan_targets() -> None:
    llm = _llm()
    llm.approval_client = _ApprovalClient()  # type: ignore[assignment]

    result = llm.compare(test_plan_id="test-plan")

    assert len(result.responses) == 3
    assert not result.errors
    assert {response.provider for response in result.responses.values()} == {
        "openai",
        "anthropic",
        "gemini",
    }


class _SlowAdapter:
    name = "openai"

    def generate(self, **_: Any) -> Any:
        time.sleep(0.05)
        return SimpleNamespace(provider="openai")


def test_compare_fans_out_in_parallel() -> None:
    llm = logllama.LLM(
        providers={
            "openai": _SlowAdapter(),
            "anthropic": SimpleNamespace(name="anthropic", generate=_SlowAdapter().generate),
            "gemini": SimpleNamespace(name="gemini", generate=_SlowAdapter().generate),
        },
        approval_client=_ApprovalClient(),  # type: ignore[arg-type]
        instrument=False,
    )

    started = time.perf_counter()
    result = llm.compare(test_plan_id="test-plan")
    elapsed = time.perf_counter() - started

    assert len(result.responses) == 3
    assert elapsed < 0.12
