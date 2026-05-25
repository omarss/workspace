"""Company-careers Playwright crawler — the long-tail SA employers.

Why this exists
---------------
The CSV seeds ~330 SA-headquartered employers; only ~6 of them surface in
Bayt or on an off-the-shelf ATS (Greenhouse / Workable / Lever). The
other ~280 host their job board on their own website. They're invisible
to every other crawler in the registry.

This crawler walks `companies` rows whose `website` is set but whose
`company_source_profiles` table has no entry yet, navigates each
company's careers page with Playwright, and harvests JSON-LD JobPosting
schemas off the rendered DOM.

Coverage strategy
-----------------
For each company we try a small ordered set of plausible career paths
(`/careers`, `/careers/jobs`, `/jobs`, `/career`, `/join-us`,
`/work-with-us`) — stopping at the first that returns at least one
JSON-LD JobPosting. Sites without JSON-LD remain invisible to this
crawler (they need a per-tenant scraper); ~30-50% of SA enterprise
careers pages do embed JSON-LD for SEO so the yield uplift is meaningful.

Configured via:
    JC_COMPANY_CAREERS_LIMIT  — cap on companies probed per run (default 200)
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar, Final
from urllib.parse import urljoin, urlparse

from psycopg.rows import dict_row

from job_crawler_db import (
    ApplicationChannelKind,
    SourceKind,
)

from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.jsonld import JobPostingLD, extract_job_postings
from ..core.types import (
    ApplicationChannelRaw,
    Listing,
    ParsedPosting,
    RawPosting,
)
from ._base import BoardCrawler

_LOG: Final = logging.getLogger("job_crawler.company_careers")

# Paths to try, in order. First one that returns >=1 JobPosting wins.
_CANDIDATE_PATHS: Final[tuple[str, ...]] = (
    "/careers",
    "/careers/jobs",
    "/careers/open-positions",
    "/jobs",
    "/job-opportunities",
    "/career",
    "/career/jobs",
    "/join-us",
    "/work-with-us",
    "/en/careers",
    "/en/jobs",
)


class CompanyCareersCrawler(BoardCrawler):
    source_slug: ClassVar[str] = "company_careers"
    source_display_name: ClassVar[str] = "Company Careers (own site)"
    source_kind: ClassVar[SourceKind] = SourceKind.company_site
    source_base_url: ClassVar[str] = "https://example.invalid"
    source_trust_weight: ClassVar[float] = 0.95  # employer-owned is authoritative
    rate: ClassVar[RateConfig] = RateConfig(
        max_rps=2.0, burst=4, max_concurrent=2,
        timeout_seconds=25.0, user_agent=IDENTIFIABLE_UA,
    )
    canary_urls: ClassVar[tuple[str, ...]] = ()
    # Playwright is essential — most enterprise careers pages are SPAs
    # that hydrate their listings client-side; a raw HTML fetch returns
    # an empty shell or boilerplate.
    use_playwright: ClassVar[bool] = True

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        if self.db is None:
            return
        limit = int(os.environ.get("JC_COMPANY_CAREERS_LIMIT", "200"))

        companies = await self._companies_to_probe(limit)
        _LOG.info("company_careers: probing %d companies", len(companies))

        for company_id, name_en, website in companies:
            base_url = self._normalize_homepage(website)
            if not base_url:
                continue
            yielded_for_company = 0
            for path in _CANDIDATE_PATHS:
                target = urljoin(base_url + "/", path.lstrip("/"))
                try:
                    # Short per-path timeout. We do NOT wait on the JSON-LD
                    # selector — many pages render it inline via SSR; we
                    # only need the DOM committed. networkidle would be
                    # nicer for SPAs but blows the per-company budget out
                    # of the water (the 280-row tail has many slow sites).
                    result = await self.http.fetch(  # type: ignore[call-arg]
                        target,
                        wait_until="domcontentloaded",
                        timeout_ms=8000,
                    )
                except Exception as exc:
                    _LOG.debug(
                        "company_careers: %s fetch failed: %s", target, exc,
                    )
                    continue
                if result.status >= 400:
                    continue
                postings = extract_job_postings(result.text or "")
                if not postings:
                    continue
                _LOG.info(
                    "company_careers: %s → %d JSON-LD postings via %s",
                    name_en or company_id, len(postings), path,
                )
                for ld in postings:
                    listing = self._listing_from_ld(
                        ld, company_id=company_id, fallback_url=target,
                    )
                    if listing is not None:
                        yielded_for_company += 1
                        yield listing
                # First path with postings wins; skip the remaining ones.
                break
            if yielded_for_company == 0:
                _LOG.info(
                    "company_careers: %s — no JSON-LD postings on %d paths",
                    name_en or company_id, len(_CANDIDATE_PATHS),
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        # The listing already carries the full JSON-LD posting; no extra
        # HTTP needed. We pack it into payload so parse() picks it up.
        ld_snapshot = listing.extra.get("ld_snapshot")
        if not isinstance(ld_snapshot, dict):
            return await super().fetch_detail(listing)
        return RawPosting(
            listing=listing,
            canonical_url=listing.detail_url,
            payload={"ld": ld_snapshot, "company_id": listing.extra.get("company_id")},
            fetched_at=datetime.now(UTC),
            duration_ms=0,
            http_status=200,
            bytes=len(str(ld_snapshot)),
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        ld_dict = raw.payload.get("ld")
        if not isinstance(ld_dict, dict):
            return None
        # Re-hydrate JobPostingLD from the snapshot so we go through the
        # same field-coercion path as detail-page scrapers.
        ld = _ld_from_dict(ld_dict)
        external_id = str(raw.payload.get("external_id") or "").strip() or (
            _stable_id(raw.canonical_url)
        )
        title = ld.title
        if not title:
            return None

        raw_location = _join_location(ld)
        company_id_str = raw.payload.get("company_id")

        channels: list[ApplicationChannelRaw] = [
            ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=raw.canonical_url,
                is_primary=True,
                raw_label="Apply on company site",
            ),
        ]

        parsed_fields = {"title"}
        missing_fields: set[str] = set()
        for name, value in (
            ("description", ld.description),
            ("raw_location", raw_location),
            ("raw_company_name", ld.company_name),
        ):
            (parsed_fields if value else missing_fields).add(name)

        # Stash the upstream company-id on company_external_id so the
        # runner's company resolver hits the same employer entity without
        # re-running string similarity.
        return ParsedPosting(
            source_job_external_id=external_id,
            canonical_url=raw.canonical_url,
            title=title,
            posted_at=ld.posted_at,
            source_updated_at=ld.posted_at,
            expires_at=ld.valid_through,
            description=ld.description,
            description_html=None,
            raw_company_name=ld.company_name,
            company_external_id=(
                company_id_str if isinstance(company_id_str, str) else None
            ),
            employment_type=ld.employment_type,
            min_experience_years=ld.min_experience_years,
            raw_location=raw_location,
            city_name_hint=ld.city,
            country_code=(ld.country or "").lower()[:2] or "sa",
            salary_min=ld.salary_min,
            salary_max=ld.salary_max,
            salary_currency=ld.salary_currency,
            salary_period=ld.salary_period,
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "company_careers", "ld": ld_dict},
        )

    def normalize(self, parsed: ParsedPosting):  # type: ignore[override]
        from ..core.normalise import to_upsert

        return to_upsert(
            parsed,
            source_id=__import__("uuid").UUID(int=0),
            company_id=None, recruiter_id=None, city_id=None,
        )

    # ------------------------------------------------------------------
    async def _companies_to_probe(
        self, limit: int,
    ) -> list[tuple[str, str, str]]:
        """Return (id, name_en, website) for companies whose careers page
        we haven't successfully crawled before.

        Selection rules:
          * `website` populated.
          * No row in `company_source_profiles` (we'd have an ATS path otherwise).
          * Order by name for stability — easy to resume after a kill.
        """
        if self.db is None:
            return []
        async with self.db.pool.connection() as conn, conn.cursor(
            row_factory=dict_row,
        ) as cur:
            await cur.execute(
                """
                SELECT c.id::text AS id, c.name_en, c.website
                FROM   companies c
                WHERE  c.website IS NOT NULL AND c.website <> ''
                  AND  c.deleted_at IS NULL
                  AND  NOT EXISTS (
                         SELECT 1 FROM company_source_profiles csp
                         WHERE csp.company_id = c.id
                       )
                ORDER BY c.name_en
                LIMIT %s
                """,
                (limit,),
            )
            rows = await cur.fetchall()
        return [(r["id"], r["name_en"] or "", r["website"]) for r in rows]

    def _normalize_homepage(self, website: str) -> str | None:
        """Take whatever the CSV captured (e.g. `aramco.com`,
        `https://example.com/`) and return a usable origin or None."""
        if not website:
            return None
        url = website.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        parsed = urlparse(url)
        if not parsed.netloc:
            return None
        # Rebuild without path/query so urljoin behaves predictably.
        return f"{parsed.scheme}://{parsed.netloc}"

    def _listing_from_ld(
        self,
        ld: JobPostingLD,
        *,
        company_id: str,
        fallback_url: str,
    ) -> Listing | None:
        if not ld.title:
            return None
        detail_url = _ld_url(ld) or fallback_url
        external_id = _stable_id(detail_url)
        return Listing(
            source_job_external_id=external_id,
            detail_url=detail_url,
            posted_at_hint=ld.posted_at,
            extra={
                "ld_snapshot": _ld_to_dict(ld),
                "external_id": external_id,
                "company_id": company_id,
            },
        )


# ---- helpers --------------------------------------------------------------
def _stable_id(url: str) -> str:
    """Deterministic id for a posting URL — survives across runs."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]


def _join_location(ld: JobPostingLD) -> str | None:
    parts = [p for p in (ld.city, ld.region, ld.country) if p]
    return ", ".join(parts) if parts else None


def _ld_url(ld: JobPostingLD) -> str | None:
    """JSON-LD often carries a `url` or `hiringOrganization.sameAs` field
    pointing to the canonical apply page. We don't currently capture it
    on `JobPostingLD`; treat the careers page URL as canonical for now."""
    return None


def _ld_to_dict(ld: JobPostingLD) -> dict[str, object]:
    """Snapshot a JobPostingLD into a primitive dict so it survives the
    runner's payload serialisation. The reverse `_ld_from_dict` rebuilds
    a JobPostingLD with the same fields."""
    return {
        "title": ld.title,
        "description": ld.description,
        "posted_at": ld.posted_at.isoformat() if ld.posted_at else None,
        "valid_through": ld.valid_through.isoformat() if ld.valid_through else None,
        "employment_type": ld.employment_type.value if ld.employment_type else None,
        "min_experience_years": ld.min_experience_years,
        "salary_min": str(ld.salary_min) if ld.salary_min is not None else None,
        "salary_max": str(ld.salary_max) if ld.salary_max is not None else None,
        "salary_currency": ld.salary_currency,
        "salary_period": ld.salary_period.value if ld.salary_period else None,
        "company_name": ld.company_name,
        "company_url": ld.company_url,
        "city": ld.city,
        "region": ld.region,
        "country": ld.country,
    }


def _ld_from_dict(snapshot: dict[str, object]) -> JobPostingLD:
    """Reverse of `_ld_to_dict` — best-effort, ignores unknown keys."""
    from decimal import Decimal

    from job_crawler_db import EmploymentType, SalaryPeriod

    def _dec(value: object) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    def _dt(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    return JobPostingLD(
        title=_str(snapshot.get("title")),
        description=_str(snapshot.get("description")),
        posted_at=_dt(snapshot.get("posted_at")),
        valid_through=_dt(snapshot.get("valid_through")),
        employment_type=(
            EmploymentType(snapshot["employment_type"])  # type: ignore[arg-type]
            if isinstance(snapshot.get("employment_type"), str) else None
        ),
        min_experience_years=(
            int(snapshot["min_experience_years"])  # type: ignore[arg-type]
            if isinstance(snapshot.get("min_experience_years"), int) else None
        ),
        salary_min=_dec(snapshot.get("salary_min")),
        salary_max=_dec(snapshot.get("salary_max")),
        salary_currency=_str(snapshot.get("salary_currency")),
        salary_period=(
            SalaryPeriod(snapshot["salary_period"])  # type: ignore[arg-type]
            if isinstance(snapshot.get("salary_period"), str) else None
        ),
        company_name=_str(snapshot.get("company_name")),
        company_url=_str(snapshot.get("company_url")),
        city=_str(snapshot.get("city")),
        region=_str(snapshot.get("region")),
        country=_str(snapshot.get("country")),
    )


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None
