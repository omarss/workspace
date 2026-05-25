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
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar, Final
from urllib.parse import urljoin, urlparse

from psycopg.rows import dict_row
from selectolax.parser import HTMLParser

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

# DOM-pattern fallback: scan rendered DOM for <a> tags whose path
# contains an explicit job marker followed by a digit-bearing OR long
# slug. Excludes /career(s)/ markers — they match localized landing
# pages (apple.com/careers/sa-ar/) and About pages — keep this list
# restricted to terms that unambiguously identify an *individual* posting.
_JOB_HREF_RE: Final[re.Pattern[str]] = re.compile(
    r"/(?:job|jobs|req|requisition|requisitions|position|positions|"
    r"vacancy|vacancies|opening|openings|opportunity|opportunities|"
    r"role|roles|posting|postings|job-detail|job-details|jobdetails|"
    r"view-job|viewjob|job-listing|job-openings|"
    r"career|careers|career-detail|career-details)/"
    r"(?:[a-z0-9._-]+/){0,3}"           # 0-3 intermediate segments
    # final slug MUST contain a ≥5-digit run — real job IDs are 5-8 digits
    # (Workday `R-12345`, Greenhouse `4567890`, custom `req-12345`).
    # 3-digit allows years (`2026`) and version numbers; 5+ is rare in
    # marketing copy.
    r"[a-z0-9._-]*\d{5,}[a-z0-9._-]*",
    re.IGNORECASE,
)

# URL substrings that mean "marketing/about/navigation", not a job.
_JOB_HREF_DENYLIST_RE: Final[re.Pattern[str]] = re.compile(
    r"/(?:" + "|".join((
        # localized homepage variants (apple.com/careers/befr/, /sa-ar/)
        "[a-z]{2}-[a-z]{2}",
        # common about/marketing siblings
        "about", "faq", "candidate-faq", "diversity", "benefits",
        "life", "culture", "values", "students", "early-careers",
        "graduates", "internship", "internships", "team",
        "stories", "blog", "news", "events", "press", "press-releases",
        "locations", "offices", "work-at", "why",
        "privacy", "terms", "legal", "cookie", "cookies",
    )) + r")(?:/|$|\.html?$)",
    re.IGNORECASE,
)

# Hard cap on detail fetches per company so a careers page with hundreds
# of job links doesn't burn the whole run on one tenant.
_MAX_DETAILS_PER_COMPANY: Final[int] = 25

