"""Integration test for the over-merge repair (`scripts.repair_crawler_data`).

Builds a synthetic over-merged cluster (two distinct roles forced into one
cluster, as the old trigram dedup did) and verifies the repair splits them
back into one cluster per role while preserving every posting.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from psycopg.rows import dict_row

from job_crawler_db import JobCrawlerDB, JobPosting, JobPostingUpsert
from scripts.repair_crawler_data import _repair_over_merges

pytestmark = pytest.mark.integration


async def _posting(
    db: JobCrawlerDB, src_id: UUID, ext: str, title: str, city_id: UUID
) -> JobPosting:
    return await db.postings.upsert(
        JobPostingUpsert(
            source_id=src_id,
            source_job_external_id=ext,
            canonical_url=f"https://bayt.com/{ext}",
            title=title,
            description="A sufficiently long description body for the posting.",
            raw_company_name="Acme",
            city_id=city_id,
            country_code="sa",
            region_code="riyadh",
        )
    )


async def test_split_restores_distinct_roles(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    bayt = await db.sources.get(slug="bayt")
    assert bayt is not None
    riyadh = (await db.geo.find_city("Riyadh"))[0][0]

    # Two distinct roles + a same-role pair, all forced into ONE cluster
    # to mimic the old over-merge.
    p_carp = await _posting(db, bayt.id, "carp", "Service Associate - Carpenter", riyadh.id)
    p_ctr1 = await _posting(db, bayt.id, "ctr1", "Service Associate - Service Center", riyadh.id)
    p_ctr2 = await _posting(db, bayt.id, "ctr2", "Service Associate - Service Center", riyadh.id)

    cluster = await db.jobs.create_from_posting(p_ctr1.id)
    # Force the other two into the same cluster (what the buggy dedup did).
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "UPDATE job_postings SET cluster_job_id = %(c)s WHERE id = ANY(%(ids)s)",
            {"c": cluster.id, "ids": [p_carp.id, p_ctr2.id]},
        )

    # Sanity: one cluster, three postings.
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT COUNT(DISTINCT cluster_job_id) AS n FROM job_postings")
        row = await cur.fetchone()
        assert row is not None and row["n"] == 1

    created = await _repair_over_merges(db, apply=True)
    assert created == 1  # Carpenter split off; the two Service Center stay

    # Now two clusters: {Carpenter}, {Service Center x2}. No posting lost.
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT COUNT(DISTINCT cluster_job_id) AS n FROM job_postings")
        row = await cur.fetchone()
        assert row is not None and row["n"] == 2
        await cur.execute("SELECT COUNT(*) AS n FROM job_postings WHERE cluster_job_id IS NULL")
        row = await cur.fetchone()
        assert row is not None and row["n"] == 0

    carp = await db.postings.get(p_carp.id)
    ctr1 = await db.postings.get(p_ctr1.id)
    ctr2 = await db.postings.get(p_ctr2.id)
    assert carp is not None and ctr1 is not None and ctr2 is not None
    assert carp.cluster_job_id != ctr1.cluster_job_id  # split apart
    assert ctr1.cluster_job_id == ctr2.cluster_job_id   # same role stays together

    # Idempotent: a second pass finds nothing to split.
    assert await _repair_over_merges(db, apply=True) == 0
