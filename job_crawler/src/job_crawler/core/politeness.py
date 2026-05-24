"""Per-host token-bucket throttle + concurrency cap.

Keeps a registry of HostThrottle objects keyed by hostname so two crawlers
hitting the same site (rare, but possible) share a single bucket.
"""

from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from urllib.parse import urlsplit


class _HostThrottle:
    """One token bucket + one semaphore per host."""

    __slots__ = (
        "_last_refill",
        "_lock",
        "_sem",
        "_tokens",
        "burst",
        "max_concurrent",
        "max_rps",
    )

    def __init__(self, *, max_rps: float, burst: int, max_concurrent: int) -> None:
        self.max_rps = max_rps
        self.burst = burst
        self.max_concurrent = max_concurrent
        self._lock = asyncio.Lock()
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._sem = asyncio.Semaphore(max_concurrent)

    async def acquire(self) -> None:
        """Block until a token is available; also acquires the concurrency slot."""
        await self._sem.acquire()
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(float(self.burst), self._tokens + elapsed * self.max_rps)
            self._last_refill = now
            wait = (1.0 - self._tokens) / self.max_rps if self._tokens < 1.0 else 0.0
            self._tokens -= 1.0  # consume optimistically; the wait below honours it
        if wait > 0:
            await asyncio.sleep(wait)

    def release(self) -> None:
        self._sem.release()


class PolitenessRegistry:
    """Process-wide cache of host throttles. Always use the same instance for
    one HttpClient → one process → one host = one bucket."""

    __slots__ = ("_hosts",)

    def __init__(self) -> None:
        self._hosts: dict[str, _HostThrottle] = {}

    def for_host(
        self,
        url: str,
        *,
        max_rps: float,
        burst: int,
        max_concurrent: int,
    ) -> _HostThrottle:
        host = urlsplit(url).hostname or url
        existing = self._hosts.get(host)
        if existing is None:
            existing = _HostThrottle(
                max_rps=max_rps,
                burst=burst,
                max_concurrent=max_concurrent,
            )
            self._hosts[host] = existing
        return existing


# Module-level singleton — shared by every HttpClient in this process.
REGISTRY = PolitenessRegistry()


# ---------------------------------------------------------------------------
# robots.txt cache (one-day TTL). Pure-stdlib; only consults the file once
# per host per process. Fail-open on errors (we still want to crawl).
# ---------------------------------------------------------------------------
_ROBOTS_CACHE: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}
_ROBOTS_TTL_SECONDS: float = 86400.0


async def robots_allows(url: str, user_agent: str) -> bool:
    """True when robots.txt allows the given UA to fetch `url`.

    Cached for 24 h per host. Failures (timeout, 5xx, parse error) fail-open.
    Synchronous-looking but the fetch is offloaded to a thread executor so
    we don't block the loop on slow robots servers.
    """
    host_url = _origin(url)
    now = time.monotonic()
    cached = _ROBOTS_CACHE.get(host_url)
    if cached and (now - cached[0]) < _ROBOTS_TTL_SECONDS:
        return cached[1].can_fetch(user_agent, url)

    loop = asyncio.get_running_loop()

    def _fetch() -> urllib.robotparser.RobotFileParser:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(host_url + "/robots.txt")
        try:
            rp.read()
        except Exception:
            # Fail-open: produce a parser that allows everything.
            rp.parse([])
        return rp

    try:
        rp = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch),
            timeout=5.0,
        )
    except Exception:
        return True  # fail-open
    _ROBOTS_CACHE[host_url] = (now, rp)
    return rp.can_fetch(user_agent, url)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
