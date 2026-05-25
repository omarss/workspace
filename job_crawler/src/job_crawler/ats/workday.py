"""Workday (myworkdayjobs.com) crawler.

Workday's public guest portal speaks a POST-based JSON API.

URL shape (varies by Workday hosting cluster — wd1 / wd3 / wd5 / wd103):
    POST https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    Body: {"appliedFacets": {}, "limit": 20, "offset": <n>, "searchText": ""}

The response carries summaries + `externalPath`; the per-job detail is at:
    GET https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}

Configured via JC_WORKDAY_TENANTS (CSV) with tuples in `tenant:site:host`
form, e.g.:

    JC_WORKDAY_TENANTS=accenture:Accenture_Careers:wd5,pepsico:PepsiCo:wd5
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
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

_LOG: Final = logging.getLogger("job_crawler.workday")


@dataclass(frozen=True, slots=True)
class _Tenant:
    tenant: str   # subdomain (also used inside the URL path)
    site: str    # career site name (e.g. "External", "Accenture_Careers")
    host: str = "wd5"

    @property
    def list_url(self) -> str:
        return (f"https://{self.tenant}.{self.host}.myworkdayjobs.com"
                f"/wday/cxs/{self.tenant}/{self.site}/jobs")

    def detail_url(self, external_path: str) -> str:
        return (f"https://{self.tenant}.{self.host}.myworkdayjobs.com"
                f"/wday/cxs/{self.tenant}/{self.site}{external_path}")


class WorkdayCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "workday"
    source_display_name: ClassVar[str] = "Workday"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://myworkdayjobs.com"
    source_trust_weight: ClassVar[float] = 0.92
    rate: ClassVar[RateConfig] = RateConfig(max_rps=4.0, burst=8, max_concurrent=4, timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA)
    # No public canary URL — Workday tenants are vendor-specific.
    canary_urls: ClassVar[tuple[str, ...]] = ()

    PAGE_SIZE: ClassVar[int] = 20

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        tenants = _parse_tenants(os.environ.get("JC_WORKDAY_TENANTS", ""))
        for t in tenants:
            offset = 0
            while True:
                body = {
                    "appliedFacets": {},
                    "limit": self.PAGE_SIZE,
                    "offset": offset,
                    "searchText": "",
                }
                try:
                    result = await self.http.fetch(
                        t.list_url, method="POST", json_body=body,
                        headers={"Accept": "application/json",
                                 "Content-Type": "application/json"},
                    )
                except Exception as exc:
                    _LOG.warning("workday %s/%s POST failed: %s",
                                 t.tenant, t.site, exc)
                    break
                page = result.json or {}
                postings = page.get("jobPostings") or []
                if not postings:
                    break
                for job in postings:
                    posted = _parse_posted_on(job.get("postedOn"))
                    if posted and posted < since:
                        continue
                    ext_path = str(job.get("externalPath") or "")
                    if not ext_path:
                        continue
                    yield Listing(
                        source_job_external_id=ext_path.rsplit("/", 1)[-1],
                        detail_url=t.detail_url(ext_path),
                        posted_at_hint=posted,
                        extra={"tenant": t, "summary": job},
                    )
                offset += self.PAGE_SIZE
                # Defensive cap; Workday returns total but we trust postings list.
                if offset >= int(page.get("total", 0)) or offset >= 1000:
                    break

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        try:
            result = await self.http.fetch(
                listing.detail_url,
                headers={"Accept": "application/json"},
            )
        except Exception:
            return None
        body = result.json or {}
        return RawPosting(
            listing=listing,
            canonical_url=result.url,
            payload={"json": body, "summary": listing.extra.get("summary"),
                     "tenant": listing.extra.get("tenant")},
            fetched_at=datetime.now(UTC),
            duration_ms=result.duration_ms,
            http_status=result.status,
            bytes=result.bytes,
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        body = raw.payload.get("json") or {}
        summary = raw.payload.get("summary") or {}
        tenant: _Tenant | None = raw.payload.get("tenant")
        info = (body.get("jobPostingInfo") or {}) if isinstance(body, dict) else {}

        external_id = str(info.get("id") or summary.get("bulletFields", [None])[0] or "")
        title = (info.get("title") or summary.get("title") or "").strip()
        if not external_id or not title:
            return None

        description_html = info.get("jobDescription") or None
        description = _strip_html(description_html) if description_html else None

        raw_location = (info.get("location") or summary.get("locationsText") or "").strip() or None
        remote = bool(info.get("remoteType") and "remote" in info["remoteType"].lower())
        work_arr = (
            WorkArrangement.remote if remote else
            WorkArrangement.hybrid if raw_location and "hybrid" in raw_location.lower() else
            WorkArrangement.onsite if raw_location else None
        )

        emp_type_str = (info.get("timeType") or "").lower()
        emp_type = (
            EmploymentType.full_time if "full" in emp_type_str
            else EmploymentType.part_time if "part" in emp_type_str
            else None
        )

        apply_url = (
            info.get("externalUrl")
            or (tenant.detail_url(str(info.get("externalPath", ""))) if tenant else raw.canonical_url)
        )
        channels: list[ApplicationChannelRaw] = []
        if apply_url:
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=apply_url, is_primary=True,
                raw_label="Apply on Workday",
            ))

        raw_company_name = tenant.tenant.replace("-", " ").title() if tenant else None

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
        ):
            (parsed_fields if value else missing_fields).add(name)

        posted = _parse_posted_on(info.get("postedOn") or summary.get("postedOn"))
        # Workday returns startDate/endDate ISO dates on info.
        from datetime import datetime as _dt

        def _iso(value: object) -> _dt | None:
            if not isinstance(value, str) or not value:
                return None
            try:
                return _dt.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None

        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=_iso(info.get("startDate")) or posted,
            source_updated_at=_iso(info.get("postedDate") or info.get("startDate")) or posted,
            expires_at=_iso(info.get("endDate")),
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            company_external_id=tenant.tenant if tenant else None,
            employment_type=emp_type,
            work_arrangement=work_arr,
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "workday", "job": info},
        )
# ---- helpers --------------------------------------------------------------
def _parse_tenants(raw: str) -> tuple[_Tenant, ...]:
    """Parse a CSV like 'accenture:Accenture_Careers:wd5,pepsico:PepsiCo:wd5'."""
    out: list[_Tenant] = []
    for spec in (x.strip() for x in raw.split(",") if x.strip()):
        parts = spec.split(":")
        if len(parts) == 2:
            out.append(_Tenant(tenant=parts[0], site=parts[1]))
        elif len(parts) == 3:
            out.append(_Tenant(tenant=parts[0], site=parts[1], host=parts[2]))
    return tuple(out)


def _parse_posted_on(value: object) -> datetime | None:
    """Workday returns 'postedOn' as 'Posted 2 Days Ago' or ISO. Best-effort."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        pass
    # Loose "Posted X (Day|Hour|Minute)s Ago"
    import re
    from datetime import timedelta
    m = re.search(r"(\d+)\s*(day|hour|minute)s?\s*ago", value, re.IGNORECASE)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = {"minute": timedelta(minutes=n),
             "hour":   timedelta(hours=n),
             "day":    timedelta(days=n)}.get(unit, timedelta())
    return datetime.now(UTC) - delta


def _strip_html(html: str) -> str:
    from selectolax.parser import HTMLParser

    return HTMLParser(html).text(separator="\n", strip=True)


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    head = raw_location.split(",")[0].strip()
    return head or None


_ = BaseCrawler
