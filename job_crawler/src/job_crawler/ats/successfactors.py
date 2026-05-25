"""SAP SuccessFactors career portal crawler.

Why this matters for SA: most of the largest Saudi employers (Aramco,
SABIC, Ma'aden, STC, NEOM, etc.) host their careers on SF, either on
SF's own subdomains or on a custom domain that proxies through.

Public guest portal pattern (no auth):

    https://career5.successfactors.eu/sfcareer/jobreqcareerpc?company={code}
    https://performancemanager4.successfactors.com/career?company={code}

Per-job detail:
    https://career5.successfactors.eu/sfcareer/jobreqcareerpc?company={code}&jobId={req_id}

Configured via JC_SUCCESSFACTORS_TENANTS (CSV) as `code:host` pairs, e.g.:

    JC_SUCCESSFACTORS_TENANTS=aramco:career5,sabic:performancemanager4,maaden:career5

Hosts known to work:
  * career5            (SF EU pod)
  * career             (SF US pod)
  * performancemanager4 (SF US pod, newer rendering)

Because the SF guest portal returns server-rendered HTML, we use
`selectolax` + a small set of selectors. Selectors live in
PARSE_SELECTORS so an SF rebrand is a one-spot edit.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Final

from selectolax.parser import HTMLParser

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

_LOG: Final = logging.getLogger("job_crawler.successfactors")


@dataclass(frozen=True, slots=True)
class _Tenant:
    code: str            # company code in the URL, e.g. "aramco"
    host: str = "career5"  # SF pod prefix

    @property
    def list_url(self) -> str:
        return (f"https://{self.host}.successfactors.eu/sfcareer/jobreqcareerpc"
                f"?company={self.code}&lang=en_US")

    def detail_url(self, req_id: str) -> str:
        return (f"https://{self.host}.successfactors.eu/sfcareer/jobreqcareerpc"
                f"?company={self.code}&jobId={req_id}&lang=en_US")


class SuccessFactorsCrawler(ATSBoardCrawler):
    source_slug: ClassVar[str] = "successfactors"
    source_display_name: ClassVar[str] = "SuccessFactors"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://career5.successfactors.eu"
    source_trust_weight: ClassVar[float] = 0.90
    rate: ClassVar[RateConfig] = RateConfig(max_rps=3.0, burst=8, max_concurrent=4, timeout_seconds=30.0, user_agent=IDENTIFIABLE_UA)
    # No public canary URL — SF guest portals are vendor-specific.
    canary_urls: ClassVar[tuple[str, ...]] = ()

    # Default SA mega-employer tenants. Each is `code:host`. SF tenant codes
    # are vendor-assigned (not obvious from the company name) — these are
    # *best guesses* that need confirming per employer. Override via
    # JC_SUCCESSFACTORS_TENANTS once you've confirmed each one's portal URL.
    # Leaving empty by default avoids burning cycles on bad guesses.
    default_tenants: ClassVar[tuple[str, ...]] = ()

    # Selectors centralised so SF tweaks are one-spot edits.
    PARSE_SELECTORS: ClassVar[dict[str, str]] = {
        "result_row":    "tr.jobResultsItem, div.jobResultsItem, a[id^='jobLink']",
        "result_link":   "a[id^='jobLink'], a.jobTitle",
        "result_title":  "a[id^='jobLink'], a.jobTitle, .jobTitleColumn",
        "result_location": ".jobLocationColumn, .jobLocation",
        "result_posted": ".jobPostedDate, .postedDate",
        "detail_title":  "#jobreqTitleContainer h1, h1.jobTitle, #jobTitle",
        "detail_loc":    "#jobreqLocationContainer, .jobLocation",
        "detail_body":   "#jobreqDescriptionContainer, .jobDescription, .jobDetails",
        "apply_link":    "a#applyButton, a[href*='applycareerssite'], a.applyButton",
    }
    _JOB_ID_RE: ClassVar[re.Pattern[str]] = re.compile(r"jobId=([0-9]+)")

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        env_raw = os.environ.get("JC_SUCCESSFACTORS_TENANTS", "")
        tenants = _parse_tenants(env_raw or ",".join(self.default_tenants))
        for t in tenants:
            try:
                result = await self.http.fetch(t.list_url)
            except Exception as exc:
                _LOG.warning("SF tenant %s fetch failed: %s", t.code, exc)
                continue
            tree = HTMLParser(result.text)
            anchors = tree.css(self.PARSE_SELECTORS["result_link"])
            if not anchors:
                _LOG.info("SF tenant %s: no job links on page (selectors stale?)",
                          t.code)
                continue
            seen_ids: set[str] = set()
            for a in anchors:
                href = a.attributes.get("href") or ""
                m = self._JOB_ID_RE.search(href)
                if not m:
                    continue
                req_id = m.group(1)
                if req_id in seen_ids:
                    continue
                seen_ids.add(req_id)
                yield Listing(
                    source_job_external_id=req_id,
                    detail_url=t.detail_url(req_id),
                    extra={"tenant": t, "title_hint": a.text(strip=True) or None},
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        try:
            result = await self.http.fetch(listing.detail_url)
        except Exception:
            return None
        return RawPosting(
            listing=listing,
            canonical_url=result.url,
            payload={"html": result.text, "tenant": listing.extra.get("tenant"),
                     "title_hint": listing.extra.get("title_hint")},
            fetched_at=datetime.now(UTC),
            duration_ms=result.duration_ms,
            http_status=result.status,
            bytes=result.bytes,
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        html = raw.payload.get("html")
        if not isinstance(html, str):
            return None
        tree = HTMLParser(html)

        title_node = tree.css_first(self.PARSE_SELECTORS["detail_title"])
        title = title_node.text(strip=True) if title_node else (raw.payload.get("title_hint") or "")
        if not title:
            return None

        loc_node = tree.css_first(self.PARSE_SELECTORS["detail_loc"])
        body_node = tree.css_first(self.PARSE_SELECTORS["detail_body"])
        apply_node = tree.css_first(self.PARSE_SELECTORS["apply_link"])

        raw_location = loc_node.text(strip=True) if loc_node else None
        description_html = body_node.html if body_node else None
        description = body_node.text(separator="\n", strip=True) if body_node else None

        channels: list[ApplicationChannelRaw] = []
        if apply_node is not None:
            href = apply_node.attributes.get("href") or ""
            channels.append(ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=href or raw.canonical_url,
                is_primary=True,
                raw_label=apply_node.text(strip=True) or "Apply",
            ))

        tenant: _Tenant | None = raw.payload.get("tenant")
        raw_company_name = tenant.code.replace("-", " ").title() if tenant else None

        # SF pages embed the post date in plain text; best-effort regex.
        posted_at = _extract_post_date(html)

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", description),
            ("raw_location", raw_location),
        ):
            (parsed_fields if value else missing_fields).add(name)

        external_id = raw.listing.source_job_external_id
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=posted_at,
            description=description,
            description_html=description_html,
            raw_company_name=raw_company_name,
            company_external_id=tenant.code if tenant else None,
            employment_type=EmploymentType.full_time,
            work_arrangement=_arrangement(raw_location, description),
            raw_location=raw_location,
            city_name_hint=_city_hint(raw_location),
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "successfactors", "html_bytes": len(html)},
        )
# ---- helpers --------------------------------------------------------------
def _parse_tenants(raw: str) -> tuple[_Tenant, ...]:
    """Parse 'aramco:career5,sabic:performancemanager4' into tenants."""
    out: list[_Tenant] = []
    for spec in (x.strip() for x in raw.split(",") if x.strip()):
        parts = spec.split(":")
        if len(parts) == 1:
            out.append(_Tenant(code=parts[0]))
        elif len(parts) >= 2:
            out.append(_Tenant(code=parts[0], host=parts[1]))
    return tuple(out)


_POST_DATE_RE = re.compile(
    r"(?:Posted|Date Posted|تاريخ النشر)[:\s]+([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
    re.IGNORECASE,
)


def _extract_post_date(html: str) -> datetime | None:
    m = _POST_DATE_RE.search(html)
    if not m:
        return None
    raw = m.group(1).replace("-", "/")
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _arrangement(loc: str | None, desc: str | None) -> WorkArrangement | None:
    blob = " ".join(x for x in (loc, desc) if x).lower()
    if not blob:
        return None
    if "remote" in blob:
        return WorkArrangement.remote
    if "hybrid" in blob:
        return WorkArrangement.hybrid
    return WorkArrangement.onsite


def _city_hint(raw_location: str | None) -> str | None:
    if not raw_location:
        return None
    head = raw_location.split(",")[0].strip()
    return head or None


_ = BaseCrawler
