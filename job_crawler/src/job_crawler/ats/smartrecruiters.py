"""SmartRecruiters crawler.

Public, unauthenticated JSON API per company id:
    https://api.smartrecruiters.com/v1/companies/{company_id}/postings?limit=100

The list endpoint returns summaries with location + posted date; the detail
endpoint adds the full description. Configured via JC_SR_COMPANIES (CSV).
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

_LOG: Final = logging.getLogger("job_crawler.smartrecruiters")


class SmartRecruitersCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "smartrecruiters"
    source_display_name: ClassVar[str] = "SmartRecruiters"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://api.smartrecruiters.com"
    source_trust_weight: ClassVar[float] = 0.92
    rate: ClassVar[RateConfig] = RateConfig(max_rps=6.0, burst=12, max_concurrent=6, timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA)
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://api.smartrecruiters.com/v1/companies/Bosch/postings?limit=3",
    )
    boards_env_var: ClassVar[str] = "JC_SR_COMPANIES"
    default_boards: ClassVar[tuple[str, ...]] = ()

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        companies = await self.boards()
        for company in companies:
            url = (f"{self.source_base_url}/v1/companies/{company}"
                   f"/postings?limit=100")
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("SR company %s fetch failed: %s", company, exc)
                continue
            payload = result.json or {}
            for posting in payload.get("content", []) or []:
                released = _parse_dt(posting.get("releasedDate"))
                if released and released < since:
                    continue
                pid = posting.get("id")
                if not pid:
                    continue
                yield Listing(
                    source_job_external_id=str(pid),
                    detail_url=str(posting.get("ref") or ""),
                    posted_at_hint=released,
                    extra={"summary": posting, "company": company},
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        """Pull the full posting (description + experience info)."""
        company = listing.extra.get("company")
        pid = listing.source_job_external_id
        if not company:
            return await super().fetch_detail(listing)
        url = (f"{self.source_base_url}/v1/companies/{company}"
               f"/postings/{pid}")
        try:
            result = await self.http.fetch(url)
        except Exception:
            return None
        body = result.json or {}
        return RawPosting(
            listing=listing,
            canonical_url=str(body.get("postingUrl") or body.get("applyUrl") or result.url),
            payload={"json": body, "summary": listing.extra.get("summary"),
                     "company": company},
            fetched_at=datetime.now(UTC),
            duration_ms=result.duration_ms,
            http_status=result.status,
            bytes=result.bytes,
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        body = raw.payload.get("json")
        summary = raw.payload.get("summary") or {}
        if not isinstance(body, dict):
            return None
        external_id = str(body.get("id") or summary.get("id") or "")
        title = (body.get("name") or summary.get("name") or "").strip()
        if not external_id or not title:
            return None

        location = body.get("location") or summary.get("location") or {}
        city = (location.get("city") or "").strip()
        region = (location.get("region") or "").strip()
        country = (location.get("country") or "").strip()
        raw_location = ", ".join(p for p in (city, region, country) if p) or None
        remote_location = bool(location.get("remote", False))

        # Description fields — SR splits intro / job description / qualifications.
        jad = body.get("jobAd") or {}
        sections = (jad.get("sections") or {})
        parts = []
        for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
            s = sections.get(key) or {}
            text = (s.get("text") or "").strip()
            if text:
                parts.append(text)
        description_html = ("\n\n".join(parts)) or None
        description = _strip_html(description_html) if description_html else None

        emp_type = _employment(
            (body.get("typeOfEmployment") or {}).get("id", "")
            or summary.get("typeOfEmployment", {}).get("id", "")
        )

        work_arr = (
            WorkArrangement.remote if remote_location else
            WorkArrangement.hybrid if raw_location and "hybrid" in raw_location.lower() else
            WorkArrangement.onsite if raw_location else None
        )

        apply_url = str(body.get("applyUrl") or body.get("postingUrl") or "")
        channels: list[ApplicationChannelRaw] = []
        if apply_url:
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=apply_url, is_primary=True,
                raw_label="Apply on SmartRecruiters",
            ))

        company_obj = body.get("company") or summary.get("company") or {}
        raw_company_name = (
            company_obj.get("name") if isinstance(company_obj, dict) else None
        ) or raw.payload.get("company")

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
            ("raw_company_name", raw_company_name),
        ):
            (parsed_fields if value else missing_fields).add(name)

        released = _parse_dt(body.get("releasedDate") or summary.get("releasedDate"))
        updated = _parse_dt(body.get("lastModified")) or released
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=released,
            source_updated_at=updated,
            description=description,
            description_html=description_html,
            raw_company_name=str(raw_company_name) if raw_company_name else None,
            company_external_id=str(raw.payload.get("company") or ""),
            employment_type=emp_type,
            work_arrangement=work_arr,
            raw_location=raw_location,
            city_name_hint=city or None,
            country_code=_country_code(country),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "smartrecruiters", "job": body},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, location=None,
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
        "full-time":  EmploymentType.full_time,
        "permanent":  EmploymentType.full_time,
        "part-time":  EmploymentType.part_time,
        "contract":   EmploymentType.contract,
        "temporary":  EmploymentType.temporary,
        "internship": EmploymentType.internship,
        "intern":     EmploymentType.internship,
    }.get(value.lower())


def _country_code(country: str) -> str:
    """Best-effort country code. Defaults to 'sa' so the FK is satisfied."""
    if not country:
        return "sa"
    lower = country.lower()
    common = {
        "sa": "sa", "saudi arabia": "sa", "ksa": "sa",
        "ae": "ae", "united arab emirates": "ae", "uae": "ae",
    }
    if lower in common:
        return common[lower]
    return "sa"


_ = BaseCrawler
