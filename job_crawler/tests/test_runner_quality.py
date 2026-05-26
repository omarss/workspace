"""Integration: `CrawlerRunner` enforces quality gates end-to-end.

Spins up a stub crawler that yields a handful of listings — some good,
some that fail each quality gate — and asserts:

  * the bad ones land in `crawl_fetches` with `outcome='rejected'` and
    an `error_message` prefixed `quality:<reason>`;
  * the good ones still produce postings;
  * `RunStats.quality_rejects` counters tally each reason.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

import pytest
from psycopg.rows import dict_row

from job_crawler.core.base import BaseCrawler
from job_crawler.core.runner import CrawlerRunner
from job_crawler.core.types import Listing, ParsedPosting, RawPosting
from job_crawler_db import JobCrawlerDB, SourceKind

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Stub crawler
# ---------------------------------------------------------------------------


class _StubCrawler(BaseCrawler):
    """Returns whatever the test sets up — no HTTP, no parsing."""

    source_slug: ClassVar[str] = "stub_quality"
    source_display_name: ClassVar[str] = "Stub"
    source_kind: ClassVar[SourceKind] = SourceKind.ats
    source_base_url: ClassVar[str] = "https://stub.invalid"
    source_trust_weight: ClassVar[float] = 0.5
    requires_gcc_location: ClassVar[bool] = False

    def __init__(
        self,
        listings: list[Listing],
        parsed: Mapping[str, ParsedPosting | None],
    ) -> None:
        # Bypass HttpClient — the runner never asks the stub to fetch.
        self.http = None  # type: ignore[assignment]
        self.db = None
        self._listings = listings
        self._parsed = parsed

    async def discover_listings(self, *, since: datetime) -> AsyncIterator[Listing]:
        for listing in self._listings:
            yield listing

    async def fetch_detail(self, listing: Listing) -> RawPosting | None:
        return RawPosting(
            listing=listing,
            canonical_url=listing.detail_url,
            payload={"html": ""},
            fetched_at=datetime.now(UTC),
            duration_ms=0,
            http_status=200,
            bytes=0,
        )

    def parse(self, raw: RawPosting) -> ParsedPosting | None:
        return self._parsed.get(raw.listing.source_job_external_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_GOOD_DESC = (
    "We are hiring a backend engineer to build distributed services in "
    "Python. You will work on scaling the payments platform, lead code "
    "reviews, and mentor junior engineers across our remote team."
)


def _good_parsed(eid: str = "good-1", url: str = "https://stub.invalid/jobs/good-1") -> ParsedPosting:
    return ParsedPosting(
        source_job_external_id=eid,
        canonical_url=url,
        title="Senior Python Engineer",
        description=_GOOD_DESC,
        raw_company_name="Acme Saudi",
        posted_at=datetime.now(UTC),
    )


async def _fetch_records(db: JobCrawlerDB, source_id: UUID) -> list[dict[str, Any]]:
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT url, outcome, error_message
            FROM   crawl_fetches
            WHERE  source_id = %(s)s
            ORDER  BY fetched_at;
            """,
            {"s": source_id},
        )
        return list(await cur.fetchall())


async def _count_postings(db: JobCrawlerDB, source_id: UUID) -> int:
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT COUNT(*) AS n FROM job_postings WHERE source_id = %(s)s",
            {"s": source_id},
        )
        row = await cur.fetchone()
    return int(row["n"]) if row else 0


async def _count_companies(db: JobCrawlerDB) -> int:
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT COUNT(*) AS n FROM companies")
        row = await cur.fetchone()
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_runner_drops_nav_url_listings(db: JobCrawlerDB) -> None:
    """A listing with a nav URL never gets fetched and isn't recorded
    (no HTTP happened, nothing to record)."""
    listings = [
        Listing(source_job_external_id="good", detail_url="https://stub.invalid/jobs/good"),
        Listing(source_job_external_id="nav", detail_url="https://stub.invalid/search"),
    ]
    parsed = {"good": _good_parsed(eid="good", url="https://stub.invalid/jobs/good")}
    crawler = _StubCrawler(listings, parsed)
    runner = CrawlerRunner(db, crawler)

    summary = await runner.run()

    # nav URL was rejected pre-fetch → fetched counter only counts good one.
    assert summary.fetched == 1
    assert summary.new_postings == 1
    records = await _fetch_records(db, await runner.ensure_source())
    # Only one record (for the good listing) — nav-URL skip is silent.
    assert len(records) == 1
    assert records[0]["outcome"] == "created"


