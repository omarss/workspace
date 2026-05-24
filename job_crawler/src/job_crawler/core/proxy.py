"""Rotating HTTP/HTTPS/SOCKS proxy pool with permanent-failure blacklisting.

Design notes
------------
* **Random selection** weighted by recent success rate. Cold proxies start
  with weight 1.0; failures halve the weight; successes nudge it back up.
* **Two failure tiers**:
    - **Transient** (connect timeout, 5xx from the proxy, DNS issue) →
      bumps a counter. Three consecutive transient failures = blacklist.
    - **Permanent** (407 Proxy-Auth, SSL handshake failure, immediate
      RST) → blacklist on first occurrence.
* **Async-safe**: a single `asyncio.Lock` guards the mutable state. State
  is in-memory; persist to disk via `save_state(path)` if you want it to
  survive restarts.
* **Source-agnostic**: load from any combination of local files and remote
  URLs (raw GitHub URLs from monosans/proxifly/etc.). Lines starting with
  `#` are skipped; bare `host:port` is normalised to `http://host:port`.

Used by `HttpClient` (curl_cffi backend) — pass a `ProxyPool` to opt in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import httpx

_LOG: Final = logging.getLogger("job_crawler.proxy")


# ---------------------------------------------------------------------------
# Per-proxy state
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ProxyState:
    successes: int = 0
    failures_consec: int = 0
    failures_total: int = 0
    last_used_at: float = 0.0
    blacklisted_at: float | None = None
    blacklist_reason: str | None = None

    @property
    def is_blacklisted(self) -> bool:
        return self.blacklisted_at is not None

    @property
    def weight(self) -> float:
        """A simple weight in (0, 1] used to bias random selection.

        A cold proxy starts at 1.0. Each consecutive failure halves it.
        Successes raise it back toward 1.0.
        """
        return max(0.05, 0.5 ** self.failures_consec)


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------


# Failures we treat as permanent — blacklist on first occurrence.
_PERMANENT_REASONS: Final[frozenset[str]] = frozenset({
    "auth_required",        # 407 Proxy-Auth-Required
    "ssl",                  # SSL handshake failure
    "connection_refused",   # RST immediately
    "blocked_by_target",    # target site returns 403 specifically blaming the proxy IP
})

# After this many consecutive transient failures we blacklist.
_BLACKLIST_AFTER_TRANSIENT: Final[int] = 3


@dataclass(slots=True)
class ProxyPool:
    """A blacklist-aware bag of proxies, async-safe."""

    name: str = "default"
    _proxies: dict[str, _ProxyState] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # -- loading --------------------------------------------------------

    @staticmethod
    def _normalize(line: str) -> str | None:
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        # `host:port` → `http://host:port`
        if "://" not in line:
            line = "http://" + line
        # Sanity check
        parts = urlsplit(line)
        if not parts.hostname or not parts.port:
            return None
        return line

    async def load_text(self, blob: str) -> int:
        """Parse line-delimited proxies (the monosans / TheSpeedX format).

        Returns the count of newly-added URLs.
        """
        added = 0
        async with self._lock:
            for line in blob.splitlines():
                normalized = self._normalize(line)
                if normalized and normalized not in self._proxies:
                    self._proxies[normalized] = _ProxyState()
                    added += 1
        if added:
            _LOG.info("[%s] loaded %d new proxies (total: %d)",
                      self.name, added, len(self._proxies))
        return added

    async def load_file(self, path: str | Path) -> int:
        return await self.load_text(Path(path).read_text("utf-8"))

    async def load_url(self, url: str, *, timeout: float = 15.0) -> int:
        """Fetch a remote list (raw GitHub URL etc.) and merge it in."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.get(url)
                r.raise_for_status()
        except Exception as exc:
            _LOG.warning("[%s] proxy source %s failed: %s", self.name, url, exc)
            return 0
        return await self.load_text(r.text)

    # -- pick + report --------------------------------------------------

    async def pick(self) -> str | None:
        """Return a random non-blacklisted proxy, weighted by recent
        success rate. Returns None when the pool is empty.

        Selection priority:
          1. Proxies with at least one prior success — drawn proportional
             to (1 + successes), so well-performing proxies get reused.
          2. Cold proxies (no successes, no recent failures) — only sampled
             when the proven-alive pool is empty. This avoids burning a
             request on a likely-dead proxy when we have validated ones.
        """
        async with self._lock:
            proven: list[tuple[str, float]] = []
            cold: list[tuple[str, float]] = []
            for url, state in self._proxies.items():
                if state.is_blacklisted:
                    continue
                if state.successes > 0:
                    proven.append((url, state.weight * (1.0 + state.successes)))
                else:
                    cold.append((url, state.weight))
            pool = proven or cold
            if not pool:
                return None
            urls, weights = zip(*pool, strict=False)
            chosen = random.choices(urls, weights=weights, k=1)[0]
            self._proxies[chosen].last_used_at = time.time()
            return chosen

    async def mark_success(self, proxy: str) -> None:
        async with self._lock:
            state = self._proxies.get(proxy)
            if state is None:
                return
            state.successes += 1
            state.failures_consec = 0

    async def mark_failure(
        self, proxy: str, *, reason: str = "transient",
    ) -> None:
        """Record a failure. `reason` may be one of the `_PERMANENT_REASONS`
        for immediate blacklist, or anything else for a transient failure."""
        async with self._lock:
            state = self._proxies.get(proxy)
            if state is None:
                return
            state.failures_consec += 1
            state.failures_total += 1
            if reason in _PERMANENT_REASONS:
                state.blacklisted_at = time.time()
                state.blacklist_reason = reason
                _LOG.info(
                    "[%s] blacklisted %s (permanent: %s)",
                    self.name, proxy, reason,
                )
            elif state.failures_consec >= _BLACKLIST_AFTER_TRANSIENT:
                state.blacklisted_at = time.time()
                state.blacklist_reason = (
                    f"{state.failures_consec} consecutive transient failures"
                )
                _LOG.info(
                    "[%s] blacklisted %s (transient streak: %d)",
                    self.name, proxy, state.failures_consec,
                )

    async def stats(self) -> dict[str, int | float]:
        """Snapshot of pool health — non-blocking caller-friendly."""
        async with self._lock:
            total = len(self._proxies)
            blacklisted = sum(
                1 for s in self._proxies.values() if s.is_blacklisted
            )
            alive = total - blacklisted
            succ = sum(s.successes for s in self._proxies.values())
            fail = sum(s.failures_total for s in self._proxies.values())
        return {
            "total": total,
            "alive": alive,
            "blacklisted": blacklisted,
            "successes": succ,
            "failures": fail,
            "success_rate": round(succ / max(1, succ + fail), 3),
        }

    # -- validation -----------------------------------------------------

    async def validate(
        self,
        *,
        probe_url: str = "https://httpbin.org/ip",
        timeout: float = 6.0,
        concurrency: int = 50,
        max_to_test: int | None = None,
        only_unscored: bool = True,
    ) -> dict[str, int]:
        """Test every live proxy against `probe_url` and blacklist the dead ones.

        Designed to be run periodically (e.g. via `make proxies-validate`).
        Free public proxies churn rapidly: ~90% are dead at any moment.

        * `only_unscored=True` (default) skips proxies that already have at
          least one success — those are presumed alive.
        * `max_to_test` caps the number of proxies tested per call so a
          single validation pass doesn't take forever.
        """
        async with self._lock:
            candidates = [
                url for url, s in self._proxies.items()
                if not s.is_blacklisted and (not only_unscored or s.successes == 0)
            ]
        if max_to_test:
            random.shuffle(candidates)
            candidates = candidates[:max_to_test]
        sem = asyncio.Semaphore(concurrency)
        alive_count = 0
        dead_count = 0

        async def probe(proxy_url: str) -> None:
            nonlocal alive_count, dead_count
            async with sem:
                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(timeout),
                        proxy=proxy_url,
                        verify=False,  # many free proxies break TLS verification
                    ) as client:
                        r = await client.get(probe_url)
                    if r.status_code == 200:
                        await self.mark_success(proxy_url)
                        alive_count += 1
                        return
                    await self.mark_failure(proxy_url, reason="transient")
                    dead_count += 1
                except Exception as exc:
                    await self.mark_failure(
                        proxy_url, reason=classify_failure(exc),
                    )
                    dead_count += 1

        await asyncio.gather(*(probe(u) for u in candidates))
        _LOG.info(
            "[%s] validate: tested=%d alive=%d dead=%d",
            self.name, len(candidates), alive_count, dead_count,
        )
        return {"tested": len(candidates), "alive": alive_count, "dead": dead_count}

    # -- persistence ----------------------------------------------------

    async def save_state(self, path: str | Path) -> None:
        """Persist counters + blacklist to a JSON file."""
        async with self._lock:
            snapshot = {
                url: {
                    "successes": s.successes,
                    "failures_consec": s.failures_consec,
                    "failures_total": s.failures_total,
                    "last_used_at": s.last_used_at,
                    "blacklisted_at": s.blacklisted_at,
                    "blacklist_reason": s.blacklist_reason,
                }
                for url, s in self._proxies.items()
            }
        Path(path).write_text(json.dumps(snapshot, indent=2))

    async def load_state(self, path: str | Path) -> int:
        """Restore counters + blacklist from a previous `save_state`. Adds
        any proxies not already in the pool. Returns count restored."""
        p = Path(path)
        if not p.is_file():
            return 0
        snapshot = json.loads(p.read_text("utf-8"))
        restored = 0
        async with self._lock:
            for url, meta in snapshot.items():
                state = self._proxies.setdefault(url, _ProxyState())
                state.successes = meta.get("successes", 0)
                state.failures_consec = meta.get("failures_consec", 0)
                state.failures_total = meta.get("failures_total", 0)
                state.last_used_at = meta.get("last_used_at", 0.0)
                state.blacklisted_at = meta.get("blacklisted_at")
                state.blacklist_reason = meta.get("blacklist_reason")
                restored += 1
        return restored


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


