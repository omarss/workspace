"""Auto-detect which ATS a company hosts its careers on.

Strategy: each ATS has a small set of well-known URL patterns. We probe
them in order — first the "obvious" pattern (e.g. boards.greenhouse.io/{slug}),
then the company's own `/careers` page looking for outbound ATS links.

When a probe succeeds we register a `company_source_profiles` row so the
matching ATS crawler picks the company up on its next run.

Pure async, polite (per-host throttle via core.http), idempotent.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

from job_crawler_db import Company, JobCrawlerDB, SourceKind

from ..core.config import IDENTIFIABLE_UA, RateConfig
from ..core.http import HttpClient

_LOG: Final = logging.getLogger("job_crawler.company_sites.ats_detector")

# A single shared HTTP client for the whole detection run — polite, identifiable.
_RATE: Final = RateConfig(
    max_rps=1.0, burst=2, max_concurrent=2,
    timeout_seconds=10.0, user_agent=IDENTIFIABLE_UA,
)


@dataclass(frozen=True, slots=True)
class ATSHit:
    """One successful detection: an ATS that hosts the company's board."""

    source_slug: str          # 'greenhouse' | 'lever' | 'workable' | 'successfactors'
    ats_slug: str             # e.g. 'tabby' for greenhouse, 'aramco' for SF
    profile_url: str          # the canonical hosted-board URL


@dataclass(frozen=True, slots=True)
class DetectorSummary:
    companies_scanned: int
    hits: int
    by_source: dict[str, int]


# ---------------------------------------------------------------------------
# Per-ATS probes — each returns an ATSHit or None.
# ---------------------------------------------------------------------------
async def _probe_greenhouse(http: HttpClient, slug: str) -> ATSHit | None:
    """Probe https://boards-api.greenhouse.io/v1/boards/{slug} — 200 + JSON = hit."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"
    try:
        r = await http.fetch(url)
    except Exception:
        return None
    if r.status != 200 or not isinstance(r.json, dict) or "jobs" not in r.json:
        return None
    return ATSHit(
        source_slug="greenhouse",
        ats_slug=slug,
        profile_url=f"https://boards.greenhouse.io/{slug}",
    )


async def _probe_lever(http: HttpClient, slug: str) -> ATSHit | None:
    """Probe https://api.lever.co/v0/postings/{slug}?mode=json — 200 + list = hit."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        r = await http.fetch(url)
    except Exception:
        return None
    if r.status != 200 or not isinstance(r.json, list):
        return None
    return ATSHit(
        source_slug="lever",
        ats_slug=slug,
        profile_url=f"https://jobs.lever.co/{slug}",
    )


async def _probe_workable(http: HttpClient, slug: str) -> ATSHit | None:
    """Probe Workable's v1 widget endpoint.

    The old v3 (/api/v3/accounts/{slug}/jobs) returns 404 for real production
    tenants — only the v1 widget reliably enumerates published jobs.
    We require a non-empty jobs[] because Workable returns 200 + empty body
    for *any* slug, including never-registered ones.
    """
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    try:
        r = await http.fetch(url)
    except Exception:
        return None
    if r.status != 200 or not isinstance(r.json, dict):
        return None
    jobs = r.json.get("jobs")
    if not isinstance(jobs, list) or len(jobs) == 0:
        return None
    return ATSHit(
        source_slug="workable",
        ats_slug=slug,
        profile_url=f"https://apply.workable.com/{slug}/",
    )


async def _probe_successfactors(http: HttpClient, slug: str) -> ATSHit | None:
    """Probe the SF guest portal. SF doesn't 404 unknown companies cleanly,
    so we look for a positive marker (the `jobreqcareerpc` shell + at least
    one `jobId` link or a "no jobs" banner)."""
    url = (f"https://career5.successfactors.eu/sfcareer/jobreqcareerpc"
           f"?company={slug}&lang=en_US")
    try:
        r = await http.fetch(url)
    except Exception:
        return None
    if r.status != 200 or "sfcareer" not in r.text.lower():
        return None
    # Positive marker: the page references the tenant code, AND either has
    # at least one jobId link or the recognisable empty-state widget.
    if (f"company={slug}" not in r.text and slug not in r.text):
        return None
    return ATSHit(
        source_slug="successfactors",
        ats_slug=slug,
        profile_url=url,
    )


