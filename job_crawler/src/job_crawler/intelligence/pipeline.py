"""Orchestrator that runs every intelligence pass.

Each pass is independent and idempotent — the orchestrator just sequences
them and reports counts. Used by `python -m job_crawler.cli.intelligence`
and by the runner (after a successful crawl) as a tail step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

from psycopg.rows import dict_row

from job_crawler_db import JobCrawlerDB, SalaryPeriod

from . import dedup, skill_extractor
from .extractors import (
    extract_education_level,
    extract_experience_years,
    extract_salary,
)
from .title_norm import normalize_title

_LOG: Final = logging.getLogger("job_crawler.intelligence.pipeline")


@dataclass(slots=True)
class IntelligenceSummary:
    skill_hits: int = 0
    salary_recovered: int = 0
    experience_recovered: int = 0
    education_recovered: int = 0
    titles_normalized: int = 0
    cities_resolved: int = 0
    titles_decoded: int = 0
    dedup_pairs: int = 0
    dedup_edges: int = 0
    dedup_clusters_merged: int = 0


async def enrich_unstructured_fields(
    db: JobCrawlerDB,
    *,
    batch_size: int = 500,
    limit: int | None = None,
) -> tuple[int, int, int, int]:
    """Re-derive (salary_*, experience_*, education_level, title_en/ar) from
    the description body for clusters where those fields are NULL.

    Returns (salary_count, exp_count, edu_count, title_count) of clusters touched.
    """
    salary_n = 0
    exp_n = 0
    edu_n = 0
    title_n = 0

    sql = (
        "SELECT j.id, j.title_en, j.title_ar, j.description_en, j.description_ar, "
        "       j.salary_min, j.salary_max, j.min_experience_years, j.max_experience_years, "
        "       j.min_education_level "
        "FROM   jobs j "
        "WHERE  j.deleted_at IS NULL "
    )
    if limit:
        sql += f" LIMIT {int(limit)}"

    async with db.pool.connection() as conn, conn.cursor(
        row_factory=dict_row, name="enrich_scan",
    ) as cur:
        await cur.execute(sql)
        while batch := await cur.fetchmany(batch_size):
            for row in batch:
                patches: dict[str, object] = {}
                body = (
                    (row["description_en"] or "")
                    + "\n"
                    + (row["description_ar"] or "")
                )

                # Salary — jobs_check2 requires salary_period whenever
                # min/max is set, so default to monthly (overwhelmingly the
                # KSA convention) when the extractor didn't find a period.
                if row["salary_min"] is None and row["salary_max"] is None:
                    hit = extract_salary(body)
                    if hit and hit.salary_min:
                        patches["salary_min"] = hit.salary_min
                        if hit.salary_max:
                            patches["salary_max"] = hit.salary_max
                        patches["salary_currency"] = hit.salary_currency
                        patches["salary_period"] = hit.salary_period or SalaryPeriod.monthly
                        salary_n += 1

                # Experience years
                if (
                    row["min_experience_years"] is None
                    and row["max_experience_years"] is None
                ):
                    lo, hi = extract_experience_years(body)
                    if lo is not None:
                        patches["min_experience_years"] = lo
                        if hi is not None:
                            patches["max_experience_years"] = hi
                        exp_n += 1

                # Education
                if row["min_education_level"] is None:
                    edu = extract_education_level(body)
                    if edu is not None:
                        patches["min_education_level"] = edu
                        edu_n += 1

                # Title normalization (applied to whichever side has a title).
                if row["title_en"]:
                    norm = normalize_title(row["title_en"])
                    if norm and norm != row["title_en"]:
                        patches["title_en"] = norm
                        title_n += 1
                if row["title_ar"]:
                    # Arabic title norm is a no-op for now; placeholder for later.
                    pass

                if patches:
                    try:
                        await db.jobs.update(row["id"], **patches)
                    except Exception:
                        _LOG.exception("update failed for job %s", row["id"])
    return salary_n, exp_n, edu_n, title_n


# ---------------------------------------------------------------------------
# Post-ingest backfills (idempotent — safe to run on every cycle)
# ---------------------------------------------------------------------------


async def backfill_unresolved_cities(db: JobCrawlerDB) -> int:
    """Re-run `resolve_city` against every cluster that has a raw_location
    but no `city_id`. Picks up newly-added aliases / neighborhood maps on
    each invocation. Idempotent: a cluster whose raw_location still doesn't
    resolve stays unchanged."""
    from ..core.normalise import resolve_city

    n = 0
    async with db.pool.connection() as conn, conn.cursor(
        row_factory=dict_row, name="city_backfill_scan",
    ) as cur:
        await cur.execute(
            "SELECT j.id, p.raw_location "
            "FROM jobs j JOIN job_postings p ON p.id = j.canonical_posting_id "
            "WHERE j.city_id IS NULL "
            "  AND p.raw_location IS NOT NULL "
            "  AND j.deleted_at IS NULL",
        )
        while batch := await cur.fetchmany(500):
            for row in batch:
                # PR #18 changed resolve_city to return a LocationResolution
                # tuple instead of a bare city UUID; this caller wasn't
                # updated, and the dataclass was being handed straight to
                # `jobs.update(city_id=...)` where psycopg can't adapt it.
                # Pull city_id + propagate region/country so the cluster
                # gets the full geo backfill, not just the city pin.
                loc = await resolve_city(
                    db, None, raw_location=row["raw_location"],
                )
                if loc.city_id is None:
                    continue
                patch: dict[str, object] = {"city_id": loc.city_id}
                if loc.region_code:
                    patch["region_code"] = loc.region_code
                if loc.country_code:
                    patch["country_code"] = loc.country_code
                try:
                    await db.jobs.update(row["id"], **patch)
                    n += 1
                except Exception:
                    _LOG.exception("city backfill update failed for %s", row["id"])
    return n


async def cleanup_html_entities_in_titles(db: JobCrawlerDB) -> int:
    """Strip the common HTML entities (`&amp;`, `&quot;`, `&#039;`, `&lt;`,
    `&gt;`) from existing posting titles. Modern crawls go through
    `html.unescape` in `to_upsert`, but older rows ingested before that
    fix may still carry the raw entities. Idempotent."""
    sql = (
        "UPDATE job_postings "
        "SET    title = replace(replace(replace(replace(replace("
        "         title, '&amp;', '&'), '&quot;', '\"'), "
        "         '&#039;', ''''), '&lt;', '<'), '&gt;', '>') "
        "WHERE  title ~ '&(amp|quot|#039|lt|gt);'"
    )
    async with db.pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(sql)
        # psycopg exposes affected rows via cur.rowcount post-execute.
        return max(0, cur.rowcount or 0)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_all(
    db: JobCrawlerDB,
    *,
    run_skills: bool = True,
    run_enrich: bool = True,
    run_dedup: bool = True,
    skill_limit: int | None = None,
    only_unscanned_skills: bool = True,
) -> IntelligenceSummary:
    summary = IntelligenceSummary()

    if run_skills:
        n = await skill_extractor.backfill_all(
            db, only_unscanned=only_unscanned_skills, limit=skill_limit,
        )
        summary.skill_hits = n

    if run_enrich:
        # Title cleanup runs FIRST so any subsequent re-derivation (titles
        # normalized in enrich_unstructured_fields) sees the decoded text.
        summary.titles_decoded = await cleanup_html_entities_in_titles(db)
        summary.cities_resolved = await backfill_unresolved_cities(db)
        s, e, ed, t = await enrich_unstructured_fields(db)
        summary.salary_recovered = s
        summary.experience_recovered = e
        summary.education_recovered = ed
        summary.titles_normalized = t

    if run_dedup:
        d = await dedup.run(db)
        summary.dedup_pairs = d.pairs_considered
        summary.dedup_edges = d.edges_recorded
        summary.dedup_clusters_merged = d.clusters_merged

    return summary
