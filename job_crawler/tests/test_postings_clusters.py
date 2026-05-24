"""Integration: posting upsert, snapshots, cluster lifecycle, multi-location, recruiters."""

from __future__ import annotations

from decimal import Decimal

import pytest

from job_crawler_db import (
    ApplicationChannelKind,
    EmploymentType,
    ExperienceLevel,
    JobCrawlerDB,
    JobPostingUpsert,
    PostingStatus,
    SalaryPeriod,
    SkillKind,
    SkillProficiency,
    SkillRequirement,
    WorkArrangement,
)

pytestmark = pytest.mark.integration


async def _make_posting(
    db: JobCrawlerDB,
    *,
    source_slug: str = "linkedin",
    external_id: str = "li-1",
    title: str = "Senior Software Engineer",
    description: str = "Build great software. Strong Python background required.",
    company_name: str | None = "Acme",
    hiring_manager_url: str | None = None,
) -> JobPostingUpsert:
    source = await db.sources.get(slug=source_slug)
    assert source is not None
    company = None
    if company_name:
        existing = await db.companies.find_by_name(company_name, min_similarity=0.7)
        company = existing[0][0] if existing else await db.companies.create(name_en=company_name)
    return JobPostingUpsert(
        source_id=source.id,
        source_job_external_id=external_id,
        canonical_url=f"https://{source_slug}.com/jobs/{external_id}",
        title=title,
        description=description,
        company_id=company.id if company else None,
        raw_company_name=company_name,
        raw_location="Riyadh, KSA",
        employment_type=EmploymentType.full_time,
        work_arrangement=WorkArrangement.hybrid,
        experience_level=ExperienceLevel.senior,
        salary_min=Decimal("18000"),
        salary_max=Decimal("25000"),
        salary_currency="SAR",
        salary_period=SalaryPeriod.monthly,
        hiring_manager_linkedin_url=hiring_manager_url,
        hiring_manager_name="Sarah Al-Otaibi" if hiring_manager_url else None,
    )


