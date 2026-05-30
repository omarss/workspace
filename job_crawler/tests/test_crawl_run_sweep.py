"""Integration tests for `CrawlRepo.sweep_stale_runs`.

The sweep cancels any `crawl_runs` row that's still on `status='running'`
past a configurable age, scoped to a single source. It is invoked at the
start of every runner cycle so OOM / systemd-timeout / uncaught-exception
crashes can't leave zombie rows in the table indefinitely.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import pytest

from job_crawler_db import CrawlRunStatus, JobCrawlerDB

pytestmark = pytest.mark.integration


async def _running_row(db: JobCrawlerDB, source_id: UUID, *, age_minutes: int) -> UUID:
    """Insert a synthetic `running` crawl_runs row with `started_at`
    moved into the past by `age_minutes`. Returns the row's id.

    The pool's row-factory is `dict_row` (configured globally in
    `pool._on_checkout`), so cursors here yield dict-shaped rows even
    though psycopg's stub types them as tuples by default — hence the
    explicit cast for mypy.
    """
    async with db.pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO crawl_runs (source_id, status, started_at)
            VALUES (%(s)s, 'running', now() - (%(m)s::int * INTERVAL '1 minute'))
            RETURNING id;
            """,
            {"s": source_id, "m": age_minutes},
        )
        row = await cur.fetchone()
    assert row is not None
    return cast("UUID", cast("dict[str, Any]", row)["id"])


async def test_sweep_cancels_only_rows_older_than_cap(
    seeded_reference: JobCrawlerDB,
) -> None:
    """A row older than the cap transitions to `cancelled`; a fresher
    row stays on `running`."""
    db = seeded_reference
    bayt = await db.sources.get(slug="bayt")
    assert bayt is not None

    stale_id = await _running_row(db, bayt.id, age_minutes=300)  # 5h old
    fresh_id = await _running_row(db, bayt.id, age_minutes=5)    # 5min old

    swept = await db.crawl.sweep_stale_runs(bayt.id, max_age_minutes=120)
    assert swept == 1

    stale = await db.crawl.get_run(stale_id)
    fresh = await db.crawl.get_run(fresh_id)
    assert stale is not None and stale.status is CrawlRunStatus.cancelled
    assert stale.finished_at is not None
    assert stale.error_summary is not None
    assert "120 minute" in stale.error_summary

    assert fresh is not None and fresh.status is CrawlRunStatus.running


async def test_sweep_is_scoped_to_source_id(seeded_reference: JobCrawlerDB) -> None:
    """A stale row on a DIFFERENT source must NOT be touched by a sweep
    scoped to this source. Two concurrent crawlers must not cancel each
    other's legitimate runs."""
    db = seeded_reference
    bayt = await db.sources.get(slug="bayt")
    linkedin = await db.sources.get(slug="linkedin")
    assert bayt is not None and linkedin is not None

    bayt_stale = await _running_row(db, bayt.id, age_minutes=300)
    linkedin_stale = await _running_row(db, linkedin.id, age_minutes=300)

    swept = await db.crawl.sweep_stale_runs(bayt.id, max_age_minutes=120)
    assert swept == 1

    bayt_row = await db.crawl.get_run(bayt_stale)
    linkedin_row = await db.crawl.get_run(linkedin_stale)
    assert bayt_row is not None and bayt_row.status is CrawlRunStatus.cancelled
    assert linkedin_row is not None and linkedin_row.status is CrawlRunStatus.running


async def test_sweep_ignores_already_finished_runs(
    seeded_reference: JobCrawlerDB,
) -> None:
    """A `completed` or `failed` row must remain untouched even if its
    started_at is far in the past."""
    db = seeded_reference
    bayt = await db.sources.get(slug="bayt")
    assert bayt is not None

    completed_id = await _running_row(db, bayt.id, age_minutes=600)
    await db.crawl.finish_run(completed_id, status=CrawlRunStatus.completed)

    swept = await db.crawl.sweep_stale_runs(bayt.id, max_age_minutes=120)
    assert swept == 0

    row = await db.crawl.get_run(completed_id)
    assert row is not None and row.status is CrawlRunStatus.completed
