"""Redis cache wrapper with in-memory fallback.

If `settings.redis_url` is set AND the connection succeeds, uses Redis.
Otherwise falls back to a process-local LRU dict — meaning the app keeps
running even without Redis, you just lose cross-worker caching.

Usage:
    from app.services.cache import cache
    cache.set("planet_positions:2026-05-20T11", positions, ttl=3600)
    cached = cache.get("planet_positions:2026-05-20T11")
"""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import Any
from loguru import logger

from app.config import settings


class _InMemoryCache:
    """Process-local fallback cache. Tiny — meant for local dev / single
    worker. Bounded LRU to avoid unbounded growth."""

    def __init__(self, max_items: int = 5000):
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_items

    def get(self, key: str) -> Any:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, val = entry
        if expires_at and expires_at < time.time():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return val

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        expires_at = time.time() + ttl if ttl else 0
        self._data[key] = (expires_at, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def health(self) -> dict:
        return {"backend": "in_memory", "size": len(self._data), "max": self._max}


class _RedisCache:
    def __init__(self, client):
        self._r = client

    def get(self, key: str) -> Any:
        raw = self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw.decode() if isinstance(raw, bytes) else raw

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        payload = json.dumps(value, default=str)
        if ttl:
            self._r.setex(key, ttl, payload)
        else:
            self._r.set(key, payload)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def health(self) -> dict:
        try:
            info = self._r.info("memory")
            return {"backend": "redis", "memory_used": info.get("used_memory_human", "?")}
        except Exception as e:
            return {"backend": "redis", "error": str(e)}


def _build_cache():
    if not settings.redis_url:
        logger.info("Cache backend: in-memory (REDIS_URL not set)")
        return _InMemoryCache()
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, decode_responses=False,
                                       socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        logger.info("Cache backend: Redis @ {}", settings.redis_url)
        return _RedisCache(client)
    except Exception as e:
        logger.warning("Redis unreachable ({}), falling back to in-memory", e)
        return _InMemoryCache()


cache = _build_cache()
