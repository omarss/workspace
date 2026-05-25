"""Recruitee crawler.

Public, unauthenticated JSON API per company:
    https://{subdomain}.recruitee.com/api/offers/

Returns `{"offers": [...]}` with each offer including title, location,
description (HTML), employment type, posted_at, and apply URL. One round
trip per tenant — no detail fetch needed.

Configured via JC_RECRUITEE_BOARDS (CSV of subdomains).
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

_LOG: Final = logging.getLogger("job_crawler.recruitee")


class RecruiteeCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "recruitee"
    source_display_name: ClassVar[str] = "Recruitee"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://recruitee.com"
    source_trust_weight: ClassVar[float] = 0.92
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=6.0, burst=12, max_concurrent=6,
        timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://recruitee.recruitee.com/api/offers/",
    )
    boards_env_var: ClassVar[str] = "JC_RECRUITEE_BOARDS"
    # No verified-live SA tenants known at implementation time. Discovery
    # via `make discover-ats` will surface them as `recruitee` profiles in
    # company_source_profiles, which the runner reads automatically.
    default_boards: ClassVar[tuple[str, ...]] = ()

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        boards = await self.boards()
        for slug in boards:
            url = f"https://{slug}.recruitee.com/api/offers/"
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("recruitee board %s fetch failed: %s", slug, exc)
                continue
            payload = result.json or {}
            for offer in payload.get("offers", []) or []:
                created = _parse_dt(offer.get("created_at") or offer.get("published_at"))
                if created and created < since:
                    continue
                external_id = str(offer.get("id") or offer.get("slug") or "")
                if not external_id:
                    continue
                yield Listing(
                    source_job_external_id=external_id,
                    detail_url=str(offer.get("careers_url") or offer.get("url") or ""),
                    posted_at_hint=created,
                    extra={"offer": offer, "board_slug": slug},
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        offer = listing.extra.get("offer")
        if not isinstance(offer, dict):
            return await super().fetch_detail(listing)
        return RawPosting(
            listing=listing,
            canonical_url=str(offer.get("careers_url") or listing.detail_url),
            payload={"json": offer, "board_slug": listing.extra.get("board_slug")},
            fetched_at=datetime.now(UTC),
            duration_ms=0, http_status=200, bytes=len(str(offer)),
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        offer = raw.payload.get("json")
        if not isinstance(offer, dict):
            return None
        external_id = str(offer.get("id") or offer.get("slug") or "").strip()
        title = (offer.get("title") or "").strip()
        if not external_id or not title:
            return None

        description_html = (offer.get("description") or "").strip() or None
        description = (offer.get("description_plaintext") or "").strip() or (
            _strip_html(description_html) if description_html else None
        )

        # Recruitee location fields: city, country, country_code (ISO).
        city = (offer.get("city") or "").strip()
        country = (offer.get("country") or "").strip()
        country_code = (offer.get("country_code") or "").strip().lower() or None
        raw_location = ", ".join(p for p in (city, country) if p) or None

        remote = bool(offer.get("remote"))
        work_arr: WorkArrangement | None = None
        if remote:
            work_arr = WorkArrangement.remote
        elif raw_location and "hybrid" in raw_location.lower():
            work_arr = WorkArrangement.hybrid
        elif raw_location:
            work_arr = WorkArrangement.onsite

        emp_type = _employment(str(offer.get("employment_type_code")
                                   or offer.get("employment_type") or "").lower())

        apply_url = str(offer.get("careers_apply_url")
                        or offer.get("careers_url") or "").strip()
        channels: list[ApplicationChannelRaw] = []
        if apply_url:
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=apply_url, is_primary=True,
                raw_label="Apply on Recruitee",
            ))

        board_slug = raw.payload.get("board_slug")
        raw_company_name = (
            (offer.get("company") or {}).get("name") if isinstance(offer.get("company"), dict) else None
        ) or (str(board_slug).replace("-", " ").title() if board_slug else None)

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
            ("raw_company_name", raw_company_name),
        ):
            (parsed_fields if value else missing_fields).add(name)

        posted_dt = _parse_dt(offer.get("published_at") or offer.get("created_at"))
        updated_dt = _parse_dt(offer.get("updated_at")) or posted_dt
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=posted_dt,
            source_updated_at=updated_dt,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            company_external_id=str(board_slug) if board_slug else None,
            employment_type=emp_type,
            work_arrangement=work_arr,
            raw_location=raw_location,
            city_name_hint=city or None,
            country_code=country_code or _country_code(country),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "recruitee", "job": offer},
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
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _strip_html(html: str) -> str:
    from selectolax.parser import HTMLParser

    return HTMLParser(html).text(separator="\n", strip=True)


def _employment(value: str) -> EmploymentType | None:
    return {
        "full_time": EmploymentType.full_time,
        "full-time": EmploymentType.full_time,
        "fulltime":  EmploymentType.full_time,
        "part_time": EmploymentType.part_time,
        "part-time": EmploymentType.part_time,
        "parttime":  EmploymentType.part_time,
        "contract":  EmploymentType.contract,
        "temporary": EmploymentType.temporary,
        "intern":    EmploymentType.internship,
        "internship": EmploymentType.internship,
    }.get(value)


def _country_code(country: str) -> str:
    c = country.lower()
    if c in {"saudi arabia", "saudi_arabia", "ksa"}:
        return "sa"
    if len(country) == 2:
        return c
    return "sa"
