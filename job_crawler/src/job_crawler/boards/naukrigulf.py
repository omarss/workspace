"""Naukrigulf (naukrigulf.com) crawler — Saudi Arabia + Gulf coverage.

Naukrigulf renders search results server-side. Public URL pattern:

    https://www.naukrigulf.com/jobs-in-saudi-arabia?postedWithin=30

Each `<article class="ng-box">` card carries the title + detail URL +
location. The per-job page has the description and apply CTA.

Configured via JC_NAUKRI_QUERY (free-text keyword) and JC_NAUKRI_MAX_PAGES.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Final
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from job_crawler_db import (
    ApplicationChannelKind,
    EmploymentType,
    SourceKind,
    WorkArrangement,
)

from ..core.base import BaseCrawler
from ..core.config import RateConfig
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_LOG: Final = logging.getLogger("job_crawler.naukrigulf")


class NaukrigulfCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "naukrigulf"
    source_display_name: ClassVar[str] = "Naukrigulf"
    source_kind: ClassVar[SourceKind] = SourceKind.regional_board
    source_base_url: ClassVar[str] = "https://www.naukrigulf.com"
    source_trust_weight: ClassVar[float] = 0.55
    # Naukrigulf also fingerprints at TLS+HTTP/2 (same pattern as Bayt).
    # curl_cffi Chrome impersonation gets through; the HTTP/2 reset goes
    # away because the impersonated stream matches Chrome's frame layout.
    impersonate_browser: ClassVar[str] = "chrome"
    rate: ClassVar[RateConfig] = RateConfig(max_rps=2.0, burst=4, max_concurrent=3, timeout_seconds=30.0, user_agent=None)
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://www.naukrigulf.com/jobs-in-saudi-arabia",
    )
    PARSE_SELECTORS: ClassVar[dict[str, str]] = {
        "result_card":   "article.ng-box, div.ng-box, article[data-id]",
        "result_link":   "a.info, a.designation-title, h2 a, h3 a",
        "result_loc":    ".loc, .location",
        "result_posted": ".time, .posted",
        "detail_title":  "h1.title, h1.designation, .designation-title",
        "detail_company": ".company a, .company-name",
        "detail_loc":    ".loc, .location",
        "detail_body":   "#description, .job-description, .job-detail",
        "apply_link":    "a.apply-button, a#applyBtn, a.btn-apply",
    }

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        max_pages = int(os.environ.get("JC_NAUKRI_MAX_PAGES", "40"))
        query = os.environ.get("JC_NAUKRI_QUERY", "").strip()
        for page in range(1, max_pages + 1):
            url = self._search_url(page=page, query=query)
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("naukrigulf page %d fetch failed: %s", page, exc)
                break
            tree = HTMLParser(result.text)
            cards = tree.css(self.PARSE_SELECTORS["result_card"])
            if not cards:
                _LOG.info("naukrigulf: no cards on page %d (selectors stale?)", page)
                break
            for card in cards:
                link_node = card.css_first(self.PARSE_SELECTORS["result_link"])
                if link_node is None:
                    continue
                href = link_node.attributes.get("href")
                if not href:
                    continue
                detail_url = urljoin(self.source_base_url, href)
                yield Listing(
                    source_job_external_id=_external_id_from_url(detail_url),
                    detail_url=detail_url,
                )

    def _search_url(self, *, page: int, query: str) -> str:
        path = "/jobs-in-saudi-arabia"
        if query:
            keyword = query.lower().replace(" ", "-")
            path = f"/{keyword}-jobs-in-saudi-arabia"
        suffix = "?postedWithin=30"
        if page > 1:
            suffix += f"&pageNo={page}"
        return f"{self.source_base_url}{path}{suffix}"

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str):
            return None
        tree = HTMLParser(html)

        title_node = tree.css_first(self.PARSE_SELECTORS["detail_title"])
        if title_node is None:
            return None
        title = title_node.text(strip=True)

        company_node = tree.css_first(self.PARSE_SELECTORS["detail_company"])
        loc_node = tree.css_first(self.PARSE_SELECTORS["detail_loc"])
        body_node = tree.css_first(self.PARSE_SELECTORS["detail_body"])
        apply_node = tree.css_first(self.PARSE_SELECTORS["apply_link"])

        raw_company_name = company_node.text(strip=True) if company_node else None
        raw_location = loc_node.text(strip=True) if loc_node else None
        description_html = body_node.html if body_node else None
        description = body_node.text(separator="\n", strip=True) if body_node else None

        channels: list[ApplicationChannelRaw] = []
        if apply_node is not None:
            href = apply_node.attributes.get("href") or ""
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=urljoin(self.source_base_url, href) if href else raw.canonical_url,
                is_primary=True,
                raw_label=apply_node.text(strip=True) or "Apply on Naukrigulf",
            ))

        posted_at = _extract_posted_at(html)

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("raw_company_name", raw_company_name),
            ("raw_location", raw_location),
            ("description", description),
        ):
            (parsed_fields if value else missing_fields).add(name)

        return ParsedPosting(
            source_job_external_id=_external_id_from_url(raw.canonical_url),
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=posted_at,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            employment_type=EmploymentType.full_time,
            work_arrangement=_arrangement(raw_location, description),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "naukrigulf", "html_bytes": len(html)},
        )
# ---- helpers --------------------------------------------------------------
_DAYS_AGO_RE = re.compile(r"(\d+)\s*(day|hour|minute|month)s?\s*ago", re.IGNORECASE)
_ID_FROM_URL_RE = re.compile(r"-(\d+)$|/(\d+)$|/(\d+)\.")


def _external_id_from_url(url: str) -> str:
    m = _ID_FROM_URL_RE.search(url.rstrip("/"))
    if m:
        return next(g for g in m.groups() if g)
    return url


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    return raw_location.split(",")[0].strip() or None


def _arrangement(loc: str | None, desc: str | None) -> WorkArrangement | None:
    blob = " ".join(x for x in (loc, desc) if x).lower()
    if not blob:
        return None
    if "remote" in blob:
        return WorkArrangement.remote
    if "hybrid" in blob:
        return WorkArrangement.hybrid
    return WorkArrangement.onsite


def _extract_posted_at(html: str) -> datetime | None:
    m = _DAYS_AGO_RE.search(html)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = {
        "minute": timedelta(minutes=n),
        "hour":   timedelta(hours=n),
        "day":    timedelta(days=n),
        "month":  timedelta(days=n * 30),
    }.get(unit, timedelta())
    return datetime.now(UTC) - delta


_ = BaseCrawler
