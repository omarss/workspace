"""Integration: country/region/city plumbing through postings and clusters.

Covers Findings 1, 9, 10 from FINDINGS.md:
  * `cities`/`regions` are country-scoped — no more GCC cities masquerading
    as Saudi Eastern Province.
  * `JobPostingUpsert.region_code` + `country_code` round-trip into both
    `job_postings` and the canonical `jobs` row.
  * `jobs.create_from_posting` no longer hardcodes country_code='sa'.
  * `resolve_city` honours a parsed `country_code` so ambiguous names
    (e.g. "Al Rayyan") don't cross country lines.
"""

from __future__ import annotations

import pytest

from job_crawler.core.normalise import resolve_city, to_upsert
from job_crawler.core.types import ParsedPosting
from job_crawler_db import (
    EmploymentType,
    JobCrawlerDB,
    JobPostingUpsert,
)

pytestmark = pytest.mark.integration


async def _seed_minimal_geo(db: JobCrawlerDB) -> None:
    """Seed the geo rows the country-scoped tests depend on.

    `seeded_reference` already has SA Riyadh/Jeddah/Dammam; this adds UAE
    Dubai + Qatar Al Rayyan + SA Ras Al Khair (the three names that drove
    the original findings).
    """
    # Qatar isn't in the shared `seeded_reference` fixture; seed it here
    # so the QA region FK satisfies.
    await db.reference.upsert_country(
        code="qa", name_en="Qatar", name_ar="قطر", dial_code="+974", currency="QAR",
    )
    await db.geo.upsert_region(
        code="dubai", name_en="Dubai", name_ar="دبي", country_code="ae",
    )
    await db.geo.upsert_region(
        code="al_rayyan", name_en="Al Rayyan", name_ar="الريان", country_code="qa",
    )
    await db.geo.upsert_city(
        country_code="ae", region_code="dubai",
        name_en="Dubai", name_ar="دبي",
        latitude=25.2048, longitude=55.2708,
    )
    await db.geo.upsert_city(
        country_code="qa", region_code="al_rayyan",
        name_en="Al Rayyan", name_ar="الريان",
        latitude=25.2919, longitude=51.4244,
    )
    # SA Ras Al Khair — the industrial city previously fuzz-matched to
    # UAE's "Ras Al Khaimah".
    await db.geo.upsert_city(
        country_code="sa", region_code="eastern",
        name_en="Ras Al Khair", name_ar="رأس الخير",
        latitude=27.5167, longitude=49.2333,
    )


async def test_cities_table_is_country_scoped(seeded_reference: JobCrawlerDB) -> None:
    """Same city name can exist in two countries without collision."""
    db = seeded_reference
    await _seed_minimal_geo(db)

    # "Al Rayyan" exists only in Qatar so far. Add a SA Al Rayyan-ish row
    # under a different region to prove the unique key is per-country.
    sa_rayyan = await db.geo.upsert_city(
        country_code="sa", region_code="riyadh",
        name_en="Ar Rayyan", name_ar="الريان",
        latitude=24.7, longitude=46.6,
    )
    qa_rayyan_matches = await db.geo.find_city(
        "Al Rayyan", country_code="qa", min_similarity=0.5,
    )
    assert qa_rayyan_matches, "Qatar Al Rayyan should resolve when scoped to qa"
    assert qa_rayyan_matches[0][0].country_code == "qa"

    # SA scope should NOT bring back the Qatari row.
    sa_only = await db.geo.find_city(
        "Al Rayyan", country_code="sa", min_similarity=0.5,
    )
    assert sa_only, "SA-scoped lookup should find the SA Ar Rayyan row"
    assert all(c.country_code == "sa" for c, _ in sa_only)
    assert sa_rayyan.id in {c.id for c, _ in sa_only}


async def test_resolve_city_respects_country_hint(
    seeded_reference: JobCrawlerDB,
) -> None:
    """A parsed UAE posting should resolve to a UAE city, not the SA fuzz-match."""
    db = seeded_reference
    await _seed_minimal_geo(db)

    # "Ras Al Khair" with no country hint can match SA Ras Al Khair OR
    # UAE Ras Al Khaimah by trigram. With country_code='sa' it must pick SA.
    await db.geo.upsert_region(
        code="ras_al_khaimah", name_en="Ras Al Khaimah", name_ar="رأس الخيمة",
        country_code="ae",
    )
    await db.geo.upsert_city(
        country_code="ae", region_code="ras_al_khaimah",
        name_en="Ras Al Khaimah", name_ar="رأس الخيمة",
        latitude=25.7895, longitude=55.9432,
    )

    sa_loc = await resolve_city(db, "Ras Al Khair", country_code="sa")
    assert sa_loc.country_code == "sa"
    assert sa_loc.region_code == "eastern"

    ae_loc = await resolve_city(db, "Ras Al Khaimah", country_code="ae")
    assert ae_loc.country_code == "ae"
    assert ae_loc.region_code == "ras_al_khaimah"


