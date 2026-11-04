"""Shared HTTP client, polite per-host spacing, conditional GETs and a small async TTL cache."""
import asyncio
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from .config import USER_AGENT

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=15.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class FeedError(Exception):
    pass


# Minimum gap between two requests to the same host (seconds). Default 1 s.
HOST_GAP = {"api.tomtom.com": 0.25}
_host_locks: dict[str, asyncio.Lock] = {}
_host_last: dict[str, float] = {}


async def polite_get(url: str, *, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """GET with at most one in-flight request per host and a minimum gap between them."""
    host = urlsplit(url).hostname or ""
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        wait = _host_last.get(host, 0) + HOST_GAP.get(host, 1.0) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await client().get(url, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise FeedError(f"{host}: {e.__class__.__name__} {e}") from e
        finally:
            _host_last[host] = time.monotonic()


async def get_bytes(url: str, **params: Any) -> bytes:
    r = await polite_get(url, params=params or None)
    if r.status_code != 200:
        raise FeedError(f"{url}: HTTP {r.status_code}")
    return r.content


_validators: dict[str, dict[str, str]] = {}


async def get_if_changed(url: str) -> bytes | None:
    """Download only if the resource changed since our last download (ETag / Last-Modified).

    Returns None when unchanged. Servers that ignore the headers just answer 200 again.
    """
    v = _validators.get(url, {})
    headers = {}
    if "etag" in v:
        headers["If-None-Match"] = v["etag"]
    if "last-modified" in v:
        headers["If-Modified-Since"] = v["last-modified"]
    r = await polite_get(url, headers=headers)
    if r.status_code == 304:
        return None
    if r.status_code != 200:
        raise FeedError(f"{url}: HTTP {r.status_code}")
    _validators[url] = {k: r.headers[k] for k in ("etag", "last-modified") if k in r.headers}
    return r.content


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