# Ordered probe list — cheapest / most common first.
_PROBES: Final[tuple[Callable[[HttpClient, str], Awaitable[ATSHit | None]], ...]] = (
    _probe_greenhouse,
    _probe_lever,
    _probe_workable,
    _probe_successfactors,
)


# ---------------------------------------------------------------------------
# Slug derivation
# ---------------------------------------------------------------------------
_SLUG_CLEAN = re.compile(r"[^a-z0-9-]+")


def _slug_candidates(company: Company) -> tuple[str, ...]:
    """Best-effort candidate slugs for an ATS lookup.

    Tries: explicit website hostname's leftmost label, the name lowercased
    with non-alnums removed, the name with `-` separators. Dedup'd, ordered.
    """
    seen: set[str] = set()
    out: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        v = _SLUG_CLEAN.sub("", value.lower().replace(" ", "")).strip("-")
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    if company.website:
        host = urlsplit(company.website).hostname or ""
        # strip www., take the first label (e.g. "tabby.ai" → "tabby")
        host = host.removeprefix("www.")
        if host:
            add(host.split(".")[0])
    if company.name_en:
        add(company.name_en)
        # Hyphenated form ("Saudi Telecom Company" → "saudi-telecom-company")
        hyph = re.sub(r"[^a-z0-9]+", "-",
                      company.name_en.lower()).strip("-")
        if hyph and hyph not in seen:
            seen.add(hyph)
            out.append(hyph)
    return tuple(out)


# ---------------------------------------------------------------------------
# Homepage scrape — look for outbound ATS links
# ---------------------------------------------------------------------------
_HOMEPAGE_ATS_PATTERNS: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = (
    # (source_slug, regex, capture_group_name_for_slug)
    ("greenhouse",     re.compile(r"boards\.greenhouse\.io/([A-Za-z0-9-]+)"),       "g1"),
    ("lever",          re.compile(r"jobs\.lever\.co/([A-Za-z0-9-]+)"),              "g1"),
    ("workable",       re.compile(r"apply\.workable\.com/([A-Za-z0-9-]+)"),         "g1"),
    ("smartrecruiters",re.compile(r"jobs\.smartrecruiters\.com/([A-Za-z0-9-]+)"),  "g1"),
    ("workday",        re.compile(r"([A-Za-z0-9-]+)\.(?:wd[0-9]+\.)?myworkdayjobs\.com"),
                       "g1"),
    ("successfactors", re.compile(r"successfactors\.(?:eu|com)/[^\"'>]*company=([A-Za-z0-9_-]+)"),
                       "g1"),
)


