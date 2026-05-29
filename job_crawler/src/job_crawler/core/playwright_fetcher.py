"""Headless-Chromium fetcher for SPA / bot-walled sites.

Why this exists
---------------
Some target sites are immune to `httpx` and `curl_cffi`:

* **LinkedIn / Indeed** — server-side bot walls that fingerprint TLS *and*
  HTTP/2 framing. curl_cffi gets us past the TLS layer but the behaviour
  detector still triggers on suspicious request shape.
* **Glassdoor** — Next.js SPA: the listing data only materialises after
  client-side hydration; a raw HTML fetch returns an empty shell.
* **Jadarat** — Queue-It virtual queue intercepts every anonymous request
  and redirects to a `queueittoken=…` page; the only escape is to wait
  the queue out.

A real Chromium instance defeats all three. This module wraps Playwright
behind an interface compatible with `core.http.HttpClient.fetch()` so
crawlers can swap fetchers via a single class-var flip.

Lifecycle
---------
Instantiate once per crawler run; reuse across every request:

    async with PlaywrightFetcher(rate=cls.rate, cookie=os.environ.get(...)) as bf:
        for url in urls:
            r = await bf.fetch(url, wait_for_selector="article.job")

The shared browser/context handles cookies persistence and amortises the
~3-5s Chromium launch cost.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Final, Self

from .config import RateConfig

_LOG: Final = logging.getLogger("job_crawler.playwright_fetcher")


@dataclass(slots=True)
class FetchResult:
    """Same shape as `core.http.FetchResult` so calling code can be agnostic.

    `headers` is a plain dict here (Playwright doesn't expose `httpx.Headers`)
    but the keys are case-insensitive at the source so behaviour is the same
    for our `headers.get("Retry-After")` style checks.
    """

    status: int
    url: str
    text: str
    bytes: int
    duration_ms: int
    headers: dict[str, str]
    json: Any | None = None  # only filled when explicitly requested


class PlaywrightFetcher:
    """Async Chromium driver with a fetch() interface mirroring HttpClient.

    Throttling
    ----------
    Honours `rate.max_rps` as a per-fetcher token bucket (simple sleep).
    Concurrency is implicitly bounded by `rate.max_concurrent` Chromium
    pages reused round-robin.
    """

    __slots__ = (
        "_browser",
        "_context",
        "_cookie_header",
        "_extra_headers",
        "_lock",
        "_playwright",
        "_throttle_at",
        "_user_agent",
        "rate",
    )

    def __init__(
        self,
        rate: RateConfig,
        *,
        cookie: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.rate = rate
        self._cookie_header = cookie or None
        self._extra_headers = extra_headers or {}
        self._user_agent = rate.user_agent or (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._lock = asyncio.Lock()
        # Token-bucket scheduling: next allowed wall-clock time.
        self._throttle_at = 0.0

    # -- lifecycle ------------------------------------------------------

    async def __aenter__(self) -> Self:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        # One persistent context so cookies stick across fetches.
        self._context = await self._browser.new_context(
            user_agent=self._user_agent,
            locale="en-US",
            extra_http_headers=self._extra_headers,
        )
        if self._cookie_header:
            await self._inject_cookies(self._cookie_header)
        _LOG.info("playwright: chromium launched (UA=%s)", self._user_agent)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:  # pragma: no cover — best-effort cleanup
                    _LOG.exception("playwright close failed")
        if self._playwright is not None:
            await self._playwright.stop()
        self._context = self._browser = self._playwright = None

    # -- public fetch ---------------------------------------------------

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        wait_until: str = "networkidle",
        wait_for_selector: str | None = None,
        wait_for_url_pattern: str | None = None,
        timeout_ms: int | None = None,
        via_api: bool = False,
    ) -> FetchResult:
        """Navigate to `url` in a fresh page and return its rendered HTML.

        Extra knobs beyond the HttpClient signature:

        * `wait_until` — `"load" | "domcontentloaded" | "networkidle" |
          "commit"`. Default `networkidle` so SPAs finish hydrating.
        * `wait_for_selector` — CSS selector to wait for after navigation
          before reading the body. Use this when the data you want is
          rendered after a XHR (e.g. Glassdoor cards).
        * `wait_for_url_pattern` — if set, after navigation we poll until
          the page URL contains this substring. Defeats Queue-It-style
          interstitials whose final URL only matches after the queue
          releases.
        * `timeout_ms` — overrides `rate.timeout_seconds * 1000`.
        * `via_api` — when True, route the GET through
          `context.request.fetch` (Playwright's APIRequestContext)
          instead of full browser navigation. Required for JSON
          endpoints behind Cloudflare's bot wall: they need a real
          Chromium TLS fingerprint but `page.goto` waits forever for
          `networkidle` because a JSON response never finishes
          "loading" in the browser sense. `application/json` content
          gets the same JSON-parse treatment as the non-GET path.

        Non-GET methods route through `page.request` (Playwright's built-in
        APIRequestContext) so we can still do JSON POSTs for endpoints that
        only need a real-browser TLS shape, not full rendering.
        """
        # Throttle to honour max_rps. Sleeping in the lock keeps concurrency
        # bounded — fine for sites where Chrome is the bottleneck anyway.
        if self.rate.max_rps > 0:
            async with self._lock:
                now = time.monotonic()
                if now < self._throttle_at:
                    await asyncio.sleep(self._throttle_at - now)
                self._throttle_at = max(now, self._throttle_at) + (1.0 / self.rate.max_rps)

        if self._context is None:
            raise RuntimeError("PlaywrightFetcher not entered as a context manager")

        timeout = timeout_ms or int(self.rate.timeout_seconds * 1000)

        if via_api or method.upper() != "GET":
            return await self._fetch_via_api(
                url, method=method, params=params,
                json_body=json_body, headers=headers, timeout=timeout,
            )

        merged_headers = dict(self._extra_headers)
        if headers:
            merged_headers.update(headers)

        t0 = time.monotonic()
        page = await self._context.new_page()
        if merged_headers:
            await page.set_extra_http_headers(merged_headers)

        status_code = 0
        final_url = url
        html_text = ""
        response_headers: dict[str, str] = {}
        try:
            response = await page.goto(
                _append_params(url, params), wait_until=wait_until, timeout=timeout,
            )
            if response is not None:
                status_code = response.status
                response_headers = {k.lower(): v for k, v in response.headers.items()}

            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=timeout)
                except Exception:
                    _LOG.info(
                        "playwright: selector %r never appeared on %s",
                        wait_for_selector, url,
                    )

            if wait_for_url_pattern:
                # For Queue-It-style: poll until the URL changes away from
                # the interstitial. We allow up to `timeout` total.
                start = time.monotonic()
                while time.monotonic() - start < timeout / 1000.0:
                    if wait_for_url_pattern in page.url:
                        break
                    await asyncio.sleep(2.0)
                else:
                    _LOG.info(
                        "playwright: queue/redirect on %s did not clear "
                        "within %.0fs (current URL: %s)",
                        url, timeout / 1000.0, page.url,
                    )

            final_url = page.url
            html_text = await page.content()
        finally:
            await page.close()

        duration_ms = int((time.monotonic() - t0) * 1000)
        return FetchResult(
            status=status_code or 200,
            url=final_url,
            text=html_text,
            bytes=len(html_text.encode("utf-8")),
            duration_ms=duration_ms,
            headers=response_headers,
            json=None,
        )

    # -- internals ------------------------------------------------------

    async def _fetch_via_api(
        self,
        url: str,
        *,
        method: str,
        params: dict[str, Any] | None,
        json_body: Any,
        headers: dict[str, str] | None,
        timeout: int,
    ) -> FetchResult:
        """Non-GET requests via `context.request` — keeps the browser TLS
        fingerprint without launching a full page render."""
        request_ctx = self._context.request
        merged_headers = dict(self._extra_headers)
        if headers:
            merged_headers.update(headers)
        t0 = time.monotonic()
        # Playwright's `APIRequestContext.fetch` accepts `data` (string /
        # bytes / dict for forms) but NOT a `json=` kwarg — the JSON body
        # has to be serialised manually with the right Content-Type.
        kwargs: dict[str, Any] = {
            "method": method,
            "params": params,
            "headers": merged_headers,
            "timeout": timeout,
        }
        if isinstance(json_body, (dict, list)):
            import json as _json
            kwargs["data"] = _json.dumps(json_body)
            kwargs["headers"] = {
                **merged_headers,
                "content-type": "application/json",
            }
        elif json_body is not None:
            kwargs["data"] = json_body
        resp = await request_ctx.fetch(url, **kwargs)
        body = await resp.text()
        duration_ms = int((time.monotonic() - t0) * 1000)
        # Best-effort JSON parse for application/json responses.
        json_obj: Any = None
        ct = resp.headers.get("content-type", "")
        if "json" in ct.lower():
            try:
                json_obj = await resp.json()
            except Exception:
                json_obj = None
        return FetchResult(
            status=resp.status,
            url=resp.url,
            text=body,
            bytes=len(body.encode("utf-8")),
            duration_ms=duration_ms,
            headers={k.lower(): v for k, v in resp.headers.items()},
            json=json_obj,
        )

    async def _inject_cookies(self, cookie_header: str) -> None:
        """Parse a `name=value; name2=value2; …` cookie string and inject
        each entry as a cookie on the context. Domain is left as `None`
        so Playwright derives it from the first navigation."""
        cookies = []
        for part in cookie_header.split(";"):
            kv = part.strip()
            if "=" not in kv:
                continue
            name, value = kv.split("=", 1)
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                # Domain set later (Playwright requires either domain or url).
                # We use the placeholder `.example.invalid` so add_cookies
                # validates; we'll re-add per-domain in the first navigation.
                "url": "https://example.invalid/",
            })
        if cookies and self._context is not None:
            # We can't add to example.invalid; instead, just stash the raw
            # cookie header to apply per-request via set_extra_http_headers.
            self._extra_headers.setdefault("Cookie", cookie_header)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _append_params(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    from urllib.parse import urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    qs_parts = [parsed.query] if parsed.query else []
    qs_parts.append(urlencode({k: v for k, v in params.items() if v is not None}))
    new_query = "&".join(p for p in qs_parts if p)
    return urlunparse(parsed._replace(query=new_query))
