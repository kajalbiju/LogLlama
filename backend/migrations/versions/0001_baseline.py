"""Baseline schema.

Every statement is idempotent. Databases created by the pre-migration startup code (create_all plus
ALTER TABLE on boot) already contain these tables, so they are adopted without changes.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


REQUEST_COLUMNS_ADDED_LATER = (
    "provider_request_id VARCHAR(255)",
    "retry_count INTEGER NOT NULL DEFAULT 0",
    "model_parameters JSONB",
    "service_name VARCHAR(160)",
    "environment VARCHAR(80)",
    "version VARCHAR(120)",
    "git_sha VARCHAR(80)",
    "route VARCHAR(240)",
    "user_id VARCHAR(160)",
    "tenant_id VARCHAR(160)",
    "session_id VARCHAR(160)",
    "conversation_id VARCHAR(160)",
    "request_id VARCHAR(160)",
    "trace_id VARCHAR(160)",
    "span_id VARCHAR(160)",
    "prompt_template VARCHAR(160)",
    "prompt_version VARCHAR(80)",
    "tags JSONB",
    "custom_metadata JSONB",
    "privacy JSONB",
    "request_metadata JSONB",
)

REQUEST_INDEXED_COLUMNS = (
    "project_id",
    "provider",
    "model",
    "status",
    "captured_at",
    "provider_request_id",
    "service_name",
    "environment",
    "route",
    "user_id",
    "tenant_id",
    "session_id",
    "conversation_id",
    "request_id",
    "trace_id",
    "prompt_template",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id UUID PRIMARY KEY,
            name VARCHAR(120) NOT NULL,
            api_key VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS runtime_key VARCHAR(255)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_api_key ON projects (api_key)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_runtime_key ON projects (runtime_key)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_requests (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects (id),
            external_id VARCHAR(120),
            provider VARCHAR(40) NOT NULL,
            operation VARCHAR(120) NOT NULL,
            model VARCHAR(120),
            status VARCHAR(20) NOT NULL,
            prompt JSONB,
            response JSONB,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd NUMERIC(12, 8) NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            error_type VARCHAR(160),
            error_message TEXT,
            captured_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_llm_requests_project_external_id UNIQUE (project_id, external_id)
        )
        """
    )
    for column in REQUEST_COLUMNS_ADDED_LATER:
        name = column.split(" ", 1)[0]
        op.execute(f"ALTER TABLE llm_requests ADD COLUMN IF NOT EXISTS {name} {column.split(' ', 1)[1]}")
    for column in REQUEST_INDEXED_COLUMNS:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_llm_requests_{column} ON llm_requests ({column})")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_project_environment_captured "
        "ON llm_requests (project_id, environment, captured_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_project_route_captured "
        "ON llm_requests (project_id, route, captured_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_llm_requests_project_tenant_captured "
        "ON llm_requests (project_id, tenant_id, captured_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_credentials (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects (id),
            provider VARCHAR(40) NOT NULL,
            name VARCHAR(120) NOT NULL DEFAULT 'default',
            secret_ref VARCHAR(500) NOT NULL UNIQUE,
            fingerprint VARCHAR(32) NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_provider_credentials_project_provider UNIQUE (project_id, provider)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_provider_credentials_project_id ON provider_credentials (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_provider_credentials_provider ON provider_credentials (provider)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_provider_credentials_status ON provider_credentials (status)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS test_plans (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects (id),
            prompt TEXT NOT NULL,
            system TEXT,
            targets JSONB NOT NULL,
            max_output_tokens INTEGER NOT NULL DEFAULT 256,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            requested_by VARCHAR(160),
            approved_by VARCHAR(160),
            rejection_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            approved_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ
        )
        """
    )
    op.execute("ALTER TABLE test_plans ADD COLUMN IF NOT EXISTS max_runs INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE test_plans ADD COLUMN IF NOT EXISTS run_count INTEGER NOT NULL DEFAULT 0")
    op.execute("CREATE INDEX IF NOT EXISTS ix_test_plans_project_id ON test_plans (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_test_plans_status ON test_plans (status)")


def downgrade() -> None:
    raise NotImplementedError("The baseline cannot be downgraded. Restore from a backup instead.")
