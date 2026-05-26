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
    restrictions_recovered: int = 0
    centroids_filled: int = 0
    legit_scored: int = 0
    titles_depolluted: int = 0


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


async def enrich_cluster_restrictions(
    db: JobCrawlerDB,
    *,
    batch_size: int = 500,
    limit: int | None = None,
) -> int:
    """Backfill `experience_level`, `requires_arabic`, `visa_sponsorship`
    for clusters where the corresponding column is NULL.

    These three fields are derived from text heuristics that live in
    `core.restrictions`. Posting-level extraction wires them into
    `to_upsert` (for `experience_level`); `requires_arabic` and
    `visa_sponsorship` only exist on `jobs`, so they're populated here.

    Idempotent: a cluster whose text doesn't trigger any heuristic stays
    untouched on subsequent runs. Returns the count of clusters touched.
    """
    from ..core.restrictions import (
        detect_category_code,
        detect_experience_level,
        detect_hybrid_days_per_week,
        detect_relocation_assistance,
        detect_remote_country_restriction,
        detect_requires_arabic,
        detect_visa_sponsorship,
    )

    touched = 0
    sql = (
        "SELECT j.id, j.title_en, j.title_ar, j.description_en, j.description_ar, "
        "       j.experience_level, j.requires_arabic, j.visa_sponsorship, "
        "       j.hybrid_days_per_week, j.remote_country_restriction, "
        "       j.relocation_assistance, j.category_code "
        "FROM   jobs j "
        "WHERE  j.deleted_at IS NULL "
        "  AND  ("
        "         j.experience_level         IS NULL "
        "      OR j.requires_arabic          IS NULL "
        "      OR j.visa_sponsorship         IS NULL "
        "      OR j.hybrid_days_per_week     IS NULL "
        "      OR j.remote_country_restriction IS NULL "
        "      OR j.relocation_assistance    IS NULL "
        "      OR j.category_code            IS NULL"
        "      )"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"

    async with db.pool.connection() as conn, conn.cursor(
        row_factory=dict_row, name="restrictions_scan",
    ) as cur:
        await cur.execute(sql)
        while batch := await cur.fetchmany(batch_size):
            for row in batch:
                title = row["title_en"] or row["title_ar"]
                body = "\n".join(
                    p for p in (row["description_en"], row["description_ar"]) if p
                )
                patches: dict[str, object] = {}

                if row["experience_level"] is None:
                    level = detect_experience_level(title, body)
                    if level is not None:
                        patches["experience_level"] = level

                if row["requires_arabic"] is None:
                    ra = detect_requires_arabic((title or "") + "\n" + body)
                    if ra is not None:
                        patches["requires_arabic"] = ra

                if row["visa_sponsorship"] is None:
                    vs = detect_visa_sponsorship(body)
                    if vs is not None:
                        patches["visa_sponsorship"] = vs

                if row["hybrid_days_per_week"] is None:
                    hd = detect_hybrid_days_per_week(body)
                    if hd is not None:
                        patches["hybrid_days_per_week"] = hd

                if row["remote_country_restriction"] is None:
                    rc = detect_remote_country_restriction(body)
                    if rc is not None:
                        patches["remote_country_restriction"] = rc

                if row["relocation_assistance"] is None:
                    ra2 = detect_relocation_assistance(body)
                    if ra2 is not None:
                        patches["relocation_assistance"] = ra2

                if row["category_code"] is None:
                    cat = detect_category_code(title, body)
                    if cat is not None:
                        patches["category_code"] = cat

                if patches:
                    try:
                        await db.jobs.update(row["id"], **patches)
                        touched += 1
                    except Exception:
                        _LOG.exception("restrictions update failed for %s", row["id"])
    return touched


async def backfill_office_centroids(db: JobCrawlerDB) -> int:
    """Mirror the city centroid into the cluster's office_latitude / longitude
    when both are NULL and the cluster has a resolved city.

    A cluster's `office_*` columns are intended for street-level pins;
    until we have a geocoder wired to the office_address text, the city
    centroid is the closest signal available. Idempotent: a cluster that
    already has office_latitude set isn't touched.

    Returns the count of clusters updated.
    """
    sql = """
        UPDATE jobs j
        SET    office_latitude  = c.latitude,
               office_longitude = c.longitude
        FROM   cities c
        WHERE  j.city_id          = c.id
          AND  j.office_latitude  IS NULL
          AND  j.office_longitude IS NULL
          AND  c.latitude         IS NOT NULL
          AND  c.longitude        IS NOT NULL
          AND  j.deleted_at       IS NULL;
    """
    async with db.pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(sql)
        return max(0, cur.rowcount or 0)


async def backfill_legit_score(
    db: JobCrawlerDB,
    *,
    batch_size: int = 500,
    limit: int | None = None,
) -> int:
    """Run `recompute_score` against every cluster missing a `legit_score`.

    With no fake-signal evidence in the cluster yet, recompute_score
    stamps the default 0.85 score + `verdict=pending`. The point isn't
    to detect fakes here (that's a separate detector); it's to
    populate the column so downstream queries don't see NULL for
    legit_score on every row. Once fake-signal detectors land, the
    same call refreshes the score from the accumulated evidence.

    Idempotent: a cluster that already has a legit_score is skipped.
    """
    sql = (
        "SELECT id FROM jobs "
        "WHERE  legit_score IS NULL "
        "  AND  deleted_at  IS NULL"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"

    scored = 0
    async with db.pool.connection() as conn, conn.cursor(
        row_factory=dict_row, name="legit_score_scan",
    ) as cur:
        await cur.execute(sql)
        while batch := await cur.fetchmany(batch_size):
            for row in batch:
                try:
                    await db.fake_signals.recompute_score(row["id"])
                    scored += 1
                except Exception:
                    _LOG.exception("recompute_score failed for %s", row["id"])
    return scored


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


async def cleanup_title_pollution(
    db: JobCrawlerDB,
    *,
    batch_size: int = 500,
    limit: int | None = None,
) -> int:
    """Apply `_clean_title` to every cluster title that looks polluted.

    Targets titles still carrying:
      * pipe-separator brand trails ("Manager | Acme | Riyadh")
      * Hiring Now / Career Opportunities click-bait prefixes
      * req-id paren suffixes ("(88068)", "(Tamheer NNNN)")

    Idempotent: a cluster whose cleaned title equals the current one is
    skipped (the WHERE clause filters those out before the Python loop).
    Returns the count of clusters whose `title_en` / `title_ar` changed.
    """
    from ..core.normalise import _clean_title

    sql = (
        "SELECT id, title_en, title_ar FROM jobs "
        "WHERE  deleted_at IS NULL "
        "  AND  (title_en LIKE '%|%' OR title_ar LIKE '%|%' "
        "    OR  title_en ~* '^(hiring now|now hiring|urgent|career opportunities|we are hiring|join (our|us))[ |:!]' "
        "    OR  title_ar ~* '^(hiring now|now hiring|urgent|career opportunities|we are hiring|join (our|us))[ |:!]' "
        "    OR  title_en ~ '\\([0-9]{3,}\\)$' "
        "    OR  title_en ~* '\\(tamheer[ ]+[0-9]+\\)$' "
        "    OR  title_en ~* '\\(req\\.?[ ]*[0-9]+\\)$' "
        "    OR  title_en ~* '\\(urgent.*\\)$' "
        "      )"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"

    touched = 0
    async with db.pool.connection() as conn, conn.cursor(
        row_factory=dict_row, name="title_pollution_scan",
    ) as cur:
        await cur.execute(sql)
        while batch := await cur.fetchmany(batch_size):
            for row in batch:
                patches: dict[str, object] = {}
                if row["title_en"]:
                    new_en = _clean_title(row["title_en"])
                    if new_en and new_en != row["title_en"]:
                        patches["title_en"] = new_en
                if row["title_ar"]:
                    new_ar = _clean_title(row["title_ar"])
                    if new_ar and new_ar != row["title_ar"]:
                        patches["title_ar"] = new_ar
                if patches:
                    try:
                        await db.jobs.update(row["id"], **patches)
                        touched += 1
                    except Exception:
                        _LOG.exception("title cleanup update failed for %s", row["id"])
    return touched


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
        # Strip brand-trail pipes / req-id paren suffixes from existing
        # cluster titles. Must run BEFORE category-code backfill so the
        # classifier sees the cleaned title.
        summary.titles_depolluted = await cleanup_title_pollution(db)
        summary.cities_resolved = await backfill_unresolved_cities(db)
        s, e, ed, t = await enrich_unstructured_fields(db)
        summary.salary_recovered = s
        summary.experience_recovered = e
        summary.education_recovered = ed
        summary.titles_normalized = t
        # Restrictions backfill — experience_level / requires_arabic /
        # visa_sponsorship for clusters still NULL on those columns.
        summary.restrictions_recovered = await enrich_cluster_restrictions(db)
        # Office centroid backfill — clusters with a resolved city but no
        # office_lat/long inherit the city's centroid as a coarse pin.
        summary.centroids_filled = await backfill_office_centroids(db)
        # legit_score backfill — recompute_score stamps the default 0.85
        # / pending verdict on clusters that have no signal evidence,
        # so the column stops reporting NULL across the board.
        summary.legit_scored = await backfill_legit_score(db)

    if run_dedup:
        d = await dedup.run(db)
        summary.dedup_pairs = d.pairs_considered
        summary.dedup_edges = d.edges_recorded
        summary.dedup_clusters_merged = d.clusters_merged

    return summary
