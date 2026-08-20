import asyncio
import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Select, case, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import is_secure_privileged_key, settings
from .database import Base, engine, get_session
from .models import LLMRequest, Project, ProviderCredential, TestPlan
from .pricing import estimate_cost_usd, extract_response_usage
from .schemas import (
    EventIn,
    EventBatchIn,
    EventBatchOut,
    MetadataFacetsOut,
    ProviderCredentialCreate,
    ProviderCredentialListOut,
    ProviderCredentialOut,
    RequestListOut,
    RequestOut,
    RuntimeCredentialListOut,
    SummaryOut,
    TestPlanCreate,
    TestPlanDecision,
    TestPlanListOut,
    TestPlanOut,
)
from .secret_store import get_secret_store


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_metadata_columns(conn)

    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(Project).where(Project.api_key == settings.default_api_key)
        )
        project = result.scalar_one_or_none()
        if project is None:
            project = Project(
                name=settings.default_project_name,
                api_key=settings.default_api_key,
                runtime_key=settings.default_runtime_key,
            )
            session.add(project)
        elif settings.default_runtime_key:
            project.runtime_key = settings.default_runtime_key
        elif project.runtime_key and not is_secure_privileged_key(project.runtime_key):
            project.runtime_key = None
        await repair_missing_cost_estimates(session)
        await session.commit()

    yield


app = FastAPI(title="LogLlama API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def project_from_api_key(
    x_logllama_api_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Project:
    if not x_logllama_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-LogLlama-Api-Key header.",
        )

    result = await session.execute(select(Project).where(Project.api_key == x_logllama_api_key))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
    return project


async def project_from_runtime_key(
    x_logllama_runtime_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Project:
    if not x_logllama_runtime_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-LogLlama-Runtime-Key header.",
        )
    if not is_secure_privileged_key(x_logllama_runtime_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid runtime key.")
    result = await session.execute(
        select(Project).where(Project.runtime_key == x_logllama_runtime_key)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid runtime key.")
    return project


async def require_admin(
    x_logllama_admin_key: str | None = Header(default=None),
) -> None:
    if settings.admin_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured.",
        )
    if not x_logllama_admin_key or not hmac.compare_digest(
        x_logllama_admin_key, settings.admin_api_key
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key.")


def require_persistent_secret_store() -> None:
    if settings.secret_backend == "memory" and not settings.allow_ephemeral_secrets:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Provider credential writes require a persistent secret backend. "
                "Configure OpenBao, Vault, or AWS Secrets Manager. "
                "Set LOGLLAMA_ALLOW_EPHEMERAL_SECRETS=true only for disposable development."
            ),
        )


async def default_project(session: AsyncSession) -> Project:
    result = await session.execute(select(Project).where(Project.api_key == settings.default_api_key))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=500, detail="Default project was not initialized.")
    return project


