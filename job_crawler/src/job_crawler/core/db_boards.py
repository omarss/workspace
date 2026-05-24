"""Helpers that let a crawler pull its board list from `company_source_profiles`
in addition to (or instead of) the JC_* env variable.

The auto-detector populates `company_source_profiles` with rows like:

    (company_id=acme.id, source_id=greenhouse.id,
     source_company_external_id='acme', profile_url='https://boards.greenhouse.io/acme')

Each ATS crawler then calls `await db_boards_for(db, 'greenhouse')` to get
back the slugs to iterate. Env-var slugs are merged on top, dedup'd, so
manual overrides always work.
"""

from __future__ import annotations

import logging
from typing import Final

from psycopg.rows import dict_row

from job_crawler_db import JobCrawlerDB

_LOG: Final = logging.getLogger("job_crawler.db_boards")


async def db_boards_for(db: JobCrawlerDB, source_slug: str) -> tuple[str, ...]:
    """Return every `source_company_external_id` registered against `source_slug`.

    Empty tuple when the source row is missing or no companies are wired.
    """
    source = await db.sources.get(slug=source_slug)
    if source is None:
        return ()
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT DISTINCT source_company_external_id
            FROM company_source_profiles
            WHERE source_id = %(s)s
              AND source_company_external_id IS NOT NULL
            ORDER BY source_company_external_id;
            """,
            {"s": source.id},
        )
        rows = await cur.fetchall()
    return tuple(r["source_company_external_id"] for r in rows)


def merge_board_lists(*sources: tuple[str, ...]) -> tuple[str, ...]:
    """Concatenate board-slug tuples preserving order, deduping case-insensitively."""
    seen: set[str] = set()
    out: list[str] = []
    for source in sources:
        for slug in source:
            key = slug.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(slug)
    return tuple(out)
