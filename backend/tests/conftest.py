from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
os.environ["DATABASE_URL"] = "postgresql+asyncpg://lms:lms@127.0.0.1:5432/lms_test"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = str(ROOT / ".data" / "objects")
os.environ["VECTOR_BACKEND"] = "memory"
os.environ["TASK_BACKEND"] = "inline"
os.environ["LLM_FORCE_MOCK"] = "true"
os.environ["ENVIRONMENT"] = "test"

import psycopg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import Base
from app.db.session import engine
from app.main import app


def _ensure_database() -> None:
    try:
        with psycopg.connect(
            "postgresql://lms:lms@127.0.0.1:5432/postgres", autocommit=True, connect_timeout=3
        ) as conn:
            row = conn.execute("select 1 from pg_database where datname = 'lms_test'").fetchone()
            if not row:
                conn.execute("create database lms_test")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"postgres unavailable: {exc}")


_ensure_database()


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    from app.services.vectorstore import get_vector_store

    store = get_vector_store()
    if hasattr(store, "clear"):
        store.clear()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac