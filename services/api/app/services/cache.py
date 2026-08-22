"""Redis connectivity."""
from __future__ import annotations

import redis.asyncio as redis

from app.core.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return _client


async def ping_redis() -> None:
    client = get_redis()
    await client.ping()
