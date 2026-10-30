from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from contextvars import ContextVar
from typing import Any, Iterator


@dataclass(frozen=True, slots=True)
class LogLlamaConfig:
    api_key: str | None = None
    endpoint: str = "http://localhost:8000"
    timeout_seconds: float = 1.0
    capture_prompts: bool = True
    capture_responses: bool = True
    service_name: str | None = None
    environment: str | None = None
    version: str | None = None
    git_sha: str | None = None
    default_metadata: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()
    redact_keys: tuple[str, ...] = (
        "api_key",
        "authorization",
        "cookie",
        "password",
        "secret",
        "ssn",
        "token",
    )
    max_prompt_size: int | None = None
    max_response_size: int | None = None
    metadata_allowlist: tuple[str, ...] | None = None
    metadata_denylist: tuple[str, ...] = ()
    sample_rate: float = 1.0
    capture_errors: bool = True
    capture_otel: bool = True
    enabled: bool = True
    # Events are queued in memory and sent in batches. When the queue is full, new events are dropped
    # and counted, so telemetry never blocks a provider call.
    batch_size: int = 50
    flush_interval_seconds: float = 1.0
    max_queue_size: int = 10_000


_config = LogLlamaConfig()
_env_loaded = False
_context_metadata: ContextVar[dict[str, Any]] = ContextVar("logllama_context_metadata", default={})


def init(
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
    batch_size: int | None = None,
    flush_interval_seconds: float | None = None,
    max_queue_size: int | None = None,
) -> LogLlamaConfig:
    """Configure LogLlama once for the current Python process."""
    global _config

    env_config = config_from_env()
    updates: dict[str, Any] = {
        "api_key": api_key if api_key is not None else env_config.api_key,
        "endpoint": endpoint if endpoint is not None else env_config.endpoint,
        "timeout_seconds": timeout_seconds if timeout_seconds is not None else env_config.timeout_seconds,
        "capture_prompts": capture_prompts if capture_prompts is not None else env_config.capture_prompts,
        "capture_responses": capture_responses if capture_responses is not None else env_config.capture_responses,
        "service_name": service_name if service_name is not None else env_config.service_name,
        "environment": environment if environment is not None else env_config.environment,
        "version": version if version is not None else env_config.version,
        "git_sha": git_sha if git_sha is not None else env_config.git_sha,
        "default_metadata": default_metadata if default_metadata is not None else env_config.default_metadata,
        "tags": tuple(tags) if tags is not None else env_config.tags,
        "redact_keys": tuple(redact_keys) if redact_keys is not None else env_config.redact_keys,
        "max_prompt_size": max_prompt_size if max_prompt_size is not None else env_config.max_prompt_size,
        "max_response_size": max_response_size if max_response_size is not None else env_config.max_response_size,
        "metadata_allowlist": (
            tuple(metadata_allowlist) if metadata_allowlist is not None else env_config.metadata_allowlist
        ),
        "metadata_denylist": tuple(metadata_denylist) if metadata_denylist is not None else env_config.metadata_denylist,
        "sample_rate": _clamp_sample_rate(sample_rate if sample_rate is not None else env_config.sample_rate),
        "capture_errors": capture_errors if capture_errors is not None else env_config.capture_errors,
        "capture_otel": capture_otel if capture_otel is not None else env_config.capture_otel,
        "enabled": enabled if enabled is not None else env_config.enabled,
        "batch_size": batch_size if batch_size is not None else env_config.batch_size,
        "flush_interval_seconds": (
            flush_interval_seconds if flush_interval_seconds is not None else env_config.flush_interval_seconds
        ),
        "max_queue_size": max_queue_size if max_queue_size is not None else env_config.max_queue_size,
    }
    _config = replace(_config, **updates)
    return _config


def get_config(**overrides: Any) -> LogLlamaConfig:
    config = config_from_env()
    for key, value in overrides.items():
        if value is not None:
            config = replace(config, **{key: value})
    return config