async def test_runner_drops_short_description_postings(db: JobCrawlerDB) -> None:
    """A parsed posting with a too-short description is rejected with
    outcome='rejected' and the reason tag in error_message."""
    listings = [
        Listing(source_job_external_id="good", detail_url="https://stub.invalid/jobs/good"),
        Listing(source_job_external_id="short", detail_url="https://stub.invalid/jobs/short"),
    ]
    parsed = {
        "good": _good_parsed(eid="good", url="https://stub.invalid/jobs/good"),
        "short": ParsedPosting(
            source_job_external_id="short",
            canonical_url="https://stub.invalid/jobs/short",
            title="A Real Title",
            description="too short",
            raw_company_name="Acme",
            posted_at=datetime.now(UTC),
        ),
    }
    crawler = _StubCrawler(listings, parsed)
    runner = CrawlerRunner(db, crawler)

    summary = await runner.run()

    assert summary.new_postings == 1  # the good one
    records = await _fetch_records(db, await runner.ensure_source())
    rejected = [r for r in records if r["outcome"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["error_message"].startswith("quality:short_description")
    assert await _count_postings(db, await runner.ensure_source()) == 1


async def test_runner_drops_garbage_company_postings(db: JobCrawlerDB) -> None:
    """Garbage company name (trailing `&`) is caught by the parsed gate
    before it can create a junk `companies` row."""
    listings = [
        Listing(source_job_external_id="bad-co", detail_url="https://stub.invalid/jobs/bad-co"),
    ]
    parsed = {
        "bad-co": ParsedPosting(
            source_job_external_id="bad-co",
            canonical_url="https://stub.invalid/jobs/bad-co",
            title="Engineer",
            description=_GOOD_DESC,
            raw_company_name="Qwer0770&",
            posted_at=datetime.now(UTC),
        ),
    }
    crawler = _StubCrawler(listings, parsed)
    runner = CrawlerRunner(db, crawler)

    summary = await runner.run()

    assert summary.new_postings == 0
    records = await _fetch_records(db, await runner.ensure_source())
    assert len(records) == 1
    assert records[0]["outcome"] == "rejected"
    assert records[0]["error_message"].startswith("quality:garbage_company")
    # No companies row was created for the garbage name.
    assert await _count_companies(db) == 0


async def test_runner_drops_intra_run_duplicates(db: JobCrawlerDB) -> None:
    """Two listings with different external ids but identical description
    bodies — the second one is rejected as a paginator duplicate."""
    listings = [
        Listing(source_job_external_id="a", detail_url="https://stub.invalid/jobs/a"),
        Listing(source_job_external_id="b", detail_url="https://stub.invalid/jobs/b"),
    ]
    parsed = {
        "a": _good_parsed(eid="a", url="https://stub.invalid/jobs/a"),
        "b": ParsedPosting(
            source_job_external_id="b",
            canonical_url="https://stub.invalid/jobs/b",
            title="Senior Python Engineer",
            description=_GOOD_DESC,  # SAME body as 'a'
            raw_company_name="Acme Saudi",
            posted_at=datetime.now(UTC),
        ),
    }
    crawler = _StubCrawler(listings, parsed)
    runner = CrawlerRunner(db, crawler)

    summary = await runner.run()

    assert summary.new_postings == 1  # only 'a' persisted
    records = await _fetch_records(db, await runner.ensure_source())
    rejected = [r for r in records if r["outcome"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["error_message"].startswith("quality:intra_run_dup")
