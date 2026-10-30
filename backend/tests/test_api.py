import asyncio
import hashlib
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


CSRF = {"X-LogLlama-Request": "1"}
PASSWORD = "correct horse battery"


def _query_one(database_url: str, sql: str, params: dict | None = None):
    async def run():
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(text(sql), params or {})
                return result.first()
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _signup(client, email: str | None = None, organization_name: str = "Acme") -> str:
    email = email or f"user-{uuid.uuid4().hex[:10]}@example.com"
    client.cookies.clear()
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Test User",
            "organization_name": organization_name,
        },
        headers=CSRF,
    )
    assert response.status_code == 201, response.text
    return email


def _login(client, email: str) -> None:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}, headers=CSRF)
    assert response.status_code == 200, response.text


def _me(client) -> dict:
    response = client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    return response.json()


def _organization_id(client) -> str:
    return _me(client)["organizations"][0]["id"]


def _first_project_id(client, organization_id: str) -> str:
    response = client.get("/api/projects", params={"organization_id": organization_id})
    assert response.status_code == 200, response.text
    return response.json()[0]["id"]


def _owner_project(client, email: str) -> tuple[str, str]:
    _login(client, email)
    organization_id = _organization_id(client)
    return organization_id, _first_project_id(client, organization_id)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_schema_is_at_alembic_head(database_url):
    from app.services.bootstrap import expected_schema_revision

    row = _query_one(database_url, "SELECT version_num FROM alembic_version")
    assert row is not None
    assert row.version_num == expected_schema_revision()


def test_signup_creates_owner_session(client):
    email = _signup(client)

    me = _me(client)
    assert me["user"]["email"] == email
    assert [org["role"] for org in me["organizations"]] == ["owner"]
    assert "logllama_session" in client.cookies


def test_duplicate_signup_is_rejected(client):
    email = _signup(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "organization_name": "Other"},
        headers=CSRF,
    )
    assert response.status_code == 409


def test_wrong_password_is_rejected(client):
    email = _signup(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "not the password at all"},
        headers=CSRF,
    )
    assert response.status_code == 401
    assert "logllama_session" not in client.cookies


def test_data_endpoints_require_a_session(client):
    client.cookies.clear()
    response = client.get("/api/requests", params={"project_id": str(uuid.uuid4())})
    assert response.status_code == 401


def test_cookie_authenticated_writes_need_the_csrf_header(client):
    _signup(client)
    response = client.post("/api/organizations", json={"name": "No header"})
    assert response.status_code == 403


def test_logout_revokes_the_session(client):
    _signup(client)
    token = client.cookies.get("logllama_session")
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204

    client.cookies.clear()
    client.cookies.set("logllama_session", token)
    assert client.get("/api/auth/me").status_code == 401


def test_other_organizations_projects_are_not_visible(client):
    owner_email = _signup(client, organization_name="Owner Org")
    _, project_id = _owner_project(client, owner_email)

    intruder_email = _signup(client, organization_name="Intruder Org")
    _login(client, intruder_email)
    response = client.get("/api/requests", params={"project_id": project_id})
    assert response.status_code == 404


def test_viewer_cannot_manage_keys_but_developer_can(client):
    owner_email = _signup(client, organization_name="Roles Org")
    organization_id, project_id = _owner_project(client, owner_email)

    member_email = _signup(client, organization_name="Member Org")
    _login(client, owner_email)
    invite = client.post(
        f"/api/organizations/{organization_id}/members",
        json={"email": member_email, "role": "viewer"},
        headers=CSRF,
    )
    assert invite.status_code == 200, invite.text

    _login(client, member_email)
    denied = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "viewer key", "kind": "ingest"},
        headers=CSRF,
    )
    assert denied.status_code == 403
    assert client.get("/api/requests", params={"project_id": project_id}).status_code == 200

    _login(client, owner_email)
    promote = client.post(
        f"/api/organizations/{organization_id}/members",
        json={"email": member_email, "role": "developer"},
        headers=CSRF,
    )
    assert promote.status_code == 200, promote.text

    _login(client, member_email)
    created = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "developer key", "kind": "ingest"},
        headers=CSRF,
    )
    assert created.status_code == 201, created.text
    assert created.json()["key"].startswith("llm_")