async def test_posting_upsert_persists_region_and_country(
    seeded_reference: JobCrawlerDB,
) -> None:
    """End-to-end: a Riyadh posting writes through to jobs.region_code='riyadh'."""
    db = seeded_reference
    await _seed_minimal_geo(db)

    source = await db.sources.get(slug="bayt")
    assert source is not None
    parsed = ParsedPosting(
        source_job_external_id="bayt-1",
        canonical_url="https://bayt.com/jobs/bayt-1",
        title="Senior Backend Engineer",
        description="Build APIs.",
        raw_company_name="Acme",
        raw_location="Olaya, Riyadh, Saudi Arabia",
        employment_type=EmploymentType.full_time,
    )
    location = await resolve_city(
        db,
        parsed.city_name_hint,
        raw_location=parsed.raw_location,
        country_code=parsed.country_code,
    )
    assert location.country_code == "sa"
    assert location.region_code == "riyadh"

    upsert = to_upsert(
        parsed,
        source_id=source.id,
        company_id=None,
        recruiter_id=None,
        location=location,
    )
    assert upsert.country_code == "sa"
    assert upsert.region_code == "riyadh"
    assert upsert.city_id is not None

    posting = await db.postings.upsert(upsert)
    assert posting.country_code == "sa"
    assert posting.region_code == "riyadh"

    # Cluster bootstrap must mirror both.
    job = await db.jobs.create_from_posting(posting.id)
    assert job.country_code == "sa"
    assert job.region_code == "riyadh"


async def test_dubai_posting_stores_country_ae_not_sa(
    seeded_reference: JobCrawlerDB,
) -> None:
    """Greenhouse-style Dubai posting: country must end up 'ae'."""
    db = seeded_reference
    await _seed_minimal_geo(db)

    source = await db.sources.get(slug="greenhouse")
    assert source is not None
    parsed = ParsedPosting(
        source_job_external_id="gh-dubai-1",
        canonical_url="https://boards.greenhouse.io/acme/jobs/gh-dubai-1",
        title="EMEA Regulatory Counsel",
        description="UAE-based role.",
        raw_company_name="Acme",
        raw_location="Dubai, United Arab Emirates",
        country_code="ae",
    )
    location = await resolve_city(
        db,
        parsed.city_name_hint,
        raw_location=parsed.raw_location,
        country_code=parsed.country_code,
    )
    assert location.country_code == "ae"

    upsert = to_upsert(
        parsed,
        source_id=source.id,
        company_id=None,
        recruiter_id=None,
        location=location,
    )
    assert upsert.country_code == "ae"
    assert upsert.region_code == "dubai"

    posting = await db.postings.upsert(upsert)
    assert posting.country_code == "ae"
    assert posting.region_code == "dubai"
    assert posting.city_id is not None

    job = await db.jobs.create_from_posting(posting.id)
    assert job.country_code == "ae"
    assert job.region_code == "dubai"


async def test_country_only_resolution_when_city_not_seeded(
    seeded_reference: JobCrawlerDB,
) -> None:
    """Remote job in a country we know but no seeded city should still record country."""
    db = seeded_reference

    source = await db.sources.get(slug="greenhouse")
    assert source is not None
    parsed = ParsedPosting(
        source_job_external_id="gh-remote-ae-1",
        canonical_url="https://boards.greenhouse.io/acme/jobs/gh-remote-ae-1",
        title="Ecosystem Sales Manager, MEA",
        description="Remote UAE.",
        raw_company_name="Acme",
        raw_location="Remote, United Arab Emirates",
        country_code="ae",
    )
    location = await resolve_city(
        db,
        parsed.city_name_hint,
        raw_location=parsed.raw_location,
        country_code=parsed.country_code,
    )
    # No seeded UAE city matches "Remote" — country still surfaces.
    assert location.country_code == "ae"
    assert location.city_id is None

    upsert = to_upsert(
        parsed,
        source_id=source.id,
        company_id=None,
        recruiter_id=None,
        location=location,
    )
    assert upsert.country_code == "ae"
    assert upsert.city_id is None

    posting = await db.postings.upsert(upsert)
    assert posting.country_code == "ae"
    assert posting.region_code is None


async def test_recompute_canonical_mirrors_region_and_country(
    seeded_reference: JobCrawlerDB,
) -> None:
    """When a higher-trust posting joins the cluster, region/country move with it."""
    db = seeded_reference
    await _seed_minimal_geo(db)

    bayt = await db.sources.get(slug="bayt")
    greenhouse = await db.sources.get(slug="greenhouse")
    assert bayt is not None and greenhouse is not None

    # First posting (low-trust Bayt) lands a Riyadh cluster.
    bayt_loc = await resolve_city(db, None, raw_location="Riyadh, KSA", country_code="sa")
    bayt_upsert = JobPostingUpsert(
        source_id=bayt.id,
        source_job_external_id="bayt-region-1",
        canonical_url="https://bayt.com/jobs/bayt-region-1",
        title="Engineer",
        description="Some description.",
        raw_location="Riyadh, KSA",
        city_id=bayt_loc.city_id,
        region_code=bayt_loc.region_code,
        country_code=bayt_loc.country_code or "sa",
    )
    p1 = await db.postings.upsert(bayt_upsert)
    job = await db.jobs.create_from_posting(p1.id)
    assert job.region_code == "riyadh"
    assert job.country_code == "sa"

    # Greenhouse posting joins the cluster with a UAE Dubai location. After
    # recompute, the canonical posting flips to Greenhouse (higher trust)
    # and the cluster's region/country mirror that.
    gh_loc = await resolve_city(db, "Dubai", raw_location="Dubai, UAE", country_code="ae")
    gh_upsert = JobPostingUpsert(
        source_id=greenhouse.id,
        source_job_external_id="gh-region-1",
        canonical_url="https://boards.greenhouse.io/acme/jobs/gh-region-1",
        title="Engineer",
        description="Some description.",
        raw_location="Dubai, UAE",
        city_id=gh_loc.city_id,
        region_code=gh_loc.region_code,
        country_code=gh_loc.country_code or "ae",
    )
    p2 = await db.postings.upsert(gh_upsert)
    await db.postings.attach_to_cluster(p2.id, job.id)

    refreshed = await db.jobs.recompute_canonical(job.id)
    assert refreshed.canonical_posting_id == p2.id
    assert refreshed.region_code == "dubai"
    assert refreshed.country_code == "ae"
