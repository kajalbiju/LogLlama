import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


CSRF = {"X-LogLlama-Request": "1"}
PASSWORD = "correct horse battery"


def _error_message_for(database_url: str, external_id: str) -> str | None:
    async def run():
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text("SELECT error_message FROM llm_requests WHERE external_id = :external_id"),
                    {"external_id": external_id},
                )
                return result.scalar_one()
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_error_message_is_redacted_before_it_is_stored(client, database_url):
    email = f"redact-{uuid.uuid4().hex[:10]}@example.com"
    client.cookies.clear()
    signup = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "organization_name": "Redaction Org"},
        headers=CSRF,
    )
    assert signup.status_code == 201, signup.text
    organization_id = signup.json()["organizations"][0]["id"]
    project_id = client.get("/api/projects", params={"organization_id": organization_id}).json()[0]["id"]
    ingest_key = client.post(
        f"/api/projects/{project_id}/api-keys",
        json={"name": "redaction", "kind": "ingest"},
        headers=CSRF,
    ).json()["key"]

    external_id = f"redact-{uuid.uuid4().hex}"
    response = client.post(
        "/v1/events",
        json={
            "external_id": external_id,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "status": "error",
            "error": {
                "type": "AuthenticationError",
                "message": "Incorrect API key provided: =sk-proj*****abcd1234efgh5678. Check yours.",
            },
        },
        headers={"X-LogLlama-Api-Key": ingest_key},
    )
    assert response.status_code == 202, response.text

    stored = _error_message_for(database_url, external_id)
    assert "abcd1234efgh5678" not in stored
    assert "[REDACTED]" in stored
