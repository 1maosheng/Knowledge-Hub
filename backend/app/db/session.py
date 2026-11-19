from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import Base

_settings = get_settings()

_pool_kwargs: dict = {}
if _settings.environment == "test":
    # Tests run each case on a fresh event loop; pooled asyncpg connections would
    # be bound to the previous (closed) loop.
    _pool_kwargs["poolclass"] = NullPool

engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    echo=False,
    **_pool_kwargs,
)

session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    await engine.dispose()