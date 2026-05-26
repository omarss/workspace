"""Quality gates that drop noisy / duplicate postings BEFORE the DB sees them.

Three checkers, run at three chokepoints by `CrawlerRunner`:

* `check_listing`        — listing-stage URL sanity. Rejects nav / search /
                           login URLs that occasionally leak through a
                           crawler's `discover_listings` iterator.
* `check_parsed`         — post-parse universal sanity gate. Rejects empty
                           or placeholder titles, very short / low-diversity
                           descriptions, garbage company names, and
                           implausible `posted_at` dates.
* `check_intra_run_dup`  — pure helper. The runner keeps a set of
                           `content_hash` values seen in the current run
                           and skips re-discoveries that paginators
                           frequently yield (e.g. the same listing on
                           pages 1 and 2).

Each check returns `QualityReject(reason, detail)` on failure. `reason`
is a stable tag that doubles as a scorecard counter name; `detail` is a
human-readable message stored in `crawl_fetches.error_message`.

Reject-only semantics: failing any check drops the posting entirely. No
schema change required — `crawl_fetches.outcome = 'rejected'` is a new
value on the existing free-text column.

Why centralised
---------------
Before this module, every crawler grew its own ad-hoc filters:
`company_careers.py` had a required-title + min-description gate,
`bayt.py` stripped nav-prefix titles, the runner short-circuited garbage
company names. Same intent, 3 different code paths and 3 different bug
profiles. One module owning all parse-stage rejects means one place to
audit, one set of scorecard counters, and one set of tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urlsplit

from .normalise import _clean_company_name, _clean_text
from .types import Listing, ParsedPosting


@dataclass(frozen=True, slots=True)
class QualityReject:
    """A failed quality check.

    `reason` is a short snake_case tag — stable identifier we surface
    in scorecard counters + crawl_fetches accounting. `detail` is the
    one-line human-readable message stored alongside the reject.
    """

    reason: str
    detail: str


# ---------------------------------------------------------------------------
# Listing-stage gate
# ---------------------------------------------------------------------------

# Path segments that mark a URL as a nav / search / landing page rather
# than an individual job-detail page. Conservative on purpose: most
# crawlers' `discover_listings` already returns real detail URLs, so
# anything in this set is an obvious leak (e.g. a "/search" link that
# slipped through the result list extractor).
_NAV_PATH_TOKENS: Final[frozenset[str]] = frozenset({
    "",
    "search",
    "search-jobs",
    "login",
    "signin",
    "signup",
    "register",
    "error",
    "404",
    "not-found",
    "sitemap",
    "robots.txt",
})


def check_listing(listing: Listing) -> QualityReject | None:
    """Return a reject when the listing URL is obviously not a job-detail page.

    Catches the obvious leaks (homepage, search-results, login) without
    inventing a "real job URL must look like X" heuristic — those false
    positive on every ATS we don't know yet. New nav paths can be added
    to `_NAV_PATH_TOKENS` as they show up in `crawl_fetches`.
    """
    url = (listing.detail_url or "").strip()
    if not url:
        return QualityReject("bad_url", "detail_url is empty")
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return QualityReject("bad_url", f"missing scheme/host: {url!r}")
    path = parts.path or "/"
    # Strip leading / trailing slashes then take the last non-empty
    # segment — that's the one that disambiguates a job from a nav page.
    segments = [s for s in path.strip("/").split("/") if s]
    if not segments:
        return QualityReject("nav_url", f"homepage path: {path!r}")
    last = segments[-1].lower()
    if last in _NAV_PATH_TOKENS:
        return QualityReject("nav_url", f"nav path: {path!r}")
    return None


# ---------------------------------------------------------------------------
# Post-parse gate
# ---------------------------------------------------------------------------

# Title placeholders we see when a parser hit a nav page or a JSON-LD
# stub with the literal "Job" / "Apply" filler. Whole-string match
# (lower-cased) so real titles like "Job Scheduler Engineer" aren't
# touched.
_PLACEHOLDER_TITLES: Final[frozenset[str]] = frozenset({
    "job",
    "jobs",
    "career",
    "careers",
    "search",
    "vacancy",
    "vacancies",
    "apply",
    "apply now",
    "open positions",
    "untitled",
    "n/a",
    "tbd",
})

# Hard caps. A real job title rarely exceeds 200 chars; anything longer
# is almost always nav-bar text bleed (the original Bayt leak).
_MAX_TITLE_CHARS: Final[int] = 200

# Description length is the single most predictive sanity gate: under
# 100 chars we're almost always looking at a CAPTCHA stub, a 404 page,
# or a Saudi-gov-portal banner.
_MIN_DESC_CHARS: Final[int] = 100

# Distinct token count catches descriptions that ARE long but are pure
# boilerplate or lorem-ipsum filler (e.g. "Apply Apply Apply ...").
_MIN_DESC_UNIQUE_WORDS: Final[int] = 10

# posted_at sanity. We allow up to 24h in the future to absorb timezone
# parsing slop on JSON-LD timestamps without dropping legit postings.
_FUTURE_POSTED_AT_TOLERANCE: Final[timedelta] = timedelta(hours=24)
_MAX_POSTED_AT_AGE: Final[timedelta] = timedelta(days=365)

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"\w+", re.UNICODE)


def check_parsed(parsed: ParsedPosting, *, now: datetime | None = None) -> QualityReject | None:
    """Return a reject when a parsed posting fails any quality gate.

    Order matters: cheaper checks first so noisy sources fail fast.
    First-failed-check wins so the scorecard reason tag is deterministic.

    `now` is injectable for testing — defaults to `datetime.now(UTC)`.
    """
    title = _clean_text(parsed.title) or ""
    if not title:
        return QualityReject("empty_title", "title empty after cleaning")
    if len(title) > _MAX_TITLE_CHARS:
        return QualityReject(
            "long_title",
            f"title len={len(title)} > {_MAX_TITLE_CHARS}",
        )
    if title.lower() in _PLACEHOLDER_TITLES:
        return QualityReject("placeholder_title", f"placeholder: {title!r}")
    # A title that's all digits / punctuation has no information value
    # (real titles always carry at least one alpha token).
    if not any(ch.isalpha() for ch in title):
        return QualityReject("non_alpha_title", f"no alpha chars: {title!r}")

    description = _clean_text(parsed.description) or ""
    if len(description) < _MIN_DESC_CHARS:
        return QualityReject(
            "short_description",
            f"description len={len(description)} < {_MIN_DESC_CHARS}",
        )
    unique_words = {
        w.lower()
        for w in _WORD_RE.findall(description)
        if len(w) >= 2
    }
    if len(unique_words) < _MIN_DESC_UNIQUE_WORDS:
        return QualityReject(
            "low_diversity_description",
            f"unique_words={len(unique_words)} < {_MIN_DESC_UNIQUE_WORDS}",
        )

    # Company name is optional at the schema level but most sources
    # surface it. Reject only the present-but-garbage case so sources
    # that legitimately can't extract a company aren't penalised.
    raw_company = parsed.raw_company_name
    if raw_company and _clean_company_name(raw_company) is None:
        return QualityReject(
            "garbage_company",
            f"unusable company name: {raw_company!r}",
        )

    posted_at = parsed.posted_at
    if posted_at is not None:
        current = now or datetime.now(UTC)
        if posted_at > current + _FUTURE_POSTED_AT_TOLERANCE:
            return QualityReject(
                "future_posted_at",
                f"posted_at={posted_at.isoformat()} > now+24h",
            )
        if current - posted_at > _MAX_POSTED_AT_AGE:
            return QualityReject(
                "stale_posted_at",
                f"posted_at={posted_at.isoformat()} > 365d ago",
            )

    return None


# ---------------------------------------------------------------------------
# Intra-run dedup helper
# ---------------------------------------------------------------------------

def check_intra_run_dup(
    parsed: ParsedPosting,
    *,
    seen_content_hashes: set[bytes],
) -> QualityReject | None:
    """Skip re-discoveries of the same posting within one run.

    Paginators routinely surface the same listing on multiple pages
    (page 1 + page 2 overlap on Bayt) — without this gate every such
    re-discovery triggers a full upsert+update cycle, inflating the
    crawl_fetches outcome='updated' count and re-bumping last_fetch_at
    for no real reason.

    Caller mutates `seen_content_hashes` on success (when this returns
    None). The set is scoped to ONE crawler run; cross-run dedup is
    handled later by `intelligence/dedup.py`.

    Returns None when the description is empty (no hash to compare) —
    other checks already cover the empty-description case.
    """
    from job_crawler_db.hashing import content_hash

    h = content_hash(parsed.description)
    if h is None:
        return None
    if h in seen_content_hashes:
        return QualityReject(
            "intra_run_dup",
            "identical content_hash already seen in this run",
        )
    seen_content_hashes.add(h)
    return None
