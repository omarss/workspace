"""End-to-end pipeline test — simulates a realistic crawl + dedupe + search.

This is the broadest test in the suite. It walks the crawler's full happy
path so any regression that breaks the pipeline shows up in a single failure.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from job_crawler_db import (
    ApplicationChannelKind,
    ClusterVerdict,
    DuplicateReason,
    EmploymentType,
    ExperienceLevel,
    JobCrawlerDB,
    JobPostingUpsert,
    SalaryPeriod,
    SkillKind,
    SkillProficiency,
    SkillRequirement,
    SynonymKind,
    WorkArrangement,
    detect_ai_generation,
)

pytestmark = pytest.mark.integration


async def test_full_ingest_dedupe_search_pipeline(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    # --- 0. Seed search synonyms + skill taxonomy ------------------------
    python = await db.skills.create(slug="python", name_en="Python", kind=SkillKind.tool)
    django = await db.skills.create(
        slug="django", name_en="Django", kind=SkillKind.tool, parent_id=python.id
    )
    await db.skills.add_alias(python.id, "Py3")
    await db.synonyms.create_group(
        canonical_term="Python",
        kind=SynonymKind.skill,
        terms=[("python", "en"), ("py", "en"), ("بايثون", "ar")],
    )
    await db.synonyms.create_group(
        canonical_term="Software Engineer",
        kind=SynonymKind.job_title,
        terms=[
            ("software engineer", "en"),
            ("swe", "en"),
            ("software developer", "en"),
            ("مهندس برمجيات", "ar"),
        ],
    )

    # --- 1. Start a crawl run ------------------------------------------
    linkedin = await db.sources.get(slug="linkedin")
    bayt = await db.sources.get(slug="bayt")
    greenhouse = await db.sources.get(slug="greenhouse")
    assert linkedin and bayt and greenhouse

    run = await db.crawl.start_run(linkedin.id, config={"query": "python riyadh"})

    # --- 2. Ingest a posting from LinkedIn -----------------------------
    riyadh = (await db.geo.find_city("Riyadh"))[0][0]
    acme = await db.companies.resolve(
        raw_name="Acme Saudi",
        source_id=linkedin.id,
        source_profile_url="https://linkedin.com/company/acme-saudi",
    )
    recruiter = await db.recruiters.resolve(
        linkedin_url="https://linkedin.com/in/lina-talent",
        full_name="Lina Al-Recruiter",
    )

    li_payload = JobPostingUpsert(
        source_id=linkedin.id,
        source_job_external_id="li-9001",
        canonical_url="https://linkedin.com/jobs/9001?utm_source=email",
        title="Senior Python Engineer",
        description="Build scalable Django services on PostgreSQL. 5+ years Python required.",
        company_id=acme.id,
        raw_company_name="Acme Saudi",
        posted_by_recruiter_id=recruiter.id,
        employment_type=EmploymentType.full_time,
        work_arrangement=WorkArrangement.hybrid,
        experience_level=ExperienceLevel.senior,
        raw_location="Riyadh, KSA · Hybrid",
        city_id=riyadh.id,
        hybrid_days_per_week=2,
        salary_min=Decimal("20000"),
        salary_max=Decimal("28000"),
        salary_currency="SAR",
        salary_period=SalaryPeriod.monthly,
        hiring_manager_name="Sarah Al-Otaibi",
        hiring_manager_linkedin_url="https://linkedin.com/in/sarah-al-otaibi",
    )
    li_post = await db.postings.upsert(li_payload)
    await db.crawl.record_fetch(
        run.id,
        linkedin.id,
        li_payload.canonical_url,
        outcome="created",
        http_status=200,
        duration_ms=420,
        bytes=42000,
        posting_id=li_post.id,
    )

    # --- 3. Ingest a duplicate of the SAME job from Bayt ---------------
    bayt_payload = JobPostingUpsert(
        source_id=bayt.id,
        source_job_external_id="bayt-7777",
        canonical_url="https://bayt.com/en/saudi/jobs/7777",
        title="Senior Python Engineer",  # same title
        description="Build scalable Django services on PostgreSQL. 5+ years Python required.",
        company_id=acme.id,
        raw_company_name="Acme Saudi",
        employment_type=EmploymentType.full_time,
        work_arrangement=WorkArrangement.hybrid,
        experience_level=ExperienceLevel.senior,
        city_id=riyadh.id,
    )
    bayt_post = await db.postings.upsert(bayt_payload)

    # --- 4. Ingest a higher-trust ATS posting for the same job ---------
    gh_payload = JobPostingUpsert(
        source_id=greenhouse.id,
        source_job_external_id="gh-100",
        canonical_url="https://boards.greenhouse.io/acme/jobs/100",
        title="Senior Python Engineer (Riyadh, Hybrid)",
        description="Build scalable Django services on PostgreSQL. 5+ years Python required.",
        company_id=acme.id,
        raw_company_name="Acme Saudi",
        employment_type=EmploymentType.full_time,
        work_arrangement=WorkArrangement.hybrid,
        experience_level=ExperienceLevel.senior,
        city_id=riyadh.id,
        salary_min=Decimal("22000"),
        salary_max=Decimal("30000"),
        salary_currency="SAR",
        salary_period=SalaryPeriod.monthly,
    )
    gh_post = await db.postings.upsert(gh_payload)

    # --- 5. Dedupe: same content hash across all three -----------------
    await db.dedupe.add_edge(
        li_post.id, bayt_post.id, reason=DuplicateReason.exact_content_hash, similarity=1.0
    )
    await db.dedupe.add_edge(
        li_post.id, gh_post.id, reason=DuplicateReason.exact_content_hash, similarity=1.0
    )

    # --- 6. Cluster: create the cluster from the highest-trust posting -
    cluster = await db.jobs.create_from_posting(gh_post.id)
    await db.postings.attach_to_cluster(li_post.id, cluster.id)
    await db.postings.attach_to_cluster(bayt_post.id, cluster.id)
    cluster = await db.jobs.recompute_canonical(cluster.id)
    assert cluster.posting_count == 3
    assert cluster.canonical_posting_id == gh_post.id
    assert cluster.title_en == gh_payload.title

    # --- 7. Skill linkage with granular metadata -----------------------
    await db.jobs.link_skill(
        cluster.id,
        python.id,
        requirement=SkillRequirement.required,
        proficiency_level=SkillProficiency.advanced,
        min_years=5,
        importance=0.95,
    )
    await db.jobs.link_skill(
        cluster.id,
        django.id,
        requirement=SkillRequirement.required,
        proficiency_level=SkillProficiency.intermediate,
        min_years=3,
        importance=0.75,
    )

    # --- 8. Application channels ---------------------------------------
    await db.postings.add_application_channel(
        gh_post.id,
        kind=ApplicationChannelKind.url,
        value="https://boards.greenhouse.io/acme/jobs/100/apply",
        is_primary=True,
    )

    # --- 9. Run AI detection + fake signals + score --------------------
    ai = detect_ai_generation(gh_post.description)
    # The hand-crafted description is short and human-like → low score.
    assert not ai.is_likely_ai()
    cluster = await db.fake_signals.recompute_score(cluster.id)
    await db.jobs.set_verdict(cluster.id, ClusterVerdict.legit, legit_score=0.92)

    # --- 10. Add a second cluster (different job) for search variety ---
    other = await db.postings.upsert(
        JobPostingUpsert(
            source_id=linkedin.id,
            source_job_external_id="li-9002",
            canonical_url="https://linkedin.com/jobs/9002",
            title="Frontend React Developer",
            description="Build SPAs with React and TypeScript.",
            company_id=acme.id,
            employment_type=EmploymentType.full_time,
            work_arrangement=WorkArrangement.remote,
            experience_level=ExperienceLevel.mid,
            city_id=riyadh.id,
            salary_min=Decimal("12000"),
            salary_max=Decimal("18000"),
            salary_currency="SAR",
            salary_period=SalaryPeriod.monthly,
        ),
    )
    other_cluster = await db.jobs.create_from_posting(other.id)
    await db.jobs.set_verdict(other_cluster.id, ClusterVerdict.legit, legit_score=0.88)

    # --- 11. Search the cluster from multiple angles -------------------
    # 11a. Direct English match.
    hits = await db.search.find_jobs("python engineer")
    assert hits and hits[0].job.id == cluster.id

    # 11b. Synonym (SWE).
    hits = await db.search.find_jobs("SWE")
    assert any(h.job.id == cluster.id for h in hits)

    # 11c. Typo tolerance — "pyhton" misspelled.
    hits = await db.search.find_jobs("pyhton")
    assert any(h.job.id == cluster.id for h in hits)

    # 11d. Cross-language — Arabic input finds the English-titled job
    #      via the synonym group containing "بايثون".
    hits = await db.search.find_jobs("بايثون")
    assert any(h.job.id == cluster.id for h in hits)

    # 11e. Skill-required filter.
    hits = await db.search.find_jobs(required_skill_ids=[python.id, django.id])
    assert hits and all(h.job.id == cluster.id for h in hits)

    # 11f. Filter-only (no query): all three legit clusters appear? No, two.
    hits = await db.search.find_jobs(employment_type=EmploymentType.full_time, limit=10)
    cluster_ids = {h.job.id for h in hits}
    assert cluster.id in cluster_ids
    assert other_cluster.id in cluster_ids

    # 11g. Hybrid+Riyadh+salary filter — only the python cluster.
    hits = await db.search.find_jobs(
        work_arrangement=WorkArrangement.hybrid,
        city_id=riyadh.id,
        min_salary=18000,
    )
    assert hits and hits[0].job.id == cluster.id

    # --- 12. Finish the crawl run --------------------------------------
    await db.crawl.increment_counter(run.id, pages=3, seen=4, new=4)
    finished = await db.crawl.finish_run(run.id)
    assert finished.pages_fetched == 3
    assert finished.postings_new == 4
