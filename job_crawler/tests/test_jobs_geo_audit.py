"""Integration tests for `JobsRepo.audit_geo_atomic_triples`.

PR #85 fixed `recompute_canonical` so that every `jobs` row's
`(city_id, country_code, region_code)` triple is derived atomically
from the linked `cities` row. The audit is the standing guard against
a regression: a code path that writes `country_code` / `region_code`
independently of the linked city will surface here.
"""

from __future__ import annotations

import pytest

from job_crawler_db import JobCrawlerDB

pytestmark = pytest.mark.integration


async def test_audit_returns_empty_for_consistent_clusters(
    seeded_reference: JobCrawlerDB,
) -> None:
    """Right after `recompute_canonical` runs, every cluster's geo
    triple must agree with its linked city."""
    db = seeded_reference

    bayt = await db.sources.get(slug="bayt")
    assert bayt is not None
    riyadh = (await db.geo.find_city("Riyadh"))[0][0]
    from job_crawler_db import JobPostingUpsert

    upsert = JobPostingUpsert(
        source_id=bayt.id,
        source_job_external_id="audit-1",
        canonical_url="https://bayt.com/audit-1",
        title="Senior Engineer",
        description="Long description body for testing.",
        raw_company_name="Acme",
        city_id=riyadh.id,
        country_code="sa",
        region_code="riyadh",
    )
    posting = await db.postings.upsert(upsert)
    cluster = await db.jobs.create_from_posting(posting.id)
    await db.jobs.recompute_canonical(cluster.id)

    violations = await db.jobs.audit_geo_atomic_triples()
    assert violations == []


async def test_audit_flags_manually_desynced_triple(
    seeded_reference: JobCrawlerDB,
) -> None:
    """If a manual UPDATE writes `country_code` independently of the
    linked city, the audit must catch it. This protects against future
    code paths that bypass `recompute_canonical`."""
    db = seeded_reference

    bayt = await db.sources.get(slug="bayt")
    assert bayt is not None
    riyadh = (await db.geo.find_city("Riyadh"))[0][0]
    from job_crawler_db import JobPostingUpsert

    upsert = JobPostingUpsert(
        source_id=bayt.id,
        source_job_external_id="audit-2",
        canonical_url="https://bayt.com/audit-2",
        title="Backend Engineer",
        description="Long description body for testing.",
        raw_company_name="Acme",
        city_id=riyadh.id,
        country_code="sa",
        region_code="riyadh",
    )
    posting = await db.postings.upsert(upsert)
    cluster = await db.jobs.create_from_posting(posting.id)
    await db.jobs.recompute_canonical(cluster.id)

    # Simulate a buggy code path that breaks the atomic triple by
    # writing region_code independently of city_id. We pick `makkah`
    # because it's seeded in the seeded_reference fixture (so the
    # (sa, makkah) FK passes) but doesn't match the linked city's
    # region (`riyadh`) — exactly the desync the audit must catch.
    async with db.pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE jobs SET region_code='makkah' WHERE id=%(j)s",
            {"j": cluster.id},
        )

    violations = await db.jobs.audit_geo_atomic_triples()
    assert len(violations) == 1
    row = violations[0]
    assert row["job_id"] == cluster.id
    assert row["job_country_code"] == "sa"
    assert row["city_country_code"] == "sa"
    assert row["job_region_code"] == "makkah"
    assert row["city_region_code"] == "riyadh"