async def ensure_metadata_columns(conn) -> None:
    statements = [
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS runtime_key VARCHAR(255)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_runtime_key ON projects (runtime_key)",
        "ALTER TABLE test_plans ADD COLUMN IF NOT EXISTS max_runs INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE test_plans ADD COLUMN IF NOT EXISTS run_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS service_name VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS provider_request_id VARCHAR(255)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS model_parameters JSONB",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_provider_request_id ON llm_requests (provider_request_id)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS environment VARCHAR(80)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS version VARCHAR(120)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS git_sha VARCHAR(80)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS route VARCHAR(240)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS user_id VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS session_id VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS request_id VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS trace_id VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS span_id VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS prompt_template VARCHAR(160)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(80)",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS tags JSONB",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS custom_metadata JSONB",
        "ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS privacy JSONB",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_service_name ON llm_requests (service_name)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_environment ON llm_requests (environment)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_route ON llm_requests (route)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_user_id ON llm_requests (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_tenant_id ON llm_requests (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_session_id ON llm_requests (session_id)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_conversation_id ON llm_requests (conversation_id)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_request_id ON llm_requests (request_id)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_trace_id ON llm_requests (trace_id)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_prompt_template ON llm_requests (prompt_template)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_project_environment_captured ON llm_requests (project_id, environment, captured_at)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_project_route_captured ON llm_requests (project_id, route, captured_at)",
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_project_tenant_captured ON llm_requests (project_id, tenant_id, captured_at)",
    ]
    for statement in statements:
        await conn.execute(text(statement))


async def repair_missing_cost_estimates(session: AsyncSession) -> None:
    result = await session.execute(
        select(LLMRequest).where(
            LLMRequest.status == "success",
            LLMRequest.cost_usd == Decimal("0"),
            LLMRequest.response.is_not(None),
        )
    )
    for request in result.scalars():
        input_tokens, output_tokens = extract_response_usage(request.response)
        estimated_cost = estimate_cost_usd(request.model, input_tokens, output_tokens)
        if estimated_cost == 0:
            continue
        request.input_tokens = input_tokens
        request.output_tokens = output_tokens
        request.total_tokens = request.total_tokens or input_tokens + output_tokens
        request.cost_usd = estimated_cost


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/admin/provider-credentials", response_model=ProviderCredentialListOut)
async def list_provider_credentials(
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ProviderCredentialListOut:
    project = await default_project(session)
    result = await session.execute(
        select(ProviderCredential)
        .where(ProviderCredential.project_id == project.id)
        .order_by(ProviderCredential.provider, ProviderCredential.name)
    )
    return ProviderCredentialListOut(
        credentials=list(result.scalars()),
        secret_backend=settings.secret_backend,
    )


@app.post(
    "/api/admin/provider-credentials",
    response_model=ProviderCredentialOut,
    status_code=status.HTTP_201_CREATED,
)
async def save_provider_credential(
    payload: ProviderCredentialCreate,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ProviderCredential:
    require_persistent_secret_store()
    project = await default_project(session)
    result = await session.execute(
        select(ProviderCredential).where(
            ProviderCredential.project_id == project.id,
            ProviderCredential.provider == payload.provider,
        )
    )
    credential = result.scalar_one_or_none()
    credential_id = credential.id if credential else uuid4()
    secret_ref = (
        credential.secret_ref
        if credential
        else f"{settings.secret_prefix}/{project.id}/{payload.provider}/{credential_id}"
    )
    await asyncio.to_thread(get_secret_store().put, secret_ref, payload.api_key)
    fingerprint = hashlib.sha256(payload.api_key.encode("utf-8")).hexdigest()[:12]
    now = datetime.now(timezone.utc)
    if credential is None:
        credential = ProviderCredential(
            id=credential_id,
            project_id=project.id,
            provider=payload.provider,
            name=payload.name,
            secret_ref=secret_ref,
            fingerprint=fingerprint,
            version=1,
            status="active",
            updated_at=now,
        )
        session.add(credential)
    else:
        credential.name = payload.name
        credential.fingerprint = fingerprint
        credential.version += 1
        credential.status = "active"
        credential.updated_at = now
    await session.commit()
    await session.refresh(credential)
    return credential


@app.delete("/api/admin/provider-credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_credential(
    credential_id: UUID,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    project = await default_project(session)
    result = await session.execute(
        select(ProviderCredential).where(
            ProviderCredential.id == credential_id,
            ProviderCredential.project_id == project.id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=404, detail="Provider credential not found.")
    await asyncio.to_thread(get_secret_store().delete, credential.secret_ref)
    await session.delete(credential)
    await session.commit()


@app.get("/v1/runtime/provider-credentials", response_model=RuntimeCredentialListOut)
async def runtime_provider_credentials(
    response: Response,
    project: Project = Depends(project_from_runtime_key),
    session: AsyncSession = Depends(get_session),
) -> RuntimeCredentialListOut:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    result = await session.execute(
        select(ProviderCredential).where(
            ProviderCredential.project_id == project.id,
            ProviderCredential.status == "active",
        ).order_by(ProviderCredential.updated_at.desc())
    )
    credentials_by_provider: dict[str, ProviderCredential] = {}
    for credential in result.scalars():
        credentials_by_provider.setdefault(credential.provider, credential)
    credentials = list(credentials_by_provider.values())
    values = await asyncio.gather(
        *(asyncio.to_thread(get_secret_store().get, item.secret_ref) for item in credentials)
    )
    return RuntimeCredentialListOut(
        credentials=[
            {
                "provider": item.provider,
                "api_key": value,
                "version": item.version,
                "updated_at": item.updated_at,
            }
            for item, value in zip(credentials, values, strict=True)
        ]
    )


@app.post("/v1/test-plans", response_model=TestPlanOut, status_code=status.HTTP_201_CREATED)
async def create_test_plan(
    payload: TestPlanCreate,
    project: Project = Depends(project_from_api_key),
    session: AsyncSession = Depends(get_session),
) -> TestPlan:
    targets = [
        {
            "provider": "anthropic" if target.provider == "claude" else target.provider,
            "model": target.model,
        }
        for target in payload.targets
    ]
    if len({(target["provider"], target["model"]) for target in targets}) != len(targets):
        raise HTTPException(status_code=422, detail="Test targets must be unique.")
    plan = TestPlan(
        project_id=project.id,
        prompt=payload.prompt,
        system=payload.system,
        targets=targets,
        max_output_tokens=payload.max_output_tokens,
        max_runs=payload.max_runs,
        status="pending",
        requested_by=payload.requested_by,
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return plan


@app.get("/v1/test-plans/{test_plan_id}", response_model=TestPlanOut)
async def get_test_plan(
    test_plan_id: UUID,
    project: Project = Depends(project_from_api_key),
    session: AsyncSession = Depends(get_session),
) -> TestPlan:
    result = await session.execute(
        select(TestPlan).where(
            TestPlan.id == test_plan_id,
            TestPlan.project_id == project.id,
        )
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Test plan not found.")
    return plan


@app.post("/v1/test-plans/{test_plan_id}/lease", response_model=TestPlanOut)
async def lease_test_plan(
    test_plan_id: UUID,
    project: Project = Depends(project_from_api_key),
    session: AsyncSession = Depends(get_session),
) -> TestPlan:
    result = await session.execute(
        select(TestPlan)
        .where(
            TestPlan.id == test_plan_id,
            TestPlan.project_id == project.id,
        )
        .with_for_update()
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Test plan not found.")
    now = datetime.now(timezone.utc)
    if plan.status != "approved":
        raise HTTPException(status_code=409, detail=f"Test plan is {plan.status}.")
    if plan.expires_at and plan.expires_at <= now:
        raise HTTPException(status_code=409, detail="Test plan has expired.")
    if plan.run_count >= plan.max_runs:
        raise HTTPException(status_code=409, detail="Test plan has no remaining runs.")
    plan.run_count += 1
    await session.commit()
    await session.refresh(plan)
    return plan


@app.get("/api/admin/test-plans", response_model=TestPlanListOut)
async def list_test_plans(
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TestPlanListOut:
    project = await default_project(session)
    result = await session.execute(
        select(TestPlan)
        .where(TestPlan.project_id == project.id)
        .order_by(TestPlan.created_at.desc())
        .limit(100)
    )
    return TestPlanListOut(test_plans=list(result.scalars()))


@app.post("/api/admin/test-plans/{test_plan_id}/approve", response_model=TestPlanOut)
async def approve_test_plan(
    test_plan_id: UUID,
    payload: TestPlanDecision,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TestPlan:
    plan = await _admin_test_plan(session, test_plan_id)
    now = datetime.now(timezone.utc)
    plan.status = "approved"
    plan.approved_by = "admin"
    plan.rejection_reason = None
    plan.approved_at = now
    plan.expires_at = now + timedelta(hours=payload.expires_in_hours)
    await session.commit()
    await session.refresh(plan)
    return plan


@app.post("/api/admin/test-plans/{test_plan_id}/reject", response_model=TestPlanOut)
async def reject_test_plan(
    test_plan_id: UUID,
    payload: TestPlanDecision,
    _: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TestPlan:
    plan = await _admin_test_plan(session, test_plan_id)
    plan.status = "rejected"
    plan.approved_by = "admin"
    plan.rejection_reason = payload.reason
    plan.approved_at = None
    plan.expires_at = None
    await session.commit()
    await session.refresh(plan)
    return plan


async def _admin_test_plan(session: AsyncSession, test_plan_id: UUID) -> TestPlan:
    project = await default_project(session)
    result = await session.execute(
        select(TestPlan).where(
            TestPlan.id == test_plan_id,
            TestPlan.project_id == project.id,
        )
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Test plan not found.")
    return plan


@app.post("/v1/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    event: EventIn,
    project: Project = Depends(project_from_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    accepted, duplicates = await store_events(session, project, [event])
    return {"status": "accepted" if accepted else "duplicate_ignored"}


@app.post(
    "/v1/events/batch",
    response_model=EventBatchOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_event_batch(
    payload: EventBatchIn,
    project: Project = Depends(project_from_api_key),
    session: AsyncSession = Depends(get_session),
) -> EventBatchOut:
    accepted, duplicates = await store_events(session, project, payload.events)
    return EventBatchOut(accepted=accepted, duplicates=duplicates)


async def store_events(
    session: AsyncSession,
    project: Project,
    events: list[EventIn],
) -> tuple[int, int]:
    accepted = 0
    duplicates = 0
    for event in events:
        request = request_from_event(project, event)
        try:
            async with session.begin_nested():
                session.add(request)
                await session.flush()
        except IntegrityError:
            duplicates += 1
        else:
            accepted += 1
    await session.commit()
    return accepted, duplicates


def request_from_event(project: Project, event: EventIn) -> LLMRequest:
    usage = event.usage
    total_tokens = usage.total_tokens or usage.input_tokens + usage.output_tokens
    cost_usd = event.cost_usd
    if cost_usd is None:
        cost_usd = estimate_cost_usd(event.model, usage.input_tokens, usage.output_tokens)

    normalized = normalize_event_metadata(event)
    return LLMRequest(
        project_id=project.id,
        external_id=event.external_id,
        provider=event.provider,
        operation=event.operation,
        model=event.model,
        provider_request_id=event.provider_request_id,
        retry_count=event.retry_count,
        model_parameters=event.model_parameters,
        status=event.status,
        prompt=event.prompt,
        response=event.response,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        latency_ms=event.latency_ms,
        error_type=event.error.type if event.error else None,
        error_message=event.error.message if event.error else None,
        service_name=normalized["service_name"],
        environment=normalized["environment"],
        version=normalized["version"],
        git_sha=normalized["git_sha"],
        route=normalized["route"],
        user_id=normalized["user_id"],
        tenant_id=normalized["tenant_id"],
        session_id=normalized["session_id"],
        conversation_id=normalized["conversation_id"],
        request_id=normalized["request_id"],
        trace_id=normalized["trace_id"],
        span_id=normalized["span_id"],
        prompt_template=normalized["prompt_template"],
        prompt_version=normalized["prompt_version"],
        tags=normalized["tags"],
        custom_metadata=normalized["custom_metadata"],
        privacy=normalized["privacy"],
        request_metadata=normalized["request_metadata"],
        captured_at=event.captured_at or datetime.now(timezone.utc),
    )


@app.get("/api/requests", response_model=RequestListOut)
async def list_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    provider: str | None = None,
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
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> RequestListOut:
    project = await default_project(session)
    since, until, _ = resolve_time_bounds(minutes=minutes, days=days, start=start, end=end)
    query: Select[tuple[LLMRequest]] = apply_time_bounds(
        select(LLMRequest).where(LLMRequest.project_id == project.id),
        since,
        until,
    )

    query = apply_request_filters(
        query,
        status_filter=status_filter,
        provider=provider,
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


@app.get("/api/metadata/facets", response_model=MetadataFacetsOut)
async def metadata_facets(
    minutes: int | None = Query(default=None, ge=1, le=60 * 24 * 30),
    days: int | None = Query(default=None, ge=1, le=30),
    start: datetime | None = None,
    end: datetime | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    provider: str | None = None,
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
    project = await default_project(session)
    since, until, _ = resolve_time_bounds(minutes=minutes, days=days, start=start, end=end)
    filters = {
        "status_filter": status_filter,
        "provider": provider,
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
    return MetadataFacetsOut(
        providers=await distinct_values(session, project.id, LLMRequest.provider, since, until, filters),
        service_names=await distinct_values(session, project.id, LLMRequest.service_name, since, until, filters),
        environments=await distinct_values(session, project.id, LLMRequest.environment, since, until, filters),
        routes=await distinct_values(session, project.id, LLMRequest.route, since, until, filters),
        tenant_ids=await distinct_values(session, project.id, LLMRequest.tenant_id, since, until, filters),
        prompt_templates=await distinct_values(session, project.id, LLMRequest.prompt_template, since, until, filters),
        models=await distinct_values(session, project.id, LLMRequest.model, since, until, filters),
        statuses=await distinct_values(session, project.id, LLMRequest.status, since, until, filters),
    )


@app.get("/api/traces/{trace_id}", response_model=RequestListOut)
async def get_trace(trace_id: str, session: AsyncSession = Depends(get_session)) -> RequestListOut:
    project = await default_project(session)
    result = await session.execute(
        select(LLMRequest)
        .where(LLMRequest.project_id == project.id, LLMRequest.trace_id == trace_id)
        .order_by(LLMRequest.captured_at.asc())
    )
    return RequestListOut(requests=list(result.scalars()))


@app.get("/api/conversations/{conversation_id}", response_model=RequestListOut)
async def get_conversation(conversation_id: str, session: AsyncSession = Depends(get_session)) -> RequestListOut:
    project = await default_project(session)
    result = await session.execute(
        select(LLMRequest)
        .where(LLMRequest.project_id == project.id, LLMRequest.conversation_id == conversation_id)
        .order_by(LLMRequest.captured_at.asc())
    )
    return RequestListOut(requests=list(result.scalars()))


@app.get("/api/requests/{request_id}", response_model=RequestOut)
async def get_request(request_id: UUID, session: AsyncSession = Depends(get_session)) -> LLMRequest:
    project = await default_project(session)
    result = await session.execute(
        select(LLMRequest).where(LLMRequest.id == request_id, LLMRequest.project_id == project.id)
    )
    request = result.scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    return request


@app.get("/api/metrics/summary", response_model=SummaryOut)
async def metrics_summary(
    minutes: int | None = Query(default=None, ge=1, le=60 * 24 * 30),
    hours: int | None = Query(default=None, ge=1, le=24 * 30),
    start: datetime | None = None,
    end: datetime | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    provider: str | None = None,
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
    project = await default_project(session)
    since, until, window_minutes = resolve_time_bounds(
        minutes=minutes,
        hours=hours,
        start=start,
        end=end,
    )
    base_query: Select[tuple[LLMRequest]] = apply_request_filters(
        apply_time_bounds(
            select(LLMRequest).where(LLMRequest.project_id == project.id),
            since,
            until,
        ),
        status_filter=status_filter,
        provider=provider,
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
        func.coalesce(func.sum(base_query.c.cost_usd), Decimal("0")),
        func.coalesce(func.avg(base_query.c.latency_ms), 0),
        func.coalesce(func.sum(case((base_query.c.status == "error", 1), else_=0)), 0),
        func.coalesce(func.sum(base_query.c.total_tokens), 0),
    )
    total_result = await session.execute(total_query)
    total_requests, total_cost, avg_latency, error_count, total_tokens = total_result.one()

    bucket_name = "minute" if window_minutes <= 60 else "hour"
    bucket = func.date_trunc(bucket_name, base_query.c.captured_at).label("bucket")
    series_query = (
        select(
            bucket,
            func.count(base_query.c.id).label("requests"),
            func.coalesce(func.sum(base_query.c.cost_usd), Decimal("0")).label("cost_usd"),
            func.coalesce(func.avg(base_query.c.latency_ms), 0).label("avg_latency_ms"),
            func.coalesce(func.sum(case((base_query.c.status == "error", 1), else_=0)), 0).label("error_count"),
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    series_result = await session.execute(series_query)
    series = [
        {
            "bucket": row.bucket,
            "requests": row.requests,
            "cost_usd": row.cost_usd,
            "avg_latency_ms": float(row.avg_latency_ms),
            "error_count": row.error_count,
        }
        for row in series_result
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


def resolve_time_bounds(
    *,
    minutes: int | None = None,
    hours: int | None = None,
    days: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[datetime, datetime | None, int]:
    if (start is None) != (end is None):
        raise HTTPException(status_code=422, detail="Both start and end are required for an exact time range.")

    if start is not None and end is not None:
        normalized_start = normalize_time_boundary(start)
        normalized_end = normalize_time_boundary(end)
        if normalized_start >= normalized_end:
            raise HTTPException(status_code=422, detail="Start must be earlier than end.")
        window_minutes = max(1, int((normalized_end - normalized_start).total_seconds() / 60))
        return normalized_start, normalized_end, window_minutes

    window_minutes = resolve_window_minutes(minutes=minutes, hours=hours, days=days)
    return datetime.now(timezone.utc) - timedelta(minutes=window_minutes), None, window_minutes


def normalize_time_boundary(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def apply_time_bounds(
    query: Select[tuple[LLMRequest]],
    since: datetime,
    until: datetime | None = None,
) -> Select[tuple[LLMRequest]]:
    query = query.where(LLMRequest.captured_at >= since)
    if until is not None:
        query = query.where(LLMRequest.captured_at <= until)
    return query


def apply_request_filters(
    query: Select[tuple[LLMRequest]],
    *,
    status_filter: str | None = None,
    provider: str | None = None,
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
) -> Select[tuple[LLMRequest]]:
    if status_filter:
        query = query.where(LLMRequest.status == status_filter)
    if provider:
        query = query.where(LLMRequest.provider == provider)
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


def normalize_event_metadata(event: EventIn) -> dict[str, object]:
    metadata = dict(event.metadata or {})
    custom_metadata = dict(event.custom_metadata or {})

    normalized: dict[str, object] = {}
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


async def distinct_values(
    session: AsyncSession,
    project_id: UUID,
    column,
    since: datetime | None = None,
    until: datetime | None = None,
    filters: dict[str, str | None] | None = None,
) -> list[str]:
    query = select(column).where(LLMRequest.project_id == project_id, column.is_not(None))
    if since is not None:
        query = query.where(LLMRequest.captured_at >= since)
    if until is not None:
        query = query.where(LLMRequest.captured_at <= until)
    if filters:
        query = apply_request_filters(query, **filters)
    result = await session.execute(
        query
        .distinct()
        .order_by(column)
        .limit(200)
    )
    return [str(value) for value in result.scalars() if value]
