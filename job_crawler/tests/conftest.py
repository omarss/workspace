"""Integration-test fixtures.

A single PostgreSQL 18 container is spun up per test session via
`testcontainers-python`. The schema is applied once; every test gets a
fresh state via TRUNCATE of every data table (the container restart cost
would dominate test runtime otherwise).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from job_crawler_db import JobCrawlerDB, Settings, apply_schema

# Names of every table populated by the lib. Order does not matter because
# we TRUNCATE ... CASCADE, but listing them keeps the intent obvious.
_DATA_TABLES: tuple[str, ...] = (
    "crawl_fetches",
    "crawl_runs",
    "posting_snapshots",
    "posting_duplicate_edges",
    "posting_skills_raw",
    "application_channels",
    "job_fake_signals",
    "job_skills",
    "job_locations",
    "job_postings",
    "jobs",
    "synonym_terms",
    "synonym_groups",
    "skill_aliases",
    "skills",
    "company_source_profiles",
    "company_aliases",
    "recruiters",
    "companies",
    "sources",
    "cities",
    "regions",
    "job_categories",
    "industries",
    "countries",
)


@pytest.fixture(scope="session")
def postgres_container() -> PostgresContainer:
    """Boots a PostgreSQL 18 container for the whole test session."""
    container = PostgresContainer(image="postgres:18-alpine", driver=None)
    container.start()
    yield container
    container.stop()


@pytest.fixture(scope="session")
def dsn(postgres_container: PostgresContainer) -> str:
    """Return a libpq-style DSN for the running container."""
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    return (
        f"postgresql://{postgres_container.username}:{postgres_container.password}"
        f"@{host}:{port}/{postgres_container.dbname}"
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _schema(dsn: str) -> AsyncIterator[None]:
    """Apply the schema once per test session."""
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=False) as conn:
        await apply_schema(conn)
    yield


@pytest_asyncio.fixture(loop_scope="session")
async def db(dsn: str, _schema: None) -> AsyncIterator[JobCrawlerDB]:
    """Yield a fresh `JobCrawlerDB` against a freshly-truncated database."""
    # Truncate all data tables — fast, atomic, RESTART IDENTITY keeps the
    # uuidv7 monotonic ordering predictable across tests.
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "TRUNCATE TABLE " + ", ".join(_DATA_TABLES) + " RESTART IDENTITY CASCADE;",
            )

    settings = Settings(
        dsn=dsn,
        pool_min_size=1,
        pool_max_size=4,
        statement_timeout_ms=10_000,
        application_name="job_crawler_db_tests",
    )
    async with JobCrawlerDB(settings) as instance:
        # Every table that defaults country_code='sa' references countries,
        # so we always seed Saudi Arabia. Everything else is opt-in via
        # `seeded_reference`.
        await instance.reference.upsert_country(
            code="sa",
            name_en="Saudi Arabia",
            name_ar="المملكة العربية السعودية",
            dial_code="+966",
            currency="SAR",
        )
        yield instance


# ---------------------------------------------------------------------------
# Convenience seed fixtures used by many tests
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(loop_scope="session")
async def seeded_reference(db: JobCrawlerDB) -> JobCrawlerDB:
    """Insert the minimum reference data tests rely on (country + regions + cities + sources)."""
    await db.reference.upsert_country(
        code="sa",
        name_en="Saudi Arabia",
        name_ar="المملكة العربية السعودية",
        dial_code="+966",
        currency="SAR",
    )
    await db.reference.upsert_country(
        code="ae",
        name_en="United Arab Emirates",
        name_ar="الإمارات العربية المتحدة",
        dial_code="+971",
        currency="AED",
    )
    await db.geo.upsert_region(code="riyadh", name_en="Riyadh", name_ar="الرياض")
    await db.geo.upsert_region(code="makkah", name_en="Makkah", name_ar="مكة المكرمة")
    await db.geo.upsert_region(code="eastern", name_en="Eastern", name_ar="الشرقية")
    await db.geo.upsert_city(
        region_code="riyadh",
        name_en="Riyadh",
        name_ar="الرياض",
        latitude=24.7136,
        longitude=46.6753,
    )
    await db.geo.upsert_city(
        region_code="makkah", name_en="Jeddah", name_ar="جدة", latitude=21.4858, longitude=39.1925
    )
    await db.geo.upsert_city(
        region_code="eastern",
        name_en="Dammam",
        name_ar="الدمام",
        latitude=26.4207,
        longitude=50.0888,
    )

    await db.sources.upsert(
        slug="linkedin",
        display_name="LinkedIn",
        kind="aggregator",
        base_url="https://linkedin.com",
        trust_weight=0.60,
    )
    await db.sources.upsert(
        slug="bayt",
        display_name="Bayt",
        kind="regional_board",
        base_url="https://bayt.com",
        trust_weight=0.55,
    )
    await db.sources.upsert(
        slug="greenhouse",
        display_name="Greenhouse",
        kind="ats",
        base_url="https://boards.greenhouse.io",
        trust_weight=0.95,
    )
    await db.sources.upsert(
        slug="jadarat",
        display_name="Jadarat",
        kind="gov_board",
        base_url="https://jadarat.sa",
        trust_weight=0.85,
    )

    await db.reference.upsert_industry(
        code="tech_software",
        name_en="Software",
        name_ar="البرمجيات",
    )
    return db


# Silence "asyncio_default_fixture_loop_scope" warning by being explicit.
_ = os
