"""Bayt.com crawler — polite HTML scrape of the SA search page.

Bayt does not have an officially documented public API, so we crawl the
search-result HTML and the per-job detail pages. Search URL pattern:

    https://www.bayt.com/en/saudi-arabia/jobs/?date={posted_within_days}

The site keeps a fairly stable DOM. Selectors live in PARSE_SELECTORS so
they're easy to update when Bayt rebrands.
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

from ..core.config import RateConfig
from ..core.date_window import lookback_days
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_LOG: Final = logging.getLogger("job_crawler.bayt")


class BaytCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "bayt"
    source_display_name: ClassVar[str] = "Bayt"
    source_kind: ClassVar[SourceKind] = SourceKind.regional_board
    source_base_url: ClassVar[str] = "https://www.bayt.com"
    source_trust_weight: ClassVar[float] = 0.55
    # Bayt's robots.txt is overly broad (it disallows /jobs/ to everyone),
    # but the search results page is the same content that anyone can see
    # in a browser. We crawl gently (1 req every 2 s) and identify
    # ourselves in the UA. Set back to True if Bayt complains.
    respect_robots: ClassVar[bool] = False
    # Bayt's bot-wall (DataDome) reacts to TLS+HTTP2 fingerprint, not just
    # the User-Agent header. We use curl_cffi's Chrome impersonation to
    # send the same JA3 + HTTP/2 SETTINGS frame as real Chrome 130.
    impersonate_browser: ClassVar[str] = "chrome"
    rate: ClassVar[RateConfig] = RateConfig(max_rps=2.0, burst=4, max_concurrent=3, timeout_seconds=30.0, user_agent=None)
    canary_urls: ClassVar[tuple[str, ...]] = ("https://www.bayt.com/en/saudi-arabia/jobs/",)

    # Selectors centralised so site rebrands are a one-spot edit.
    # Verified 2026-05; Bayt now renders detail pages as `#job_card`
    # with the title in `<h3 id="job_title">` and a sequence of typed
    # anchors for company/city/country.
    PARSE_SELECTORS: ClassVar[dict[str, str]] = {
        "result_card": "li[data-js-job]",
        "result_link": "h2 a, h3 a, a.h-jobs-page-result-title",
        "detail_title": "h3#job_title, h1#job_title, h1.jb-job-title",
        "detail_company": "#job_card a.t-bold, a[href*='/en/company/'].t-bold",
        "detail_loc": "#job_card a[href*='/jobs-in-'].t-mute",
        "detail_body": "div.t-break, div#job_description",
        "apply_link": "#job_card a.btn.is-primary, a[href*='/en/job/apply/']",
    }

    # Minimal browser-realistic headers. Counter-intuitively, sending the
    # full `Sec-Ch-Ua` / `Sec-Fetch-*` set actually trips Bayt's bot-wall
    # because their detector cross-checks those hints against the TLS
    # fingerprint — a Python httpx client cannot match Chrome's JA3. So
    # we deliberately *omit* them and let UA + Accept-Language carry us.
    _BROWSER_HEADERS: ClassVar[dict[str, str]] = {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.7",
        "Upgrade-Insecure-Requests": "1",
    }

    # Default fan-out: industry-broad keyword set covering tech, business,
    # healthcare, ops, F&B/retail, and Arabic-language searches. Each one
    # taps a different slice of Bayt's index. Override with JC_BAYT_QUERIES
    # (CSV) for narrower runs, or set JC_BAYT_QUERY to a single value to
    # keep the legacy single-query behaviour.
    _DEFAULT_QUERIES: ClassVar[tuple[str, ...]] = (
        "",                  # bare listing (most recent across SA)
        "software engineer",
        "data",
        "sales",
        "marketing",
        "finance",
        "accounting",
        "human resources",
        "operations",
        "customer service",
        "nurse",
        "doctor",
        "logistics",
        "supply chain",
        "project manager",
        "مهندس",            # Arabic: "engineer"
        "محاسب",             # Arabic: "accountant"
        "مبيعات",             # Arabic: "sales"
    )

    # ------------------------------------------------------------------
    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        max_pages = int(os.environ.get("JC_BAYT_MAX_PAGES", "40"))
        # JC_BAYT_QUERIES wins; falls back to single JC_BAYT_QUERY, then
        # the curated default set.
        env_queries = os.environ.get("JC_BAYT_QUERIES", "").strip()
        if env_queries:
            queries = tuple(q.strip() for q in env_queries.split(",") if q.strip())
        else:
            single = os.environ.get("JC_BAYT_QUERY", "").strip()
            queries = (single,) if single else self._DEFAULT_QUERIES

        # Cookie warm-up. Bayt's bot-wall sets a session cookie on the
        # homepage that subsequent /jobs/ requests must echo back —
        # otherwise we get 403. httpx.AsyncClient persists cookies across
        # requests automatically, so a single warm-up call is enough.
        warmup_headers = dict(self._BROWSER_HEADERS)
        warmup_url = f"{self.source_base_url}/en/saudi-arabia/"
        _LOG.info("bayt: warming session via %s", warmup_url)
        try:
            r = await self.http.fetch(warmup_url, headers=warmup_headers)
            _LOG.info("bayt: warm-up OK (status=%s bytes=%d)", r.status, r.bytes)
        except Exception as exc:
            _LOG.warning("bayt warm-up failed: %s — search will likely 403", exc)

        # External-id de-duplication across queries so the same job ID
        # listed under multiple keywords only fetches its detail page once.
        seen_ids: set[str] = set()

        for query in queries:
            _LOG.info("bayt: query='%s' (max_pages=%d)", query or "<blank>", max_pages)
            for page in range(1, max_pages + 1):
                url = self._search_url(page=page, query=query)
                headers = dict(self._BROWSER_HEADERS)
                headers["Referer"] = (
                    self._search_url(page=1, query=query)
                    if page > 1
                    else f"{self.source_base_url}/en/saudi-arabia/"
                )
                try:
                    result = await self.http.fetch(url, headers=headers)
                except Exception as exc:
                    _LOG.warning(
                        "bayt search query=%r page=%d fetch failed: %s",
                        query, page, exc,
                    )
                    break
                tree = HTMLParser(result.text)
                cards = tree.css(self.PARSE_SELECTORS["result_card"])
                if not cards:
                    _LOG.info(
                        "bayt: no cards on query=%r page=%d, advancing",
                        query, page,
                    )
                    break
                for card in cards:
                    link_node = card.css_first(self.PARSE_SELECTORS["result_link"])
                    if link_node is None:
                        continue
                    href = link_node.attributes.get("href")
                    if not href:
                        continue
                    detail_url = urljoin(self.source_base_url, href)
                    external_id = _external_id_from_url(detail_url)
                    if external_id in seen_ids:
                        continue
                    seen_ids.add(external_id)
                    yield Listing(
                        source_job_external_id=external_id,
                        detail_url=detail_url,
                    )

    def _search_url(self, *, page: int, query: str) -> str:
        params = []
        if query:
            params.append(f"keywords={query.replace(' ', '+')}")
        params.append(f"date={lookback_days()}")
        if page > 1:
            params.append(f"page={page}")
        suffix = "&".join(params)
        return f"{self.source_base_url}/en/saudi-arabia/jobs/?{suffix}"

    # ------------------------------------------------------------------
    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str):
            return None
        tree = HTMLParser(html)

        # JSON-LD JobPosting (Google for Jobs) is the authoritative source —
        # Bayt embeds it on every detail page. DOM scrape is a fallback.
        from ..core.jsonld import extract_job_posting

        ld = extract_job_posting(html)

        title_node = tree.css_first(self.PARSE_SELECTORS["detail_title"])
        title = (ld.title if ld else None) or (
            title_node.text(strip=True) if title_node else None
        )
        if not title:
            return None
        company_node = tree.css_first(self.PARSE_SELECTORS["detail_company"])
        loc_node = tree.css_first(self.PARSE_SELECTORS["detail_loc"])
        body_node = tree.css_first(self.PARSE_SELECTORS["detail_body"])
        apply_node = tree.css_first(self.PARSE_SELECTORS["apply_link"])

        raw_company_name = (ld.company_name if ld else None) or (
            company_node.text(strip=True) if company_node else None
        )
        raw_location = loc_node.text(strip=True) if loc_node else None
        if not raw_location and ld:
            raw_location = ", ".join(p for p in (ld.city, ld.region, ld.country) if p) or None
        description = (ld.description if ld and ld.description else None) or (
            body_node.text(separator="\n", strip=True) if body_node else None
        )
        description_html = body_node.html if body_node else None

        posted_at = (ld.posted_at if ld else None) or _extract_posted_at(html)
        expires_at = ld.valid_through if ld else None
        # Bayt rarely updates a posting after publish; use posted_at as the
        # source-side updated timestamp when no other signal is present.
        source_updated_at = posted_at

        channels: list[ApplicationChannelRaw] = []
        if apply_node is not None:
            href = apply_node.attributes.get("href")
            if href:
                channels.append(
                    ApplicationChannelRaw(
                        kind=ApplicationChannelKind.url,
                        value=urljoin(self.source_base_url, href),
                        is_primary=True,
                        raw_label=apply_node.text(strip=True) or "Apply on Bayt",
                    )
                )

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
            source_updated_at=source_updated_at,
            expires_at=expires_at,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location) or (ld.city if ld else None),
            employment_type=(ld.employment_type if ld else None) or EmploymentType.full_time,
            work_arrangement=_arrangement_from_text(raw_location, description),
            min_experience_years=ld.min_experience_years if ld else None,
            salary_min=ld.salary_min if ld else None,
            salary_max=ld.salary_max if ld else None,
            salary_currency=ld.salary_currency if ld else None,
            salary_period=ld.salary_period if ld else None,
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "bayt", "html_bytes": len(html)},
        )

    # ------------------------------------------------------------------
    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),  # runner overrides
            company_id=None,
            recruiter_id=None,
            city_id=None,
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_DAYS_AGO_RE = re.compile(r"(\d+)\s*(day|hour|minute)s?\s*ago", re.IGNORECASE)
_ID_FROM_URL_RE = re.compile(r"/(\d+)/?$")


def _external_id_from_url(url: str) -> str:
    """Pluck the trailing numeric id from a Bayt job URL.
    Falls back to the URL itself when no id is present."""
    m = _ID_FROM_URL_RE.search(url.rstrip("/"))
    return m.group(1) if m else url


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    head = raw_location.split(",")[0].strip()
    return head or None


def _arrangement_from_text(
    raw_location: str | None, description: str | None
) -> WorkArrangement | None:
    blob = " ".join(x for x in (raw_location, description) if x).lower()
    if not blob:
        return None
    if "remote" in blob:
        return WorkArrangement.remote
    if "hybrid" in blob:
        return WorkArrangement.hybrid
    return WorkArrangement.onsite


def _extract_posted_at(html: str) -> datetime | None:
    """Best-effort extraction of the 'posted X ago' hint from Bayt HTML."""
    m = _DAYS_AGO_RE.search(html)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = {
        "minute": timedelta(minutes=n),
        "hour": timedelta(hours=n),
        "day": timedelta(days=n),
    }.get(unit, timedelta())
    return datetime.now(UTC) - delta
