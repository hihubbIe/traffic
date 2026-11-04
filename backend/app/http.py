"""Shared HTTP client and a small async TTL cache for upstream feeds."""
import asyncio
import time
from typing import Any, Awaitable, Callable

import httpx

from .config import USER_AGENT

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    return _client


async def close() -> None:
    if _client is not None:
        await _client.aclose()


class FeedError(Exception):
    pass


_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def cached(key: str, ttl: float, producer: Callable[[], Awaitable[Any]]) -> Any:
    """Return a cached value younger than ttl seconds, else produce it once (deduplicated)."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        value = await producer()
        _cache[key] = (time.time(), value)
        return value


async def get_bytes(url: str, **params: Any) -> bytes:
    try:
        r = await client().get(url, params=params or None)
    except httpx.HTTPError as e:
        raise FeedError(f"{url}: {e}") from e
    if r.status_code != 200:
        raise FeedError(f"{url}: HTTP {r.status_code}")
    return r.content
