"""Shared async Redis client for the whole server."""
from __future__ import annotations

import os
from typing import Optional

try:
    import redis.asyncio as aioredis

    _redis: Optional[aioredis.Redis] = None

    async def get_redis() -> Optional[aioredis.Redis]:
        global _redis
        if _redis is None:
            try:
                _redis = aioredis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                await _redis.ping()
            except Exception:
                _redis = None
        return _redis

except ImportError:
    async def get_redis() -> None:  # type: ignore[misc]
        return None
