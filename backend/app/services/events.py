import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LLMRequest
from ..pricing import estimate_cost_usd
from ..schemas import EventIn
from .redaction import redact_text


CORRELATION_FIELDS = (
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
)

# Postgres caps a statement at 32,767 bind parameters. Chunking keeps large batches under that limit.
INSERT_CHUNK_ROWS = 200
MAX_ERROR_MESSAGE_CHARS = 2000


def normalize_event_metadata(event: EventIn) -> dict[str, Any]:
    metadata = dict(event.metadata or {})
    custom_metadata = dict(event.custom_metadata or {})

    normalized: dict[str, Any] = {}
    for field in CORRELATION_FIELDS:
        normalized[field] = getattr(event, field) or metadata.get(field)

    tags = event.tags if event.tags is not None else metadata.get("tags")
    normalized["tags"] = tags if isinstance(tags, list) else []

    metadata_custom = metadata.get("custom_metadata")
    if isinstance(metadata_custom, dict):
        custom_metadata = {**metadata_custom, **custom_metadata}

    reserved = {*CORRELATION_FIELDS, "tags", "custom_metadata", "privacy"}
    for key, value in metadata.items():
        if key not in reserved:
            custom_metadata.setdefault(key, value)

    normalized["custom_metadata"] = custom_metadata
    normalized["privacy"] = event.privacy or metadata.get("privacy") or {}
    normalized["request_metadata"] = {
        **{field: value for field, value in normalized.items() if field in CORRELATION_FIELDS and value is not None},
        "tags": normalized["tags"],
        "custom_metadata": custom_metadata,
    }
    return normalized


def _error_message(event: EventIn) -> str | None:
    """Redact, then cap, the provider error text so one failure cannot store an unbounded body."""
    if not event.error or not event.error.message:
        return None
    return redact_text(event.error.message)[:MAX_ERROR_MESSAGE_CHARS]


def build_request_row(event: EventIn, project_id: uuid.UUID, now: datetime) -> dict[str, Any]:
    usage = event.usage
    total_tokens = usage.total_tokens or usage.input_tokens + usage.output_tokens
    cost_usd = event.cost_usd
    if cost_usd is None:
        cost_usd = estimate_cost_usd(event.model, usage.input_tokens, usage.output_tokens)

    normalized = normalize_event_metadata(event)
    return {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "external_id": event.external_id,
        "provider": event.provider,
        "operation": event.operation,
        "model": event.model,
        "provider_request_id": event.provider_request_id,
        "retry_count": event.retry_count,
        "model_parameters": event.model_parameters,
        "status": event.status,
        "prompt": event.prompt,
        "response": event.response,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
        "latency_ms": event.latency_ms,
        "error_type": event.error.type if event.error else None,
        "error_message": _error_message(event),
        "service_name": normalized["service_name"],
        "environment": normalized["environment"],
        "version": normalized["version"],
        "git_sha": normalized["git_sha"],
        "route": normalized["route"],
        "user_id": normalized["user_id"],
        "tenant_id": normalized["tenant_id"],
        "session_id": normalized["session_id"],
        "conversation_id": normalized["conversation_id"],
        "request_id": normalized["request_id"],
        "trace_id": normalized["trace_id"],
        "span_id": normalized["span_id"],
        "prompt_template": normalized["prompt_template"],
        "prompt_version": normalized["prompt_version"],
        "tags": normalized["tags"],
        "custom_metadata": normalized["custom_metadata"],
        "privacy": normalized["privacy"],
        "request_metadata": normalized["request_metadata"],
        "captured_at": event.captured_at or now,
        "created_at": now,
    }


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def insert_events(session: AsyncSession, project_id: uuid.UUID, events: list[EventIn]) -> tuple[int, int]:
    """Insert events for one project. Returns (accepted, duplicates); duplicates share a project and external_id."""
    now = datetime.now(timezone.utc)
    rows = [build_request_row(event, project_id, now) for event in events]

    accepted = 0
    for chunk in _chunks(rows, INSERT_CHUNK_ROWS):
        result = await session.execute(insert(LLMRequest).values(chunk).on_conflict_do_nothing())
        accepted += result.rowcount or 0

    await session.commit()
    return accepted, len(rows) - accepted
