from __future__ import annotations

from typing import Any

from .base import GenerationResponse, Usage, read_value


class CursorAdapter:
    """Normalize a Cursor SDK Agent into the LogLlama ``generate`` contract."""

    name = "cursor"

    def __init__(self, client: Any):
        self.client = client

    def generate(
        self,
        *,
        prompt: str | None,
        messages: list[dict[str, Any]] | None,
        model: str,
        system: str | None,
        max_output_tokens: int | None,
        temperature: float | None,
        metadata: dict[str, Any] | None,
        provider_options: dict[str, Any] | None,
    ) -> GenerationResponse:
        del max_output_tokens, temperature
        message = prompt or _messages_to_text(messages)
        if system:
            message = f"{system}\n\n{message}"

        options = dict(provider_options or {})
        options.setdefault("model", model)
        if metadata and getattr(self.client.send, "_logllama_wrapped", False):
            options["logllama_metadata"] = metadata
        run = self.client.send(message, options) if options else self.client.send(message)
        raw = run.wait()
        return GenerationResponse(
            text=str(read_value(raw, "result", "") or ""),
            provider=self.name,
            model=str(_model_id(read_value(raw, "model")) or model),
            usage=_usage(raw),
            finish_reason=_finish_reason(raw),
            raw=raw,
        )


def _messages_to_text(messages: list[dict[str, Any]] | None) -> str:
    if not messages:
        return ""
    return "\n".join(str(message.get("content", "")) for message in messages)


def _model_id(value: Any) -> Any:
    return read_value(value, "id") or value


def _usage(raw: Any) -> Usage:
    usage = read_value(raw, "usage")
    input_tokens = _int_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _int_value(usage, "output_tokens", "completion_tokens")
    total_tokens = _int_value(usage, "total_tokens") or input_tokens + output_tokens
    return Usage(input_tokens, output_tokens, total_tokens)


def _int_value(value: Any, *names: str) -> int:
    for name in names:
        candidate = read_value(value, name)
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            pass
    return 0


def _finish_reason(raw: Any) -> str | None:
    value = read_value(raw, "status")
    return str(value) if value is not None else None
