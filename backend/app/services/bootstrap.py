from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ..config import settings
from ..models import ApiKey, Organization, Project
from ..security import display_prefix, hash_token


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
DEVELOPMENT_ORG_SLUG = "development"


def expected_schema_revision() -> str:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()


async def verify_schema_revision(engine: AsyncEngine) -> None:
    """Startup never changes the schema. It only refuses to serve against a database that is not migrated."""
    expected = expected_schema_revision()
    async with engine.connect() as connection:
        current = await connection.run_sync(
            lambda sync_connection: MigrationContext.configure(sync_connection).get_current_revision()
        )
    if current != expected:
        found = current or "none (unversioned database)"
        raise RuntimeError(
            f"Database schema is at {found}, expected {expected}. "
            "Run `alembic upgrade head` from the backend directory."
        )


async def _development_project(session: AsyncSession) -> Project:
    organization = (
        await session.execute(select(Organization).where(Organization.slug == DEVELOPMENT_ORG_SLUG))
    ).scalar_one_or_none()
    if organization is None:
        organization = Organization(name="Development", slug=DEVELOPMENT_ORG_SLUG)
        session.add(organization)
        await session.flush()

    project = (
        await session.execute(
            select(Project).where(
                Project.organization_id == organization.id,
                Project.name == settings.default_project_name,
            )
        )
    ).scalar_one_or_none()
    if project is None:
        project = Project(organization_id=organization.id, name=settings.default_project_name)
        session.add(project)
        await session.flush()
    return project


async def seed_default_keys(session: AsyncSession) -> None:
    """Create the configured development keys once. A revoked seeded key stays revoked."""
    seeds = (("ingest", settings.default_api_key), ("runtime", settings.default_runtime_key))
    for kind, raw_key in seeds:
        if not raw_key:
            continue
        key_hash = hash_token(raw_key)
        exists = (await session.execute(select(ApiKey.id).where(ApiKey.key_hash == key_hash))).first()
        if exists is not None:
            continue
        project = await _development_project(session)
        session.add(
            ApiKey(
                project_id=project.id,
                name=f"Seeded {kind} key",
                kind=kind,
                key_prefix=display_prefix(raw_key),
                key_hash=key_hash,
            )
        )
    await session.commit()
