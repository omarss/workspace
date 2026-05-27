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
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Final, cast
from urllib.parse import urljoin, urlparse

from psycopg.rows import dict_row
from selectolax.parser import HTMLParser

from job_crawler_db import (
    ApplicationChannelKind,
    SourceKind,
)

from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.jsonld import JobPostingLD, extract_job_postings
from ..core.normalise import coerce_country_code
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

# Detail-page body extractors on .gov.sa templates (KKU was the live
# example) latch onto the SA-government "verification banner" — a
# 12k-char Arabic disclaimer that wraps the main content. The DOM
# selectors can't tell it apart from real content, so we filter on the
# distinctive opening phrase: "Official government site affiliated
# with the Government of the Kingdom of Saudi Arabia".
_SA_GOV_BOILERPLATE_PREFIX: Final[str] = (
    "موقع حكومي رسمي تابع لحكومة المملكة العربية السعودية"
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
    # Multinationals' career sites (DXC, Cisco, Accenture, ...) serve
    # *global* postings even when we seeded the SA-region URL. The runner's
    # GCC-only geo filter drops anything whose `raw_location` isn't a GCC
    # country, preventing Melbourne/Bangalore/Eschborn rows from polluting
    # the SA-focused corpus.
    requires_gcc_location: ClassVar[bool] = True
    # Same rationale as `ATSBoardCrawler`: companies' careers pages list
    # actively-hiring roles only, so the `JC_LOOKBACK_DAYS` date window
    # would over-drop. Treat "first seen by us" as the freshness signal;
    # `telegram_broadcasts` prevents re-broadcasting on subsequent runs.
    requires_recent_posted_at: ClassVar[bool] = False

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        if self.db is None:
            return
        limit = int(os.environ.get("JC_COMPANY_CAREERS_LIMIT", "200"))

        companies = await self._companies_to_probe(limit)
        seeded = sum(1 for c in companies if c[3] == "seed")
        _LOG.info(
            "company_careers: %d companies (%d seeded, %d homepage-probe)",
            len(companies), seeded, len(companies) - seeded,
        )

        for company_id, name_en, candidate_urls, kind in companies:
            _LOG.debug(
                "company_careers: %s [%s] %d candidate URL(s)",
                name_en or company_id, kind, len(candidate_urls),
            )
            yielded = 0
            landing_html = ""
            landing_url = ""
            for target in candidate_urls:
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
                        name_en or company_id, len(postings), target,
                    )
                    for ld in postings:
                        listing = self._listing_from_ld(
                            ld,
                            company_id=company_id,
                            company_name=name_en,
                            fallback_url=target,
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
                    extra={
                        "company_id": company_id,
                        # Used by parse() as raw_company_name fallback
                        # when ld.company_name is None (the common case
                        # for DOM-fallback DOM extractions).
                        "company_name": name_en,
                        "from_dom": True,
                    },
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
                    "company_name": listing.extra.get("company_name"),
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
                "company_name": listing.extra.get("company_name"),
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
        # `.strip()` because some DOM extractors leave a whitespace-only
        # title (KKU's gov-portal pages were storing rows with title = '   '
        # and the page's verification-banner text as description). Reject
        # those at the parser instead of writing junk into the DB.
        title = (ld.title or "").strip()
        if not title:
            return None

        # Short descriptions on the DOM-fallback path are usually the page
        # chrome ("Search Jobs | Post Your CV" — 42 chars on DACO). 100
        # chars is enough to rule out navbars while keeping legitimate
        # one-paragraph postings.
        description = (ld.description or "").strip() or None
        if description is None or len(description) < 100:
            _LOG.info(
                "company_careers: rejecting low-quality parse "
                "(title=%r, desc_len=%d) for %s",
                title[:60], len(description or ""), raw.canonical_url,
            )
            return None
        # KKU-style .gov.sa pages: the DOM extractor latches onto the
        # SA-gov "verification banner" wrapping the main content. The
        # banner is large (12k chars) so the >=100 gate doesn't catch
        # it. If the description STARTS with that exact phrase, treat
        # the body as junk — set to None so the row keeps its real
        # title + company_id (PR #40) but doesn't mislead in search.
        if description.startswith(_SA_GOV_BOILERPLATE_PREFIX):
            _LOG.info(
                "company_careers: dropping SA-gov-portal boilerplate body "
                "for %s (kept title + company)", raw.canonical_url,
            )
            description = None

        raw_location = _join_location(ld)
        company_id_str = raw.payload.get("company_id")
        # discover_listings stores the parent company's name in
        # listing.extra so we can fall back to it when JSON-LD or DOM
        # didn't surface the employer (every Batterjee / Hala / etc.
        # detail page where ld.company_name is None).
        company_name_hint = raw.payload.get("company_name") or None
        if isinstance(company_name_hint, str):
            company_name_hint = company_name_hint.strip() or None
        raw_company_name = ld.company_name or company_name_hint

        channels: list[ApplicationChannelRaw] = [
            ApplicationChannelRaw(
                kind=ApplicationChannelKind.url,
                value=raw.canonical_url,
                is_primary=True,
                raw_label="Apply on company site",
            ),
        ]

        parsed_fields = {"title"}
        if description:
            parsed_fields.add("description")
        else:
            # description was dropped (boilerplate); track as missing
            pass
        missing_fields: set[str] = set()
        for name, value in (
            ("raw_location", raw_location),
            ("raw_company_name", raw_company_name),
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
            description=description,
            description_html=None,
            raw_company_name=raw_company_name,
            company_external_id=(
                company_id_str if isinstance(company_id_str, str) else None
            ),
            employment_type=ld.employment_type,
            min_experience_years=ld.min_experience_years,
            raw_location=raw_location,
            city_name_hint=ld.city,
            # JSON-LD `addressCountry` is wildly inconsistent — "United
            # States" naively truncated yields "un", which trips the FK
            # on job_postings.country_code. coerce_country_code keeps
            # only known-seeded codes and falls back to 'sa' otherwise.
            country_code=coerce_country_code(ld.country, default="sa"),
            salary_min=ld.salary_min,
            salary_max=ld.salary_max,
            salary_currency=ld.salary_currency,
            salary_period=ld.salary_period,
            application_channels=channels,
            parsed_fields=parsed_fields,
            missing_fields=missing_fields,
            raw_payload={"source": "company_careers", "ld": ld_dict},
        )
    # ------------------------------------------------------------------
    async def _companies_to_probe(
        self, limit: int,
    ) -> list[tuple[str, str, list[str], str]]:
        """Return `(id, name, candidate_urls, kind)` for the crawl target set.

        Two-tier selection (each tier capped by `limit` independently —
        a seeded company never bumps a probe company out of the run):

        * `kind="seed"` — companies with a `company_careers`
          `company_source_profiles` row. The seed CSV's `careers_url`
          column lands here via `discover/manual_seed.py::load`. We use
          the seeded URLs verbatim (no `/careers` guessing) and the
          Playwright fetcher hits them directly.
        * `kind="probe"` — companies with `website` populated but no
          source profile of any kind. Falls back to the
          `/careers`-style probe of `_CANDIDATE_PATHS`.

        Why the split? Pre-fix, the probe skipped any company with a
        source_profile — which would have made the seed CSV's careers
        URLs invisible. Now the seed wins.
        """
        if self.db is None:
            return []
        async with self.db.pool.connection() as conn, conn.cursor(
            row_factory=dict_row,
        ) as cur:
            await cur.execute(
                """
                SELECT c.id::text AS id, c.name_en,
                       array_agg(csp.profile_url ORDER BY csp.profile_url) AS urls
                FROM   companies c
                JOIN   company_source_profiles csp ON csp.company_id = c.id
                JOIN   sources s ON s.id = csp.source_id
                WHERE  s.slug = 'company_careers'
                  AND  c.deleted_at IS NULL
                GROUP  BY c.id, c.name_en
                ORDER  BY c.name_en
                LIMIT  %s
                """,
                (limit,),
            )
            seeded_rows = await cur.fetchall()

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
            probe_rows = await cur.fetchall()

        out: list[tuple[str, str, list[str], str]] = []
        for r in seeded_rows:
            urls = [u for u in (r["urls"] or []) if u]
            if urls:
                out.append((r["id"], r["name_en"] or "", urls, "seed"))
        for r in probe_rows:
            base_url = self._normalize_homepage(r["website"])
            if not base_url:
                continue
            urls = [urljoin(base_url + "/", p.lstrip("/")) for p in _CANDIDATE_PATHS]
            out.append((r["id"], r["name_en"] or "", urls, "probe"))
        return out

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
        company_name: str = "",
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
                "company_name": company_name,
            },
        )


