"""BaseCrawler — the contract every per-site crawler implements.

A crawler's job is to translate a remote source into a stream of
JobPostingUpsert payloads. The runner (core.runner) handles the rest:
HTTP, retries, snapshots, dedupe edges, cluster attach, fake-signal
scoring, health bookkeeping, alerting.

Subclasses fill in four methods. Each one is small (~30-80 lines):

    discover_listings(since)      -> AsyncIterator[Listing]
    fetch_detail(listing)         -> RawPosting | None  (default: HttpClient.fetch)
    parse(raw)                    -> ParsedPosting | None
    normalize(parsed)             -> JobPostingUpsert + side data
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import ClassVar

from job_crawler_db import JobCrawlerDB, JobPostingUpsert, SourceKind

from .config import RateConfig
from .http import HttpClient
from .types import Listing, ParsedPosting, RawPosting


class BaseCrawler(ABC):
    """Abstract base. Subclasses set the ClassVars + implement the four methods."""

    # ---- per-source identity / config ---------------------------------
    source_slug: ClassVar[str]
    source_display_name: ClassVar[str]
    source_kind: ClassVar[SourceKind]
    source_base_url: ClassVar[str]
    source_trust_weight: ClassVar[float] = 0.50
    rate: ClassVar[RateConfig] = RateConfig()
    # Default OFF: we crawl aggressively. Boards and ATS APIs frequently
    # publish overly-broad robots.txt rules that would block legitimate
    # job-search aggregation. Set True on a per-crawler basis if a site
    # genuinely doesn't want to be touched.
    respect_robots: ClassVar[bool] = False
    # When True, the runner drops postings whose location isn't in the GCC
    # (SA + UAE + BH + KW + QA + OM). ATS crawlers set this; boards leave it
    # off because their search URLs are already SA-scoped.
    requires_gcc_location: ClassVar[bool] = False
    # When True, the CLI uses an HTTP/1.1-only AsyncClient for this crawler.
    # Some sites (Naukrigulf) reset HTTP/2 streams mid-response; HTTP/1.1
    # works around it.
    prefer_http_1_1: ClassVar[bool] = False
    # When set, the CLI routes requests through `curl_cffi` impersonating
    # the named browser ("chrome", "chrome120", "safari", "firefox"...) so
    # the TLS+HTTP/2 fingerprint matches a real browser. Required to get
    # past Cloudflare/DataDome-style bot walls (Bayt, parts of Indeed).
    impersonate_browser: ClassVar[str | None] = None
    # When True the CLI builds a rotating `ProxyPool` and passes it to the
    # crawler's HttpClient. Each request picks a random non-blacklisted
    # proxy; failures auto-blacklist after a few transient failures or one
    # permanent failure (auth required, SSL handshake, blocked-by-target).
    # Sites typically need this AND impersonate_browser together.
    use_proxy_pool: ClassVar[bool] = False
    # When True the CLI substitutes the HttpClient with a `PlaywrightFetcher`
    # (headless Chromium) — for SPA sites whose listings only materialise
    # after JS hydration (Glassdoor), TLS+behavioural bot walls (LinkedIn,
    # Indeed) and queue-interstitials (Jadarat). ~3-5s Chromium launch is
    # amortised across the whole run.
    use_playwright: ClassVar[bool] = False
    # 1-3 URLs that should always parse correctly. Hand-picked stable jobs;
    # the canary system fetches these on every cycle to detect site changes.
    canary_urls: ClassVar[tuple[str, ...]] = ()
    # Optional version string — bump in code when you change the parser so
    # the breakage detector can clear the stale state.
    crawler_version: ClassVar[str] = "v1"

    # ---- runtime state -------------------------------------------------
    __slots__ = ("db", "http")

    def __init__(self, http: HttpClient, db: JobCrawlerDB | None = None) -> None:
        self.http = http
        # `db` is optional so crawlers + their tests can be instantiated without
        # a real DB. The runner always passes one through; per-crawler
        # subclasses can use `self.db` to pull dynamic config (e.g. board
        # slugs from `company_source_profiles`) when it's set.
        self.db = db

    # ---- contract (override in subclasses) ----------------------------

    @abstractmethod
    def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        """Yield Listings for jobs posted on/after `since`.

        Implementations MUST honour the date cutoff at the source side
        (e.g. add `posted_within=30` to the search URL). The runner will
        still drop stale postings as a safety net.
        """

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        """Default: GET listing.detail_url via self.http and pack the body.
        Override when the source needs a different shape (POST, JSON body)."""
        from datetime import datetime

        try:
            result = await self.http.fetch(listing.detail_url)
        except Exception:
            return None
        payload: dict[str, object] = (
            {"json": result.json} if result.json is not None else {"html": result.text}
        )
        return RawPosting(
            listing=listing,
            canonical_url=result.url,
            payload=payload,
            fetched_at=datetime.now(UTC),
            duration_ms=result.duration_ms,
            http_status=result.status,
            bytes=result.bytes,
        )

    @abstractmethod
    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        """Turn raw bytes into structured fields. Return None on parse failure
        — the runner counts this for the breakage detector."""

    @abstractmethod
    def normalize(self, parsed: ParsedPosting) -> JobPostingUpsert:
        """Turn the parsed fields into the DB upsert struct.

        Typically thin glue: copy fields, set source_id (the runner injects
        it just before calling), default missing enums.
        """
