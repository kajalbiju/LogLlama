import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import is_secure_privileged_key
from .database import get_session
from .models import ApiKey, AuthSession, Membership, Project, User
from .security import hash_token


SESSION_COOKIE_NAME = "logllama_session"
CSRF_HEADER = "X-LogLlama-Request"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
KEY_LAST_USED_WRITE_INTERVAL = timedelta(minutes=5)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"data:read"}),
    "developer": frozenset({"data:read", "keys:manage", "projects:manage"}),
    "test_approver": frozenset({"data:read", "tests:approve"}),
    "credential_admin": frozenset({"data:read", "credentials:manage"}),
    "owner": frozenset(
        {
            "data:read",
            "keys:manage",
            "projects:manage",
            "tests:approve",
            "credentials:manage",
            "members:manage",
        }
    ),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def role_allows(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


async def require_csrf_header(request: Request) -> None:
    """Cookie-authenticated writes must send a custom header, which forces a CORS preflight for cross-origin callers."""
    if request.method in SAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing {CSRF_HEADER} header.")


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required.")

    result = await session.execute(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    auth_session = result.scalar_one_or_none()
    if auth_session is None or auth_session.revoked_at is not None or auth_session.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Sign in again.")

    user = await session.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in required.")
    return user


async def membership_for(session: AsyncSession, user: User, organization_id: uuid.UUID) -> Membership | None:
    result = await session.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def require_organization_permission(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    permission: str,
) -> Membership:
    # Non-members get 404 so that resource IDs cannot be probed across organizations.
    membership = await membership_for(session, user, organization_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    if not role_allows(membership.role, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your role does not allow this action.")
    return membership


async def require_project_permission(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    permission: str,
) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    await require_organization_permission(session, user, project.organization_id, permission)
    return project


def project_from_query(permission: str):
    async def dependency(
        project_id: uuid.UUID = Query(...),
        user: User = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ) -> Project:
        return await require_project_permission(session, user, project_id, permission)

    return dependency


def project_from_path(permission: str):
    async def dependency(
        project_id: uuid.UUID = Path(...),
        user: User = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ) -> Project:
        return await require_project_permission(session, user, project_id, permission)

    return dependency


async def _project_for_key(
    session: AsyncSession,
    raw_key: str | None,
    kind: str,
    header_name: str,
) -> Project:
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Missing {header_name} header.")
    if kind == "runtime" and not is_secure_privileged_key(raw_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid runtime key.")

    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == hash_token(raw_key), ApiKey.kind == kind)
    )
    api_key = result.scalar_one_or_none()
    now = utcnow()
    if api_key is None or api_key.revoked_at is not None or (api_key.expires_at and api_key.expires_at <= now):
        detail = "Invalid runtime key." if kind == "runtime" else "Invalid API key."
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

    if api_key.last_used_at is None or now - api_key.last_used_at > KEY_LAST_USED_WRITE_INTERVAL:
        api_key.last_used_at = now
        await session.commit()

    project = await session.get(Project, api_key.project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
    return project


async def ingest_project(
    x_logllama_api_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Project:
    return await _project_for_key(session, x_logllama_api_key, "ingest", "X-LogLlama-Api-Key")


async def runtime_project(
    x_logllama_runtime_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Project:
    return await _project_for_key(session, x_logllama_runtime_key, "runtime", "X-LogLlama-Runtime-Key")