# ---- helpers --------------------------------------------------------------
def _stable_id(url: str) -> str:
    """Deterministic id for a posting URL — survives across runs."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]


def _ld_from_detail_html(html: str) -> JobPostingLD:
    """Build a JobPostingLD from a detail-page HTML.

    JSON-LD is the first-class source — but when the detail page's
    JSON-LD omits a field (datePosted is the common gap on
    Cisco / Halliburton / Petrofac), we top up from DOM. Refresh
    every gap independently so a partial JSON-LD doesn't block us
    from extracting the bits that ARE in the DOM.
    """
    from dataclasses import replace as _dc_replace

    ld_list = extract_job_postings(html)
    ld = ld_list[0] if ld_list else JobPostingLD()
    try:
        tree = HTMLParser(html)
    except Exception:
        return ld

    def _txt(node: object) -> str | None:
        if node is None:
            return None
        text = node.text(separator=" ", strip=True) if hasattr(node, "text") else ""
        text = re.sub(r"\s+", " ", text or "").strip()
        return text or None

    fields: dict[str, object] = {}
    if not ld.title:
        fields["title"] = _txt(tree.css_first(_DETAIL_TITLE_CSS))
    if not ld.description:
        fields["description"] = _txt(tree.css_first(_DETAIL_BODY_CSS))
    if not ld.city:
        fields["city"] = _txt(tree.css_first(_DETAIL_LOCATION_CSS))
    if not ld.posted_at:
        dom_posted = _dom_posted_at(tree, html)
        if dom_posted is not None:
            fields["posted_at"] = dom_posted
    if fields:
        ld = _dc_replace(ld, **fields)  # type: ignore[arg-type]
    return ld


def _dom_posted_at(tree: HTMLParser, html: str) -> datetime | None:
    """Best-effort publish-date extraction from a detail-page DOM + HTML.

    Five-stage cascade — first hit wins. Designed to cover the wide
    variety of templates SA enterprises use:

      1. Semantic markup attributes — schema.org microdata, HTML5
         <time datetime>, Open Graph, common meta tags.
      2. data-* attributes that carry ISO dates (Greenhouse-hosted
         boards stash `data-posted-at`/`data-created-at` on job tiles).
      3. CSS-class heuristics — `.posted-date`, `[class*="posted"]`,
         `[class*="published"]`, `[class*="date"]` etc. — short text
         nodes that often hold a human-readable date.
      4. ISO-date regex (`YYYY-MM-DD`) scan over the rendered body
         text; picks the most recent date that's ≤ today.
      5. Relative-date phrases ("posted 5 days ago" / Arabic "منذ 5
         أيام" / "Posted on May 20, 2026") — translated to absolute
         datetimes via simple offset math.

    Returns a tz-aware datetime in UTC, or None when every stage
    misses. Out-of-window dates (> today or > 90 days old) are
    rejected before returning — they're almost always a footer
    "© 2024" copyright or a placeholder.
    """
    # --- Stage 1: semantic markup ----------------------------------------
    for css, attr in (
        ('[itemprop="datePosted"]', "content"),
        ('[itemprop="datePosted"]', "datetime"),
        ("time[datetime]", "datetime"),
        ('meta[property="article:published_time"]', "content"),
        ('meta[name="datePosted"]', "content"),
        ('meta[itemprop="datePosted"]', "content"),
    ):
        for node in tree.css(css):
            value = node.attributes.get(attr) if node.attributes else None
            dt = _parse_dt_loose(value)
            if dt is not None:
                return dt

    # --- Stage 2: data-* attributes carrying ISO dates -------------------
    for css, attr in (
        ('[data-posted-at]', "data-posted-at"),
        ('[data-created-at]', "data-created-at"),
        ('[data-publish-date]', "data-publish-date"),
        ('[data-published]', "data-published"),
        ('[data-job-posted]', "data-job-posted"),
    ):
        for node in tree.css(css):
            value = node.attributes.get(attr) if node.attributes else None
            dt = _parse_dt_loose(value)
            if dt is not None:
                return dt

    # --- Stage 3: CSS-class heuristics -----------------------------------
    for css in (
        ".posted-date",
        ".publish-date",
        ".published-date",
        ".job-date",
        ".date-posted",
        "[class*='postedDate']",
        "[class*='publishDate']",
        "[class*='posted']",
        "[class*='published']",
    ):
        for node in tree.css(css):
            text = node.text(separator=" ", strip=True) if hasattr(node, "text") else ""
            # short text nodes only — long blocks are body content, not a date
            if not text or len(text) > 80:
                continue
            dt = _parse_date_from_text(text)
            if dt is not None:
                return dt

    # --- Stage 4: ISO-date regex over body text --------------------------
    # Most recent valid date ≤ today wins. Cap window at 90d so a
    # footer "© 2014" doesn't leak through.
    iso_dates: set[str] = set(_ISO_DATE_RE.findall(html))
    today = datetime.now(UTC).date()
    best: datetime | None = None
    for raw in iso_dates:
        try:
            dt = datetime.fromisoformat(raw).replace(tzinfo=UTC)
        except ValueError:
            continue
        d = dt.date()
        if d > today:
            continue
        if (today - d).days > 90:
            continue
        if best is None or dt > best:
            best = dt
    if best is not None:
        return best

    # --- Stage 5: relative date phrases ----------------------------------
    body_text = tree.body.text(separator=" ", strip=True) if tree.body else ""
    rel = _parse_relative_date(body_text)
    if rel is not None:
        return rel
    return None


_ISO_DATE_RE: Final[re.Pattern[str]] = re.compile(r"\b(20\d{2}-[01]\d-[0-3]\d)\b")

# English "posted 5 days ago" + Arabic equivalents. Hours/minutes count as
# "today" (good enough for daily-resolution sources).
_REL_DAYS_EN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:posted|published|listed|created)\s+(\d{1,3})\+?\s+days?\s+ago\b",
    re.IGNORECASE,
)
_REL_HOURS_EN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:posted|published|listed|created)\s+(\d{1,3})\+?\s+hours?\s+ago\b",
    re.IGNORECASE,
)
_REL_DAYS_AR: Final[re.Pattern[str]] = re.compile(
    r"(?:نشر|منذ|قبل)\s*(\d{1,3})\s*(?:يوم|أيام|يوماً)",
)
# "Posted on May 20, 2026" / "Posted on 20 May 2026"
_REL_ABS_EN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:posted|published)\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+20\d{2}|\d{1,2}\s+[A-Za-z]+\s+20\d{2})\b",
    re.IGNORECASE,
)


def _parse_relative_date(text: str) -> datetime | None:
    """Translate "posted N days ago" / Arabic equivalent to a datetime."""
    if not text:
        return None
    now = datetime.now(UTC)
    m = _REL_DAYS_EN.search(text) or _REL_DAYS_AR.search(text)
    if m:
        try:
            days = int(m.group(1))
        except ValueError:
            days = 0
        return now - timedelta(days=days)
    m = _REL_HOURS_EN.search(text)
    if m:
        try:
            hours = int(m.group(1))
        except ValueError:
            hours = 0
        return now - timedelta(hours=hours)
    m = _REL_ABS_EN.search(text)
    if m:
        for fmt in ("%B %d, %Y", "%B %d %Y", "%d %B %Y"):
            try:
                return datetime.strptime(m.group(1), fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _parse_date_from_text(text: str) -> datetime | None:
    """Tiny text-to-date parser — tries ISO first, then a few common
    human-readable formats. Returns tz-aware UTC or None."""
    text = text.strip()
    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        try:
            return datetime.fromisoformat(iso_match.group(1)).replace(tzinfo=UTC)
        except ValueError:
            pass
    for fmt in ("%B %d, %Y", "%d %B %Y", "%b %d, %Y", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_dt_loose(value: str | None) -> datetime | None:
    """Parse a datetime string from an HTML attribute. Accepts ISO 8601
    with or without trailing `Z`. Returns tz-aware UTC."""
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


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
            # isinstance() narrows the value to int but mypy doesn't carry
            # that narrowing through the dict re-lookup, so cast.
            cast(int, snapshot["min_experience_years"])
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
