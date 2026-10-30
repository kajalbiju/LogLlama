import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..deps import project_from_query, require_csrf_header
from ..models import LLMRequest, Project
from ..schemas import MetadataFacetsOut, RequestListOut, RequestOut, SummaryOut
from ..services.queries import apply_request_filters, distinct_values, resolve_window_minutes


router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf_header)])


@router.get("/requests", response_model=RequestListOut)
async def list_requests(
    project: Project = Depends(project_from_query("data:read")),
    status_filter: str | None = Query(default=None, alias="status"),
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
    minutes: int | None = Query(default=None, ge=1, le=60 * 24 * 30),
    days: int | None = Query(default=None, ge=1, le=30),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> RequestListOut:
    since = datetime.now(timezone.utc) - timedelta(minutes=resolve_window_minutes(minutes=minutes, days=days))
    query: Select = select(LLMRequest).where(
        LLMRequest.project_id == project.id,
        LLMRequest.captured_at >= since,
    )
    query = apply_request_filters(
        query,
        status_filter=status_filter,
        model=model,
        service_name=service_name,
        environment=environment,
        route=route,
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        trace_id=trace_id,
        prompt_template=prompt_template,
        prompt_version=prompt_version,
        q=q,
    )
    query = query.order_by(LLMRequest.captured_at.desc()).limit(limit)
    result = await session.execute(query)
    return RequestListOut(requests=list(result.scalars()))


@router.get("/requests/{request_id}", response_model=RequestOut)
async def get_request(
    request_id: uuid.UUID,
    project: Project = Depends(project_from_query("data:read")),
    session: AsyncSession = Depends(get_session),
) -> LLMRequest:
    result = await session.execute(
        select(LLMRequest).where(LLMRequest.id == request_id, LLMRequest.project_id == project.id)
    )
    request = result.scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    return request


@router.get("/metadata/facets", response_model=MetadataFacetsOut)
async def metadata_facets(
    project: Project = Depends(project_from_query("data:read")),
    minutes: int | None = Query(default=None, ge=1, le=60 * 24 * 30),
    days: int | None = Query(default=None, ge=1, le=30),
    status_filter: str | None = Query(default=None, alias="status"),
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
    session: AsyncSession = Depends(get_session),
) -> MetadataFacetsOut:
    since = datetime.now(timezone.utc) - timedelta(minutes=resolve_window_minutes(minutes=minutes, days=days))
    filters = {
        "status_filter": status_filter,
        "model": model,
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
        "q": q,
    }
    project_id = project.id
    return MetadataFacetsOut(
        service_names=await distinct_values(session, project_id, LLMRequest.service_name, since, filters),
        environments=await distinct_values(session, project_id, LLMRequest.environment, since, filters),
        routes=await distinct_values(session, project_id, LLMRequest.route, since, filters),
        tenant_ids=await distinct_values(session, project_id, LLMRequest.tenant_id, since, filters),
        prompt_templates=await distinct_values(session, project_id, LLMRequest.prompt_template, since, filters),
        models=await distinct_values(session, project_id, LLMRequest.model, since, filters),
        statuses=await distinct_values(session, project_id, LLMRequest.status, since, filters),
    )


@router.get("/metrics/summary", response_model=SummaryOut)
async def metrics_summary(
    project: Project = Depends(project_from_query("data:read")),
    minutes: int | None = Query(default=None, ge=1, le=60 * 24 * 30),
    hours: int | None = Query(default=None, ge=1, le=24 * 30),
    status_filter: str | None = Query(default=None, alias="status"),
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
    session: AsyncSession = Depends(get_session),
) -> SummaryOut:
    window_minutes = resolve_window_minutes(minutes=minutes, hours=hours)
    since = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    base_query = apply_request_filters(
        select(LLMRequest).where(LLMRequest.project_id == project.id, LLMRequest.captured_at >= since),
        status_filter=status_filter,
        model=model,
        service_name=service_name,
        environment=environment,
        route=route,
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        conversation_id=conversation_id,
        request_id=request_id,
        trace_id=trace_id,
        prompt_template=prompt_template,
        prompt_version=prompt_version,
        q=q,
    ).subquery()

    total_query = select(
        func.count(base_query.c.id),
        # Requests with unknown cost are excluded from the cost total rather than counted as zero.
        func.coalesce(func.sum(base_query.c.cost_usd), 0),
        func.coalesce(func.avg(base_query.c.latency_ms), 0),
        func.coalesce(func.sum(case((base_query.c.status == "error", 1), else_=0)), 0),
        func.coalesce(func.sum(base_query.c.total_tokens), 0),
    )
    total_requests, total_cost, avg_latency, error_count, total_tokens = (await session.execute(total_query)).one()

    bucket_name = "minute" if window_minutes <= 60 else "hour"
    bucket = func.date_trunc(bucket_name, base_query.c.captured_at).label("bucket")
    series_query = (
        select(
            bucket,
            func.count(base_query.c.id).label("requests"),
            func.coalesce(func.sum(base_query.c.cost_usd), 0).label("cost_usd"),
            func.coalesce(func.avg(base_query.c.latency_ms), 0).label("avg_latency_ms"),
            func.coalesce(func.sum(case((base_query.c.status == "error", 1), else_=0)), 0).label("error_count"),
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    series = [
        {
            "bucket": row.bucket,
            "requests": row.requests,
            "cost_usd": row.cost_usd,
            "avg_latency_ms": float(row.avg_latency_ms),
            "error_count": row.error_count,
        }
        for row in (await session.execute(series_query))
    ]

    total_requests = int(total_requests or 0)
    error_rate = float(error_count or 0) / total_requests if total_requests else 0.0
    return SummaryOut(
        total_requests=total_requests,
        total_cost_usd=total_cost,
        avg_latency_ms=float(avg_latency or 0),
        error_rate=error_rate,
        total_tokens=int(total_tokens or 0),
        series=series,
    )


@router.get("/traces/{trace_id}", response_model=RequestListOut)
async def get_trace(
    trace_id: str,
    project: Project = Depends(project_from_query("data:read")),
    session: AsyncSession = Depends(get_session),
) -> RequestListOut:
    result = await session.execute(
        select(LLMRequest)
        .where(LLMRequest.project_id == project.id, LLMRequest.trace_id == trace_id)
        .order_by(LLMRequest.captured_at.asc())
    )
    return RequestListOut(requests=list(result.scalars()))


@router.get("/conversations/{conversation_id}", response_model=RequestListOut)
async def get_conversation(
    conversation_id: str,
    project: Project = Depends(project_from_query("data:read")),
    session: AsyncSession = Depends(get_session),
) -> RequestListOut:
    result = await session.execute(
        select(LLMRequest)
        .where(LLMRequest.project_id == project.id, LLMRequest.conversation_id == conversation_id)
        .order_by(LLMRequest.captured_at.asc())
    )
    return RequestListOut(requests=list(result.scalars()))