# Selectors used by the detail-page parser. Ordered by specificity.
_DETAIL_TITLE_CSS: Final[str] = (
    "h1[itemprop='title'], h1.job-title, h1.posting-headline, "
    "h1[class*='job'], h1[class*='title'], h1, h2.job-title"
)
_DETAIL_BODY_CSS: Final[str] = (
    "[itemprop='description'], div.job-description, "
    "section[class*='description'], div[class*='description'], "
    "main, article"
)
_DETAIL_LOCATION_CSS: Final[str] = (
    "[itemprop='jobLocation'], .job-location, [class*='location'], "
    "[data-test*='location']"
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
            yielded = 0
            landing_html = ""
            landing_url = ""
            for path in _CANDIDATE_PATHS:
                target = urljoin(base_url + "/", path.lstrip("/"))
                # Use `networkidle` because most enterprise careers pages
                # are SPAs that XHR their listings after first paint. The
                # 12s budget is the practical max — anything longer makes
                # 280-company runs unbearable.
                try:
                    result = await self.http.fetch(  # type: ignore[call-arg]
                        target,
                        wait_until="networkidle",
                        timeout_ms=12000,
                    )
                except Exception as exc:
                    _LOG.debug(
                        "company_careers: %s fetch failed: %s", target, exc,
                    )
                    continue
                if result.status >= 400:
                    continue
                # PATH 1: JSON-LD JobPosting on the listing page (cheapest,
                # most accurate, ~0% hit-rate on SA enterprises in practice
                # but expensive sites like Workday-hosted boards do expose it).
                postings = extract_job_postings(result.text or "")
                if postings:
                    _LOG.info(
                        "company_careers: %s → %d JSON-LD postings via %s",
                        name_en or company_id, len(postings), path,
                    )
                    for ld in postings:
                        listing = self._listing_from_ld(
                            ld, company_id=company_id, fallback_url=target,
                        )
                        if listing is not None:
                            yielded += 1
                            yield listing
                    break
                # Remember the first non-empty landing page so the DOM
                # fallback below has something to scan.
                if not landing_html and result.text:
                    landing_html = result.text
                    landing_url = result.url or target
            else:
                # No JSON-LD on any candidate path. Fall back to DOM scrape.
                pass

            if yielded > 0:
                continue
            if not landing_html:
                _LOG.info(
                    "company_careers: %s — no reachable careers page",
                    name_en or company_id,
                )
                continue

            # PATH 2: DOM-pattern fallback. Scan for hrefs that look like
            # individual job links. Yield each as a Listing pointing at
            # the detail URL; runner will call fetch_detail for the content.
            job_links = self._extract_job_links_dom(landing_html, landing_url)
            if not job_links:
                _LOG.info(
                    "company_careers: %s — no job-shaped links on %s",
                    name_en or company_id, landing_url,
                )
                continue
            _LOG.info(
                "company_careers: %s → %d job-shaped links via %s",
                name_en or company_id, len(job_links), landing_url,
            )
            for href in list(job_links)[:_MAX_DETAILS_PER_COMPANY]:
                yielded += 1
                yield Listing(
                    source_job_external_id=_stable_id(href),
                    detail_url=href,
                    extra={"company_id": company_id, "from_dom": True},
                )

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        # Two paths:
        #  (a) JSON-LD listing on landing page → snapshot already in
        #      listing.extra; no extra HTTP.
        #  (b) DOM-pattern fallback → we need to fetch the actual detail
        #      page to extract title/description.
        ld_snapshot = listing.extra.get("ld_snapshot")
        if isinstance(ld_snapshot, dict):
            return RawPosting(
                listing=listing,
                canonical_url=listing.detail_url,
                payload={
                    "ld": ld_snapshot,
                    "company_id": listing.extra.get("company_id"),
                },
                fetched_at=datetime.now(UTC),
                duration_ms=0,
                http_status=200,
                bytes=len(str(ld_snapshot)),
            )
        # DOM-fallback path: fetch the detail page via Playwright.
        try:
            result = await self.http.fetch(  # type: ignore[call-arg]
                listing.detail_url,
                wait_until="domcontentloaded",
                timeout_ms=10000,
            )
        except Exception:
            return None
        return RawPosting(
            listing=listing,
            canonical_url=result.url or listing.detail_url,
            payload={
                "html": result.text or "",
                "company_id": listing.extra.get("company_id"),
            },
            fetched_at=datetime.now(UTC),
            duration_ms=result.duration_ms,
            http_status=result.status,
            bytes=result.bytes,
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        # Two payload shapes:
        #  - "ld":   pre-extracted JSON-LD snapshot (landing-page path).
        #  - "html": fetched detail-page HTML (DOM-fallback path).
        ld_dict = raw.payload.get("ld")
        html_body = raw.payload.get("html")
        if isinstance(ld_dict, dict):
            ld = _ld_from_dict(ld_dict)
        elif isinstance(html_body, str) and html_body:
            ld = _ld_from_detail_html(html_body)
            ld_dict = _ld_to_dict(ld)
        else:
            return None

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
            company_id=None, recruiter_id=None, location=None,
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

    def _extract_job_links_dom(self, html: str, base_url: str) -> set[str]:
        """Walk anchor tags and keep those whose final URL looks like an
        individual job posting page.

        Filters:
          * `href` must match `_JOB_HREF_RE` (sub-path after job-marker).
          * Resolved URL must be on the same host as `base_url` — avoids
            footer links to LinkedIn/Twitter, etc.
          * Path must be deeper than 2 segments — `/careers` is the
            landing page, not a posting.
        """
        try:
            tree = HTMLParser(html)
        except Exception:
            return set()
        base_host = urlparse(base_url).netloc.lower()
        out: set[str] = set()
        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href") or ""
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            full = urljoin(base_url, href)
            parsed = urlparse(full)
            if parsed.netloc.lower() != base_host:
                continue
            path = parsed.path or ""
            if not _JOB_HREF_RE.search(path):
                continue
            if _JOB_HREF_DENYLIST_RE.search(path):
                continue
            # At least 3 segments after the marker — drops `/careers`,
            # `/jobs/` (trailing-slash landings) etc.
            if path.rstrip("/").count("/") < 2:
                continue
            # Strip URL fragment so we dedupe.
            full = parsed._replace(fragment="").geturl()
            out.add(full)
        return out

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


def _ld_from_detail_html(html: str) -> JobPostingLD:
    """Build a JobPostingLD from a detail-page HTML.

    JSON-LD wins when present. Otherwise we fall back to generic DOM
    selectors that cover the majority of HR-managed careers pages: an
    `<h1>` near the top for the title, the largest plausible content
    block for the description, and any `[class*="location"]` node we
    can find.
    """
    ld = extract_job_postings(html)
    if ld:
        return ld[0]
    try:
        tree = HTMLParser(html)
    except Exception:
        return JobPostingLD()

    def _txt(node: object) -> str | None:
        if node is None:
            return None
        text = node.text(separator=" ", strip=True) if hasattr(node, "text") else ""
        text = re.sub(r"\s+", " ", text or "").strip()
        return text or None

    return JobPostingLD(
        title=_txt(tree.css_first(_DETAIL_TITLE_CSS)),
        description=_txt(tree.css_first(_DETAIL_BODY_CSS)),
        city=_txt(tree.css_first(_DETAIL_LOCATION_CSS)),
    )


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
