import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402, F401  (registers every table on Base.metadata)
from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Only one backend replica may migrate at a time. The lock is session-level, so it is taken and released on one connection.
MIGRATION_LOCK_SQL = text("SELECT pg_advisory_lock(hashtext('logllama_schema_migrations'))")
MIGRATION_UNLOCK_SQL = text("SELECT pg_advisory_unlock(hashtext('logllama_schema_migrations'))")


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.execute(MIGRATION_LOCK_SQL)
        try:
            await connection.run_sync(do_run_migrations)
            await connection.commit()
        except Exception:
            await connection.rollback()
            raise
        finally:
            await connection.execute(MIGRATION_UNLOCK_SQL)
            await connection.commit()
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