async def _scan_homepage(http: HttpClient, company: Company) -> list[ATSHit]:
    """Fetch the company's careers page (or homepage), grep for ATS links."""
    if not company.website:
        return []
    candidate_paths = ("/careers", "/jobs", "/career", "/join-us", "/work-with-us", "/")
    base = company.website.rstrip("/")
    seen: set[tuple[str, str]] = set()
    hits: list[ATSHit] = []
    for path in candidate_paths:
        url = urljoin(base + "/", path.lstrip("/"))
        try:
            r = await http.fetch(url)
        except Exception:
            continue
        text = r.text or ""
        for source_slug, pattern, _ in _HOMEPAGE_ATS_PATTERNS:
            for match in pattern.finditer(text):
                slug = match.group(1).strip()
                key = (source_slug, slug.lower())
                if key in seen:
                    continue
                seen.add(key)
                profile_url = match.group(0)
                if not profile_url.startswith("http"):
                    profile_url = "https://" + profile_url
                hits.append(ATSHit(source_slug, slug, profile_url))
        # Stop early once we've found hits — no need to probe more paths.
        if hits:
            break
        # Discover internal "careers" links from the homepage and try one
        try:
            careers_links = _find_careers_links(text, base)
        except Exception:
            careers_links = ()
        for href in careers_links[:2]:
            try:
                rc = await http.fetch(href)
            except Exception:
                continue
            inner = rc.text or ""
            for source_slug, pattern, _ in _HOMEPAGE_ATS_PATTERNS:
                for match in pattern.finditer(inner):
                    slug = match.group(1).strip()
                    key = (source_slug, slug.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    profile_url = match.group(0)
                    if not profile_url.startswith("http"):
                        profile_url = "https://" + profile_url
                    hits.append(ATSHit(source_slug, slug, profile_url))
            if hits:
                break
        if hits:
            break
    return hits


_CAREERS_LINK_RE = re.compile(
    r'href=["\']([^"\']+(?:careers?|jobs|join|work-with-us|hiring)[^"\']*)["\']',
    re.IGNORECASE,
)


def _find_careers_links(html: str, base: str) -> tuple[str, ...]:
    """Pull /careers-shaped internal links from a homepage."""
    tree = HTMLParser(html)
    found: list[str] = []
    for m in _CAREERS_LINK_RE.finditer(html):
        href = m.group(1)
        if href.startswith("http") or href.startswith("/"):
            found.append(urljoin(base + "/", href))
        if len(found) >= 5:
            break
    return tuple(dict.fromkeys(found))  # dedup, preserve order
    _ = tree  # keep the parser import alive for selectolax shape consistency


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def detect_for_companies(
    db: JobCrawlerDB,
    companies: Iterable[Company],
) -> DetectorSummary:
    """Probe every company in `companies` and register hits via
    `db.companies.add_source_profile()`."""
    by_source: dict[str, int] = {}
    hits_total = 0
    scanned = 0

    # Ensure the four ATS sources exist so we have IDs to FK against.
    src_ids: dict[str, str] = {}
    for slug, name in (
        ("greenhouse", "Greenhouse"),
        ("lever", "Lever"),
        ("workable", "Workable"),
        ("smartrecruiters", "SmartRecruiters"),
        ("workday", "Workday"),
        ("successfactors", "SuccessFactors"),
    ):
        s = await db.sources.upsert(
            slug=slug, display_name=name, kind=SourceKind.ats,
            base_url="https://example.invalid", trust_weight=0.90,
        )
        src_ids[slug] = str(s.id)

    async with HttpClient(_RATE, respect_robots=False) as http:
        for company in companies:
            scanned += 1
            company_hits: list[ATSHit] = []

            # 1. Direct probes against derived slug candidates (cheap).
            for slug in _slug_candidates(company):
                for probe in _PROBES:
                    hit = await probe(http, slug)
                    if hit is not None:
                        company_hits.append(hit)
                        # Each probe is per-ATS; one hit per ATS per slug.
                if company_hits:
                    break

            # 2. Fallback to homepage scrape if probes missed.
            if not company_hits:
                company_hits = await _scan_homepage(http, company)

            # Register each hit.
            for hit in company_hits:
                source_id_str = src_ids.get(hit.source_slug)
                if source_id_str is None:
                    continue
                try:
                    from uuid import UUID
                    await db.companies.add_source_profile(
                        company.id, UUID(source_id_str), hit.profile_url,
                        source_company_external_id=hit.ats_slug,
                    )
                    hits_total += 1
                    by_source[hit.source_slug] = by_source.get(hit.source_slug, 0) + 1
                    _LOG.info("[%s] %s → %s (%s)",
                              hit.source_slug, company.name_en, hit.ats_slug,
                              hit.profile_url)
                except Exception:
                    _LOG.exception("could not register profile for %s", company.id)
    return DetectorSummary(
        companies_scanned=scanned,
        hits=hits_total,
        by_source=by_source,
    )


# Re-export for the CLI / Makefile.
__all__ = ["ATSHit", "DetectorSummary", "detect_for_companies"]
