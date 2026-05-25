"""Greenhouse Boards crawler.

Public, unauthenticated JSON API:
    https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

`content=true` returns the full job description in one round-trip per board,
so we only hit the network once per company per run.

Boards are configured via the JC_GREENHOUSE_BOARDS env var (CSV) or fall
back to a small known-good seed list.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar, Final

from job_crawler_db import EmploymentType, SourceKind, WorkArrangement

from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.types import Listing, ParsedPosting, RawPosting
from ._base import ATSBoardCrawler

_LOG: Final = logging.getLogger("job_crawler.greenhouse")


class GreenhouseCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "greenhouse"
    source_display_name: ClassVar[str] = "Greenhouse"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://boards-api.greenhouse.io"
    source_trust_weight: ClassVar[float] = 0.95
    rate: ClassVar[RateConfig] = RateConfig(max_rps=8.0, burst=16, max_concurrent=8, timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA)
    # One stable board guaranteed to have at least one open posting.
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://boards-api.greenhouse.io/v1/boards/greenhouse/jobs?content=true",
    )
    boards_env_var: ClassVar[str] = "JC_GREENHOUSE_BOARDS"
    # Known-good Greenhouse boards as of 2026. Only verified-live slugs go
    # here — silent 404s on missing boards waste retries and confuse the
    # health detector. Add new ones from the auto-detector output
    # (`make discover-ats`) which writes them to company_source_profiles.
    default_boards: ClassVar[tuple[str, ...]] = (
        "tamara",        # Tamara (SA fintech) — confirmed live
        "hala",          # Hala (SA SMB digital bank) — confirmed live
        "careem",        # Careem — confirmed live (regional, lots of SA roles)
    )

    # ------------------------------------------------------------------
    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        boards = await self.boards()
        for slug in boards:
            url = f"{self.source_base_url}/v1/boards/{slug}/jobs?content=true"
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("greenhouse board %s fetch failed: %s", slug, exc)
                continue
            if not result.json:
                continue
            for job in result.json.get("jobs", []):
                updated_at = _parse_dt(job.get("updated_at"))
                if updated_at and updated_at < since:
                    continue
                external_id = str(job["id"])
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=job.get("absolute_url", ""),
                    posted_at_hint=updated_at,
                    # We pass the full job dict through `extra` so parse()
                    # doesn't need a second HTTP call.
                    extra={"job_payload": job, "board_slug": slug},
                )

    # ------------------------------------------------------------------
    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        """The list response already carries the full content; just wrap it."""
        job = listing.extra.get("job_payload")
        if not isinstance(job, dict):
            # Fall back to a real fetch if extra is missing (e.g. canary URL).
            return await super().fetch_detail(listing)
        return RawPosting(
            listing=listing,
            canonical_url=job.get("absolute_url", listing.detail_url),
            payload={"json": job, "board_slug": listing.extra.get("board_slug")},
            fetched_at=datetime.now(UTC),
            duration_ms=0,
            http_status=200,
            bytes=len(str(job)),
        )

    # ------------------------------------------------------------------
    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        job = raw.payload.get("json")
        if not isinstance(job, dict):
            return None
        try:
            external_id = str(job["id"])
            title = str(job["title"])
        except (KeyError, TypeError):
            return None

        # Greenhouse returns description as escaped HTML; strip tags for
        # plain text but keep the original on description_html.
        from selectolax.parser import HTMLParser

        html = job.get("content") or ""
        if isinstance(html, str) and html:
            text = HTMLParser(html).text(separator="\n", strip=True)
        else:
            text = None

        location_obj = job.get("location") or {}
        raw_location = (location_obj.get("name") or "").strip() or None

        parsed_fields: set[str] = {"title"}
        missing_fields: set[str] = set()
        if text:
            parsed_fields.add("description")
        else:
            missing_fields.add("description")
        if raw_location:
            parsed_fields.add("raw_location")
        else:
            missing_fields.add("raw_location")

        # Department / metadata can hint at remote.
        work_arrangement = _arrangement(raw_location)

        # The hosting company name comes from `company_name` (when set) or
        # the board slug (sluggified).
        board_slug = raw.payload.get("board_slug")
        raw_company_name = job.get("company_name") or (
            str(board_slug).replace("-", " ").title() if board_slug else None
        )

        # apply URL
        from job_crawler_db import ApplicationChannelKind

        from ..core.types import ApplicationChannelRaw

        apply_url = job.get("absolute_url")
        channels = []
        if apply_url:
            channels.append(
                ApplicationChannelRaw(
                    kind=ApplicationChannelKind.url,
                    value=str(apply_url),
                    is_primary=True,
                    raw_label="Apply on Greenhouse",
                )
            )

        # Greenhouse exposes:
        #   * first_published — when the role first went live  (== posted_at)
        #   * updated_at      — last source-side change         (== source_updated_at)
        # Older boards only have updated_at; fall back to it for posted_at.
        first_pub = _parse_dt(job.get("first_published"))
        updated_at = _parse_dt(job.get("updated_at"))
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=first_pub or updated_at,
            source_updated_at=updated_at,
            description=text,
            description_html=html if isinstance(html, str) else None,
            raw_company_name=raw_company_name,
            company_external_id=str(board_slug) if board_slug else None,
            employment_type=EmploymentType.full_time,  # GH boards rarely flag this
            work_arrangement=work_arrangement,
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "greenhouse", "job": job},
        )

    # ------------------------------------------------------------------
    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        # Nothing source-specific to do — to_upsert handles the conversion.
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),  # placeholder; runner overrides
            company_id=None,
            recruiter_id=None,
            location=None,
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Greenhouse uses ISO-8601 with explicit UTC offset.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _arrangement(raw_location: str | None) -> WorkArrangement | None:
    if not raw_location:
        return None
    lower = raw_location.lower()
    if "remote" in lower:
        return WorkArrangement.remote
    if "hybrid" in lower:
        return WorkArrangement.hybrid
    return WorkArrangement.onsite


def _city_hint(raw_location: str | None) -> str | None:
    """Pluck the first comma-separated token as the city hint."""
    if not raw_location:
        return None
    head = raw_location.split(",")[0].strip()
    return head or None
