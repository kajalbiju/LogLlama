from __future__ import annotations

import functools
import hashlib
import json
import random
import time
from typing import Any, Callable

from .client import monotonic_ms, new_external_id, now_iso, post_event_async, safe_json
from .config import LogLlamaConfig, get_config, get_context_metadata
from .redaction import redact_text


CORRELATION_FIELDS = {
    "service_name",
    "environment",
    "version",
    "git_sha",
    "route",
    "user_id",
    "tenant_id",
    "session_id",
    "conversation_id",
    "request_id",
    "trace_id",
    "span_id",
    "prompt_template",
    "prompt_version",
}

MODEL_PARAMETER_FIELDS = {
    "candidate_count",
    "frequency_penalty",
    "logprobs",
    "max_completion_tokens",
    "max_output_tokens",
    "max_tokens",
    "presence_penalty",
    "reasoning",
    "reasoning_effort",
    "response_logprobs",
    "response_mime_type",
    "seed",
    "stop",
    "stop_sequences",
    "temperature",
    "text",
    "thinking_config",
    "top_k",
    "top_logprobs",
    "top_p",
}
MODEL_PARAMETER_CONTAINERS = ("config", "generation_config")
PROVIDER_REQUEST_ID_HEADERS = (
    "x-request-id",
    "request-id",
    "x-goog-request-id",
)
RETRY_COUNT_HEADERS = (
    "x-stainless-retry-count",
    "x-retry-count",
    "grpc-previous-rpc-attempts",
)


def wrap_openai(openai_client: Any, **kwargs: Any) -> Any:
    return instrument_openai(openai_client, **kwargs)


def track_openai(openai_client: Any, **kwargs: Any) -> Any:
    return instrument_openai(openai_client, **kwargs)


def instrument_openai(
    openai_client: Any,
    api_key: str | None = None,
    endpoint: str | None = None,
    timeout_seconds: float | None = None,
    capture_prompts: bool | None = None,
    capture_responses: bool | None = None,
    service_name: str | None = None,
    environment: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
    default_metadata: dict[str, Any] | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    redact_keys: list[str] | tuple[str, ...] | None = None,
    max_prompt_size: int | None = None,
    max_response_size: int | None = None,
    metadata_allowlist: list[str] | tuple[str, ...] | None = None,
    metadata_denylist: list[str] | tuple[str, ...] | None = None,
    sample_rate: float | None = None,
    capture_errors: bool | None = None,
    capture_otel: bool | None = None,
    enabled: bool | None = None,
) -> Any:
    config = get_config(
        api_key=api_key,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        capture_prompts=capture_prompts,
        capture_responses=capture_responses,
        service_name=service_name,
        environment=environment,
        version=version,
        git_sha=git_sha,
        default_metadata=default_metadata,
        tags=tags,
        redact_keys=redact_keys,
        max_prompt_size=max_prompt_size,
        max_response_size=max_response_size,
        metadata_allowlist=metadata_allowlist,
        metadata_denylist=metadata_denylist,
        sample_rate=sample_rate,
        capture_errors=capture_errors,
        capture_otel=capture_otel,
        enabled=enabled,
    )

    _wrap_path(openai_client, ("chat", "completions"), "create", "chat.completions.create", config)
    _wrap_path(openai_client, ("responses",), "create", "responses.create", config)
    return openai_client


def _wrap_path(root: Any, path: tuple[str, ...], method_name: str, operation: str, config: LogLlamaConfig) -> None:
    target = root
    for part in path:
        target = getattr(target, part, None)
        if target is None:
            return

    original = getattr(target, method_name, None)
    if original is None or getattr(original, "_logllama_wrapped", False):
        return

    wrapped = _wrap_call(original, operation, config)
    setattr(target, method_name, wrapped)


def _wrap_call(original: Callable[..., Any], operation: str, config: LogLlamaConfig) -> Callable[..., Any]:
    @functools.wraps(original)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        external_id = new_external_id()
        start = time.perf_counter()
        model = kwargs.get("model")
        logllama_metadata = kwargs.pop("logllama_metadata", None)
        prompt = _prepare_capture(_extract_prompt(operation, kwargs), config, "prompt")
        model_parameters = _extract_model_parameters(kwargs, config)
        explicit_retry_count = _metadata_retry_count(logllama_metadata)
        metadata = _build_event_metadata(config, kwargs, external_id, logllama_metadata)
        should_capture_success = _should_capture(config, metadata)

        try:
            response = original(*args, **kwargs)
        except Exception as exc:
            if config.capture_errors:
                post_event_async(
                    config,
                    {
                        "external_id": external_id,
                        "provider": "openai",
                        "operation": operation,
                        "model": model,
                        "status": "error",
                        "prompt": prompt,
                        "response": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                        "latency_ms": monotonic_ms(start),
                        "error": {"type": exc.__class__.__name__, "message": redact_text(str(exc))},
                        "provider_request_id": _extract_provider_request_id(exc),
                        "retry_count": _extract_retry_count(exc, explicit_retry_count),
                        "model_parameters": model_parameters,
                        **metadata,
                        "captured_at": now_iso(),
                    },
                )
            raise

        if not should_capture_success:
            return response

        usage = _extract_usage(response)
        response_model = _extract_response_model(response) or model
        captured_response = _prepare_capture(response, config, "response")
        post_event_async(
            config,
            {
                "external_id": external_id,
                "provider": "openai",
                "operation": operation,
                "model": response_model,
                "status": "success",
                "prompt": prompt,
                "response": captured_response,
                "usage": usage,
                "latency_ms": monotonic_ms(start),
                "error": None,
                "provider_request_id": _extract_provider_request_id(response),
                "retry_count": _extract_retry_count(response, explicit_retry_count),
                "model_parameters": model_parameters,
                **metadata,
                "captured_at": now_iso(),
            },
        )
        return response

    wrapper._logllama_wrapped = True  # type: ignore[attr-defined]
    return wrapper


