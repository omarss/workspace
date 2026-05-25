"""Glassdoor (glassdoor.com) crawler.

⚠️ Anti-bot reality: Glassdoor is a Next.js SPA — the initial HTML
contains no listings, all data is fetched via an internal GraphQL endpoint
that demands a CSRF token + a session cookie. With `curl_cffi` chrome
impersonation we *can* reach the home page (200 instead of 403) but the
listings page hydrates client-side, so we get an empty shell.

The crawler is implemented end-to-end against the SSR fallback shape and
honours an optional `JC_GLASSDOOR_COOKIE` env var. With a real browser
session captured into that cookie, the SSR fallback fires and we get
postings. Without it, expect `fetched > 0, parsed = 0`.

Configured via:
    JC_GLASSDOOR_LOCATION_ID  — Glassdoor location id (default 191 = SA)
    JC_GLASSDOOR_MAX_PAGES    — pages (default 20)
    JC_GLASSDOOR_COOKIE       — full cookie header captured from a browser
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import ClassVar, Final
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from job_crawler_db import (
    ApplicationChannelKind,
    SourceKind,
)

from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.jsonld import JobPostingLD, extract_job_posting
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_LOG: Final = logging.getLogger("job_crawler.glassdoor")


class GlassdoorCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "glassdoor"
    source_display_name: ClassVar[str] = "Glassdoor"
    source_kind: ClassVar[SourceKind] = SourceKind.aggregator
    source_base_url: ClassVar[str] = "https://www.glassdoor.com"
    source_trust_weight: ClassVar[float] = 0.65
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=1.0, burst=2, max_concurrent=2,
        timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://www.glassdoor.com/Job/saudi-arabia-jobs-SRCH_IL.0,12_IN191.htm",
    )
    # Glassdoor is a Next.js SPA — listings hydrate client-side, so a
    # raw HTML fetch returns an empty shell. Playwright lets Chrome run
    # the JS so we see the same DOM a human would.
    use_playwright: ClassVar[bool] = True
    use_proxy_pool: ClassVar[bool] = False
    requires_gcc_location: ClassVar[bool] = True

    _CARD_RE: ClassVar[re.Pattern[str]] = re.compile(
        r'data-job-id="([^"]+)"|/partner/jobListing\.htm\?jobListingId=(\d+)',
    )

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        location_id = os.environ.get("JC_GLASSDOOR_LOCATION_ID", "191").strip()
        max_pages = int(os.environ.get("JC_GLASSDOOR_MAX_PAGES", "20"))
        cookie = os.environ.get("JC_GLASSDOOR_COOKIE", "").strip()

        headers: dict[str, str] = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if cookie:
            headers["Cookie"] = cookie

        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            url = self._search_url(location_id=location_id, page=page)
            try:
                result = await self.http.fetch(url, headers=headers)
            except Exception as exc:
                _LOG.warning("glassdoor search page %d failed: %s", page, exc)
                break
            html = result.text or ""
            if not html or result.status >= 400:
                _LOG.info(
                    "glassdoor: status=%s on page %d, stopping",
                    result.status, page,
                )
                break
            # Glassdoor SPA returns 0 jobs in initial HTML without a real
            # cookie. Detect that and bail cleanly.
            ids_found = set()
            for m in self._CARD_RE.finditer(html):
                ids_found.add(m.group(1) or m.group(2))
            ids_found.discard(None)
            new_ids = ids_found - seen
            if not new_ids:
                if page == 1:
                    _LOG.info(
                        "glassdoor: no IDs on first page — likely SPA-hydrated "
                        "without a valid session cookie; stopping",
                    )
                break
            seen.update(new_ids)
            for jid in new_ids:
                detail_url = (
                    f"{self.source_base_url}/partner/jobListing.htm?jobListingId={jid}"
                )
                yield Listing(
                    source_job_external_id=jid,
                    detail_url=detail_url,
                )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str) or not html:
            return None

        ld = extract_job_posting(html)
        tree = HTMLParser(html)
        title = (ld.title if ld else None) or _txt(
            tree.css_first("h1[data-test='job-title'], h1.JobDetails_jobTitle"),
        )
        if not title:
            return None
        m = re.search(r"jobListingId=(\d+)", raw.canonical_url)
        if not m:
            return None
        external_id = m.group(1)

        body_node = tree.css_first(
            "[data-test='jobDescriptionText'], div.JobDetails_jobDescription",
        )
        description = (ld.description if ld else None) or (
            _txt(body_node) if body_node else None
        )
        description_html = body_node.html if body_node else None
        raw_company_name = (
            (ld.company_name if ld else None)
            or _txt(tree.css_first(
                "[data-test='employer-name'], .EmployerProfile_employerName",
            ))
            or None
        )
        raw_location = _join_location(ld) or _txt(
            tree.css_first("[data-test='location'], .JobDetails_location"),
        ) or None

        channels: list[ApplicationChannelRaw] = [
            ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=raw.canonical_url,
                is_primary=True,
                raw_label="Apply on Glassdoor",
            ),
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
            description_html=description_html,
            raw_company_name=raw_company_name,
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            country_code="sa",
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "glassdoor"},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, city_id=None,
        )

    # ------------------------------------------------------------------
    def _search_url(self, *, location_id: str, page: int) -> str:
        # Glassdoor's "SRCH_IL.0,12_IN{id}.htm" pattern is the SA listing.
        # Pagination uses `_IP{N}.htm` appended.
        base = f"/Job/saudi-arabia-jobs-SRCH_IL.0,12_IN{location_id}"
        path = f"{base}_IP{page}.htm" if page > 1 else f"{base}.htm"
        return urljoin(self.source_base_url, path)


# ---- helpers --------------------------------------------------------------
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
