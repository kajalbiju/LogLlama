"""Organizations, users, roles, sessions, hashed API keys, and cost backfill.

Forward-only: the plaintext keys that existed before this revision cannot be recovered from their hashes.

Revision ID: 0002_tenancy_hashed_keys
Revises: 0001_baseline
Create Date: 2026-10-26
"""

import hashlib
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.pricing import estimate_cost_usd


revision: str = "0002_tenancy_hashed_keys"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEVELOPMENT_ORG_SLUG = "development"
COST_BACKFILL_BATCH = 1000


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id UUID PRIMARY KEY,
            email VARCHAR(320) NOT NULL UNIQUE,
            name VARCHAR(120) NOT NULL DEFAULT '',
            password_hash VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL,
            last_login_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE organizations (
            id UUID PRIMARY KEY,
            name VARCHAR(120) NOT NULL,
            slug VARCHAR(80) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE memberships (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
            role VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_memberships_user_organization UNIQUE (user_id, organization_id),
            CONSTRAINT ck_memberships_role CHECK (
                role IN ('owner', 'credential_admin', 'test_approver', 'developer', 'viewer')
            )
        )
        """
    )
    op.execute("CREATE INDEX ix_memberships_user_id ON memberships (user_id)")
    op.execute("CREATE INDEX ix_memberships_organization_id ON memberships (organization_id)")

    op.execute(
        """
        CREATE TABLE auth_sessions (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)")

    # Every existing project moves under one organization. Fresh installs get it from the startup seed.
    op.execute("ALTER TABLE projects ADD COLUMN organization_id UUID")
    op.execute(
        """
        INSERT INTO organizations (id, name, slug, created_at)
        SELECT gen_random_uuid(), 'Development', 'development', now()
        WHERE EXISTS (SELECT 1 FROM projects WHERE organization_id IS NULL)
          AND NOT EXISTS (SELECT 1 FROM organizations WHERE slug = 'development')
        """
    )
    op.execute(
        f"""
        UPDATE projects
        SET organization_id = (SELECT id FROM organizations WHERE slug = '{DEVELOPMENT_ORG_SLUG}')
        WHERE organization_id IS NULL
        """
    )
    op.execute("ALTER TABLE projects ALTER COLUMN organization_id SET NOT NULL")
    op.execute(
        """
        ALTER TABLE projects
        ADD CONSTRAINT fk_projects_organization_id
        FOREIGN KEY (organization_id) REFERENCES organizations (id) ON DELETE CASCADE
        """
    )
    op.execute("CREATE INDEX ix_projects_organization_id ON projects (organization_id)")

    op.execute(
        """
        CREATE TABLE api_keys (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
            name VARCHAR(120) NOT NULL,
            kind VARCHAR(16) NOT NULL,
            key_prefix VARCHAR(16) NOT NULL,
            key_hash VARCHAR(64) NOT NULL UNIQUE,
            created_by_user_id UUID REFERENCES users (id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL,
            last_used_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            CONSTRAINT ck_api_keys_kind CHECK (kind IN ('ingest', 'runtime'))
        )
        """
    )
    op.execute("CREATE INDEX ix_api_keys_project_id ON api_keys (project_id)")

    # Move plaintext keys into hashed rows. The old plaintext columns are dropped afterwards.
    bind = op.get_bind()
    projects = bind.execute(sa.text("SELECT id, api_key, runtime_key FROM projects")).all()
    for project_id, api_key, runtime_key in projects:
        for kind, raw_key in (("ingest", api_key), ("runtime", runtime_key)):
            if not raw_key:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO api_keys (id, project_id, name, kind, key_prefix, key_hash, created_at)
                    VALUES (:id, :project_id, :name, :kind, :key_prefix, :key_hash, now())
                    ON CONFLICT (key_hash) DO NOTHING
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "project_id": project_id,
                    "name": f"Migrated {kind} key",
                    "kind": kind,
                    "key_prefix": raw_key[:8],
                    "key_hash": _sha256(raw_key),
                },
            )

    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS api_key CASCADE")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS runtime_key CASCADE")

    # Cost was previously stored as 0 for providers without a price. Recompute those rows now,
    # and store NULL where the model still has no published text-token price.
    op.execute("ALTER TABLE llm_requests ALTER COLUMN cost_usd DROP NOT NULL")
    op.execute("ALTER TABLE llm_requests ALTER COLUMN cost_usd DROP DEFAULT")
    last_id = uuid.UUID(int=0)
    while True:
        rows = bind.execute(
            sa.text(
                """
                SELECT id, model, input_tokens, output_tokens
                FROM llm_requests
                WHERE cost_usd = 0 AND id > :last_id
                ORDER BY id
                LIMIT :batch_size
                """
            ),
            {"last_id": last_id, "batch_size": COST_BACKFILL_BATCH},
        ).all()
        if not rows:
            break
        bind.execute(
            sa.text("UPDATE llm_requests SET cost_usd = :cost_usd WHERE id = :id"),
            [
                {
                    "id": row.id,
                    "cost_usd": estimate_cost_usd(row.model, row.input_tokens, row.output_tokens),
                }
                for row in rows
            ],
        )
        last_id = rows[-1].id


def downgrade() -> None:
    raise NotImplementedError(
        "0002 is forward-only: plaintext API keys cannot be recovered from their hashes. "
        "Restore from a backup to roll back."
    )
