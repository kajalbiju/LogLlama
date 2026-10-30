import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
BACKEND_DIR = Path(__file__).resolve().parents[1]

# Must run before any test module imports `app`, because settings are read at import time.
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL


async def _reset_schema(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to run database tests.")
    database_name = make_url(TEST_DATABASE_URL).database or ""
    if not database_name.endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL must point at a database whose name ends with _test.")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    from alembic import command
    from alembic.config import Config

    asyncio.run(_reset_schema(database_url))
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    return database_url


@pytest.fixture(scope="session")
def client(migrated_database: str):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
