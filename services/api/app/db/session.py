"""Async session factory and FastAPI dependency."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.services.db import get_engine

_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_sessionmaker(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Lazy singleton session factory. `engine` overrides the singleton's
    default engine (used by tests + smoke scripts that run against
    in-memory SQLite)."""
    global _session_maker
    if engine is not None:
        return async_sessionmaker(bind=engine, expire_on_commit=False)
    if _session_maker is None:
        _session_maker = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False
        )
    return _session_maker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session, rolls back on exception."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


__all__ = ["get_session", "get_sessionmaker"]
