"""Data-access layer — all SQL lives here.

Uses psycopg row-dict adapters and JSONB via psycopg.types.json.Jsonb so
Python dicts round-trip cleanly into JSONB columns.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

PLACE_COLS = (
    "place_id",
    "google_id",
    "cid",
    "name",
    "full_address",
    "borough",
    "street",
    "city",
    "postal_code",
    "country",
    "latitude",
    "longitude",
    "phone",
    "website",
    "rating",
    "reviews_count",
    "reviews_per_score",
    "photos_count",
    "price_level",
    "category",
    "subcategories",
    "working_hours",
    "popular_times",
    "plus_code",
    "bounds",
    "service_area",
    "verified",
    "business_status",
    "google_url",
    "query",
    "tile_lat",
    "tile_lng",
    "raw",
)

REVIEW_COLS = (
    "review_id",
    "place_id",
    "author_title",
    "author_id",
    "author_url",
    "author_reviews_count",
    "author_ratings_count",
    "rating",
    "text",
    "text_translated",
    "language",
    "published_at",
    "likes",
    "owner_answer",
    "owner_answer_at",
    "photos",
    "raw",
)


def _to_jsonb(row: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    out = dict(row)
    for k in keys:
        if k in out and out[k] is not None:
            out[k] = Jsonb(out[k])
    return out


def upsert_places(conn: Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    cols = ", ".join(PLACE_COLS)
    placeholders = ", ".join(f"%({c})s" for c in PLACE_COLS)
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in PLACE_COLS if c not in ("place_id",)
    )
    sql = (
        f"INSERT INTO places ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT (place_id) DO UPDATE SET {updates}, updated_at = now()"
    )
    norm = [
        _to_jsonb(
            r,
            (
                "working_hours",
                "popular_times",
                "reviews_per_score",
                "bounds",
                "service_area",
                "raw",
            ),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, norm)
    return len(rows)


def upsert_reviews(conn: Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    cols = ", ".join(REVIEW_COLS)
    placeholders = ", ".join(f"%({c})s" for c in REVIEW_COLS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in REVIEW_COLS if c != "review_id")
    sql = (
        f"INSERT INTO reviews ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT (review_id) DO UPDATE SET {updates}"
    )
    norm = [_to_jsonb(r, ("photos", "raw")) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, norm)
    return len(rows)


def mark_reviews_scraped(conn: Connection, place_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE places SET reviews_scraped_at = now() WHERE place_id = %s",
            (place_id,),
        )


def ensure_places_jobs(
    conn: Connection, combos: Iterable[tuple[str, float, float]]
) -> int:
    """Seed pending scrape_jobs for every (category, tile) not yet recorded."""
    sql = (
        "INSERT INTO scrape_jobs (kind, category, tile_lat, tile_lng, status) "
        "VALUES ('places', %s, %s, %s, 'pending') "
        "ON CONFLICT DO NOTHING"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, list(combos))
        return cur.rowcount or 0


def ensure_reviews_jobs(conn: Connection) -> int:
    """Seed pending review jobs for every place not yet processed.

    We intentionally don't filter by `reviews_count > 0` because pass 1 (the
    feed crawl) doesn't read review counts off the card — it's cheaper to let
    pass 2 open every place, backfill the detail fields, and store whatever
    reviews are there (zero for new businesses).
    """
    sql = """
    INSERT INTO scrape_jobs (kind, place_id, status)
    SELECT 'reviews', p.place_id, 'pending'
    FROM places p
    WHERE p.reviews_scraped_at IS NULL
    ON CONFLICT DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.rowcount or 0


def claim_pending_jobs(
    conn: Connection, kind: str, batch_size: int
) -> list[dict[str, Any]]:
    """Atomically move up to `batch_size` pending jobs of `kind` to 'running'.

    Uses SKIP LOCKED so multiple workers can share the queue safely.
    """
    sql = """
    UPDATE scrape_jobs
    SET status = 'running',
        started_at = now(),
        attempts = attempts + 1
    WHERE id IN (
        SELECT id FROM scrape_jobs
        WHERE kind = %s AND status = 'pending'
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT %s
    )
    RETURNING id, kind, category, tile_lat, tile_lng, place_id
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (kind, batch_size))
        return list(cur.fetchall())


def save_job_request(conn: Connection, job_id: int, request_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scrape_jobs SET outscraper_request_id = %s WHERE id = %s",
            (request_id, job_id),
        )


def complete_job(conn: Connection, job_id: int, count: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scrape_jobs SET status='completed', results_count=%s, "
            "finished_at=now(), error=NULL WHERE id=%s",
            (count, job_id),
        )


def fail_job(conn: Connection, job_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scrape_jobs SET status='failed', finished_at=now(), error=%s "
            "WHERE id=%s",
            (error[:2000], job_id),
        )


def status_summary(conn: Connection) -> list[dict[str, Any]]:
    sql = """
    SELECT kind, status, COUNT(*) AS n, COALESCE(SUM(results_count), 0) AS results
    FROM scrape_jobs
    GROUP BY kind, status
    ORDER BY kind, status
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def counts(conn: Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM places")
        p = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM reviews")
        r = cur.fetchone()[0]
    return {"places": p, "reviews": r}
