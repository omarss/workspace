"""Integration: SourcesRepo.upsert preserves operator-set crawl_enabled.

Finding 14: crawler_health auto-disables broken sources, but the legacy
upsert always wrote `crawl_enabled = EXCLUDED.crawl_enabled` so
`CrawlerRunner.ensure_source()` re-enabled the source on every run. The
fix is COALESCE — only an explicit non-None value overrides.
"""

from __future__ import annotations

import pytest

from job_crawler_db import JobCrawlerDB, SourceKind

pytestmark = pytest.mark.integration


async def test_upsert_preserves_existing_crawl_enabled(db: JobCrawlerDB) -> None:
    """A source disabled by crawler_health stays disabled across runner upserts."""
    source = await db.sources.upsert(
        slug="linkedin",
        display_name="LinkedIn",
        kind=SourceKind.aggregator,
        base_url="https://linkedin.com",
        trust_weight=0.6,
    )
    assert source.crawl_enabled is True

    # Simulate crawler_health.mark_broken disabling the source.
    await db.sources._execute(
        "UPDATE sources SET crawl_enabled = false WHERE id = %(s)s",
        {"s": source.id},
    )

    # The runner calls upsert(...) with no crawl_enabled kwarg on every
    # invocation — that must NOT silently flip the flag back to True.
    after_runner = await db.sources.upsert(
        slug="linkedin",
        display_name="LinkedIn",
        kind=SourceKind.aggregator,
        base_url="https://linkedin.com",
        trust_weight=0.6,
    )
    assert after_runner.crawl_enabled is False, (
        "runner upsert silently re-enabled a broken source"
    )


async def test_upsert_explicit_true_re_enables(db: JobCrawlerDB) -> None:
    """An operator explicitly passing crawl_enabled=True still works."""
    source = await db.sources.upsert(
        slug="bayt",
        display_name="Bayt",
        kind=SourceKind.regional_board,
        base_url="https://bayt.com",
        trust_weight=0.55,
        crawl_enabled=False,
    )
    assert source.crawl_enabled is False

    flipped = await db.sources.upsert(
        slug="bayt",
        display_name="Bayt",
        kind=SourceKind.regional_board,
        base_url="https://bayt.com",
        trust_weight=0.55,
        crawl_enabled=True,
    )
    assert flipped.crawl_enabled is True


async def test_upsert_explicit_false_disables(db: JobCrawlerDB) -> None:
    """Operator can still disable an enabled source via explicit kwarg."""
    await db.sources.upsert(
        slug="greenhouse",
        display_name="Greenhouse",
        kind=SourceKind.ats,
        base_url="https://boards.greenhouse.io",
        trust_weight=0.9,
    )

    disabled = await db.sources.upsert(
        slug="greenhouse",
        display_name="Greenhouse",
        kind=SourceKind.ats,
        base_url="https://boards.greenhouse.io",
        trust_weight=0.9,
        crawl_enabled=False,
    )
    assert disabled.crawl_enabled is False
