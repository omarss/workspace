"""Tanqeeb (saudi.tanqeeb.com) crawler.

Tanqeeb is an Arab job aggregator with a Saudi-specific subdomain. Public
browsing is limited to the latest ~7 jobs on the homepage plus a few per
regional / category page (login required for deeper paging). The detail
page exposes a clean JSON-LD JobPosting block which we extract via the
shared `core.jsonld` helper.

URL patterns:
    Listing:  https://saudi.tanqeeb.com/ar (latest 7-16)
              https://saudi.tanqeeb.com/ar/s/{category}/{region}  (~3-7 per)
    Detail:   https://saudi.tanqeeb.com/ar/jobs-in-saudi/all/jobs/{numeric}.html

Configured via JC_TANQEEB_EXTRA_PATHS (CSV of extra listing paths to
scrape on top of the homepage; supports the Arabic-URL-encoded regional
routes).
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
    EmploymentType,
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

_LOG: Final = logging.getLogger("job_crawler.tanqeeb")


class TanqeebCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "tanqeeb"
    source_display_name: ClassVar[str] = "Tanqeeb"
    source_kind: ClassVar[SourceKind] = SourceKind.local_board
    source_base_url: ClassVar[str] = "https://saudi.tanqeeb.com"
    source_trust_weight: ClassVar[float] = 0.65
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=2.0, burst=4, max_concurrent=2,
        timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://saudi.tanqeeb.com/ar",
    )

    # Regional landing pages reachable without login. Each yields a handful
    # of latest postings for that region; the union covers most-KSA.
    _DEFAULT_LISTING_PATHS: ClassVar[tuple[str, ...]] = (
        "/ar",  # latest across SA
        "/ar/s/%D9%88%D8%B8%D8%A7%D8%A6%D9%81/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%81%D9%8A-%D8%A7%D9%84%D8%B1%D9%8A%D8%A7%D8%B6",       # Riyadh
        "/ar/s/%D9%88%D8%B8%D8%A7%D8%A6%D9%81/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%81%D9%89-%D8%AC%D8%AF%D8%A9",                          # Jeddah
        "/ar/s/%D9%88%D8%B8%D8%A7%D8%A6%D9%81/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%81%D9%8A-%D8%A7%D9%84%D8%AF%D9%85%D8%A7%D9%85",        # Dammam
        "/ar/s/%D9%88%D8%B8%D8%A7%D8%A6%D9%81/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%81%D9%8A-%D8%A7%D9%84%D8%AE%D8%A8%D8%B1",              # Khobar
        "/ar/s/%D9%88%D8%B8%D8%A7%D8%A6%D9%81/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D9%81%D9%8A-%D9%85%D9%83%D8%A9",                          # Makkah
        "/ar/s/%D9%88%D8%B8%D8%A7%D8%A6%D9%81/%D9%88%D8%B8%D8%A7%D8%A6%D9%81-%D8%A7%D9%84%D9%85%D8%AF%D9%8A%D9%86%D8%A9-%D8%A7%D9%84%D9%85%D9%86%D9%88%D8%B1%D9%87",  # Madinah
    )

    _DETAIL_HREF_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"/ar/jobs-in-saudi/all/jobs/([0-9]+)\.html",
    )

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        paths = self._listing_paths()
        seen: set[str] = set()
        for path in paths:
            url = urljoin(self.source_base_url, path)
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("tanqeeb listing %s failed: %s", path, exc)
                continue
            html = result.text or ""
            for match in self._DETAIL_HREF_RE.finditer(html):
                detail_path = match.group(0)
                external_id = match.group(1)
                if external_id in seen:
                    continue
                seen.add(external_id)
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=urljoin(self.source_base_url, detail_path),
                )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str) or not html:
            return None

        ld = extract_job_posting(html)
        tree = HTMLParser(html)

        title = (ld.title if ld else None) or _txt(
            tree.css_first("h1.job-title-with-logo, h1.job-title, h1")
        )
        if not title:
            return None
        external_id_m = self._DETAIL_HREF_RE.search(raw.canonical_url)
        if not external_id_m:
            return None
        external_id = external_id_m.group(1)

        body_node = tree.css_first(".job-description, section.job-body")
        description_html = body_node.html if body_node else None
        description = (ld.description if ld else None) or (
            _txt(body_node) if body_node else None
        )

        raw_company_name = (
            (ld.company_name if ld else None)
            or _txt(tree.css_first(".company-name, a[href*='employers']"))
            or None
        )
        raw_location = _join_location(ld) or _txt(
            tree.css_first(".job-location, .location"),
        ) or None

        channels: list[ApplicationChannelRaw] = [
            ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=raw.canonical_url,
                is_primary=True,
                raw_label="Apply on Tanqeeb",
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
            description_html=description_html,
            raw_company_name=raw_company_name,
            employment_type=(ld.employment_type if ld else None),
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            country_code="sa",
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "tanqeeb"},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, city_id=None,
        )

    # ------------------------------------------------------------------
    def _listing_paths(self) -> tuple[str, ...]:
        extra = os.environ.get("JC_TANQEEB_EXTRA_PATHS", "").strip()
        if extra:
            return self._DEFAULT_LISTING_PATHS + tuple(
                p.strip() for p in extra.split(",") if p.strip()
            )
        return self._DEFAULT_LISTING_PATHS


# ---- helpers --------------------------------------------------------------
def _txt(node: object) -> str:
    if node is None:
        return ""
    text = node.text(separator=" ", strip=True) if hasattr(node, "text") else ""
    return re.sub(r"\s+", " ", text or "").strip()


def _employment(value: str | None) -> EmploymentType | None:
    if not value:
        return None
    v = value.strip().lower().replace("-", " ").replace("_", " ")
    return {
        "full time":  EmploymentType.full_time,
        "fulltime":   EmploymentType.full_time,
        "part time":  EmploymentType.part_time,
        "parttime":   EmploymentType.part_time,
        "contract":   EmploymentType.contract,
        "contractor": EmploymentType.contract,
        "temporary":  EmploymentType.temporary,
        "internship": EmploymentType.internship,
        "intern":     EmploymentType.internship,
    }.get(v)


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
