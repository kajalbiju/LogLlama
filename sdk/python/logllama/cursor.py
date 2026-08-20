from __future__ import annotations

import functools
import time
from typing import Any, Callable

from .client import monotonic_ms, new_external_id, now_iso, post_event_async, safe_json
from .config import LogLlamaConfig, get_config
from .openai import (
    _build_event_metadata,
    _extract_provider_request_id,
    _extract_retry_count,
    _metadata_retry_count,
    _prepare_capture,
    _should_capture,
)


def wrap_cursor(cursor_agent: Any, **kwargs: Any) -> Any:
    """Instrument a ``cursor_sdk.Agent`` instance.

    Cursor agent runs are asynchronous from the SDK's perspective: ``send``
    returns a Run and ``wait`` (or ``text``) yields its terminal result.  The
    wrapper intentionally emits a success event only once that result is
    available, so response and usage fields reflect the completed run.
    """
    original = getattr(cursor_agent, "send", None)
    if original is None or getattr(original, "_logllama_wrapped", False):
        return cursor_agent

    config = get_config(**kwargs)

    @functools.wraps(original)
    def send(*args: Any, **call_kwargs: Any) -> Any:
        args, call_kwargs, logllama_metadata = _remove_logllama_metadata(args, call_kwargs)
        external_id = new_external_id()
        start = time.perf_counter()
        prompt = _prepare_capture(_message_from_call(args, call_kwargs), config, "prompt")
        model = _model_from_call(cursor_agent, args, call_kwargs)
        metadata = _build_event_metadata(config, call_kwargs, external_id, logllama_metadata)
        should_capture = _should_capture(config, metadata)
        retry_count = _metadata_retry_count(logllama_metadata)

        try:
            run = original(*args, **call_kwargs)
        except Exception as exc:
            _capture_error(
                config, external_id, model, prompt, metadata, retry_count, start, exc
            )
            raise

        return _TrackedCursorRun(
            run,
            lambda response: _capture_success(
                config,
                external_id,
                model,
                prompt,
                metadata,
                retry_count,
                start,
                response,
                should_capture,
            ),
            lambda exc: _capture_error(
                config, external_id, model, prompt, metadata, retry_count, start, exc
            ),
        )

    send._logllama_wrapped = True  # type: ignore[attr-defined]
    setattr(cursor_agent, "send", send)
    return cursor_agent


instrument_cursor = wrap_cursor
track_cursor = wrap_cursor


class _TrackedCursorRun:
    """Transparent Run proxy that records one terminal result."""

    def __init__(
        self,
        run: Any,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self._run = run
        self._on_success = on_success
        self._on_error = on_error
        self._captured = False

    def wait(self, *args: Any, **kwargs: Any) -> Any:
        return self._terminal("wait", *args, **kwargs)

    def text(self, *args: Any, **kwargs: Any) -> Any:
        return self._terminal("text", *args, **kwargs)

    def _terminal(self, name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self._run, name)
        try:
            result = method(*args, **kwargs)
        except Exception as exc:
            self._capture_error(exc)
            raise
        response = result
        if name == "text":
            response = {
                "id": _read_value(self._run, "run_id"),
                "result": result,
                "usage": _read_value(self._run, "usage"),
            }
        self._capture_success(response)
        return result

    def _capture_success(self, response: Any) -> None:
        if not self._captured:
            self._captured = True
            self._on_success(response)

    def _capture_error(self, exc: Exception) -> None:
        if not self._captured:
            self._captured = True
            self._on_error(exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._run, name)


def _remove_logllama_metadata(
    args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any], Any]:
    kwargs = dict(kwargs)
    metadata = kwargs.pop("logllama_metadata", None)

    # Cursor SDK accepts a mapping as its optional SendOptions argument.  Keep
    # LogLlama correlation metadata out of that provider payload.
    if len(args) >= 2 and isinstance(args[1], dict):
        options = dict(args[1])
        metadata = options.pop("logllama_metadata", metadata)
        args = (args[0], options, *args[2:])
    elif isinstance(kwargs.get("options"), dict):
        options = dict(kwargs["options"])
        metadata = options.pop("logllama_metadata", metadata)
        kwargs["options"] = options
    return args, kwargs, metadata


def _message_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if args:
        return args[0]
    return kwargs.get("message")


def _model_from_call(agent: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    options = args[1] if len(args) >= 2 else kwargs.get("options")
    model = _read_value(options, "model") or _read_value(agent, "model")
    model_id = _read_value(model, "id")
    return str(model_id or model) if model is not None else None


def _capture_error(
    config: LogLlamaConfig,
    external_id: str,
    model: str | None,
    prompt: Any,
    metadata: dict[str, Any],
    retry_count: int | None,
    start: float,
    exc: Exception,
) -> None:
    if not config.capture_errors:
        return
    post_event_async(
        config,
        {
            "external_id": external_id,
            "provider": "cursor",
            "operation": "agents.send",
            "model": model,
            "status": "error",
            "prompt": prompt,
            "response": None,
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "latency_ms": monotonic_ms(start),
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
            "provider_request_id": _extract_provider_request_id(exc),
            "retry_count": _extract_retry_count(exc, retry_count),
            "model_parameters": {},
            **metadata,
            "captured_at": now_iso(),
        },
    )


def _capture_success(
    config: LogLlamaConfig,
    external_id: str,
    requested_model: str | None,
    prompt: Any,
    metadata: dict[str, Any],
    retry_count: int | None,
    start: float,
    response: Any,
    should_capture: bool,
) -> None:
    if not should_capture:
        return
    payload = _cursor_response_payload(response)
    post_event_async(
        config,
        {
            "external_id": external_id,
            "provider": "cursor",
            "operation": "agents.send",
            "model": str(payload.get("model") or requested_model) if (payload.get("model") or requested_model) else None,
            "status": "success",
            "prompt": prompt,
            "response": _prepare_capture(payload, config, "response"),
            "usage": _cursor_usage(response),
            "latency_ms": monotonic_ms(start),
            "error": None,
            "provider_request_id": _extract_provider_request_id(response),
            "retry_count": _extract_retry_count(response, retry_count),
            "model_parameters": {},
            **metadata,
            "captured_at": now_iso(),
        },
    )


def _cursor_response_payload(response: Any) -> dict[str, Any]:
    payload = safe_json(response)
    if isinstance(payload, dict):
        return payload
    return {
        "id": _read_value(response, "id") or _read_value(response, "run_id"),
        "model": _model_value(_read_value(response, "model")),
        "status": _read_value(response, "status"),
        "result": _read_value(response, "result") or payload,
    }


def _cursor_usage(response: Any) -> dict[str, int]:
    usage = _read_value(response, "usage")
    input_tokens = _int_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _int_value(usage, "output_tokens", "completion_tokens")
    total_tokens = _int_value(usage, "total_tokens") or input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _read_value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _model_value(model: Any) -> Any:
    return _read_value(model, "id") or model


def _int_value(value: Any, *names: str) -> int:
    for name in names:
        candidate = _read_value(value, name)
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            pass
    return 0
