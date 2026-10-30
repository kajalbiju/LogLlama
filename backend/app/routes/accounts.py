import re
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_session
from ..deps import (
    SESSION_COOKIE_NAME,
    current_user,
    project_from_path,
    require_csrf_header,
    require_organization_permission,
    utcnow,
)
from ..models import ApiKey, AuthSession, Membership, Organization, Project, User
from ..schemas import (
    ApiKeyCreate,
    ApiKeyCreatedOut,
    ApiKeyOut,
    LoginIn,
    MemberOut,
    MemberUpsert,
    OrganizationCreate,
    OrganizationOut,
    ProjectCreate,
    ProjectOut,
    SessionOut,
    SignupIn,
    UserOut,
)
from ..security import (
    dummy_password_hash,
    hash_password,
    hash_token,
    is_valid_email,
    new_api_key,
    new_session_token,
    normalize_email,
    display_prefix,
    verify_password,
)
from ..services.bootstrap import DEVELOPMENT_ORG_SLUG


router = APIRouter(prefix="/api", dependencies=[Depends(require_csrf_header)])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    return slug or "organization"


async def _unique_slug(session: AsyncSession, name: str) -> str:
    base = _slugify(name)
    taken = (await session.execute(select(Organization.id).where(Organization.slug == base))).first()
    return base if taken is None else f"{base}-{secrets.token_hex(3)}"


async def _session_out(session: AsyncSession, user: User) -> SessionOut:
    rows = (
        await session.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user.id)
            .order_by(Organization.name)
        )
    ).all()
    return SessionOut(
        user=UserOut.model_validate(user),
        organizations=[
            OrganizationOut(id=organization.id, name=organization.name, slug=organization.slug, role=role)
            for organization, role in rows
        ],
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def _start_session(session: AsyncSession, user: User, response: Response) -> None:
    token = new_session_token()
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
        )
    )
    user.last_login_at = utcnow()
    await session.commit()
    _set_session_cookie(response, token)


async def _owner_count(session: AsyncSession, organization_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count(Membership.id)).where(
            Membership.organization_id == organization_id,
            Membership.role == "owner",
        )
    )
    return int(result.scalar_one())


