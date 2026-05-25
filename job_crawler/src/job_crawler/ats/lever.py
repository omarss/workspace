"""Lever (jobs.lever.co) crawler.

Public, unauthenticated JSON API per company:
    https://api.lever.co/v0/postings/{site}?mode=json

Returns a flat list of postings with descriptionPlain pre-rendered, so
one request per company is enough. We pass `?mode=json` explicitly so
Lever doesn't try to return HTML.

Boards configured via JC_LEVER_BOARDS (CSV). Defaults to a tiny SA-relevant seed.
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

_LOG: Final = logging.getLogger("job_crawler.lever")


class LeverCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "lever"
    source_display_name: ClassVar[str] = "Lever"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://api.lever.co"
    source_trust_weight: ClassVar[float] = 0.93
    rate: ClassVar[RateConfig] = RateConfig(max_rps=8.0, burst=16, max_concurrent=8, timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA)
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://api.lever.co/v0/postings/lever?mode=json",
    )
    boards_env_var: ClassVar[str] = "JC_LEVER_BOARDS"
    default_boards: ClassVar[tuple[str, ...]] = ()  # seed via env

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        boards = await self.boards()
        for slug in boards:
            url = f"{self.source_base_url}/v0/postings/{slug}?mode=json"
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("lever board %s fetch failed: %s", slug, exc)
                continue
            if not isinstance(result.json, list):
                continue
            for job in result.json:
                created_at = _epoch_to_dt(job.get("createdAt"))
                if created_at and created_at < since:
                    continue
                external_id = str(job.get("id") or "")
                if not external_id:
                    continue
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=str(job.get("hostedUrl") or ""),
                    posted_at_hint=created_at,
                    extra={"job_payload": job, "board_slug": slug},
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        """List response carries full content; reuse it (zero extra HTTP)."""
        job = listing.extra.get("job_payload")
        if not isinstance(job, dict):
            return await super().fetch_detail(listing)
        return RawPosting(
            listing=listing,
            canonical_url=str(job.get("hostedUrl") or listing.detail_url),
            payload={"json": job, "board_slug": listing.extra.get("board_slug")},
            fetched_at=datetime.now(UTC),
            duration_ms=0, http_status=200, bytes=len(str(job)),
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        job = raw.payload.get("json")
        if not isinstance(job, dict):
            return None
        external_id = str(job.get("id") or "").strip()
        title = (job.get("text") or "").strip()
        if not external_id or not title:
            return None

        categories = job.get("categories") or {}
        raw_location = (categories.get("location") or "").strip() or None
        commitment = (categories.get("commitment") or "").strip().lower()
        work_type = (categories.get("workplaceType") or "").strip().lower()

        description = (job.get("descriptionPlain") or "").strip() or None
        description_html = (job.get("description") or "").strip() or None

        # Apply URL
        apply_url = str(job.get("applyUrl") or job.get("hostedUrl") or "").strip()
        channels: list[ApplicationChannelRaw] = []
        if apply_url:
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=apply_url, is_primary=True,
                raw_label="Apply on Lever",
            ))

        board_slug = raw.payload.get("board_slug")
        raw_company_name = str(board_slug).replace("-", " ").title() if board_slug else None

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
        ):
            (parsed_fields if value else missing_fields).add(name)

        created_dt = _epoch_to_dt(job.get("createdAt"))
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=created_dt,
            source_updated_at=created_dt,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            company_external_id=str(board_slug) if board_slug else None,
            employment_type=_employment(commitment),
            work_arrangement=_arrangement(work_type, raw_location),
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "lever", "job": job},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, location=None,
        )


# ---- helpers --------------------------------------------------------------
def _epoch_to_dt(ms: object) -> datetime | None:
    """Lever returns createdAt in ms-since-epoch (int)."""
    if not isinstance(ms, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    except (OverflowError, OSError):
        return None


def _employment(commitment: str) -> EmploymentType | None:
    """Map Lever's commitment label to our enum."""
    if not commitment:
        return None
    m = {
        "full-time": EmploymentType.full_time,
        "full time": EmploymentType.full_time,
        "part-time": EmploymentType.part_time,
        "part time": EmploymentType.part_time,
        "contract":  EmploymentType.contract,
        "temporary": EmploymentType.temporary,
        "internship": EmploymentType.internship,
    }
    return m.get(commitment)


def _arrangement(work_type: str, raw_location: str | None) -> WorkArrangement | None:
    if work_type in {"remote", "on-site", "onsite", "hybrid"}:
        return {
            "remote":  WorkArrangement.remote,
            "on-site": WorkArrangement.onsite,
            "onsite":  WorkArrangement.onsite,
            "hybrid":  WorkArrangement.hybrid,
        }[work_type]
    if raw_location:
        lower = raw_location.lower()
        if "remote" in lower:
            return WorkArrangement.remote
        if "hybrid" in lower:
            return WorkArrangement.hybrid
    return None


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    head = raw_location.split(",")[0].strip()
    return head or None