def test_api_keys_are_shown_once_and_stored_as_hashes(client, database_url):
    email = _signup(client, organization_name="Hash Org")
    _, project_id = _owner_project(client, email)

    created = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "hash check", "kind": "ingest"},
        headers=CSRF,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    raw_key = body["key"]

    listed = client.get(f"/api/projects/{project_id}/api-keys").json()
    assert all("key" not in item for item in listed)

    row = _query_one(database_url, "SELECT key_prefix, key_hash FROM api_keys WHERE id = :id", {"id": body["id"]})
    assert row.key_hash == hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    assert row.key_prefix == raw_key[:8]
    assert raw_key not in row.key_hash


def test_ingest_batch_counts_duplicates_and_prices_claude(client):
    email = _signup(client, organization_name="Batch Org")
    organization_id, project_id = _owner_project(client, email)
    created = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "batch", "kind": "ingest"},
        headers=CSRF,
    )
    ingest_key = created.json()["key"]

    event = {
        "provider": "anthropic",
        "operation": "messages.create",
        "model": "claude-sonnet-5-5",
        "status": "success",
        "usage": {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500},
        "latency_ms": 120,
        "route": "/support",
    }
    payload = {
        "events": [
            {**event, "external_id": "batch-1"},
            {**event, "external_id": "batch-2"},
            {**event, "external_id": "batch-1"},
        ]
    }
    response = client.post("/v1/events/batch", json=payload, headers={"X-LogLlama-Api-Key": ingest_key})
    assert response.status_code == 202, response.text
    assert response.json() == {"accepted": 2, "duplicates": 1}

    _login(client, email)
    summary = client.get("/api/metrics/summary", params={"project_id": project_id}).json()
    assert summary["total_requests"] == 2
    # 1,000 input tokens at $2/M plus 500 output tokens at $10/M is $0.007 per request.
    assert Decimal(str(summary["total_cost_usd"])) == Decimal("0.014")


def test_unknown_models_have_unknown_cost(client):
    email = _signup(client, organization_name="Unknown Cost Org")
    _, project_id = _owner_project(client, email)
    ingest_key = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "unknown", "kind": "ingest"},
        headers=CSRF,
    ).json()["key"]

    client.post(
        "/v1/events",
        json={
            "external_id": "unknown-model-1",
            "provider": "anthropic",
            "model": "claude-mystery-9",
            "status": "success",
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
        headers={"X-LogLlama-Api-Key": ingest_key},
    )

    _login(client, email)
    requests = client.get("/api/requests", params={"project_id": project_id, "model": "claude-mystery-9"}).json()
    assert requests["requests"][0]["cost_usd"] is None


def test_batch_size_is_limited(client):
    email = _signup(client, organization_name="Limit Org")
    _, project_id = _owner_project(client, email)
    ingest_key = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "limit", "kind": "ingest"},
        headers=CSRF,
    ).json()["key"]

    events = [{"status": "success", "provider": "openai", "model": "gpt-4o-mini"} for _ in range(501)]
    response = client.post("/v1/events/batch", json={"events": events}, headers={"X-LogLlama-Api-Key": ingest_key})
    assert response.status_code == 422


def test_revoked_keys_stop_working(client):
    email = _signup(client, organization_name="Revoke Org")
    _, project_id = _owner_project(client, email)
    created = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "to revoke", "kind": "ingest"},
        headers=CSRF,
    ).json()
    headers = {"X-LogLlama-Api-Key": created["key"]}
    event = {"status": "success", "provider": "openai", "model": "gpt-4o-mini"}
    assert client.post("/v1/events", json=event, headers=headers).status_code == 202

    assert client.delete(f"/api/projects/{project_id}/api-keys/{created['id']}", headers=CSRF).status_code == 204
    assert client.post("/v1/events", json=event, headers=headers).status_code == 401


