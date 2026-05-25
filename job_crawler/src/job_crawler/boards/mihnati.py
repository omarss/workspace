"""Mihnati (mihnati.com) crawler.

Mihnati is a Saudi Arabia job board (ASP.NET-era site).

URL patterns (as observed historically):
    Search:  https://www.mihnati.com/Search.aspx?Country=Saudi+Arabia&page={N}
    Detail:  https://www.mihnati.com/JobDetails.aspx?JobID={id}

The site renders server-side HTML. Detail pages expose title + description
+ recruiter contact (when present) as straightforward DOM nodes.

Configured via JC_MIHNATI_MAX_PAGES (int) and JC_MIHNATI_QUERY (optional
keyword passed to the `q=` parameter).
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
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_LOG: Final = logging.getLogger("job_crawler.mihnati")


class MihnatiCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "mihnati"
    source_display_name: ClassVar[str] = "Mihnati"
    source_kind: ClassVar[SourceKind] = SourceKind.local_board
    source_base_url: ClassVar[str] = "https://www.mihnati.com"
    source_trust_weight: ClassVar[float] = 0.60
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=2.0, burst=4, max_concurrent=2,
        timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://www.mihnati.com/Search.aspx?Country=Saudi+Arabia",
    )

    PARSE_SELECTORS: ClassVar[dict[str, str]] = {
        # Generic ASP.NET listing card markers — fall through if Mihnati
        # rebuilds the markup. The runner records parse failures so we'd
        # notice via the canary.
        # Tight selector: must include `JobID=` or `/Jobs/Details/`. The
        # broader `/job/` / `/Jobs/` substring matches mihnati's error
        # pages (`/site/error?e=cnf_jobs`) so it has to stay specific.
        "card_link":      "a[href*='JobDetails.aspx?JobID='], a[href*='/Jobs/Details/']",
        "detail_title":   "h1, h2.jobTitle, span#lblTitle, .job-title",
        "detail_company": ".companyName, span#lblCompany, a[href*='companyprofile']",
        "detail_loc":     ".jobLocation, span#lblLocation, .location",
        "detail_body":    ".jobDescription, div#divJobDescription, .description, section.body",
    }
    _ID_FROM_URL_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:JobID=|/jobs?/)([^/&?#]+)", re.IGNORECASE,
    )

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        max_pages = int(os.environ.get("JC_MIHNATI_MAX_PAGES", "20"))
        query = os.environ.get("JC_MIHNATI_QUERY", "").strip()
        seen: set[str] = set()

        for page in range(1, max_pages + 1):
            url = self._search_url(page=page, query=query)
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("mihnati search page %d failed: %s", page, exc)
                break
            html = result.text or ""
            if not html or result.status >= 400:
                _LOG.info("mihnati: page %d status=%s, stopping", page, result.status)
                break
            tree = HTMLParser(html)
            cards = tree.css(self.PARSE_SELECTORS["card_link"])
            if not cards:
                _LOG.info("mihnati: no cards on page %d, stopping", page)
                break
            for link in cards:
                href = link.attributes.get("href")
                if not href:
                    continue
                detail_url = urljoin(self.source_base_url, href)
                external_id = self._external_id(detail_url)
                if not external_id or external_id in seen:
                    continue
                seen.add(external_id)
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=detail_url,
                )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str) or not html:
            return None
        tree = HTMLParser(html)

        title_node = tree.css_first(self.PARSE_SELECTORS["detail_title"])
        company_node = tree.css_first(self.PARSE_SELECTORS["detail_company"])
        loc_node = tree.css_first(self.PARSE_SELECTORS["detail_loc"])
        body_node = tree.css_first(self.PARSE_SELECTORS["detail_body"])

        title = _txt(title_node)
        if not title:
            return None
        # Mihnati interleaves promotional cards ("post your job free!") in
        # the same listing layout as real jobs. Live row
        # `019e5e2a-d4fa-7142-afc9-0d097723b4b6` was such a card. Reject by
        # title pattern before we waste a posting row + cluster bootstrap.
        if _is_promo_title(title):
            _LOG.info("mihnati: skipping promo card: %s", title)
            return None
        external_id = self._external_id(raw.canonical_url)
        if not external_id:
            return None

        description_html = body_node.html if body_node else None
        description = _txt(body_node) or None
        raw_location = _txt(loc_node) or None
        raw_company_name = _txt(company_node) or None

        channels: list[ApplicationChannelRaw] = [
            ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=raw.canonical_url,
                is_primary=True,
                raw_label="Apply on Mihnati",
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
            posted_at=None,  # Mihnati exposes "X days ago" not a date — skip
            source_updated_at=None,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            country_code="sa",
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "mihnati"},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, location=None,
        )

    # ------------------------------------------------------------------
    def _search_url(self, *, page: int, query: str) -> str:
        params: dict[str, str] = {"Country": "Saudi Arabia"}
        if query:
            params["q"] = query
        if page > 1:
            params["page"] = str(page)
        return f"{self.source_base_url}/Search.aspx?{urlencode(params)}"

    def _external_id(self, url: str) -> str:
        m = self._ID_FROM_URL_RE.search(url)
        return m.group(1) if m else url.rstrip("/").rsplit("/", 1)[-1]


# ---- helpers --------------------------------------------------------------
def _txt(node: object) -> str:
    """Best-effort text extraction with whitespace normalisation."""
    if node is None:
        return ""
    text = getattr(node, "text", lambda **_: "")(strip=True) if callable(
        getattr(node, "text", None)
    ) else ""
    return re.sub(r"\s+", " ", text or "").strip()


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    head = raw_location.split(",")[0].strip()
    return head or None


# Promotional cards Mihnati interleaves with real jobs. Substrings, not
# regex — both Arabic and English variants observed in live audit data.
# Lowercased; the check folds the title before matching.
_PROMO_TITLE_PHRASES: Final[tuple[str, ...]] = (
    "أعلن عن وظيفتك",     # "Post your job" (Arabic)
    "post your job",        # English self-service signup card
    "اعلن وظيفتك",         # alternate Arabic spelling without alef-with-hamza
    "أعلن وظيفتك",         # another variant
)


def _is_promo_title(title: str) -> bool:
    """True when the title matches a known Mihnati promotional card."""
    folded = title.casefold()
    return any(phrase.casefold() in folded for phrase in _PROMO_TITLE_PHRASES)