async def test_upsert_inserts_and_idempotently_updates(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    payload = await _make_posting(db)

    p1 = await db.postings.upsert(payload)
    assert p1.fetch_count == 1
    assert p1.url_hash and len(p1.url_hash) == 32
    assert p1.content_hash is not None

    p2 = await db.postings.upsert(payload)
    assert p2.id == p1.id
    assert p2.fetch_count == 2
    # No tracked field changed → no snapshot row.
    snaps = await db.postings.list_snapshots(p1.id)
    assert snaps == []


async def test_upsert_records_snapshot_when_title_changes(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    payload = await _make_posting(db)
    p1 = await db.postings.upsert(payload)

    changed = payload.model_copy(update={"title": "Staff Software Engineer"})
    p2 = await db.postings.upsert(changed)
    assert p2.id == p1.id
    assert p2.title == "Staff Software Engineer"

    snaps = await db.postings.list_snapshots(p1.id)
    assert len(snaps) == 1
    assert snaps[0].changed_fields["title"] == "Staff Software Engineer"


async def test_upsert_records_snapshot_when_description_changes(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    payload = await _make_posting(db, description="Original description.")
    p1 = await db.postings.upsert(payload)

    changed = payload.model_copy(update={"description": "Updated and rewritten description!"})
    await db.postings.upsert(changed)

    snaps = await db.postings.list_snapshots(p1.id)
    assert len(snaps) == 1
    assert "description" in snaps[0].changed_fields


async def test_get_by_url_normalises_tracking_params(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    payload = await _make_posting(db, external_id="li-2")
    p1 = await db.postings.upsert(payload)

    # Same URL with utm params should hash to the same row.
    found = await db.postings.get_by_url(
        f"{payload.canonical_url}?utm_source=newsletter&utm_campaign=spring",
    )
    assert found is not None and found.id == p1.id


async def test_cluster_from_posting_and_attach_more(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p1 = await db.postings.upsert(await _make_posting(db, external_id="li-3"))
    cluster = await db.jobs.create_from_posting(p1.id)
    assert cluster.posting_count == 1
    assert cluster.canonical_posting_id == p1.id
    assert cluster.title_en == p1.title

    # Same job re-posted on Bayt — attach to the same cluster.
    p2 = await db.postings.upsert(
        await _make_posting(db, source_slug="bayt", external_id="bayt-3", title="Senior SWE"),
    )
    await db.postings.attach_to_cluster(p2.id, cluster.id)

    refreshed = await db.jobs.get(cluster.id)
    assert refreshed is not None
    assert refreshed.posting_count == 2

    # Re-attach is idempotent.
    await db.postings.attach_to_cluster(p2.id, cluster.id)
    refreshed2 = await db.jobs.get(cluster.id)
    assert refreshed2 is not None
    assert refreshed2.posting_count == 2


async def test_recompute_canonical_picks_higher_trust_source(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    li_payload = await _make_posting(db, source_slug="linkedin", external_id="li-cn")
    gh_payload = await _make_posting(
        db,
        source_slug="greenhouse",
        external_id="gh-cn",
        title="Greenhouse Senior SWE",
    )
    p_li = await db.postings.upsert(li_payload)
    p_gh = await db.postings.upsert(gh_payload)

    cluster = await db.jobs.create_from_posting(p_li.id)
    await db.postings.attach_to_cluster(p_gh.id, cluster.id)
    refreshed = await db.jobs.recompute_canonical(cluster.id)
    # Greenhouse trust_weight (0.95) > LinkedIn (0.60) → its title wins.
    assert refreshed.title_en == "Greenhouse Senior SWE"
    assert refreshed.canonical_posting_id == p_gh.id


async def test_merge_clusters_moves_postings_and_signals(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    p1 = await db.postings.upsert(await _make_posting(db, external_id="li-A"))
    p2 = await db.postings.upsert(await _make_posting(db, external_id="li-B", source_slug="bayt"))
    c1 = await db.jobs.create_from_posting(p1.id)
    c2 = await db.jobs.create_from_posting(p2.id)
    assert c1.id != c2.id

    # Add evidence on the source cluster — it should survive the merge.
    from job_crawler_db import FakeSignalKind

    await db.fake_signals.add(c2.id, FakeSignalKind.reposted_within_30d, weight=-0.2)

    merged = await db.jobs.merge(target=c1.id, source=c2.id)
    assert merged.id == c1.id
    assert merged.posting_count == 2
    # Source cluster gone.
    assert await db.jobs.get(c2.id) is None
    # Signal re-pointed.
    signals = await db.fake_signals.list_for_job(c1.id)
    assert any(s.kind == FakeSignalKind.reposted_within_30d for s in signals)


async def test_skill_linkage_with_granular_fields(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p = await db.postings.upsert(await _make_posting(db, external_id="li-skills"))
    cluster = await db.jobs.create_from_posting(p.id)
    python = await db.skills.create(slug="python", name_en="Python", kind=SkillKind.tool)

    link = await db.jobs.link_skill(
        cluster.id,
        python.id,
        requirement=SkillRequirement.required,
        proficiency_level=SkillProficiency.advanced,
        min_years=4,
        last_used_within_years=2,
        importance=0.9,
        confidence=0.95,
    )
    assert link.min_years == 4
    assert link.proficiency_level == SkillProficiency.advanced

    listed = await db.jobs.list_skills(cluster.id)
    assert len(listed) == 1
    link_back, skill = listed[0]
    assert skill.name_en == "Python"
    assert link_back.importance == Decimal("0.900")


async def test_application_channels_per_posting(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p = await db.postings.upsert(await _make_posting(db, external_id="li-apply"))
    await db.postings.add_application_channel(
        p.id,
        kind=ApplicationChannelKind.url,
        value="https://acme.sa/apply/1",
        is_primary=True,
    )
    await db.postings.add_application_channel(
        p.id,
        kind=ApplicationChannelKind.email,
        value="careers@acme.sa",
    )
    chans = await db.postings.list_application_channels(p.id)
    assert len(chans) == 2
    primary = [c for c in chans if c.is_primary]
    assert len(primary) == 1


async def test_multiple_locations_for_one_job(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p = await db.postings.upsert(await _make_posting(db, external_id="li-multi"))
    cluster = await db.jobs.create_from_posting(p.id)

    riyadh = (await db.geo.find_city("Riyadh"))[0][0]
    jeddah = (await db.geo.find_city("Jeddah"))[0][0]
    dammam = (await db.geo.find_city("Dammam"))[0][0]

    await db.job_locations.add(cluster.id, city_id=riyadh.id, is_primary=True)
    await db.job_locations.add(cluster.id, city_id=jeddah.id)
    await db.job_locations.add(cluster.id, city_id=dammam.id, office_address="Khobar Tower")

    locs = await db.job_locations.list_for_job(cluster.id)
    assert len(locs) == 3
    primary = [loc for loc in locs if loc.is_primary]
    assert len(primary) == 1 and primary[0].city_id == riyadh.id


async def test_setting_a_new_primary_demotes_old(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    p = await db.postings.upsert(await _make_posting(db, external_id="li-primary"))
    cluster = await db.jobs.create_from_posting(p.id)

    riyadh = (await db.geo.find_city("Riyadh"))[0][0]
    jeddah = (await db.geo.find_city("Jeddah"))[0][0]
    await db.job_locations.add(cluster.id, city_id=riyadh.id, is_primary=True)
    await db.job_locations.add(cluster.id, city_id=jeddah.id, is_primary=True)

    locs = await db.job_locations.list_for_job(cluster.id)
    primaries = [loc for loc in locs if loc.is_primary]
    assert len(primaries) == 1
    assert primaries[0].city_id == jeddah.id


async def test_recruiter_attribution_on_posting(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    recruiter = await db.recruiters.create(
        full_name="Lina Recruiter",
        linkedin_url="https://linkedin.com/in/lina-recruiter",
    )
    payload = await _make_posting(db, external_id="li-r")
    payload = payload.model_copy(update={"posted_by_recruiter_id": recruiter.id})
    p = await db.postings.upsert(payload)
    assert p.posted_by_recruiter_id == recruiter.id


async def test_hiring_manager_propagates_to_cluster_canonical(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    payload = await _make_posting(
        db,
        external_id="li-hm",
        hiring_manager_url="https://linkedin.com/in/sarah-al-otaibi",
    )
    p = await db.postings.upsert(payload)
    cluster = await db.jobs.create_from_posting(p.id)
    refreshed = await db.jobs.recompute_canonical(cluster.id)
    assert refreshed.hiring_manager_linkedin_url == "https://linkedin.com/in/sarah-al-otaibi"
    assert refreshed.hiring_manager_name == "Sarah Al-Otaibi"


async def test_mark_status_and_close_when_no_active_posting(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    p = await db.postings.upsert(await _make_posting(db, external_id="li-close"))
    cluster = await db.jobs.create_from_posting(p.id)
    await db.postings.mark_status(p.id, PostingStatus.removed)
    refreshed = await db.jobs.recompute_canonical(cluster.id)
    assert refreshed.closed_at is not None
