"""Jadarat (jadarat.sa) crawler — KSA government job portal.

Jadarat is the official Saudi Ministry of Labor jobs portal.

⚠️ Anti-bot reality: every anonymous request to jadarat.sa is redirected
through Queue-It (queueittoken=…) which is an enterprise virtual-queue
system. Without solving the queue (either by acquiring a valid token via
manual browser session or paying for residential routing) the crawler
yields nothing.

The code path is implemented against the most plausible API endpoint
shape (Next.js JSON API). When a session cookie / queue-token becomes
available (set JC_JADARAT_COOKIE env var), the crawler will start
returning results.

Configured via:
    JC_JADARAT_COOKIE         — cookie string captured from a real browser
    JC_JADARAT_MAX_PAGES      — pagination cap (default 10)
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar, Final

from job_crawler_db import (
    ApplicationChannelKind,
    SourceKind,
)

from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.jsonld import JobPostingLD
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_IDS_FROM_HTML_RE: Final = re.compile(r"JobID=([A-Za-z0-9_-]+)")


def _ids_from_html(html: str) -> set[str]:
    return set(_IDS_FROM_HTML_RE.findall(html))


def _txt(node: object) -> str:
    if node is None:
        return ""
    text = node.text(separator=" ", strip=True) if hasattr(node, "text") else ""
    return re.sub(r"\s+", " ", text or "").strip()


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    head = raw_location.split(",")[0].strip()
    return head or None


def _join_location(ld: JobPostingLD | None) -> str | None:
    if ld is None:
        return None
    parts = [p for p in (ld.city, ld.region, ld.country) if p]
    return ", ".join(parts) if parts else None

_LOG: Final = logging.getLogger("job_crawler.jadarat")


class JadaratCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "jadarat"
    source_display_name: ClassVar[str] = "Jadarat (KSA Gov)"
    source_kind: ClassVar[SourceKind] = SourceKind.gov_board
    source_base_url: ClassVar[str] = "https://jadarat.sa"
    source_trust_weight: ClassVar[float] = 0.98  # gov source — authoritative
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=0.3, burst=1, max_concurrent=1,
        # Queue-It releases on its own schedule; give Chromium up to 4 min
        # per request to sit through the queue.
        timeout_seconds=240.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://jadarat.sa/JobSearch",
    )
    # Playwright headless Chromium — sits through the Queue-It interstitial
    # on its own (no need for a captured cookie) by waiting for the URL to
    # drop the `queueittoken=` parameter. See `_LISTING_URL` below.
    use_playwright: ClassVar[bool] = True

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        # Playwright sits through Queue-It automatically: we navigate to
        # /JobSearch and wait for the URL to no longer contain the queue
        # token. After release the SPA hydrates and exposes job cards.
        max_pages = int(os.environ.get("JC_JADARAT_MAX_PAGES", "10"))
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            url = f"{self.source_base_url}/JobSearch?pageno={page}"
            try:
                result = await self.http.fetch(  # type: ignore[call-arg]
                    url,
                    wait_for_url_pattern="/JobSearch",
                    wait_for_selector="a[href*='JobID'], [data-testid='job-card']",
                )
            except Exception as exc:
                _LOG.warning("jadarat page %d failed: %s", page, exc)
                break
            if "queueittoken" in (result.url or ""):
                _LOG.warning(
                    "jadarat: Queue-It did not release within timeout on page %d",
                    page,
                )
                break
            # Extract jobId-bearing hrefs from the hydrated DOM.
            ids = _ids_from_html(result.text or "")
            new_ids = ids - seen
            if not new_ids:
                _LOG.info("jadarat: no new IDs on page %d, stopping", page)
                break
            seen.update(new_ids)
            for jid in new_ids:
                detail_url = f"{self.source_base_url}/JobDetails?JobID={jid}"
                yield Listing(
                    source_job_external_id=jid,
                    detail_url=detail_url,
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        # Playwright path: navigate to the detail URL, wait for the
        # Queue-It interstitial to release, return the hydrated HTML.
        try:
            result = await self.http.fetch(  # type: ignore[call-arg]
                listing.detail_url,
                wait_for_url_pattern="/JobDetails",
                wait_for_selector="h1, [data-testid='job-title']",
            )
        except Exception:
            return None
        return RawPosting(
            listing=listing,
            canonical_url=result.url,
            payload={"html": result.text},
            fetched_at=datetime.now(UTC),
            duration_ms=result.duration_ms,
            http_status=result.status,
            bytes=result.bytes,
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        from selectolax.parser import HTMLParser

        from ..core.jsonld import extract_job_posting

        html = raw.payload.get("html")
        if not isinstance(html, str) or not html:
            return None

        ld = extract_job_posting(html)
        tree = HTMLParser(html)

        # External id from the URL (most reliable across DOM shapes).
        m = re.search(r"JobID=([^&]+)", raw.canonical_url)
        if not m:
            return None
        external_id = m.group(1)

        title = (ld.title if ld else None) or _txt(
            tree.css_first("h1, [data-testid='job-title']"),
        )
        if not title:
            return None

        description = (ld.description if ld else None) or _txt(
            tree.css_first(
                "[data-testid='job-description'], "
                ".job-description, .description, article, main",
            ),
        )

        raw_company_name = (ld.company_name if ld else None) or _txt(
            tree.css_first(
                "[data-testid='company-name'], .company-name, "
                "a[href*='company']",
            ),
        ) or None

        raw_location = _join_location(ld) or _txt(
            tree.css_first(
                "[data-testid='job-location'], .location, .region",
            ),
        ) or None

        channels: list[ApplicationChannelRaw] = [
            ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=raw.canonical_url,
                is_primary=True,
                raw_label="Apply on Jadarat",
            )
        ]

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
            ("raw_company_name", raw_company_name),
        ):
            (parsed_fields if value else missing_fields).add(name)

        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=(ld.posted_at if ld else None),
            source_updated_at=(ld.posted_at if ld else None),
            expires_at=(ld.valid_through if ld else None),
            description=description,
            raw_company_name=raw_company_name,
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            country_code="sa",
            # Jadarat lists only KSA-nationals jobs by design.
            saudi_nationals_only=True,
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "jadarat"},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, location=None,
        )


# ---- helpers --------------------------------------------------------------
def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:len(fmt) - 2 + 4], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    # Try ISO with offset
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    except ValueError:
        return None
