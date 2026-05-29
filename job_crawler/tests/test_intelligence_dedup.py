"""Integration tests for the cluster-dedup pipeline (`intelligence.dedup`).

The pipeline runs as the tail step of every crawl. These tests verify
each stage in isolation against a real Postgres instance (testcontainer)
to catch regressions in the SQL join shape or the post-merge canonical
recomputation.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from job_crawler.intelligence import dedup
from job_crawler_db import (
    EmploymentType,
    JobCrawlerDB,
    JobPostingUpsert,
    SalaryPeriod,
)

pytestmark = pytest.mark.integration


async def _make_posting(
    db: JobCrawlerDB,
    *,
    source_slug: str,
    external_id: str,
    title: str,
    description: str,
    company_id: UUID,
    city_id: UUID | None = None,
    raw_location: str = "Riyadh, KSA",
) -> JobPostingUpsert:
    source = await db.sources.get(slug=source_slug)
    assert source is not None, f"seed missing source {source_slug}"
    return JobPostingUpsert(
        source_id=source.id,
        source_job_external_id=external_id,
        canonical_url=f"https://{source_slug}.example/jobs/{external_id}",
        title=title,
        description=description,
        company_id=company_id,
        raw_company_name="Tamara",
        raw_location=raw_location,
        city_id=city_id,
        employment_type=EmploymentType.full_time,
        salary_min=Decimal("18000"),
        salary_max=Decimal("25000"),
        salary_currency="SAR",
        salary_period=SalaryPeriod.monthly,
    )


async def test_stage3_merges_when_one_side_has_null_city(
    seeded_reference: JobCrawlerDB,
) -> None:
    """Stage 3 catches the "recycled" pattern where the same role is on
    a direct ATS (with city resolved) AND on an aggregator (city=NULL).
    Stage 2 misses these because of its strict `city_id` equality."""
    db = seeded_reference
    company = await db.companies.create(name_en="Tamara")
    riyadh_matches = await db.geo.find_city("Riyadh", country_code="sa", limit=1)
    assert riyadh_matches, "seed missing Riyadh"
    riyadh = riyadh_matches[0][0]

    # ATS posting: city resolved.
    p_gh = await db.postings.upsert(
        await _make_posting(
            db,
            source_slug="greenhouse",
            external_id="gh-1001",
            title="Senior Python Engineer",
            description="Build payment infrastructure. Strong Python required.",
            company_id=company.id,
            city_id=riyadh.id,
        ),
    )
    # Aggregator repost: city left NULL.
    p_bayt = await db.postings.upsert(
        await _make_posting(
            db,
            source_slug="bayt",
            external_id="bayt-1001",
            title="Senior Python Engineer",
            description="Different blurb — paraphrased by the agency.",
            company_id=company.id,
            city_id=None,
            raw_location="Saudi Arabia",
        ),
    )
    c_gh = await db.jobs.create_from_posting(p_gh.id)
    c_bayt = await db.jobs.create_from_posting(p_bayt.id)
    assert c_gh.id != c_bayt.id, "must start as two separate clusters"

    summary = await dedup.run(db)

    # Stage 3 should have merged the two clusters. Surviving cluster's
    # canonical is the ATS posting (direct tier wins).
    p_gh_after = await db.postings.get(p_gh.id)
    p_bayt_after = await db.postings.get(p_bayt.id)
    assert p_gh_after is not None and p_bayt_after is not None
    assert p_gh_after.cluster_job_id == p_bayt_after.cluster_job_id
    assert p_gh_after.cluster_job_id is not None
    survivor = await db.jobs.get(p_gh_after.cluster_job_id)
    assert survivor is not None
    assert survivor.canonical_posting_id == p_gh.id, (
        "ATS posting must win over Bayt — direct over intermediate"
    )
    assert summary.clusters_merged >= 1


async def test_stage3_skips_when_titles_diverge(
    seeded_reference: JobCrawlerDB,
) -> None:
    """Stage 3 requires title sim ≥ 0.85. Two genuinely different roles
    at the same company must NOT collapse just because both have the
    same NULL city."""
    db = seeded_reference
    company = await db.companies.create(name_en="Tamara")

    p_se = await db.postings.upsert(
        await _make_posting(
            db,
            source_slug="bayt",
            external_id="bayt-se",
            title="Software Engineer",
            description="Backend role.",
            company_id=company.id,
            city_id=None,
        ),
    )
    p_pm = await db.postings.upsert(
        await _make_posting(
            db,
            source_slug="bayt",
            external_id="bayt-pm",
            title="Product Manager",
            description="Product role.",
            company_id=company.id,
            city_id=None,
        ),
    )
    c_se = await db.jobs.create_from_posting(p_se.id)
    c_pm = await db.jobs.create_from_posting(p_pm.id)

    await dedup.run(db)

    p_se_after = await db.postings.get(p_se.id)
    p_pm_after = await db.postings.get(p_pm.id)
    assert p_se_after is not None and p_pm_after is not None
    assert p_se_after.cluster_job_id != p_pm_after.cluster_job_id, (
        "different roles must remain separate clusters"
    )
    assert p_se_after.cluster_job_id == c_se.id
    assert p_pm_after.cluster_job_id == c_pm.id


async def test_recompute_canonical_prefers_ats_over_aggregator(
    seeded_reference: JobCrawlerDB,
) -> None:
    """The cluster's canonical_posting_id must point to the most direct
    source available. Greenhouse (ATS, tier=2) outranks LinkedIn
    (aggregator, tier=0) regardless of trust_weight tiebreakers."""
    db = seeded_reference
    company = await db.companies.create(name_en="Tamara")

    p_li = await db.postings.upsert(
        await _make_posting(
            db,
            source_slug="linkedin",
            external_id="li-1",
            title="Backend Engineer",
            description="LinkedIn copy.",
            company_id=company.id,
        ),
    )
    cluster = await db.jobs.create_from_posting(p_li.id)

    p_gh = await db.postings.upsert(
        await _make_posting(
            db,
            source_slug="greenhouse",
            external_id="gh-1",
            title="Backend Engineer",
            description="Greenhouse copy.",
            company_id=company.id,
        ),
    )
    await db.postings.attach_to_cluster(p_gh.id, cluster.id)

    refreshed = await db.jobs.recompute_canonical(cluster.id)
    assert refreshed.canonical_posting_id == p_gh.id, (
        "ATS (direct) must win over LinkedIn (aggregator)"
    )


async def test_recompute_canonical_prefers_gov_over_ats(
    seeded_reference: JobCrawlerDB,
) -> None:
    """Government portal (Jadarat) outranks ATS — top of the direct tier."""
    db = seeded_reference
    company = await db.companies.create(name_en="Saudi Aramco")

    p_gh = await db.postings.upsert(
        await _make_posting(
            db,
            source_slug="greenhouse",
            external_id="gh-aramco",
            title="Petroleum Engineer",
            description="Aramco via Greenhouse.",
            company_id=company.id,
        ),
    )
    cluster = await db.jobs.create_from_posting(p_gh.id)

    p_jad = await db.postings.upsert(
        await _make_posting(
            db,
            source_slug="jadarat",
            external_id="jad-aramco",
            title="Petroleum Engineer",
            description="Aramco via Jadarat.",
            company_id=company.id,
        ),
    )
    await db.postings.attach_to_cluster(p_jad.id, cluster.id)

    refreshed = await db.jobs.recompute_canonical(cluster.id)
    assert refreshed.canonical_posting_id == p_jad.id, (
        "gov_board outranks ATS in the directness tier"
    )
