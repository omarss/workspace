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
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar, Final

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

_LOG: Final = logging.getLogger("job_crawler.jadarat")


class JadaratCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "jadarat"
    source_display_name: ClassVar[str] = "Jadarat (KSA Gov)"
    source_kind: ClassVar[SourceKind] = SourceKind.gov_board
    source_base_url: ClassVar[str] = "https://jadarat.sa"
    source_trust_weight: ClassVar[float] = 0.98  # gov source — authoritative
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=1.0, burst=2, max_concurrent=2,
        timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://jadarat.sa/JobSearch",
    )

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        # Without a valid session cookie / queue token Jadarat 302s us
        # straight to its queue page on every request. Detect that early
        # so we don't burn the rate-limit budget for nothing.
        cookie = os.environ.get("JC_JADARAT_COOKIE", "").strip()
        if not cookie:
            _LOG.warning(
                "jadarat: JC_JADARAT_COOKIE not set — site is behind Queue-It "
                "and requires a real browser session token to enumerate. "
                "Skipping discover.",
            )
            return

        max_pages = int(os.environ.get("JC_JADARAT_MAX_PAGES", "10"))
        headers = {"Cookie": cookie, "Accept": "application/json"}
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            url = (
                f"{self.source_base_url}/api/jobseeker/getjobs"
                f"?lang=ar&pageno={page}&country_id=1"
            )
            try:
                result = await self.http.fetch(url, headers=headers)
            except Exception as exc:
                _LOG.warning("jadarat page %d failed: %s", page, exc)
                break
            payload = result.json or {}
            jobs = payload.get("DataList") or payload.get("data") or []
            if not isinstance(jobs, list) or not jobs:
                _LOG.info("jadarat page %d empty, stopping", page)
                break
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                external_id = str(
                    job.get("JobID") or job.get("JobNo") or job.get("id") or ""
                ).strip()
                if not external_id or external_id in seen:
                    continue
                seen.add(external_id)
                detail_url = f"{self.source_base_url}/JobDetails?JobID={external_id}"
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=detail_url,
                    extra={"job": job},
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        # The list response carries the full record; no extra HTTP needed.
        job = listing.extra.get("job")
        if not isinstance(job, dict):
            return await super().fetch_detail(listing)
        return RawPosting(
            listing=listing,
            canonical_url=listing.detail_url,
            payload={"json": job},
            fetched_at=datetime.now(UTC),
            duration_ms=0, http_status=200, bytes=len(str(job)),
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        job = raw.payload.get("json")
        if not isinstance(job, dict):
            return None
        external_id = str(
            job.get("JobID") or job.get("JobNo") or job.get("id") or ""
        ).strip()
        title = (
            job.get("JobTitleAR")
            or job.get("JobTitle")
            or job.get("title")
            or ""
        ).strip()
        if not external_id or not title:
            return None

        # Jadarat exposes Arabic + English titles + a description; field
        # names vary slightly across endpoints, so we coalesce.
        description = (
            job.get("JobDescriptionAR")
            or job.get("JobDescription")
            or job.get("description")
            or ""
        ).strip() or None

        raw_company_name = (
            job.get("CompanyNameAR")
            or job.get("CompanyName")
            or job.get("EmployerName")
            or ""
        ).strip() or None

        raw_location = (
            job.get("RegionAR")
            or job.get("Region")
            or job.get("City")
            or ""
        ).strip() or None

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

        posted_dt = _parse_dt(
            job.get("PostingDate") or job.get("CreatedDate") or job.get("posted_at")
        )
        expires_dt = _parse_dt(
            job.get("ExpiryDate") or job.get("ValidThrough") or job.get("expires_at")
        )
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=posted_dt,
            source_updated_at=posted_dt,
            expires_at=expires_dt,
            description=description,
            raw_company_name=raw_company_name,
            raw_location=raw_location,
            city_name_hint=raw_location,
            country_code="sa",
            # Jadarat lists only KSA-nationals jobs by design.
            saudi_nationals_only=True,
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "jadarat", "job": job},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, city_id=None,
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
