import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..deps import current_user, project_from_query, require_csrf_header, require_project_permission
from ..models import ProviderCredential, Project, TestPlan, User
from ..schemas import (
    ProviderCredentialCreate,
    ProviderCredentialListOut,
    ProviderCredentialOut,
    TestPlanDecision,
    TestPlanListOut,
    TestPlanOut,
)
from ..secret_store import get_secret_store


router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_csrf_header)])


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


@router.get("/provider-credentials", response_model=ProviderCredentialListOut)
async def list_provider_credentials(
    project: Project = Depends(project_from_query("credentials:manage")),
    session: AsyncSession = Depends(get_session),
) -> ProviderCredentialListOut:
    result = await session.execute(
        select(ProviderCredential)
        .where(ProviderCredential.project_id == project.id)
        .order_by(ProviderCredential.provider, ProviderCredential.name)
    )
    return ProviderCredentialListOut(
        credentials=[ProviderCredentialOut.model_validate(item) for item in result.scalars()],
        secret_backend=settings.secret_backend,
    )


@router.post(
    "/provider-credentials",
    response_model=ProviderCredentialOut,
    status_code=status.HTTP_201_CREATED,
)
async def save_provider_credential(
    payload: ProviderCredentialCreate,
    project: Project = Depends(project_from_query("credentials:manage")),
    session: AsyncSession = Depends(get_session),
) -> ProviderCredentialOut:
    require_persistent_secret_store()
    result = await session.execute(
        select(ProviderCredential).where(
            ProviderCredential.project_id == project.id,
            ProviderCredential.provider == payload.provider,
        )
    )
    credential = result.scalar_one_or_none()
    credential_id = credential.id if credential else uuid.uuid4()
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
    return ProviderCredentialOut.model_validate(credential)


@router.delete("/provider-credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_credential(
    credential_id: uuid.UUID,
    project: Project = Depends(project_from_query("credentials:manage")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await session.execute(
        select(ProviderCredential).where(
            ProviderCredential.id == credential_id,
            ProviderCredential.project_id == project.id,
        )
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider credential not found.")
    await asyncio.to_thread(get_secret_store().delete, credential.secret_ref)
    await session.delete(credential)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/test-plans", response_model=TestPlanListOut)
async def list_test_plans(
    project: Project = Depends(project_from_query("data:read")),
    session: AsyncSession = Depends(get_session),
) -> TestPlanListOut:
    result = await session.execute(
        select(TestPlan)
        .where(TestPlan.project_id == project.id)
        .order_by(TestPlan.created_at.desc())
        .limit(100)
    )
    return TestPlanListOut(test_plans=[TestPlanOut.model_validate(plan) for plan in result.scalars()])


async def _decide_test_plan(
    session: AsyncSession,
    user: User,
    test_plan_id: uuid.UUID,
) -> TestPlan:
    plan = await session.get(TestPlan, test_plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test plan not found.")
    await require_project_permission(session, user, plan.project_id, "tests:approve")
    return plan


@router.post("/test-plans/{test_plan_id}/approve", response_model=TestPlanOut)
async def approve_test_plan(
    test_plan_id: uuid.UUID,
    payload: TestPlanDecision,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> TestPlanOut:
    plan = await _decide_test_plan(session, user, test_plan_id)
    now = datetime.now(timezone.utc)
    plan.status = "approved"
    plan.approved_by = user.email
    plan.rejection_reason = None
    plan.approved_at = now
    plan.expires_at = now + timedelta(hours=payload.expires_in_hours)
    await session.commit()
    await session.refresh(plan)
    return TestPlanOut.model_validate(plan)


@router.post("/test-plans/{test_plan_id}/reject", response_model=TestPlanOut)
async def reject_test_plan(
    test_plan_id: uuid.UUID,
    payload: TestPlanDecision,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> TestPlanOut:
    plan = await _decide_test_plan(session, user, test_plan_id)
    plan.status = "rejected"
    plan.approved_by = user.email
    plan.rejection_reason = payload.reason
    plan.approved_at = None
    plan.expires_at = None
    await session.commit()
    await session.refresh(plan)
    return TestPlanOut.model_validate(plan)
