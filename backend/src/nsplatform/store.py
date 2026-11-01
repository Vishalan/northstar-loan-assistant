"""Key-value store with TTL for sessions, the connector cache and idempotency keys.

Uses Redis when REDIS_URL is set (any orchestrator replica can serve any turn); otherwise an
in-process dict, which is fine for a single local process.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any


class MemoryStore:
    def __init__(self):
        self._data: dict[str, tuple[float | None, str]] = {}

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        expires, raw = item
        if expires is not None and expires < time.time():
            self._data.pop(key, None)
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_s: float | None = None) -> None:
        self._data[key] = (time.time() + ttl_s if ttl_s else None, json.dumps(value, default=str))

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, ttl_s: float) -> int:
        current = await self.get(key) or 0
        item = self._data.get(key)
        expires = item[0] if item else time.time() + ttl_s
        self._data[key] = (expires, json.dumps(current + 1))
        return current + 1


class RedisStore:
    def __init__(self, url: str):
        import redis.asyncio as redis

        self._r = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        raw = await self._r.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: Any, ttl_s: float | None = None) -> None:
        await self._r.set(key, json.dumps(value, default=str), ex=int(ttl_s) if ttl_s else None)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def incr(self, key: str, ttl_s: float) -> int:
        value = await self._r.incr(key)
        if value == 1:
            await self._r.expire(key, int(ttl_s))
        return value


def make_store():
    url = os.environ.get("REDIS_URL")
    return RedisStore(url) if url else MemoryStore()
