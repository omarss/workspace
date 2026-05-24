"""Wuzzuf (wuzzuf.net) crawler.

Wuzzuf's public search page renders server-side. URL pattern:

    https://wuzzuf.net/search/jobs/?filters%5Bcountry%5D%5B0%5D=Saudi+Arabia
                                  &filters%5Bdate_post%5D%5B0%5D=last_30_days
                                  &start={page * page_size}

Each `<div class="css-1gatmva">` (or `.job-listing-card`) card carries the
title + detail URL. The per-job page renders the description.

Configured via JC_WUZZUF_QUERY (free-text keyword) and JC_WUZZUF_MAX_PAGES.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Final
from urllib.parse import urlencode, urljoin

from selectolax.parser import HTMLParser

from job_crawler_db import (
    ApplicationChannelKind,
    EmploymentType,
    SourceKind,
    WorkArrangement,
)

from ..core.base import BaseCrawler
from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_LOG: Final = logging.getLogger("job_crawler.wuzzuf")


class WuzzufCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "wuzzuf"
    source_display_name: ClassVar[str] = "Wuzzuf"
    source_kind: ClassVar[SourceKind] = SourceKind.regional_board
    source_base_url: ClassVar[str] = "https://wuzzuf.net"
    source_trust_weight: ClassVar[float] = 0.55
    rate: ClassVar[RateConfig] = RateConfig(max_rps=3.0, burst=6, max_concurrent=3, timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA)
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://wuzzuf.net/search/jobs/?filters%5Bcountry%5D%5B0%5D=Saudi+Arabia",
    )

    PAGE_SIZE: ClassVar[int] = 15  # Wuzzuf default

    # Selectors centralised. Wuzzuf is built with Emotion CSS (hashed class
    # names like `css-1gatmva`); we match on a *stable* combination of
    # structural selectors + the `href` pattern of the title link.
    PARSE_SELECTORS: ClassVar[dict[str, str]] = {
        "card_link":     "a[href*='/jobs/p/'], a[href*='/jobs/']",
        "detail_title":  "h1, h2.css-f9uh36",
        "detail_company": "a[href*='/jobs/at/'], a.css-17s97q8",
        "detail_loc":    "span[data-test='job-location'], .css-1jldrwd",
        "detail_body":   "div[data-test='job-details'], section.css-1xeoq57",
        "apply_link":    "a[href*='/apply/'], a.css-1ye0xfz",
    }
    _ID_FROM_URL_RE: ClassVar[re.Pattern[str]] = re.compile(r"/jobs/p/([^/?#]+)")

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        max_pages = int(os.environ.get("JC_WUZZUF_MAX_PAGES", "40"))
        query = os.environ.get("JC_WUZZUF_QUERY", "").strip()

        seen: set[str] = set()
        for page in range(max_pages):
            url = self._search_url(page=page, query=query)
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("wuzzuf page %d fetch failed: %s", page, exc)
                break
            tree = HTMLParser(result.text)
            anchors = tree.css(self.PARSE_SELECTORS["card_link"])
            if not anchors:
                _LOG.info("wuzzuf: no cards on page %d", page)
                break
            yielded_this_page = 0
            for a in anchors:
                href = a.attributes.get("href") or ""
                m = self._ID_FROM_URL_RE.search(href)
                if not m:
                    continue
                external_id = m.group(1)
                if external_id in seen:
                    continue
                seen.add(external_id)
                yielded_this_page += 1
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=urljoin(self.source_base_url, href),
                )
            if yielded_this_page == 0:
                break

    def _search_url(self, *, page: int, query: str) -> str:
        params = {
            "filters[country][0]": "Saudi Arabia",
            "filters[date_post][0]": "last_30_days",
        }
        if query:
            params["q"] = query
        if page > 0:
            params["start"] = page * self.PAGE_SIZE
        return f"{self.source_base_url}/search/jobs/?{urlencode(params)}"

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
                raw_label=apply_node.text(strip=True) or "Apply on Wuzzuf",
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

        external_id = raw.listing.source_job_external_id
        return ParsedPosting(
            source_job_external_id=external_id,
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
            raw_payload={"source": "wuzzuf", "html_bytes": len(html)},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, city_id=None,
        )


# ---- helpers --------------------------------------------------------------
_REL_TIME_RE = re.compile(
    r"(\d+)\s*(minute|hour|day|week|month)s?\s*ago", re.IGNORECASE,
)


def _extract_posted_at(html: str) -> datetime | None:
    m = _REL_TIME_RE.search(html)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = {
        "minute": timedelta(minutes=n),
        "hour":   timedelta(hours=n),
        "day":    timedelta(days=n),
        "week":   timedelta(weeks=n),
        "month":  timedelta(days=n * 30),
    }.get(unit, timedelta())
    return datetime.now(UTC) - delta


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


_ = BaseCrawler
