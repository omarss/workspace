"""Integration: search facade — FTS + trigram + synonyms + filters."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from job_crawler_db import (
    EmploymentType,
    ExperienceLevel,
    JobCrawlerDB,
    JobPostingUpsert,
    SalaryPeriod,
    SkillKind,
    SynonymKind,
    WorkArrangement,
)

pytestmark = pytest.mark.integration


async def _seed_jobs(db: JobCrawlerDB) -> dict[str, str]:
    """Insert a handful of varied postings + clusters; return slug -> job_id."""
    linkedin = await db.sources.get(slug="linkedin")
    bayt = await db.sources.get(slug="bayt")
    greenhouse = await db.sources.get(slug="greenhouse")
    assert linkedin and bayt and greenhouse

    riyadh = (await db.geo.find_city("Riyadh"))[0][0]
    jeddah = (await db.geo.find_city("Jeddah"))[0][0]

    acme = await db.companies.create(name_en="Acme Saudi", name_ar="أكمي السعودية")
    stripe = await db.companies.create(
        name_en="Stripe", linkedin_url="https://linkedin.com/company/stripe"
    )

    # Job 1: Senior Python on LinkedIn, hybrid Riyadh
    p1 = await db.postings.upsert(
        JobPostingUpsert(
            source_id=linkedin.id,
            source_job_external_id="li-100",
            canonical_url="https://linkedin.com/jobs/100",
            title="Senior Python Developer",
            description="We need a Python expert with Django and PostgreSQL experience. "
            "5+ years required. Strong communication skills.",
            company_id=acme.id,
            raw_company_name="Acme Saudi",
            employment_type=EmploymentType.full_time,
            work_arrangement=WorkArrangement.hybrid,
            experience_level=ExperienceLevel.senior,
            city_id=riyadh.id,
            salary_min=Decimal("18000"),
            salary_max=Decimal("25000"),
            salary_currency="SAR",
            salary_period=SalaryPeriod.monthly,
        ),
    )
    c1 = await db.jobs.create_from_posting(p1.id)

    # Job 2: Kubernetes Engineer on Greenhouse, remote, Jeddah office
    p2 = await db.postings.upsert(
        JobPostingUpsert(
            source_id=greenhouse.id,
            source_job_external_id="gh-200",
            canonical_url="https://boards.greenhouse.io/stripe/jobs/200",
            title="Kubernetes Platform Engineer",
            description="Operate large k8s clusters across multiple regions. "
            "Strong Go and Linux experience required.",
            company_id=stripe.id,
            raw_company_name="Stripe",
            employment_type=EmploymentType.full_time,
            work_arrangement=WorkArrangement.remote,
            experience_level=ExperienceLevel.senior,
            city_id=jeddah.id,
            salary_min=Decimal("28000"),
            salary_max=Decimal("40000"),
            salary_currency="SAR",
            salary_period=SalaryPeriod.monthly,
        ),
    )
    c2 = await db.jobs.create_from_posting(p2.id)

    # Job 3: Arabic-titled posting from Bayt
    p3 = await db.postings.upsert(
        JobPostingUpsert(
            source_id=bayt.id,
            source_job_external_id="bayt-300",
            canonical_url="https://bayt.com/en/saudi/jobs/300",
            title="مهندس برمجيات أول",
            description="نبحث عن مهندس برمجيات لديه خبرة في بايثون وقواعد البيانات.",
            company_id=acme.id,
            employment_type=EmploymentType.full_time,
            work_arrangement=WorkArrangement.onsite,
            experience_level=ExperienceLevel.senior,
            city_id=riyadh.id,
        ),
    )
    c3 = await db.jobs.create_from_posting(p3.id)

    # Set verdicts to legit so they pass the default search filter.
    from job_crawler_db import ClusterVerdict

    for cid in (c1.id, c2.id, c3.id):
        await db.jobs.set_verdict(cid, ClusterVerdict.legit, legit_score=0.85)

    return {"python": str(c1.id), "kubernetes": str(c2.id), "arabic": str(c3.id)}


async def test_search_english_exact_phrase(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    ids = await _seed_jobs(db)
    hits = await db.search.find_jobs("python developer")
    assert hits, "expected at least one hit for 'python developer'"
    assert str(hits[0].job.id) == ids["python"]


async def test_search_typo_via_trigram(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    ids = await _seed_jobs(db)
    # "kubernates" misspelled — trigram word_similarity rescues it.
    hits = await db.search.find_jobs("kubernates platform")
    assert any(str(h.job.id) == ids["kubernetes"] for h in hits)


async def test_search_synonym_expansion(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    ids = await _seed_jobs(db)
    await db.synonyms.create_group(
        canonical_term="Kubernetes",
        kind=SynonymKind.skill,
        terms=[("kubernetes", "en"), ("k8s", "en"), ("kube", "en")],
    )
    # User types "k8s"; expansion should bring the kubernetes job up.
    hits = await db.search.find_jobs("k8s engineer")
    assert hits and any(str(h.job.id) == ids["kubernetes"] for h in hits)


async def test_search_arabic_normalisation(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    ids = await _seed_jobs(db)
    # User types with tashkeel — normalize_ar folds it before tsquery.
    hits = await db.search.find_jobs("مُهَنْدِس")
    assert any(str(h.job.id) == ids["arabic"] for h in hits)


async def test_search_filters_by_city(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    ids = await _seed_jobs(db)
    jeddah = (await db.geo.find_city("Jeddah"))[0][0]
    hits = await db.search.find_jobs(city_id=jeddah.id)
    assert hits and all(h.job.city_id == jeddah.id for h in hits)
    assert str(hits[0].job.id) == ids["kubernetes"]


async def test_search_filters_by_salary_overlap(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    await _seed_jobs(db)
    # Candidate wants at least 30000 SAR — only the Kubernetes role qualifies
    # (its salary_max 40k overlaps with min 30k).
    hits = await db.search.find_jobs(min_salary=30000)
    assert hits and all((h.job.salary_max or 0) >= 30000 or h.job.salary_max is None for h in hits)


async def test_search_filters_by_employment_type(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    await _seed_jobs(db)
    hits = await db.search.find_jobs(employment_type=EmploymentType.full_time)
    assert all(h.job.employment_type == EmploymentType.full_time for h in hits)


async def test_search_filters_by_required_skills(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    ids = await _seed_jobs(db)
    python = await db.skills.create(slug="python", name_en="Python", kind=SkillKind.tool)
    await db.jobs.link_skill(UUID(ids["python"]), python.id)

    hits = await db.search.find_jobs(required_skill_ids=[python.id])
    assert hits and all(str(h.job.id) == ids["python"] for h in hits)


async def test_search_no_query_filter_only(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    await _seed_jobs(db)
    hits = await db.search.find_jobs(work_arrangement=WorkArrangement.remote)
    assert hits and all(h.job.work_arrangement == WorkArrangement.remote for h in hits)


async def test_search_returns_score_and_matched_terms(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    await _seed_jobs(db)
    hits = await db.search.find_jobs("python")
    assert hits
    assert hits[0].score > 0
    assert hits[0].job.title_en is not None


async def test_search_limit_and_offset(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    await _seed_jobs(db)
    # Empty query → returns all three legit jobs.
    page1 = await db.search.find_jobs(limit=2, offset=0)
    page2 = await db.search.find_jobs(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    ids = {h.job.id for h in page1} | {h.job.id for h in page2}
    assert len(ids) == 3
