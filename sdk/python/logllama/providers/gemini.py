from __future__ import annotations

from typing import Any

from .base import GenerationResponse, Usage, read_value


class GeminiAdapter:
    name = "gemini"

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
        input_value: Any = messages if messages is not None else prompt or ""
        generation_config = dict(provider_options or {})
        if max_output_tokens is not None:
            generation_config["max_output_tokens"] = max_output_tokens
        if temperature is not None:
            generation_config["temperature"] = temperature

        if getattr(self.client, "interactions", None) is not None:
            payload: dict[str, Any] = {"model": model, "input": input_value}
            if system is not None:
                payload["system_instruction"] = system
            if generation_config:
                payload["generation_config"] = generation_config
            if metadata and getattr(self.client.interactions.create, "_logllama_wrapped", False):
                payload["logllama_metadata"] = metadata
            raw = self.client.interactions.create(**payload)
            text = str(read_value(raw, "output_text", "") or "")
        else:
            payload = {"model": model, "contents": input_value}
            config: dict[str, Any] = generation_config
            if system is not None:
                config["system_instruction"] = system
            if config:
                payload["config"] = config
            if metadata and getattr(self.client.models.generate_content, "_logllama_wrapped", False):
                payload["logllama_metadata"] = metadata
            raw = self.client.models.generate_content(**payload)
            text = str(read_value(raw, "text", "") or "")

        return GenerationResponse(
            text=text,
            provider=self.name,
            model=str(read_value(raw, "model", model) or model),
            usage=_gemini_usage(raw),
            finish_reason=_finish_reason(raw),
            raw=raw,
        )


def _gemini_usage(raw: Any) -> Usage:
    usage = read_value(raw, "usage_metadata") or read_value(raw, "usage")
    input_tokens = _int_value(usage, "prompt_token_count", "input_tokens", "total_input_tokens")
    output_tokens = _int_value(
        usage,
        "candidates_token_count",
        "output_tokens",
        "total_output_tokens",
    )
    total_tokens = _int_value(usage, "total_token_count", "total_tokens")
    return Usage(input_tokens, output_tokens, total_tokens or input_tokens + output_tokens)


def _int_value(value: Any, *names: str) -> int:
    for name in names:
        item = read_value(value, name)
        if item is not None:
            try:
                return int(item)
            except (TypeError, ValueError):
                return 0
    return 0


def _finish_reason(raw: Any) -> str | None:
    candidates = read_value(raw, "candidates", []) or []
    if candidates:
        reason = read_value(candidates[0], "finish_reason")
        return str(reason) if reason is not None else None
    status = read_value(raw, "status")
    return str(status) if status is not None else None
