"""Crawl orchestration — Playwright edition.

Pass 1 (`run_places`):
    for every pending (category, tile) job, do a Google Maps search, scroll
    the results feed, and upsert each card as a minimal `places` row.

Pass 2 (`run_reviews`):
    for every place that has no reviews yet, open its detail page, extract
    the richer fields (phone, website, hours, address, plus code) to update
    the row, then extract every review the page exposes.

Resumability is handled by `scrape_jobs` exactly as before — we just call the
Playwright scraper directly in the worker instead of submitting to an API.
Concurrency inside one process is fixed at 1 because Playwright's sync API
is not thread-safe. For parallelism run the CLI in several terminals; SKIP
LOCKED in `claim_pending_jobs` prevents double-work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from . import repo
from .categories import CATEGORIES
from .config import settings
from .db import connection
from .normalize import normalize_place, normalize_review
from .scraper import PlaywrightScraper
from .tiling import tile_grid

console = Console()

BATCH_SIZE = 20


@dataclass
class _JobRow:
    id: int
    kind: str
    category: str | None
    tile_lat: float | None
    tile_lng: float | None
    place_id: str | None


def _category_query(slug: str) -> str:
    for s, q in CATEGORIES:
        if s == slug:
            return q
    raise KeyError(f"unknown category slug: {slug}")


def _active_categories() -> list[tuple[str, str]]:
    flt = {s.strip() for s in settings.categories_filter.split(",") if s.strip()}
    if not flt:
        return CATEGORIES
    return [c for c in CATEGORIES if c[0] in flt]


def seed_places_jobs() -> int:
    tiles = tile_grid(
        settings.riyadh_lat_min,
        settings.riyadh_lat_max,
        settings.riyadh_lng_min,
        settings.riyadh_lng_max,
        settings.tile_km,
    )
    cats = _active_categories()
    combos = [(slug, t.lat, t.lng) for slug, _ in cats for t in tiles]
    with connection() as conn:
        n = repo.ensure_places_jobs(conn, combos)
        conn.commit()
    console.print(
        f"[bold]places jobs:[/] {len(combos)} combos "
        f"({len(cats)} categories × {len(tiles)} tiles), {n} newly seeded"
    )
    return n


def seed_reviews_jobs() -> int:
    with connection() as conn:
        n = repo.ensure_reviews_jobs(conn)
        conn.commit()
    console.print(f"[bold]reviews jobs:[/] {n} newly seeded")
    return n


def run_places() -> None:
    seed_places_jobs()
    _run_queue("places", _process_place_job)


def run_reviews() -> None:
    seed_reviews_jobs()
    _run_queue("reviews", _process_review_job)


def _run_queue(kind: str, worker) -> None:
    with connection() as conn:
        remaining = _pending_count(conn, kind)
    if remaining == 0:
        console.print(f"no pending [bold]{kind}[/] jobs")
        return

    console.print(
        f"processing {remaining} pending [bold]{kind}[/] jobs "
        f"(headless={settings.scraper_headless})"
    )
    with (
        PlaywrightScraper() as scraper,
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress,
    ):
        pb = progress.add_task(kind, total=remaining)
        while True:
            with connection() as conn:
                batch = [_JobRow(**r) for r in repo.claim_pending_jobs(conn, kind, BATCH_SIZE)]
                conn.commit()
            if not batch:
                break
            for job in batch:
                try:
                    worker(scraper, job)
                except Exception as exc:  # noqa: BLE001
                    console.log(f"[red]job {job.id} crashed:[/] {exc}")
                    with connection() as conn:
                        repo.fail_job(conn, job.id, str(exc))
                        conn.commit()
                progress.advance(pb)


def _pending_count(conn, kind: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM scrape_jobs WHERE kind=%s AND status IN ('pending','running')",
            (kind,),
        )
        return cur.fetchone()[0]


# ---- workers --------------------------------------------------------------


def _process_place_job(scraper: PlaywrightScraper, job: _JobRow) -> None:
    assert job.category and job.tile_lat is not None and job.tile_lng is not None
    query = _category_query(job.category)
    cards = scraper.search_places(query=query, lat=job.tile_lat, lng=job.tile_lng)

    rows: list[dict[str, Any]] = []
    for rec in cards:
        row = normalize_place(
            rec,
            category_slug=job.category,
            query=query,
            tile_lat=job.tile_lat,
            tile_lng=job.tile_lng,
        )
        if row:
            rows.append(row)

    with connection() as conn:
        n = repo.upsert_places(conn, rows)
        repo.complete_job(conn, job.id, n)
        conn.commit()


def _process_review_job(scraper: PlaywrightScraper, job: _JobRow) -> None:
    assert job.place_id
    # We need the place URL to re-open the detail page. It was saved during
    # places pass 1 (scraper writes it to the raw payload → normalized row).
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT google_url FROM places WHERE place_id = %s",
            (job.place_id,),
        )
        row = cur.fetchone()
    if not row or not row[0]:
        with connection() as conn:
            repo.fail_job(conn, job.id, "place has no google_url; rerun places pass")
            conn.commit()
        return
    place_url: str = row[0]

    detail, review_records = scraper.fetch_place(
        place_url=place_url,
        reviews_limit=settings.reviews_per_place,
        sort=settings.reviews_sort,
    )

    # Update the place row with the detail fields (keeps category + tile intact).
    detail_row = normalize_place(
        {**detail, "place_id": job.place_id},
        category_slug=_fetch_place_category(job.place_id),
        query="",  # detail pass has no search query
        tile_lat=0.0,
        tile_lng=0.0,
    )

    review_rows = [
        r
        for r in (normalize_review(rec, place_id=job.place_id) for rec in review_records)
        if r
    ]

    with connection() as conn:
        if detail_row:
            # Preserve original category/tile/query from pass 1 — we only update
            # the fields that came back from the detail page.
            _update_place_detail(conn, job.place_id, detail_row)
        n = repo.upsert_reviews(conn, review_rows)
        repo.mark_reviews_scraped(conn, job.place_id)
        repo.complete_job(conn, job.id, n)
        conn.commit()


def _fetch_place_category(place_id: str) -> str:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT category FROM places WHERE place_id=%s", (place_id,))
        r = cur.fetchone()
        return r[0] if r and r[0] else ""


def _update_place_detail(conn, place_id: str, row: dict[str, Any]) -> None:
    fields = [
        "name",
        "full_address",
        "latitude",
        "longitude",
        "phone",
        "website",
        "rating",
        "reviews_count",
        "reviews_per_score",
        "price_level",
        "plus_code",
        "google_url",
        "subcategories",
        "bounds",
        "service_area",
    ]
    from psycopg.types.json import Jsonb

    jsonb_cols = {"reviews_per_score", "bounds", "service_area", "working_hours", "popular_times"}
    set_parts = []
    params: list[Any] = []
    for f in fields:
        if f in row and row[f] is not None:
            set_parts.append(f"{f} = %s")
            params.append(Jsonb(row[f]) if f in jsonb_cols else row[f])
    if not set_parts:
        return
    set_parts.append("updated_at = now()")
    params.append(place_id)
    sql = f"UPDATE places SET {', '.join(set_parts)} WHERE place_id = %s"
    with conn.cursor() as cur:
        cur.execute(sql, params)