def _extract_prompt(operation: str, kwargs: dict[str, Any]) -> Any:
    if operation == "responses.create":
        return safe_json(kwargs.get("input"))
    return safe_json(kwargs.get("messages") or kwargs.get("prompt"))


def _extract_request_metadata(kwargs: dict[str, Any], logllama_metadata: Any = None) -> dict[str, Any]:
    metadata = {}
    provider_metadata = kwargs.get("metadata")
    if isinstance(provider_metadata, dict):
        metadata.update(safe_json(provider_metadata))
    if isinstance(logllama_metadata, dict):
        metadata.update(safe_json(logllama_metadata))
    return metadata


def _extract_model_parameters(
    kwargs: dict[str, Any],
    config: LogLlamaConfig,
) -> dict[str, Any]:
    parameters = {
        key: safe_json(value)
        for key, value in kwargs.items()
        if key in MODEL_PARAMETER_FIELDS and value is not None
    }
    for container_name in MODEL_PARAMETER_CONTAINERS:
        container = safe_json(kwargs.get(container_name))
        if not isinstance(container, dict):
            continue
        for key, value in container.items():
            if key in MODEL_PARAMETER_FIELDS and value is not None:
                parameters[key] = safe_json(value)
    return _remove_none_values(_redact_value(parameters, config))


def _remove_none_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_none_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_remove_none_values(item) for item in value if item is not None]
    return value


def _extract_provider_request_id(value: Any) -> str | None:
    for name in ("_request_id", "request_id", "response_id", "id"):
        request_id = _read_value(value, name)
        if request_id:
            return str(request_id)
    headers = _response_headers(value)
    for name in PROVIDER_REQUEST_ID_HEADERS:
        request_id = headers.get(name)
        if request_id:
            return str(request_id)
    return None


def _extract_retry_count(value: Any, explicit_retry_count: int | None = None) -> int:
    if explicit_retry_count is not None:
        return explicit_retry_count
    for name in ("retry_count", "retries_taken"):
        retry_count = _nonnegative_int(_read_value(value, name))
        if retry_count is not None:
            return retry_count
    headers = _response_headers(value)
    for name in RETRY_COUNT_HEADERS:
        retry_count = _nonnegative_int(headers.get(name))
        if retry_count is not None:
            return retry_count
    return 0


def _metadata_retry_count(logllama_metadata: Any) -> int | None:
    if not isinstance(logllama_metadata, dict):
        return None
    return _nonnegative_int(logllama_metadata.get("retry_count"))


