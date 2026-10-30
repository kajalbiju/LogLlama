from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


class UsagePayload(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ErrorPayload(BaseModel):
    type: str | None = None
    message: str | None = None


class EventIn(BaseModel):
    external_id: str | None = None
    provider: str = Field(default="openai", max_length=40)
    operation: str = Field(default="chat.completions.create", max_length=120)
    model: str | None = None
    provider_request_id: str | None = Field(default=None, max_length=255)
    retry_count: int = Field(default=0, ge=0)
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(pattern="^(success|error)$")
    prompt: Any = None
    response: Any = None
    usage: UsagePayload = Field(default_factory=UsagePayload)
    cost_usd: Decimal | None = None
    latency_ms: int = Field(default=0, ge=0)
    error: ErrorPayload | None = None
    service_name: str | None = Field(default=None, max_length=160)
    environment: str | None = Field(default=None, max_length=80)
    version: str | None = Field(default=None, max_length=120)
    git_sha: str | None = Field(default=None, max_length=80)
    route: str | None = Field(default=None, max_length=240)
    user_id: str | None = Field(default=None, max_length=160)
    tenant_id: str | None = Field(default=None, max_length=160)
    session_id: str | None = Field(default=None, max_length=160)
    conversation_id: str | None = Field(default=None, max_length=160)
    request_id: str | None = Field(default=None, max_length=160)
    trace_id: str | None = Field(default=None, max_length=160)
    span_id: str | None = Field(default=None, max_length=160)
    prompt_template: str | None = Field(default=None, max_length=160)
    prompt_version: str | None = Field(default=None, max_length=80)
    tags: list[str] | None = None
    custom_metadata: dict[str, Any] | None = None
    privacy: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    captured_at: datetime | None = None


class BatchEventsIn(BaseModel):
    events: list[EventIn] = Field(min_length=1)


class BatchIngestOut(BaseModel):
    accepted: int
    duplicates: int


class RequestOut(BaseModel):
    id: UUID
    external_id: str | None
    provider: str
    operation: str
    model: str | None
    provider_request_id: str | None
    retry_count: int
    model_parameters: dict[str, Any] | None
    status: str
    prompt: Any
    response: Any
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: Decimal | None
    latency_ms: int
    error_type: str | None
    error_message: str | None
    service_name: str | None
    environment: str | None
    version: str | None
    git_sha: str | None
    route: str | None
    user_id: str | None
    tenant_id: str | None
    session_id: str | None
    conversation_id: str | None
    request_id: str | None
    trace_id: str | None
    span_id: str | None
    prompt_template: str | None
    prompt_version: str | None
    tags: list[str] | None
    custom_metadata: dict[str, Any] | None
    privacy: dict[str, Any] | None
    request_metadata: dict[str, Any] | None
    captured_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RequestListOut(BaseModel):
    requests: list[RequestOut]


class MetadataFacetsOut(BaseModel):
    service_names: list[str]
    environments: list[str]
    routes: list[str]
    tenant_ids: list[str]
    prompt_templates: list[str]
    models: list[str]
    statuses: list[str]


class MetricPoint(BaseModel):
    bucket: datetime
    requests: int
    cost_usd: Decimal
    avg_latency_ms: float
    error_count: int


class SummaryOut(BaseModel):
    total_requests: int
    total_cost_usd: Decimal
    avg_latency_ms: float
    error_rate: float
    total_tokens: int
    series: list[MetricPoint]


# Accounts, organizations, and keys


class SignupIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    name: str = Field(default="", max_length=120)
    organization_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class OrganizationOut(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SessionOut(BaseModel):
    user: UserOut
    organizations: list[OrganizationOut]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    name: str
    role: str


class MemberUpsert(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["owner", "credential_admin", "test_approver", "developer", "viewer"]


class ProjectOut(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    organization_id: UUID
    name: str = Field(min_length=1, max_length=120)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["ingest", "runtime"] = "ingest"
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    kind: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreatedOut(ApiKeyOut):
    # Returned exactly once, at creation. It is never stored in plaintext and cannot be recovered.
    key: str


# Provider credentials and comparison tests


class ProviderCredentialCreate(BaseModel):
    provider: str = Field(pattern="^(openai|anthropic|gemini)$")
    api_key: str = Field(min_length=8, max_length=1000)
    name: str = Field(default="default", min_length=1, max_length=120)


class ProviderCredentialOut(BaseModel):
    id: UUID
    provider: str
    name: str
    fingerprint: str
    version: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProviderCredentialListOut(BaseModel):
    credentials: list[ProviderCredentialOut]
    secret_backend: str


class RuntimeCredentialOut(BaseModel):
    provider: str
    api_key: str
    version: int
    updated_at: datetime


class RuntimeCredentialListOut(BaseModel):
    credentials: list[RuntimeCredentialOut]


class TestTarget(BaseModel):
    provider: str = Field(pattern="^(openai|anthropic|gemini|claude)$")
    model: str = Field(min_length=1, max_length=160)


class TestPlanCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    system: str | None = Field(default=None, max_length=20_000)
    targets: list[TestTarget] = Field(min_length=2, max_length=10)
    max_output_tokens: int = Field(default=256, ge=1, le=8192)
    max_runs: int = Field(default=1, ge=1, le=100)
    requested_by: str | None = Field(default=None, max_length=160)


class TestPlanDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    expires_in_hours: int = Field(default=24, ge=1, le=168)


class TestPlanOut(BaseModel):
    id: UUID
    prompt: str
    system: str | None
    targets: list[dict[str, str]]
    max_output_tokens: int
    max_runs: int
    run_count: int
    status: str
    requested_by: str | None
    approved_by: str | None
    rejection_reason: str | None
    created_at: datetime
    approved_at: datetime | None
    expires_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TestPlanListOut(BaseModel):
    test_plans: list[TestPlanOut]
