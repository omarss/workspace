"""Shared async HTTP client.

Every crawler uses this — there is no other HTTP path. Centralises:

  * httpx.AsyncClient with HTTP/2 + connection pool
  * Per-host token-bucket + concurrency cap (via politeness.REGISTRY)
  * UA rotation when the crawler doesn't pin a specific one
  * Exponential backoff with jitter (tenacity)
  * robots.txt enforcement (fail-open on errors)
  * Cap on retries; honours Retry-After headers on 429/503

The class is cheap to construct — one per crawler instance per run.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Final

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .config import USER_AGENTS, RateConfig
from .politeness import REGISTRY, robots_allows

_LOG: Final = logging.getLogger("job_crawler.http")


@dataclass(slots=True)
class FetchResult:
    """Outcome of one HTTP fetch."""

    status: int
    url: str  # final URL after redirects
    text: str
    bytes: int
    duration_ms: int
    headers: httpx.Headers
    json: Any | None  # parsed JSON when the response was application/json


class HttpClient:
    """Async HTTP client wrapping httpx, throttled by RateConfig."""

    __slots__ = (
        "_cffi_session",
        "_client",
        "_extra_headers",
        "_impersonate",
        "_proxy_pool",
        "_respect_robots",
        "_ua_fixed",
        "rate",
    )

    def __init__(
        self,
        rate: RateConfig,
        *,
        respect_robots: bool = True,
        extra_headers: dict[str, str] | None = None,
        http2: bool = True,
        impersonate: str | None = None,
        proxy_pool: Any = None,
    ) -> None:
        """
        impersonate: when set (e.g. "chrome"), routes requests through
        `curl_cffi.requests.AsyncSession` instead of `httpx.AsyncClient`.
        This matches a real browser's TLS+HTTP/2 fingerprint, which gets
        past Cloudflare/DataDome-style bot walls (e.g. Bayt). Trades the
        httpx feature set for fingerprint accuracy — use only for sites
        that need it.
        """
        self.rate = rate
        self._respect_robots = respect_robots
        self._ua_fixed = rate.user_agent
        self._impersonate = impersonate
        self._proxy_pool = proxy_pool
        self._client: httpx.AsyncClient | None = None
        self._cffi_session: Any | None = None
        self._extra_headers = extra_headers or {}

        if impersonate:
            # curl_cffi import is lazy because the binary wheel adds ~10 MB
            # to the image; only loaded when an actually-impersonating
            # crawler is instantiated.
            from curl_cffi.requests import AsyncSession  # type: ignore[import-untyped]

            self._cffi_session = AsyncSession(
                impersonate=impersonate,
                timeout=rate.timeout_seconds,
                max_clients=rate.max_concurrent * 2,
            )
        else:
            timeout = httpx.Timeout(
                connect=10.0,
                read=rate.timeout_seconds,
                write=10.0,
                pool=10.0,
            )
            limits = httpx.Limits(
                max_connections=rate.max_concurrent * 4,
                max_keepalive_connections=rate.max_concurrent * 2,
            )
            self._client = httpx.AsyncClient(
                http2=http2,
                timeout=timeout,
                limits=limits,
                follow_redirects=True,
                headers={
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9,ar;q=0.7",
                    # NB: omit 'br' on purpose — httpx only decodes gzip + deflate
                    # natively. Advertising brotli without the optional `brotli`
                    # extra leaves us with undecoded binary body bytes.
                    "Accept-Encoding": "gzip, deflate",
                    **(extra_headers or {}),
                },
            )

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        if self._cffi_session is not None:
            await self._cffi_session.close()

    # ---- single fetch with full politeness stack ---------------------

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """Polite, retried, robots-aware fetch.

        Returns a FetchResult or raises `httpx.HTTPError` after all retries
        are exhausted.
        """
        ua = self._ua_fixed or random.choice(USER_AGENTS)
        request_headers = dict(headers or {})
        request_headers.setdefault("User-Agent", ua)

        if self._respect_robots and not await robots_allows(url, ua):
            raise PermissionError(f"robots.txt disallows {url}")

        bucket = REGISTRY.for_host(
            url,
            max_rps=self.rate.max_rps,
            burst=self.rate.burst,
            max_concurrent=self.rate.max_concurrent,
        )

        async def _do() -> FetchResult:
            await bucket.acquire()
            # Pick a proxy per attempt (if a pool was configured) so a single
            # blacklisted proxy doesn't poison every retry.
            chosen_proxy: str | None = None
            if self._proxy_pool is not None:
                chosen_proxy = await self._proxy_pool.pick()
            try:
                t0 = _now_ms()
                if self._cffi_session is not None:
                    # curl_cffi already merges its own browser-like headers
                    # from the impersonate profile — we only add our overrides.
                    # curl_cffi supports per-request `proxies={...}`.
                    cffi_kwargs: dict[str, Any] = {
                        "params": params,
                        "json": json_body,
                        "headers": request_headers,
                    }
                    if chosen_proxy:
                        cffi_kwargs["proxies"] = {
                            "http": chosen_proxy,
                            "https": chosen_proxy,
                        }
                    try:
                        resp = await self._cffi_session.request(
                            method, url, **cffi_kwargs,
                        )
                    except Exception as exc:
                        if chosen_proxy and self._proxy_pool is not None:
                            from .proxy import classify_failure
                            await self._proxy_pool.mark_failure(
                                chosen_proxy, reason=classify_failure(exc),
                            )
                        raise
                else:
                    assert self._client is not None
                    # httpx doesn't accept per-request `proxies=`; we'd need a
                    # fresh client per call to rotate. For now, ignore the
                    # proxy pool on the httpx path — its sites don't need it.
                    if chosen_proxy is not None:
                        _LOG.debug(
                            "proxy_pool set but httpx backend ignores it; "
                            "use impersonate=... to enable per-request rotation",
                        )
                        chosen_proxy = None
                    resp = await self._client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers=request_headers,
                    )
                duration = _now_ms() - t0
                # 429 / 503 → raise so tenacity retries with backoff. We
                # honour Retry-After when the server sends it; otherwise we
                # synthesise a long cooldown (sites like LinkedIn rate-limit
                # without ever sending a Retry-After header).
                if resp.status_code in (429, 503):
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    if retry_after is None:
                        # No header → assume the worst. Synthesise a cooldown
                        # of 60s + 30s jitter so we stop hammering the server.
                        retry_after = 60.0 + random.uniform(0, 30)
                    # Cap the sleep. Some sites (Workable, Cloudflare) return
                    # Retry-After: 86400 as a "go away forever" signal — if we
                    # honour it literally the crawler stalls for 24h.
                    # 120s is plenty to clear most rate-limit windows; the next
                    # retry will either succeed or trip the tenacity retry cap.
                    _MAX_RETRY_AFTER_S = 120.0
                    if retry_after > _MAX_RETRY_AFTER_S:
                        _LOG.warning(
                            "rate-limited %s on %s, server asked for %.0fs; "
                            "capping sleep at %.0fs",
                            resp.status_code, url, retry_after,
                            _MAX_RETRY_AFTER_S,
                        )
                        retry_after = _MAX_RETRY_AFTER_S
                    else:
                        _LOG.warning(
                            "rate-limited %s on %s, sleeping %.1fs",
                            resp.status_code, url, retry_after,
                        )
                    import asyncio as _a

                    await _a.sleep(retry_after)
                    if chosen_proxy and self._proxy_pool is not None:
                        await self._proxy_pool.mark_failure(
                            chosen_proxy, reason="transient",
                        )
                    raise _RetryableStatus(resp.status_code, url)
                # Proxy-auth required from upstream proxy itself.
                if resp.status_code == 407 and chosen_proxy and self._proxy_pool is not None:
                    await self._proxy_pool.mark_failure(
                        chosen_proxy, reason="auth_required",
                    )
                # Target site explicitly forbids the proxy IP.
                if resp.status_code == 403 and chosen_proxy and self._proxy_pool is not None:
                    await self._proxy_pool.mark_failure(
                        chosen_proxy, reason="blocked_by_target",
                    )
                # 5xx (other than 503) → retry; 4xx other than 429 → don't.
                if 500 <= resp.status_code < 600:
                    if chosen_proxy and self._proxy_pool is not None:
                        await self._proxy_pool.mark_failure(
                            chosen_proxy, reason="transient",
                        )
                    raise _RetryableStatus(resp.status_code, url)
                resp.raise_for_status()
                # Successful 2xx via proxy — bump it up.
                if chosen_proxy and self._proxy_pool is not None:
                    await self._proxy_pool.mark_success(chosen_proxy)

                body = resp.text
                payload_json: Any | None = None
                ctype = resp.headers.get("Content-Type", "")
                if "application/json" in ctype:
                    try:
                        payload_json = resp.json()
                    except ValueError:
                        payload_json = None
                return FetchResult(
                    status=resp.status_code,
                    url=str(resp.url),
                    text=body,
                    bytes=len(resp.content),
                    duration_ms=duration,
                    headers=resp.headers,
                    json=payload_json,
                )
            finally:
                bucket.release()

        # When using curl_cffi (impersonation / proxy paths) we also need to
        # retry on its RequestsError family — connect timeouts, proxy resets,
        # SSL handshake fails. We import lazily so the dependency stays
        # optional for callers who don't impersonate.
        retry_types: tuple[type[BaseException], ...] = (
            _RetryableStatus,
            httpx.TimeoutException,
            httpx.NetworkError,
        )
        if self._cffi_session is not None:
            try:
                from curl_cffi.requests.errors import RequestsError  # type: ignore[import-untyped]

                retry_types = (*retry_types, RequestsError)
            except ImportError:
                pass

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.rate.retry_attempts),
                wait=wait_exponential_jitter(initial=0.5, max=30.0),
                retry=retry_if_exception_type(retry_types),
                reraise=True,
            ):
                with attempt:
                    return await _do()
        except RetryError as exc:
            raise exc.last_attempt.exception() from exc  # type: ignore[misc]
        raise AssertionError("unreachable")


class _RetryableStatus(Exception):
    """Internal sentinel — a status code we want tenacity to retry."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"retryable status {status} on {url}")
        self.status = status
        self.url = url


def _now_ms() -> int:
    import time as _t

    return int(_t.monotonic() * 1000)


def _parse_retry_after(value: str | None) -> float | None:
    """Return seconds to wait; None when unparseable. Supports integer
    seconds (the only form servers commonly send for our use cases)."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