def _response_headers(value: Any) -> dict[str, Any]:
    candidates = [
        _read_value(value, "headers"),
        _read_value(_read_value(value, "sdk_http_response"), "headers"),
        _read_value(_read_value(value, "http_response"), "headers"),
        _read_value(_read_value(value, "response"), "headers"),
        _read_value(_read_value(value, "_response"), "headers"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return {str(key).lower(): item for key, item in dict(candidate).items()}
        except (TypeError, ValueError):
            continue
    return {}


def _read_value(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _build_event_metadata(
    config: LogLlamaConfig,
    kwargs: dict[str, Any],
    external_id: str,
    logllama_metadata: Any = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged.update(
        {
            "service_name": config.service_name,
            "environment": config.environment,
            "version": config.version,
            "git_sha": config.git_sha,
        }
    )
    if config.default_metadata:
        merged.update(safe_json(config.default_metadata))
    merged.update(get_context_metadata())
    merged.update(_extract_request_metadata(kwargs, logllama_metadata))
    merged.update(_extract_otel_ids(config))
    merged.pop("retry_count", None)

    normalized = _filter_metadata(_redact_value(merged, config), config)
    custom_metadata = normalized.pop("custom_metadata", {})
    if not isinstance(custom_metadata, dict):
        custom_metadata = {"value": custom_metadata}

    event_metadata = {
        field: normalized.pop(field, None)
        for field in sorted(CORRELATION_FIELDS)
    }
    tags = _normalize_tags(config.tags, merged.get("tags"))
    allowed_fields = {key.lower() for key in config.metadata_allowlist} if config.metadata_allowlist else None
    if "tags" not in _denylisted_fields(config) and (allowed_fields is None or "tags" in allowed_fields):
        event_metadata["tags"] = tags
    else:
        event_metadata["tags"] = []
    normalized.pop("tags", None)

    event_metadata.update(
        {
            "custom_metadata": {
                **custom_metadata,
                **normalized,
            },
            "metadata": {
                **{key: value for key, value in event_metadata.items() if value is not None},
                "tags": tags,
                "custom_metadata": {**custom_metadata, **normalized},
            },
            "privacy": {
                "capture_prompts": config.capture_prompts,
                "capture_responses": config.capture_responses,
                "redact_keys": sorted(set(config.redact_keys)),
                "max_prompt_size": config.max_prompt_size,
                "max_response_size": config.max_response_size,
                "metadata_allowlist": list(config.metadata_allowlist) if config.metadata_allowlist else None,
                "metadata_denylist": list(config.metadata_denylist),
                "sample_rate": config.sample_rate,
                "sampled": config.sample_rate < 1.0,
                "sample_key": external_id,
            },
        }
    )
    return event_metadata


def _prepare_capture(value: Any, config: LogLlamaConfig, payload_type: str) -> Any:
    enabled = config.capture_prompts if payload_type == "prompt" else config.capture_responses
    if not enabled:
        return {
            "_logllama_capture": "disabled",
            "payload_type": payload_type,
        }

    redacted = _redact_value(safe_json(value), config)
    max_size = config.max_prompt_size if payload_type == "prompt" else config.max_response_size
    return _truncate_value(redacted, max_size, payload_type)


def _redact_value(value: Any, config: LogLlamaConfig) -> Any:
    redact_keys = {key.lower() for key in config.redact_keys}
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in redact_keys:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = _redact_value(item, config)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item, config) for item in value]
    return value


def _truncate_value(value: Any, max_size: int | None, payload_type: str) -> Any:
    if max_size is None or max_size <= 0:
        return value
    encoded = json.dumps(value, default=str)
    size = len(encoded.encode("utf-8"))
    if size <= max_size:
        return value
    preview = encoded.encode("utf-8")[:max_size].decode("utf-8", errors="ignore")
    return {
        "_logllama_capture": "truncated",
        "payload_type": payload_type,
        "size_bytes": size,
        "max_size_bytes": max_size,
        "preview": preview,
    }


def _filter_metadata(metadata: dict[str, Any], config: LogLlamaConfig) -> dict[str, Any]:
    denylist = _denylisted_fields(config)
    allowlist = {key.lower() for key in config.metadata_allowlist} if config.metadata_allowlist else None
    filtered = {}
    for key, value in metadata.items():
        normalized_key = str(key)
        comparable = normalized_key.lower()
        if comparable in denylist:
            continue
        if allowlist is not None and comparable not in allowlist:
            continue
        filtered[normalized_key] = value
    return filtered


def _denylisted_fields(config: LogLlamaConfig) -> set[str]:
    return {key.lower() for key in config.metadata_denylist}


def _normalize_tags(config_tags: tuple[str, ...], request_tags: Any) -> list[str]:
    tags = list(config_tags)
    if isinstance(request_tags, str):
        tags.append(request_tags)
    elif isinstance(request_tags, (list, tuple, set)):
        tags.extend(str(tag) for tag in request_tags if tag is not None)
    return sorted(set(tags))


def _should_capture(config: LogLlamaConfig, metadata: dict[str, Any]) -> bool:
    if config.sample_rate >= 1.0:
        return True
    if config.sample_rate <= 0.0:
        return False
    seed = (
        metadata.get("request_id")
        or metadata.get("trace_id")
        or metadata.get("conversation_id")
        or metadata.get("metadata", {}).get("request_id")
    )
    if seed:
        digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()
        value = int(digest[:8], 16) / 0xFFFFFFFF
        return value < config.sample_rate
    return random.random() < config.sample_rate


def _extract_otel_ids(config: LogLlamaConfig) -> dict[str, str]:
    if not config.capture_otel:
        return {}
    try:
        from opentelemetry import trace
    except Exception:
        return {}

    try:
        span_context = trace.get_current_span().get_span_context()
    except Exception:
        return {}
    if not getattr(span_context, "is_valid", False):
        return {}
    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


def _extract_response_model(response: Any) -> str | None:
    model = getattr(response, "model", None) or getattr(response, "model_version", None)
    if model:
        return str(model)
    if isinstance(response, dict) and response.get("model"):
        return str(response["model"])
    return None


def _extract_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        usage = getattr(response, "usage_metadata", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage") or response.get("usage_metadata")

    input_tokens = _get_usage_value(usage, "prompt_tokens", "input_tokens", "prompt_token_count")
    output_tokens = _get_usage_value(
        usage, "completion_tokens", "output_tokens", "candidates_token_count"
    )
    total_tokens = _get_usage_value(usage, "total_tokens", "total_token_count")
    if not total_tokens:
        total_tokens = input_tokens + output_tokens

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _get_usage_value(usage: Any, *names: str) -> int:
    if usage is None:
        return 0
    for name in names:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(name)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0