# Default sources — well-maintained free lists. `monosans` is pre-validated
# so it has a meaningfully higher hit rate than the raw collectors.
DEFAULT_SOURCES: Final[tuple[str, ...]] = (
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
)


async def build_default_pool(
    state_file: Path | None = None,
    sources: tuple[str, ...] = DEFAULT_SOURCES,
) -> ProxyPool:
    """One-line constructor for the common case: load from the standard
    free-list URLs + optionally restore prior state from disk."""
    pool = ProxyPool(name="default")
    if state_file:
        await pool.load_state(state_file)
    for url in sources:
        await pool.load_url(url)
    return pool


# ---------------------------------------------------------------------------
# Failure classification — shared between HttpClient back-ends.
# ---------------------------------------------------------------------------


def classify_failure(exc: BaseException) -> str:
    """Inspect an exception and return a `reason` suitable for
    `ProxyPool.mark_failure`. Conservative: when in doubt, returns
    `"transient"`."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "407" in text or ("proxy" in text and "auth" in text):
        return "auth_required"
    if any(k in text for k in ("ssl", "handshake", "certificate")):
        return "ssl"
    if "refused" in text:
        return "connection_refused"
    if "403" in text and ("blocked" in text or "denied" in text or "forbidden" in text):
        # Target site returned 403 specifically — proxy IP likely flagged.
        return "blocked_by_target"
    if "timeout" in name or "timeout" in text:
        return "transient"
    return "transient"
