"""Indeed (sa.indeed.com) crawler.

⚠️ Anti-bot reality: Indeed enforces a strict server-side bot wall on every
anonymous request. Even with `curl_cffi` chrome impersonation we receive a
`Security Check` page (HTTP 403) instead of listings. Mobile UA, RSS feed,
and the API JSON shape are all gated by the same wall.

The crawler is implemented end-to-end against the published `/jobs` SSR
shape — when residential proxies (or a session cookie captured from a real
browser via `JC_INDEED_COOKIE`) become available, it will start returning
results. Until then expect `fetched > 0, parsed = 0`.

Configured via:
    JC_INDEED_QUERY      — search keywords (default "")
    JC_INDEED_LOCATION   — location filter (default "Saudi Arabia")
    JC_INDEED_MAX_PAGES  — pages (default 20)
    JC_INDEED_COOKIE     — full cookie header captured from a browser
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import ClassVar, Final
from urllib.parse import urlencode, urljoin

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

_LOG: Final = logging.getLogger("job_crawler.indeed")


class IndeedCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "indeed"
    source_display_name: ClassVar[str] = "Indeed"
    source_kind: ClassVar[SourceKind] = SourceKind.aggregator
    source_base_url: ClassVar[str] = "https://sa.indeed.com"
    source_trust_weight: ClassVar[float] = 0.70
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=1.0, burst=2, max_concurrent=2,
        timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://sa.indeed.com/jobs?l=Saudi+Arabia",
    )
    # Playwright headless Chromium — defeats Indeed's TLS + behavioural
    # fingerprinting that 403s curl_cffi requests. IP-throttling still
    # applies; pair with `use_proxy_pool` once residential proxies are
    # wired in.
    use_playwright: ClassVar[bool] = True
    use_proxy_pool: ClassVar[bool] = False
    requires_gcc_location: ClassVar[bool] = True

    _CARD_RE: ClassVar[re.Pattern[str]] = re.compile(r'data-jk="([^"]+)"')

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        query = os.environ.get("JC_INDEED_QUERY", "").strip()
        location = os.environ.get("JC_INDEED_LOCATION", "Saudi Arabia").strip()
        max_pages = int(os.environ.get("JC_INDEED_MAX_PAGES", "20"))
        cookie = os.environ.get("JC_INDEED_COOKIE", "").strip()

        headers: dict[str, str] = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.7",
        }
        if cookie:
            headers["Cookie"] = cookie

        seen: set[str] = set()
        for page in range(max_pages):
            url = self._search_url(query=query, location=location, page=page)
            try:
                result = await self.http.fetch(url, headers=headers)
            except Exception as exc:
                _LOG.warning("indeed search page %d failed: %s", page, exc)
                break
            html = result.text or ""
            if not html or result.status >= 400 or "Security Check" in html:
                _LOG.info(
                    "indeed: status=%s on page %d (bot wall or empty); stopping",
                    result.status, page,
                )
                break
            ids = set(self._CARD_RE.findall(html))
            new_ids = ids - seen
            if not new_ids:
                _LOG.info("indeed: no new IDs on page %d, stopping", page)
                break
            seen.update(new_ids)
            for jk in new_ids:
                detail_url = f"{self.source_base_url}/viewjob?jk={jk}"
                yield Listing(
                    source_job_external_id=jk,
                    detail_url=detail_url,
                )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str) or not html:
            return None
        if "Security Check" in html or "<title>Just a moment" in html:
            return None

        ld = extract_job_posting(html)
        tree = HTMLParser(html)
        title = (ld.title if ld else None) or _txt(
            tree.css_first("h1.jobsearch-JobInfoHeader-title, h1"),
        )
        if not title:
            return None
        m = re.search(r"jk=([^&]+)", raw.canonical_url)
        if not m:
            return None
        external_id = m.group(1)

        body_node = tree.css_first("#jobDescriptionText, div.jobsearch-jobDescriptionText")
        description_html = body_node.html if body_node else None
        description = (ld.description if ld else None) or (
            _txt(body_node) if body_node else None
        )
        raw_company_name = (
            (ld.company_name if ld else None)
            or _txt(tree.css_first(
                "a[data-tn-element='companyName'], "
                ".jobsearch-CompanyInfoWithoutHeaderImage div",
            ))
            or None
        )
        raw_location = _join_location(ld) or _txt(
            tree.css_first(
                "[data-testid='inlineHeader-companyLocation'], "
                ".jobsearch-JobInfoHeader-subtitle",
            ),
        ) or None

        channels: list[ApplicationChannelRaw] = [
            ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=raw.canonical_url,
                is_primary=True,
                raw_label="Apply on Indeed",
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
            raw_payload={"source": "indeed"},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, location=None,
        )

    # ------------------------------------------------------------------
    def _search_url(self, *, query: str, location: str, page: int) -> str:
        params: dict[str, str] = {"l": location, "fromage": "30"}
        if query:
            params["q"] = query
        if page:
            params["start"] = str(page * 10)
        return urljoin(self.source_base_url, "/jobs?" + urlencode(params))


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
