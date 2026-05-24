"""Workable (apply.workable.com) crawler.

Public, unauthenticated endpoints per company subdomain:

    Listing (cheap, one round-trip):
        GET /api/v1/widget/accounts/{slug}
        → name + jobs[]; each job has shortcode, title, city/country, url,
          published_on, employment_type, but NO description.

    Detail (per-posting; ~4-6KB each):
        GET /api/v2/accounts/{slug}/jobs/{shortcode}
        → adds description (HTML), location.{country,countryCode,city,region},
          workplace, type.

Workable's older v3 (apply.workable.com/api/v3/accounts/...) returns 404 on
real production accounts even though jobs.workable.com docs still mention it
— the v1+v2 path is what actually works for guest reads.

Configured via JC_WORKABLE_BOARDS (CSV of subdomains).
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

from ..core.base import BaseCrawler
from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import ATSBoardCrawler

_LOG: Final = logging.getLogger("job_crawler.workable")


class WorkableCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "workable"
    source_display_name: ClassVar[str] = "Workable"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://apply.workable.com"
    source_trust_weight: ClassVar[float] = 0.93
    rate: ClassVar[RateConfig] = RateConfig(max_rps=6.0, burst=12, max_concurrent=6, timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA)
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://apply.workable.com/api/v1/widget/accounts/foodics",
    )
    boards_env_var: ClassVar[str] = "JC_WORKABLE_BOARDS"
    # Verified-live SA-headquartered tech companies on Workable (as of 2026-05).
    # Probed via the public widget endpoint:
    #     curl https://apply.workable.com/api/v1/widget/accounts/{slug}
    # Only include slugs returning a non-empty jobs[] — Workable returns 200
    # for any slug, so we can't just trust the status code.
    default_boards: ClassVar[tuple[str, ...]] = (
        "foodics",   # FOODICS (Riyadh, POS for restaurants) — 62 jobs at probe time
        "salla",     # Salla (Jeddah, e-commerce SaaS) — 36 jobs
        "tamatem",   # Tamatem Games (Riyadh ops) — 9 jobs
    )

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        boards = await self.boards()
        for slug in boards:
            url = f"{self.source_base_url}/api/v1/widget/accounts/{slug}"
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("workable board %s fetch failed: %s", slug, exc)
                continue
            payload = result.json or {}
            company_name = payload.get("name")
            for job in payload.get("jobs", []) or []:
                created = _parse_dt(job.get("published_on") or job.get("created_at"))
                if created and created < since:
                    continue
                shortcode = job.get("shortcode") or job.get("code")
                if not shortcode:
                    continue
                yield Listing(
                    source_job_external_id=str(shortcode),
                    detail_url=str(job.get("url") or job.get("application_url") or ""),
                    posted_at_hint=created,
                    extra={
                        "summary": job,
                        "board_slug": slug,
                        "company_name": company_name,
                    },
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        """Fetch the v2 detail document for the description body."""
        slug = listing.extra.get("board_slug")
        shortcode = listing.source_job_external_id
        if not slug or not shortcode:
            return await super().fetch_detail(listing)
        url = f"{self.source_base_url}/api/v2/accounts/{slug}/jobs/{shortcode}"
        try:
            result = await self.http.fetch(url)
        except Exception:
            return None
        body = result.json or {}
        return RawPosting(
            listing=listing,
            canonical_url=listing.detail_url or str(result.url),
            payload={
                "json": body,
                "summary": listing.extra.get("summary"),
                "board_slug": slug,
                "company_name": listing.extra.get("company_name"),
            },
            fetched_at=datetime.now(UTC),
            duration_ms=result.duration_ms,
            http_status=result.status,
            bytes=result.bytes,
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        # Detail (v2) is the source of truth; summary (v1 widget) is the
        # fallback so we still ingest even if the detail call returns
        # empty/404 (rare but possible for jobs in a transitional state).
        detail = raw.payload.get("json") or {}
        summary = raw.payload.get("summary") or {}
        from typing import Any

        job: dict[str, Any] = (
            {**summary, **detail} if isinstance(detail, dict) else summary
        )

        external_id = str(
            job.get("shortcode") or job.get("code") or job.get("id") or ""
        ).strip()
        title = (job.get("title") or "").strip()
        if not external_id or not title:
            return None

        description_html = (job.get("description") or "").strip() or None
        description = _strip_html(description_html) if description_html else None

        # v2 detail returns a dict with country/countryCode/city/region;
        # v1 widget summary has top-level city/country only. Coalesce both.
        loc = job.get("location") if isinstance(job.get("location"), dict) else None
        country = (loc or {}).get("country") or job.get("country") or ""
        country_code = (loc or {}).get("countryCode") or ""
        city = (loc or {}).get("city") or job.get("city") or ""
        region = (loc or {}).get("region") or job.get("state") or ""
        raw_location = ", ".join(p for p in (city, region, country) if p) or None

        workplace = (job.get("workplace") or "").strip().lower()
        work_arr = {
            "remote":  WorkArrangement.remote,
            "hybrid":  WorkArrangement.hybrid,
            "on_site": WorkArrangement.onsite,
            "onsite":  WorkArrangement.onsite,
        }.get(workplace)
        if work_arr is None and raw_location and "remote" in raw_location.lower():
            work_arr = WorkArrangement.remote

        # v2 uses `type` (full_time / part_time / ...); v1 widget uses
        # `employment_type` with the same vocabulary.
        emp_type = _employment(
            str(job.get("type") or job.get("employment_type") or "").lower()
        )

        # Apply URL — v1 widget exposes both `application_url` (POST target)
        # and `url` (the human-readable apply page). Prefer the human one.
        apply_url = str(job.get("url") or job.get("application_url") or "")
        channels: list[ApplicationChannelRaw] = []
        if apply_url:
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=apply_url, is_primary=True,
                raw_label="Apply on Workable",
            ))

        board_slug = raw.payload.get("board_slug")
        # Prefer the company name we captured at widget time (it's the
        # tenant's display name, not a slug guess).
        raw_company_name = (
            raw.payload.get("company_name")
            or (str(board_slug).replace("-", " ").title() if board_slug else None)
        )

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
            ("raw_company_name", raw_company_name),
        ):
            (parsed_fields if value else missing_fields).add(name)

        posted_dt = _parse_dt(job.get("published_on") or job.get("created_at"))
        updated_dt = _parse_dt(job.get("updated_at")) or posted_dt
        expires_dt = _parse_dt(job.get("expires_at") or job.get("expiry_date"))
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=posted_dt,
            source_updated_at=updated_dt,
            expires_at=expires_dt,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            company_external_id=str(board_slug) if board_slug else None,
            employment_type=emp_type,
            work_arrangement=work_arr,
            raw_location=raw_location,
            city_name_hint=city or None,
            # Prefer the ISO-2 the API hands us; fall back to name-based mapping.
            country_code=(country_code.lower() if country_code else _country_code(country)),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "workable", "job": job},
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
        "part_time": EmploymentType.part_time,
        "part-time": EmploymentType.part_time,
        "contract":  EmploymentType.contract,
        "temporary": EmploymentType.temporary,
        "internship": EmploymentType.internship,
        "intern":     EmploymentType.internship,
    }.get(value)


def _country_code(country: str) -> str:
    """Best-effort ISO-3166-1 alpha-2 from Workable's country name."""
    code = country.lower()
    if code in {"saudi arabia", "saudi_arabia", "ksa", "sa"}:
        return "sa"
    # Lowercase 2-letter strings come straight through.
    if len(country) == 2:
        return code
    return "sa"  # SA-first default; the cluster's country_code FK demands a known one.


_ = BaseCrawler
