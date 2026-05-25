"""Personio crawler.

Public, unauthenticated XML feed per tenant:
    https://{tenant}.jobs.personio.com/xml

Returns `<workzag-jobs>` with `<position>` per job. Each position carries:
    id, name (title), office + additionalOffices, jobDescriptions,
    employmentType, schedule, seniority, yearsOfExperience, createdAt.

The XML feed is the cheapest path; the human-readable page at
`/job/{id}` adds the same description, so we skip the detail fetch
unless a board explicitly opts in (forthcoming as needed).

Configured via JC_PERSONIO_BOARDS (CSV of subdomains).
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar, Final

from job_crawler_db import (
    ApplicationChannelKind,
    EmploymentType,
    ExperienceLevel,
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

_LOG: Final = logging.getLogger("job_crawler.personio")


class PersonioCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "personio"
    source_display_name: ClassVar[str] = "Personio"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://jobs.personio.com"
    source_trust_weight: ClassVar[float] = 0.92
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=4.0, burst=8, max_concurrent=4,
        timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = (
        "https://personio.jobs.personio.com/xml",
    )
    boards_env_var: ClassVar[str] = "JC_PERSONIO_BOARDS"
    # No verified-live SA tenants known at implementation time. Populate via
    # `make discover-ats` (which scrapes company homepages for personio
    # links) or set the env var manually.
    default_boards: ClassVar[tuple[str, ...]] = ()

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        boards = await self.boards()
        for slug in boards:
            url = f"https://{slug}.jobs.personio.com/xml"
            try:
                result = await self.http.fetch(url)
            except Exception as exc:
                _LOG.warning("personio tenant %s fetch failed: %s", slug, exc)
                continue
            text = result.text or ""
            try:
                root = ET.fromstring(text)
            except ET.ParseError as exc:
                _LOG.warning("personio tenant %s xml parse failed: %s", slug, exc)
                continue
            for position in root.findall("position"):
                pid = _txt(position, "id")
                if not pid:
                    continue
                created = _parse_dt(_txt(position, "createdAt"))
                if created and created < since:
                    continue
                # Build the human-readable apply URL from the slug + id.
                detail_url = f"https://{slug}.jobs.personio.com/job/{pid}"
                yield Listing(
                    source_job_external_id=str(pid),
                    detail_url=detail_url,
                    posted_at_hint=created,
                    extra={
                        # ET.Element doesn't serialise cheaply — convert to a
                        # simple dict so the rest of the pipeline stays
                        # dict-shaped like every other ATS.
                        "position": _element_to_dict(position),
                        "board_slug": slug,
                    },
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        pos = listing.extra.get("position")
        if not isinstance(pos, dict):
            return await super().fetch_detail(listing)
        return RawPosting(
            listing=listing,
            canonical_url=listing.detail_url,
            payload={"position": pos, "board_slug": listing.extra.get("board_slug")},
            fetched_at=datetime.now(UTC),
            duration_ms=0, http_status=200, bytes=len(str(pos)),
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        pos = raw.payload.get("position")
        if not isinstance(pos, dict):
            return None
        external_id = str(pos.get("id") or "").strip()
        title = (pos.get("name") or "").strip()
        if not external_id or not title:
            return None

        office = (pos.get("office") or "").strip()
        extra_offices = pos.get("additionalOffices") or []
        if isinstance(extra_offices, list):
            extra = ", ".join(o for o in extra_offices if isinstance(o, str))
        else:
            extra = ""
        raw_location = ", ".join(p for p in (office, extra) if p) or None

        # Personio `jobDescriptions` is a structured list of {name, value}.
        descriptions = pos.get("jobDescriptions") or []
        if isinstance(descriptions, list):
            html_parts = []
            for chunk in descriptions:
                if not isinstance(chunk, dict):
                    continue
                name = chunk.get("name") or ""
                value = chunk.get("value") or ""
                if name and value:
                    html_parts.append(f"<h3>{name}</h3>\n{value}")
                elif value:
                    html_parts.append(value)
            description_html = "\n\n".join(html_parts).strip() or None
        else:
            description_html = None
        description = _strip_html(description_html) if description_html else None

        # Apply URL = the detail URL (Personio's career portal handles apply).
        channels: list[ApplicationChannelRaw] = [
            ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=raw.canonical_url,
                is_primary=True,
                raw_label="Apply on Personio",
            )
        ]

        board_slug = raw.payload.get("board_slug")
        # Personio's `subcompany` field carries the employer's display name
        # when set; fall back to the slug.
        raw_company_name = (pos.get("subcompany") or "").strip() or (
            str(board_slug).replace("-", " ").title() if board_slug else None
        )

        emp_type = _employment(
            str(pos.get("schedule") or pos.get("employmentType") or "").lower()
        )
        experience = _experience_level(
            str(pos.get("seniority") or pos.get("yearsOfExperience") or "").lower(),
        )
        work_arr = _arrangement(raw_location)

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
            ("raw_company_name", raw_company_name),
        ):
            (parsed_fields if value else missing_fields).add(name)

        posted_dt = _parse_dt(pos.get("createdAt"))
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=posted_dt,
            source_updated_at=posted_dt,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            company_external_id=str(board_slug) if board_slug else None,
            employment_type=emp_type,
            experience_level=experience,
            work_arrangement=work_arr,
            raw_location=raw_location,
            city_name_hint=office or None,
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "personio", "position": pos},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, city_id=None,
        )


# ---- helpers --------------------------------------------------------------
def _txt(element: ET.Element, tag: str) -> str:
    """Return the text of `element/tag` or empty string."""
    node = element.find(tag)
    return (node.text or "").strip() if node is not None and node.text is not None else ""


def _element_to_dict(element: ET.Element) -> dict[str, object]:
    """Lossy conversion: scalars stay scalar; repeated children become lists."""
    out: dict[str, object] = {}
    for child in element:
        tag = child.tag
        if tag == "additionalOffices":
            offices = [(o.text or "").strip() for o in child.findall("office")]
            out[tag] = [o for o in offices if o]
        elif tag == "jobDescriptions":
            chunks = []
            for jd in child.findall("jobDescription"):
                name = (jd.findtext("name") or "").strip()
                value = (jd.findtext("value") or "").strip()
                chunks.append({"name": name, "value": value})
            out[tag] = chunks
        else:
            out[tag] = (child.text or "").strip()
    return out


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
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
        "full-time": EmploymentType.full_time,
        "full_time": EmploymentType.full_time,
        "fulltime": EmploymentType.full_time,
        "permanent": EmploymentType.full_time,
        "part-time": EmploymentType.part_time,
        "part_time": EmploymentType.part_time,
        "parttime": EmploymentType.part_time,
        "fixed-term": EmploymentType.contract,
        "fixed_term": EmploymentType.contract,
        "contractor": EmploymentType.contract,
        "internship": EmploymentType.internship,
        "intern": EmploymentType.internship,
        "temporary": EmploymentType.temporary,
        "trainee": EmploymentType.internship,
    }.get(value)


_YEARS_RE: Final[re.Pattern[str]] = re.compile(r"(\d+)\s*-\s*(\d+)")


def _experience_level(value: str) -> ExperienceLevel | None:
    """Map Personio's `seniority` or year-range hint to our enum."""
    if not value:
        return None
    m = {
        "student": ExperienceLevel.entry,
        "entry": ExperienceLevel.entry,
        "entry-level": ExperienceLevel.entry,
        "junior": ExperienceLevel.entry,
        "experienced": ExperienceLevel.mid,
        "professional": ExperienceLevel.mid,
        "senior": ExperienceLevel.senior,
        "lead": ExperienceLevel.lead,
        "manager": ExperienceLevel.manager,
        "director": ExperienceLevel.director,
        "executive": ExperienceLevel.executive,
    }
    hit = m.get(value)
    if hit is not None:
        return hit
    # Year-range hint like "5-7" or "lt-1"
    match = _YEARS_RE.search(value)
    if match:
        lo = int(match.group(1))
        if lo < 2:
            return ExperienceLevel.entry
        if lo < 5:
            return ExperienceLevel.mid
        if lo < 8:
            return ExperienceLevel.senior
        return ExperienceLevel.lead
    return None


def _arrangement(raw_location: str | None) -> WorkArrangement | None:
    if not raw_location:
        return None
    lower = raw_location.lower()
    if "remote" in lower:
        return WorkArrangement.remote
    if "hybrid" in lower:
        return WorkArrangement.hybrid
    return WorkArrangement.onsite
