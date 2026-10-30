import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..deps import ingest_project, runtime_project
from ..models import Project, ProviderCredential, TestPlan
from ..schemas import (
    BatchEventsIn,
    BatchIngestOut,
    EventIn,
    RuntimeCredentialListOut,
    TestPlanCreate,
    TestPlanOut,
)
from ..secret_store import get_secret_store
from ..services.events import insert_events


router = APIRouter()


@router.post("/v1/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    event: EventIn,
    project: Project = Depends(ingest_project),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    accepted, _ = await insert_events(session, project.id, [event])
    return {"status": "accepted" if accepted else "duplicate_ignored"}


@router.post("/v1/events/batch", response_model=BatchIngestOut, status_code=status.HTTP_202_ACCEPTED)
async def ingest_event_batch(
    payload: BatchEventsIn,
    project: Project = Depends(ingest_project),
    session: AsyncSession = Depends(get_session),
) -> BatchIngestOut:
    if len(payload.events) > settings.max_batch_events:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A batch may contain at most {settings.max_batch_events} events.",
        )
    accepted, duplicates = await insert_events(session, project.id, payload.events)
    return BatchIngestOut(accepted=accepted, duplicates=duplicates)


@router.post("/v1/test-plans", response_model=TestPlanOut, status_code=status.HTTP_201_CREATED)
async def create_test_plan(
    payload: TestPlanCreate,
    project: Project = Depends(ingest_project),
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


@router.get("/v1/test-plans/{test_plan_id}", response_model=TestPlanOut)
async def get_test_plan(
    test_plan_id: uuid.UUID,
    project: Project = Depends(ingest_project),
    session: AsyncSession = Depends(get_session),
) -> TestPlan:
    result = await session.execute(
        select(TestPlan).where(TestPlan.id == test_plan_id, TestPlan.project_id == project.id)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Test plan not found.")
    return plan


@router.post("/v1/test-plans/{test_plan_id}/lease", response_model=TestPlanOut)
async def lease_test_plan(
    test_plan_id: uuid.UUID,
    project: Project = Depends(ingest_project),
    session: AsyncSession = Depends(get_session),
) -> TestPlan:
    result = await session.execute(
        select(TestPlan)
        .where(TestPlan.id == test_plan_id, TestPlan.project_id == project.id)
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


@router.get("/v1/runtime/provider-credentials", response_model=RuntimeCredentialListOut)
async def runtime_provider_credentials(
    response: Response,
    project: Project = Depends(runtime_project),
    session: AsyncSession = Depends(get_session),
) -> RuntimeCredentialListOut:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    result = await session.execute(
        select(ProviderCredential)
        .where(
            ProviderCredential.project_id == project.id,
            ProviderCredential.status == "active",
        )
        .order_by(ProviderCredential.updated_at.desc())
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
