"""Integration: skill taxonomy + synonym expansion (the search ranker depends on this)."""

from __future__ import annotations

import pytest

from job_crawler_db import JobCrawlerDB, SkillKind, SynonymKind

pytestmark = pytest.mark.integration


async def test_skill_create_and_alias_fuzzy_match(db: JobCrawlerDB) -> None:
    python = await db.skills.create(
        slug="python",
        name_en="Python",
        kind=SkillKind.tool,
    )
    await db.skills.add_alias(python.id, "Py3", locale="en")
    await db.skills.add_alias(python.id, "بايثون", locale="ar")

    hits = await db.skills.find("py3", min_similarity=0.5)
    assert hits and hits[0][0].id == python.id

    # Arabic alias resolves via normalize_text trigram.
    hits = await db.skills.find("بايثون", min_similarity=0.5)
    assert hits and hits[0][0].id == python.id

    # Typo
    hits = await db.skills.find("Pyhton", min_similarity=0.4)
    assert hits and hits[0][0].id == python.id


async def test_skill_find_filtered_by_kind(db: JobCrawlerDB) -> None:
    await db.skills.create(slug="python", name_en="Python", kind=SkillKind.tool)
    await db.skills.create(slug="leadership", name_en="Leadership", kind=SkillKind.soft)
    soft_hits = await db.skills.find("lead", kind=SkillKind.soft, min_similarity=0.4)
    assert soft_hits and soft_hits[0][0].name_en == "Leadership"
    # Should NOT return python.
    assert all(s.name_en != "Python" for s, _ in soft_hits)


async def test_synonym_group_expansion_returns_siblings(db: JobCrawlerDB) -> None:
    group = await db.synonyms.create_group(
        canonical_term="Kubernetes",
        kind=SynonymKind.skill,
        terms=[
            ("kubernetes", "en"),
            ("k8s", "en"),
            ("kube", "en"),
            ("كوبرنيتيس", "ar"),
        ],
    )
    assert group.canonical_term == "Kubernetes"

    # K8S (uppercase) finds english + arabic siblings.
    expanded = await db.synonyms.expand("K8S", kind=SynonymKind.skill, include_query=False)
    surface = {t.lower() for t, _, _ in expanded}
    assert "kubernetes" in surface
    assert "kube" in surface
    assert "كوبرنيتيس" in {t for t, _, _ in expanded}

    # Cross-language: Arabic input returns English siblings.
    expanded_ar = await db.synonyms.expand("كوبرنيتيس", kind=SynonymKind.skill, include_query=False)
    surface_ar = {t.lower() for t, _, _ in expanded_ar}
    assert "kubernetes" in surface_ar


async def test_synonym_misspelled_query_still_resolves(db: JobCrawlerDB) -> None:
    await db.synonyms.create_group(
        canonical_term="JavaScript",
        kind=SynonymKind.skill,
        terms=[("javascript", "en"), ("js", "en"), ("ECMAScript", "en")],
    )
    # Typo "javascrpit" — trigram path finds the group.
    expanded = await db.synonyms.expand("javascrpit", kind=SynonymKind.skill, include_query=False)
    assert any(t.lower() == "javascript" for t, _, _ in expanded)


async def test_synonym_kind_filter_isolates_groups(db: JobCrawlerDB) -> None:
    await db.synonyms.create_group(
        canonical_term="Manager",
        kind=SynonymKind.job_title,
        terms=[("manager", "en"), ("mgr", "en")],
    )
    await db.synonyms.create_group(
        canonical_term="Manager Tool",
        kind=SynonymKind.skill,
        terms=[("project mgr tool", "en")],
    )
    # Only the job_title group's siblings should come back.
    expanded = await db.synonyms.expand("mgr", kind=SynonymKind.job_title, include_query=False)
    surface = {t for t, _, _ in expanded}
    assert "manager" in surface
    assert "project mgr tool" not in surface


async def test_synonym_expand_includes_query_by_default(db: JobCrawlerDB) -> None:
    await db.synonyms.create_group(
        canonical_term="React",
        kind=SynonymKind.skill,
        terms=[("react", "en"), ("reactjs", "en"), ("react.js", "en")],
    )
    expanded = await db.synonyms.expand("React")
    surface = [t for t, _, _ in expanded]
    assert surface[0] == "React"  # original first
    assert len(surface) >= 2
