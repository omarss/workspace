"""LinkedIn guest-API crawler (no login, no Playwright).

LinkedIn exposes an unauthenticated guest endpoint that returns
server-rendered HTML cards. It's stable enough for personal-scale
crawling but rate-limited per IP, so we move slowly and respect 429s.

Search:
    https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
      ?keywords={kw}&location={loc}&geoId=106155005    # Saudi Arabia
      &f_TPR=r2592000    # last 30 days, in seconds
      &start={start}

Detail (HTML fragment):
    https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}

LinkedIn returns a per-card `data-entity-urn` like
`urn:li:fsd_jobPosting:{job_id}` — that's our stable external id.

Env knobs:
    JC_LINKEDIN_KEYWORDS  (default "")
    JC_LINKEDIN_LOCATION  (default "Saudi Arabia")
    JC_LINKEDIN_GEO_ID    (default 106155005, Saudi Arabia)
    JC_LINKEDIN_MAX_PAGES (default 10  — LinkedIn allows ~40 pages * 25 cards)
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Final
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from job_crawler_db import (
    ApplicationChannelKind,
    EmploymentType,
    SourceKind,
    WorkArrangement,
)

from ..core.base import BaseCrawler
from ..core.config import RateConfig
from ..core.date_window import lookback_days
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_LOG: Final = logging.getLogger("job_crawler.linkedin")


class LinkedInCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "linkedin"
    source_display_name: ClassVar[str] = "LinkedIn"
    source_kind: ClassVar[SourceKind] = SourceKind.aggregator
    source_base_url: ClassVar[str] = "https://www.linkedin.com"
    source_trust_weight: ClassVar[float] = 0.60
    # LinkedIn fingerprints both TLS and runtime behaviour. curl_cffi
    # passes the TLS layer but the behavioural detector (mouse moves,
    # request cadence) still trips. Playwright runs full Chromium which
    # defeats both — at the cost of IP-rate-limit pressure. Pair with a
    # residential proxy pool to push the daily ceiling higher.
    use_playwright: ClassVar[bool] = True
    use_proxy_pool: ClassVar[bool] = False
    # LinkedIn's guest search ignores `geoId` and `location` filters for
    # anonymous traffic, so its results are MENA-wide. Drop anything that
    # doesn't have a GCC location at the runner gate.
    requires_gcc_location: ClassVar[bool] = True
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=1.0, burst=2, max_concurrent=1,
        timeout_seconds=30.0,
        user_agent=None,
        retry_attempts=4,
    )
    canary_urls: ClassVar[tuple[str, ...]] = ()
    PAGE_SIZE: ClassVar[int] = 25
    DEFAULT_GEO_ID: ClassVar[str] = "106155005"  # Saudi Arabia geoId

    PARSE_SELECTORS: ClassVar[dict[str, str]] = {
        "card":          "li, div.base-card",
        "card_link":     "a.base-card__full-link, a[href*='/jobs/view/']",
        "card_title":    "h3.base-search-card__title, .base-search-card__title",
        "card_company":  "h4.base-search-card__subtitle a, .base-search-card__subtitle",
        "card_location": ".job-search-card__location",
        "card_posted":   "time",
        "card_urn_attr": "data-entity-urn",
        # LinkedIn's public jobPosting fragment puts the title in an h2
        # (not h1 — that's the old logged-in-view markup). Keep h1 in the
        # alt list as a defensive fallback if they rebrand again.
        "detail_title":  "h2.top-card-layout__title, h1.top-card-layout__title, .topcard__title, h1.topcard__title",
        "detail_company":"a.topcard__org-name-link, .topcard__org-name-link, .top-card-layout__entity-info a",
        "detail_loc":    ".topcard__flavor--bullet, .top-card-layout__entity-info .bullet, .topcard__flavor",
        "detail_body":   "div.show-more-less-html__markup, div.description__text",
        "detail_posted": "span.posted-time-ago__text, .topcard__flavor--metadata.posted-time-ago__text, .posted-time-ago",
        "apply_link":    "a.apply-button, a[data-tracking-control-name*='apply'], code#applyUrl",
    }
    # Pulls "3479412345" from urn:li:fsd_jobPosting:3479412345.
    _JOB_ID_RE: ClassVar[re.Pattern[str]] = re.compile(r"jobPosting:(\d+)")
    _ID_FROM_URL_RE: ClassVar[re.Pattern[str]] = re.compile(r"/jobs/view/(?:[^/]*-)?(\d+)")

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        keywords = os.environ.get("JC_LINKEDIN_KEYWORDS", "").strip()
        location = os.environ.get("JC_LINKEDIN_LOCATION", "Saudi Arabia").strip()
        geo_id = os.environ.get("JC_LINKEDIN_GEO_ID", self.DEFAULT_GEO_ID)
        max_pages = int(os.environ.get("JC_LINKEDIN_MAX_PAGES", "40"))
        # Window in seconds — LinkedIn's f_TPR=rN means "last N seconds".
        window_seconds = lookback_days() * 86400

        seen: set[str] = set()
        for page in range(max_pages):
            start = page * self.PAGE_SIZE
            params = {
                "location": location,
                "geoId": geo_id,
                "f_TPR": f"r{window_seconds}",
                "start": start,
            }
            if keywords:
                params["keywords"] = keywords
            url = (f"{self.source_base_url}/jobs-guest/jobs/api/seeMoreJobPostings/search"
                   f"?{urlencode(params)}")
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("linkedin search page %d failed: %s", page, exc)
                break
            tree = HTMLParser(result.text)
            cards = tree.css(self.PARSE_SELECTORS["card_link"])
            if not cards:
                _LOG.info("linkedin: no more cards at start=%d", start)
                break
            yielded = 0
            for a in cards:
                href = a.attributes.get("href") or ""
                m = self._ID_FROM_URL_RE.search(href)
                if not m:
                    continue
                job_id = m.group(1)
                if job_id in seen:
                    continue
                seen.add(job_id)
                yielded += 1
                yield Listing(
                    source_job_external_id=job_id,
                    detail_url=f"{self.source_base_url}/jobs/view/{job_id}",
                )
            if yielded == 0:
                break

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        """Hit the guest jobPosting fragment endpoint — much smaller than the
        canonical /jobs/view/{id} page and renders the same content."""
        url = (f"{self.source_base_url}/jobs-guest/jobs/api/jobPosting/"
               f"{listing.source_job_external_id}")
        try:
            result = await self.http.fetch(url)
        except Exception:
            return None
        return RawPosting(
            listing=listing,
            canonical_url=listing.detail_url,   # canonical = /jobs/view/{id}
            payload={"html": result.text},
            fetched_at=datetime.now(UTC),
            duration_ms=result.duration_ms,
            http_status=result.status,
            bytes=result.bytes,
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str) or not html.strip():
            return None
        tree = HTMLParser(html)

        # LinkedIn embeds Google for Jobs JSON-LD on every public posting.
        # Prefer it for dates / salary / employment type; fall back to DOM
        # for description body and the apply CTA.
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
        posted_node = tree.css_first(self.PARSE_SELECTORS["detail_posted"])

        raw_company_name = (ld.company_name if ld else None) or (
            company_node.text(strip=True) if company_node else None
        )
        company_profile_url = (
            (ld.company_url if ld else None)
            or (company_node.attributes.get("href") if company_node else None)
        )
        raw_location = loc_node.text(strip=True) if loc_node else None
        if not raw_location and ld:
            raw_location = ", ".join(p for p in (ld.city, ld.region, ld.country) if p) or None
        description_html = body_node.html if body_node else None
        description = (ld.description if ld and ld.description else None) or (
            body_node.text(separator="\n", strip=True) if body_node else None
        )
        posted_at = (
            (ld.posted_at if ld else None)
            or (_posted_from_text(posted_node.text(strip=True)) if posted_node else None)
        )
        expires_at = ld.valid_through if ld else None
        # LinkedIn jobs are edited in-place; posted_at is a reasonable
        # source_updated_at proxy when we have nothing else.
        source_updated_at = posted_at

        channels: list[ApplicationChannelRaw] = []
        if apply_node is not None:
            href = apply_node.attributes.get("href") or ""
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=href or raw.canonical_url,
                is_primary=True,
                raw_label=apply_node.text(strip=True) or "Apply on LinkedIn",
            ))

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("raw_company_name", raw_company_name),
            ("raw_location", raw_location),
            ("description", description),
        ):
            (parsed_fields if value else missing_fields).add(name)

        return ParsedPosting(
            source_job_external_id=raw.listing.source_job_external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=posted_at,
            source_updated_at=source_updated_at,
            expires_at=expires_at,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            company_profile_url=str(company_profile_url) if company_profile_url else None,
            employment_type=(ld.employment_type if ld else None) or EmploymentType.full_time,
            work_arrangement=_arrangement(raw_location, description),
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location) or (ld.city if ld else None),
            min_experience_years=ld.min_experience_years if ld else None,
            salary_min=ld.salary_min if ld else None,
            salary_max=ld.salary_max if ld else None,
            salary_currency=ld.salary_currency if ld else None,
            salary_period=ld.salary_period if ld else None,
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "linkedin", "html_bytes": len(html)},
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


def _posted_from_text(text: str | None) -> datetime | None:
    if not text:
        return None
    m = _REL_TIME_RE.search(text)
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


def _arrangement(loc: str | None, desc: str | None) -> WorkArrangement | None:
    blob = " ".join(x for x in (loc, desc) if x).lower()
    if not blob:
        return None
    if "remote" in blob:
        return WorkArrangement.remote
    if "hybrid" in blob:
        return WorkArrangement.hybrid
    return WorkArrangement.onsite


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    return raw_location.split(",")[0].strip() or None


_ = BaseCrawler