def config_from_env() -> LogLlamaConfig:
    load_dotenv()
    return LogLlamaConfig(
        api_key=os.getenv("LOGLLAMA_API_KEY") or _config.api_key,
        endpoint=os.getenv("LOGLLAMA_ENDPOINT") or _config.endpoint,
        timeout_seconds=_float_env("LOGLLAMA_TIMEOUT_SECONDS", _config.timeout_seconds),
        capture_prompts=_bool_env("LOGLLAMA_CAPTURE_PROMPTS", _config.capture_prompts),
        capture_responses=_bool_env("LOGLLAMA_CAPTURE_RESPONSES", _config.capture_responses),
        service_name=os.getenv("LOGLLAMA_SERVICE_NAME") or _config.service_name,
        environment=os.getenv("LOGLLAMA_ENVIRONMENT") or _config.environment,
        version=os.getenv("LOGLLAMA_VERSION") or _config.version,
        git_sha=os.getenv("LOGLLAMA_GIT_SHA") or _config.git_sha,
        default_metadata=_config.default_metadata,
        tags=_list_env("LOGLLAMA_TAGS", _config.tags),
        redact_keys=_list_env("LOGLLAMA_REDACT_KEYS", _config.redact_keys),
        max_prompt_size=_int_env("LOGLLAMA_MAX_PROMPT_SIZE", _config.max_prompt_size),
        max_response_size=_int_env("LOGLLAMA_MAX_RESPONSE_SIZE", _config.max_response_size),
        metadata_allowlist=_optional_list_env("LOGLLAMA_METADATA_ALLOWLIST", _config.metadata_allowlist),
        metadata_denylist=_list_env("LOGLLAMA_METADATA_DENYLIST", _config.metadata_denylist),
        sample_rate=_clamp_sample_rate(_float_env("LOGLLAMA_SAMPLE_RATE", _config.sample_rate)),
        capture_errors=_bool_env("LOGLLAMA_CAPTURE_ERRORS", _config.capture_errors),
        capture_otel=_bool_env("LOGLLAMA_CAPTURE_OTEL", _config.capture_otel),
        enabled=_bool_env("LOGLLAMA_ENABLED", _config.enabled),
        batch_size=_int_env("LOGLLAMA_BATCH_SIZE", _config.batch_size) or _config.batch_size,
        flush_interval_seconds=_float_env("LOGLLAMA_FLUSH_INTERVAL_SECONDS", _config.flush_interval_seconds),
        max_queue_size=_int_env("LOGLLAMA_MAX_QUEUE_SIZE", _config.max_queue_size) or _config.max_queue_size,
    )


@contextmanager
def context(**metadata: Any) -> Iterator[None]:
    """Attach correlation metadata to LogLlama events in this execution context."""
    current = dict(_context_metadata.get())
    current.update({key: value for key, value in metadata.items() if value is not None})
    token = _context_metadata.set(current)
    try:
        yield
    finally:
        _context_metadata.reset(token)


def get_context_metadata() -> dict[str, Any]:
    return dict(_context_metadata.get())


def load_dotenv(path: str | Path | None = None) -> None:
    """Load simple KEY=VALUE pairs from .env without requiring python-dotenv."""
    global _env_loaded
    if _env_loaded and path is None:
        return

    env_path = Path(path) if path else _find_dotenv()
    if env_path is None or not env_path.exists():
        _env_loaded = True
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

    _env_loaded = True


def _find_dotenv() -> Path | None:
    current = Path.cwd()
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.exists():
            return candidate
    return None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_env(name: str, default: int | None) -> int | None:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _list_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _optional_list_env(name: str, default: tuple[str, ...] | None) -> tuple[str, ...] | None:
    value = os.getenv(name)
    if value is None:
        return default
    values = tuple(item.strip() for item in value.split(",") if item.strip())
    return values or None


def _clamp_sample_rate(value: float) -> float:
    return min(1.0, max(0.0, value))
