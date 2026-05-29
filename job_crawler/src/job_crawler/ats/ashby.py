"""Ashby (jobs.ashbyhq.com) crawler.

Public, unauthenticated JSON API per company:
    https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true

Returns a flat list of postings; the list response includes
`descriptionHtml` / `descriptionPlain` per job, so one HTTP call per
company suffices (no per-job detail fetch needed).

The endpoint sits behind Cloudflare, which rejects generic curl traffic
with 504 (gateway timeout). Playwright's real-Chromium TLS fingerprint
passes through, so we set `use_playwright=True` on this crawler.

Env knobs:
    JC_ASHBY_BOARDS — comma-separated list of Ashby board slugs to crawl
                      (e.g. "linear,notion,anthropic"). Empty default
                      because the user-curated seed lives in env / DB.

Sample known Ashby tenants (correctness not guaranteed; verify per slug):
    linear, notion, ramp, openai, anthropic, mistral, xai
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar, Final

from job_crawler_db import (
    ApplicationChannelKind,
    EmploymentType,
    SourceKind,
    WorkArrangement,
)

from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import ATSBoardCrawler

_LOG: Final = logging.getLogger("job_crawler.ashby")


class AshbyCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "ashby"
    source_display_name: ClassVar[str] = "Ashby"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://api.ashbyhq.com"
    source_trust_weight: ClassVar[float] = 0.93
    # Cloudflare 504s plain curl_cffi; real Chromium TLS gets through.
    use_playwright: ClassVar[bool] = True
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=2.0, burst=4, max_concurrent=2,
        timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        # `linear` is a stable public Ashby tenant; canary verifies the
        # API surface still responds to anonymous traffic.
        "https://api.ashbyhq.com/posting-api/job-board/linear?includeCompensation=true",
    )
    boards_env_var: ClassVar[str] = "JC_ASHBY_BOARDS"
    default_boards: ClassVar[tuple[str, ...]] = ()  # seed via env / DB

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        boards = await self.boards()
        for slug in boards:
            url = (
                f"{self.source_base_url}/posting-api/job-board/"
                f"{slug}?includeCompensation=true"
            )
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("ashby board %s fetch failed: %s", slug, exc)
                continue
            if result.status >= 400:
                _LOG.info("ashby board %s status=%d, skipping", slug, result.status)
                continue
            payload = result.json
            jobs = payload.get("jobs") if isinstance(payload, dict) else None
            if not isinstance(jobs, list):
                continue
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                if job.get("isListed") is False:
                    continue
                external_id = str(job.get("id") or "")
                if not external_id:
                    continue
                # Prefer the public-facing jobs.ashbyhq.com URL as the
                # detail/canonical so subscribers see the company-tagged
                # page, not the bare API endpoint.
                detail = str(job.get("jobUrl") or "").strip()
                if not detail:
                    detail = f"https://jobs.ashbyhq.com/{slug}/{external_id}"
                published_dt = _iso_to_dt(job.get("publishedAt"))
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=detail,
                    posted_at_hint=published_dt,
                    extra={"job_payload": job, "board_slug": slug},
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        """List response already carries descriptionHtml; reuse it."""
        job = listing.extra.get("job_payload")
        if not isinstance(job, dict):
            return await super().fetch_detail(listing)
        return RawPosting(
            listing=listing,
            canonical_url=listing.detail_url,
            payload={"json": job, "board_slug": listing.extra.get("board_slug")},
            fetched_at=datetime.now(UTC),
            duration_ms=0, http_status=200, bytes=len(str(job)),
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        job = raw.payload.get("json")
        if not isinstance(job, dict):
            return None
        external_id = str(job.get("id") or "").strip()
        title = (job.get("title") or "").strip()
        if not external_id or not title:
            return None

        raw_location = (job.get("locationName") or job.get("location") or "").strip() or None
        employment_type_label = (job.get("employmentType") or "").strip()
        is_remote = bool(job.get("isRemote"))

        description = (job.get("descriptionPlain") or "").strip() or None
        description_html = (job.get("descriptionHtml") or "").strip() or None

        # Ashby exposes `applicationFormUrl` for in-board apply and
        # `jobUrl` for the public posting. Prefer applicationFormUrl
        # because that's the canonical "Apply" target.
        apply_url = (
            str(job.get("applicationFormUrl") or "").strip()
            or str(job.get("jobUrl") or "").strip()
            or raw.canonical_url
        )
        channels: list[ApplicationChannelRaw] = []
        if apply_url:
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=apply_url, is_primary=True,
                raw_label="Apply on Ashby",
            ))

        board_slug = raw.payload.get("board_slug")
        raw_company_name = (
            str(board_slug).replace("-", " ").title()
            if board_slug else None
        )

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
        ):
            (parsed_fields if value else missing_fields).add(name)

        published_dt = _iso_to_dt(job.get("publishedAt"))

        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=published_dt,
            source_updated_at=published_dt,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            company_external_id=str(board_slug) if board_slug else None,
            employment_type=_employment(employment_type_label),
            work_arrangement=_arrangement(is_remote, raw_location),
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "ashby", "job": job},
        )


# ---- helpers --------------------------------------------------------------


def _iso_to_dt(value: object) -> datetime | None:
    """Ashby returns publishedAt as an ISO-8601 string (e.g. '2026-05-21T14:30:00.000Z')."""
    if not isinstance(value, str) or not value:
        return None
    s = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _employment(label: str) -> EmploymentType | None:
    """Ashby's employmentType is a CamelCase enum: FullTime / PartTime /
    Contract / Intern / Temporary."""
    if not label:
        return None
    m = {
        "fulltime":   EmploymentType.full_time,
        "parttime":   EmploymentType.part_time,
        "contract":   EmploymentType.contract,
        "intern":     EmploymentType.internship,
        "internship": EmploymentType.internship,
        "temporary":  EmploymentType.temporary,
    }
    return m.get(label.lower().replace(" ", "").replace("-", ""))


def _arrangement(is_remote: bool, raw_location: str | None) -> WorkArrangement | None:
    if is_remote:
        return WorkArrangement.remote
    if raw_location:
        lower = raw_location.lower()
        if "remote" in lower:
            return WorkArrangement.remote
        if "hybrid" in lower:
            return WorkArrangement.hybrid
        if "on-site" in lower or "onsite" in lower or "office" in lower:
            return WorkArrangement.onsite
    return None


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    head = raw_location.split(",")[0].strip()
    return head or None