def test_seeded_development_key_still_ingests(client):
    response = client.post(
        "/v1/events",
        json={"status": "success", "provider": "openai", "model": "gpt-4o-mini"},
        headers={"X-LogLlama-Api-Key": "llama-dev-key"},
    )
    assert response.status_code == 202


def test_runtime_key_returns_no_credentials_without_secret_store_entries(client):
    email = _signup(client, organization_name="Runtime Org")
    _, project_id = _owner_project(client, email)
    created = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "runtime", "kind": "runtime"},
        headers=CSRF,
    ).json()
    assert created["key"].startswith("llrt_")

    response = client.get("/v1/runtime/provider-credentials", headers={"X-LogLlama-Runtime-Key": created["key"]})
    assert response.status_code == 200
    assert response.json() == {"credentials": []}
    assert response.headers["cache-control"] == "no-store"

    # An ingest key must never open the runtime endpoint.
    ingest = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "ingest", "kind": "ingest"},
        headers=CSRF,
    ).json()
    wrong_kind = client.get("/v1/runtime/provider-credentials", headers={"X-LogLlama-Runtime-Key": ingest["key"]})
    assert wrong_kind.status_code == 401


def test_provider_credentials_need_a_persistent_secret_store(client):
    email = _signup(client, organization_name="Secrets Org")
    _, project_id = _owner_project(client, email)
    response = client.post(
        "/api/admin/provider-credentials",
        params={"project_id": project_id},
        json={"provider": "openai", "api_key": "sk-test-1234567890"},
        headers=CSRF,
    )
    assert response.status_code == 503


def test_test_plan_approval_requires_the_approver_role(client):
    owner_email = _signup(client, organization_name="Approval Org")
    organization_id, project_id = _owner_project(client, owner_email)
    ingest_key = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "sdk", "kind": "ingest"},
        headers=CSRF,
    ).json()["key"]
    sdk_headers = {"X-LogLlama-Api-Key": ingest_key}

    plan = client.post(
        "/v1/test-plans",
        json={
            "prompt": "Reply with only: ok",
            "targets": [
                {"provider": "openai", "model": "gpt-4o-mini"},
                {"provider": "anthropic", "model": "claude-haiku-4-5"},
            ],
            "max_output_tokens": 16,
            "max_runs": 1,
        },
        headers=sdk_headers,
    )
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]

    viewer_email = _signup(client, organization_name="Viewer Org")
    _login(client, owner_email)
    client.post(
        f"/api/organizations/{organization_id}/members",
        json={"email": viewer_email, "role": "viewer"},
        headers=CSRF,
    )
    _login(client, viewer_email)
    denied = client.post(f"/api/admin/test-plans/{plan_id}/approve", json={}, headers=CSRF)
    assert denied.status_code == 403  # Member, but a viewer cannot approve.

    _login(client, owner_email)
    approved = client.post(f"/api/admin/test-plans/{plan_id}/approve", json={}, headers=CSRF)
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by"] == owner_email

    lease = client.post(f"/v1/test-plans/{plan_id}/lease", headers=sdk_headers)
    assert lease.status_code == 200
    assert lease.json()["run_count"] == 1
    assert client.post(f"/v1/test-plans/{plan_id}/lease", headers=sdk_headers).status_code == 409


@pytest.mark.parametrize("path", ["/api/requests", "/api/metadata/facets", "/api/metrics/summary"])
def test_dashboard_reads_are_scoped_to_one_project(client, path):
    email = _signup(client, organization_name="Scope Org")
    _, project_id = _owner_project(client, email)
    missing_project = client.get(path)
    assert missing_project.status_code == 422
    assert client.get(path, params={"project_id": project_id}).status_code == 200
