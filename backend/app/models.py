import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


ROLES = ("owner", "credential_admin", "test_approver", "developer", "viewer")
ROLE_SQL = ", ".join(f"'{role}'" for role in ROLES)
API_KEY_KINDS = ("ingest", "runtime")
API_KEY_KIND_SQL = ", ".join(f"'{kind}'" for kind in API_KEY_KINDS)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="organization")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_memberships_user_organization"),
        CheckConstraint(f"role IN ({ROLE_SQL})", name="ck_memberships_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    requests: Mapped[list["LLMRequest"]] = relationship(back_populates="project")
    provider_credentials: Mapped[list["ProviderCredential"]] = relationship(back_populates="project")
    test_plans: Mapped[list["TestPlan"]] = relationship(back_populates="project")


class ApiKey(Base):
    """A project key. Only a SHA-256 hash of the secret is stored; the plaintext is shown once at creation."""

    __tablename__ = "api_keys"
    __table_args__ = (CheckConstraint(f"kind IN ({API_KEY_KIND_SQL})", name="ck_api_keys_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="api_keys")


class LLMRequest(Base):
    __tablename__ = "llm_requests"
    __table_args__ = (
        UniqueConstraint("project_id", "external_id", name="uq_llm_requests_project_external_id"),
        Index("ix_llm_requests_project_environment_captured", "project_id", "environment", "captured_at"),
        Index("ix_llm_requests_project_route_captured", "project_id", "route", "captured_at"),
        Index("ix_llm_requests_project_tenant_captured", "project_id", "tenant_id", "captured_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    prompt: Mapped[dict | list | str | None] = mapped_column(JSONB, nullable=True)
    response: Mapped[dict | list | str | None] = mapped_column(JSONB, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # NULL means the model has no published text-token price, so the cost is unknown.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_name: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    environment: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    git_sha: Mapped[str | None] = mapped_column(String(80), nullable=True)
    route: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    span_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_template: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    custom_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    privacy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    request_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    project: Mapped[Project] = relationship(back_populates="requests")


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("project_id", "provider", name="uq_provider_credentials_project_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="default")
    secret_ref: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="provider_credentials")


class TestPlan(Base):
    __tablename__ = "test_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    system: Mapped[str | None] = mapped_column(Text, nullable=True)
    targets: Mapped[list] = mapped_column(JSONB, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=256)
    max_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    requested_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="test_plans")
