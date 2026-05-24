"""Integration: company CRUD + alias-based fuzzy resolution."""

from __future__ import annotations

import pytest

from job_crawler_db import JobCrawlerDB

pytestmark = pytest.mark.integration


async def test_create_requires_a_name(db: JobCrawlerDB) -> None:
    with pytest.raises(ValueError):
        await db.companies.create()


async def test_create_get_and_alias_roundtrip(db: JobCrawlerDB) -> None:
    company = await db.companies.create(
        name_en="Saudi Aramco",
        name_ar="أرامكو السعودية",
        cr_number="1010001001",
    )
    assert company.id is not None
    assert company.is_verified is False

    fetched = await db.companies.get(company.id)
    assert fetched is not None
    assert fetched.cr_number == "1010001001"

    by_cr = await db.companies.get_by_cr_number("1010001001")
    assert by_cr is not None and by_cr.id == company.id

    alias = await db.companies.add_alias(company.id, "Aramco", locale="en")
    assert alias.company_id == company.id

    aliases = await db.companies.list_aliases(company.id)
    assert {a.alias for a in aliases} == {"Aramco"}


async def test_fuzzy_find_by_name_english(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    company = await db.companies.create(name_en="Saudi Telecom Company")
    await db.companies.add_alias(company.id, "STC", locale="en")

    # Exact match
    hits = await db.companies.find_by_name("Saudi Telecom")
    assert hits and hits[0][0].id == company.id

    # Typo
    hits = await db.companies.find_by_name("Saudii Tlecom", min_similarity=0.4)
    assert hits and hits[0][0].id == company.id

    # Via alias
    hits = await db.companies.find_by_name("STC", min_similarity=0.5)
    assert any(h[0].id == company.id for h in hits)


async def test_fuzzy_find_by_name_arabic_with_diacritics(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    company = await db.companies.create(
        name_en="STC",
        name_ar="شركة الاتصالات السعودية",
    )
    # Search with tashkeel and alef variant — both should fold via normalize_ar.
    hits = await db.companies.find_by_name("شَركَة الإتصالات السعودية", min_similarity=0.4)
    assert hits and hits[0][0].id == company.id


async def test_resolve_falls_back_to_create_then_finds_via_alias(
    seeded_reference: JobCrawlerDB,
) -> None:
    db = seeded_reference
    linkedin = await db.sources.get(slug="linkedin")
    assert linkedin is not None

    created = await db.companies.resolve(
        raw_name="Stripe Saudi Arabia",
        source_id=linkedin.id,
        source_profile_url="https://linkedin.com/company/stripe-sa",
    )
    assert created.name_en == "Stripe Saudi Arabia"

    # Second call from a different source with a near-miss name should resolve
    # to the same company via the alias trigram + alias registration.
    again = await db.companies.resolve(
        raw_name="Stripe Saudi Arbaia",  # typo
        source_id=linkedin.id,
        min_similarity=0.5,
    )
    assert again.id == created.id


async def test_source_profile_idempotent(seeded_reference: JobCrawlerDB) -> None:
    db = seeded_reference
    linkedin = await db.sources.get(slug="linkedin")
    assert linkedin is not None
    c = await db.companies.create(name_en="Acme")

    p1 = await db.companies.add_source_profile(
        c.id,
        linkedin.id,
        "https://linkedin.com/company/acme",
        source_company_external_id="123",
    )
    p2 = await db.companies.add_source_profile(
        c.id,
        linkedin.id,
        "https://linkedin.com/company/acme",
    )
    assert p1.id == p2.id


async def test_verify_marks_company(db: JobCrawlerDB) -> None:
    c = await db.companies.create(name_en="Acme")
    verified = await db.companies.verify(c.id, by="omar@example.com")
    assert verified.is_verified is True
    assert verified.verified_at is not None
    assert verified.verified_by == "omar@example.com"


async def test_update_rejects_unknown_fields(db: JobCrawlerDB) -> None:
    c = await db.companies.create(name_en="Acme")
    with pytest.raises(ValueError):
        await db.companies.update(c.id, totally_not_a_column="x")