@router.post("/auth/signup", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    if not settings.allow_signup:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sign-up is disabled on this server.")

    email = normalize_email(payload.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Enter a valid email address.")

    existing = (await session.execute(select(User.id).where(User.email == email))).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")

    # On a fresh install the first account claims the seeded Development organization, so the
    # configured development key keeps working. Later accounts always get their own organization.
    users_exist = (await session.execute(select(func.count(User.id)))).scalar_one() > 0
    claimable = None
    if not users_exist:
        claimable = (
            await session.execute(select(Organization).where(Organization.slug == DEVELOPMENT_ORG_SLUG))
        ).scalar_one_or_none()

    user = User(email=email, name=payload.name.strip(), password_hash=hash_password(payload.password))
    session.add(user)
    await session.flush()

    organization_name = payload.organization_name.strip()
    if claimable is not None:
        organization = claimable
        organization.name = organization_name
    else:
        organization = Organization(name=organization_name, slug=await _unique_slug(session, organization_name))
        session.add(organization)
        await session.flush()
        session.add(Project(organization_id=organization.id, name="Default"))

    session.add(Membership(user_id=user.id, organization_id=organization.id, role="owner"))
    try:
        await session.flush()
        await _start_session(session, user, response)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    return await _session_out(session, user)


@router.post("/auth/login", response_model=SessionOut)
async def login(
    payload: LoginIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    email = normalize_email(payload.email)
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    # Verify against a dummy hash for unknown emails so response timing does not reveal which emails exist.
    password_ok = verify_password(payload.password, user.password_hash if user else dummy_password_hash())
    if user is None or not user.is_active or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    await _start_session(session, user, response)
    return await _session_out(session, user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        auth_session = (
            await session.execute(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        ).scalar_one_or_none()
        if auth_session is not None and auth_session.revoked_at is None:
            auth_session.revoked_at = utcnow()
            await session.commit()

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/auth/me", response_model=SessionOut)
async def me(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    return await _session_out(session, user)


@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> OrganizationOut:
    name = payload.name.strip()
    organization = Organization(name=name, slug=await _unique_slug(session, name))
    session.add(organization)
    await session.flush()
    session.add(Project(organization_id=organization.id, name="Default"))
    session.add(Membership(user_id=user.id, organization_id=organization.id, role="owner"))
    await session.commit()
    return OrganizationOut(id=organization.id, name=organization.name, slug=organization.slug, role="owner")


@router.get("/organizations/{organization_id}/members", response_model=list[MemberOut])
async def list_members(
    organization_id: uuid.UUID = Path(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[MemberOut]:
    await require_organization_permission(session, user, organization_id, "data:read")
    rows = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(User.email)
        )
    ).all()
    return [
        MemberOut(user_id=member.user_id, email=account.email, name=account.name, role=member.role)
        for member, account in rows
    ]


@router.post("/organizations/{organization_id}/members", response_model=MemberOut)
async def upsert_member(
    payload: MemberUpsert,
    organization_id: uuid.UUID = Path(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MemberOut:
    await require_organization_permission(session, user, organization_id, "members:manage")
    target = (
        await session.execute(select(User).where(User.email == normalize_email(payload.email)))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No account with that email.")

    membership = (
        await session.execute(
            select(Membership).where(
                Membership.user_id == target.id,
                Membership.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = Membership(user_id=target.id, organization_id=organization_id, role=payload.role)
        session.add(membership)
    else:
        if membership.role == "owner" and payload.role != "owner" and await _owner_count(session, organization_id) <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An organization needs at least one owner.")
        membership.role = payload.role
    await session.commit()
    return MemberOut(user_id=target.id, email=target.email, name=target.name, role=membership.role)


@router.delete("/organizations/{organization_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    organization_id: uuid.UUID = Path(...),
    member_user_id: uuid.UUID = Path(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await require_organization_permission(session, user, organization_id, "members:manage")
    membership = (
        await session.execute(
            select(Membership).where(
                Membership.user_id == member_user_id,
                Membership.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    if membership.role == "owner" and await _owner_count(session, organization_id) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An organization needs at least one owner.")
    await session.delete(membership)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    organization_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProjectOut]:
    await require_organization_permission(session, user, organization_id, "data:read")
    result = await session.execute(
        select(Project).where(Project.organization_id == organization_id).order_by(Project.name)
    )
    return [ProjectOut.model_validate(project) for project in result.scalars()]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    await require_organization_permission(session, user, payload.organization_id, "projects:manage")
    project = Project(organization_id=payload.organization_id, name=payload.name.strip())
    session.add(project)
    await session.commit()
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    project: Project = Depends(project_from_path("keys:manage")),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyOut]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.project_id == project.id).order_by(ApiKey.created_at.desc())
    )
    return [ApiKeyOut.model_validate(api_key) for api_key in result.scalars()]


@router.post(
    "/projects/{project_id}/api-keys",
    response_model=ApiKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    payload: ApiKeyCreate,
    project: Project = Depends(project_from_path("keys:manage")),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreatedOut:
    raw_key = new_api_key(payload.kind)
    api_key = ApiKey(
        project_id=project.id,
        name=payload.name.strip(),
        kind=payload.kind,
        key_prefix=display_prefix(raw_key),
        key_hash=hash_token(raw_key),
        created_by_user_id=user.id,
        expires_at=utcnow() + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None,
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return ApiKeyCreatedOut(**ApiKeyOut.model_validate(api_key).model_dump(), key=raw_key)


@router.delete("/projects/{project_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID = Path(...),
    project: Project = Depends(project_from_path("keys:manage")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    api_key = (
        await session.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.project_id == project.id))
    ).scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    if api_key.revoked_at is None:
        api_key.revoked_at = utcnow()
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
