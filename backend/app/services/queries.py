import uuid
from datetime import datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LLMRequest


def resolve_window_minutes(
    *,
    minutes: int | None = None,
    hours: int | None = None,
    days: int | None = None,
) -> int:
    if minutes is not None:
        return minutes
    if hours is not None:
        return hours * 60
    if days is not None:
        return days * 24 * 60
    return 24 * 60


def apply_request_filters(
    query: Select,
    *,
    status_filter: str | None = None,
    model: str | None = None,
    service_name: str | None = None,
    environment: str | None = None,
    route: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    conversation_id: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    prompt_template: str | None = None,
    prompt_version: str | None = None,
    q: str | None = None,
) -> Select:
    if status_filter:
        query = query.where(LLMRequest.status == status_filter)
    if model:
        query = query.where(LLMRequest.model == model)

    filters = {
        "service_name": service_name,
        "environment": environment,
        "route": route,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "request_id": request_id,
        "trace_id": trace_id,
        "prompt_template": prompt_template,
        "prompt_version": prompt_version,
    }
    for field, value in filters.items():
        if value:
            query = query.where(getattr(LLMRequest, field) == value)

    if q:
        search = f"%{q.strip()}%"
        if search != "%%":
            query = query.where(
                or_(
                    LLMRequest.model.ilike(search),
                    LLMRequest.operation.ilike(search),
                    LLMRequest.status.ilike(search),
                    LLMRequest.service_name.ilike(search),
                    LLMRequest.environment.ilike(search),
                    LLMRequest.route.ilike(search),
                    LLMRequest.user_id.ilike(search),
                    LLMRequest.tenant_id.ilike(search),
                    LLMRequest.session_id.ilike(search),
                    LLMRequest.conversation_id.ilike(search),
                    LLMRequest.request_id.ilike(search),
                    LLMRequest.provider_request_id.ilike(search),
                    LLMRequest.trace_id.ilike(search),
                    LLMRequest.prompt_template.ilike(search),
                    LLMRequest.prompt_version.ilike(search),
                )
            )

    return query


async def distinct_values(
    session: AsyncSession,
    project_id: uuid.UUID,
    column,
    since: datetime | None = None,
    filters: dict[str, str | None] | None = None,
) -> list[str]:
    query = select(column).where(LLMRequest.project_id == project_id, column.is_not(None))
    if since is not None:
        query = query.where(LLMRequest.captured_at >= since)
    if filters:
        query = apply_request_filters(query, **filters)
    result = await session.execute(query.distinct().order_by(column).limit(200))
    return [str(value) for value in result.scalars() if value]
