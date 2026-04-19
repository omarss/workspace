#!/usr/bin/env python3
"""Ground-truth A/B: fire the scraper at a handful of random points +
one category, then diff what Google returned against what's in the DB
within the same radius. One-off diagnostic — not resumable, doesn't
touch scrape_jobs.

Usage:
    .venv/bin/python scripts/coverage_check.py

Edits POINTS / QUERIES below to tweak scope.
"""
from __future__ import annotations

import math

import psycopg
from psycopg.rows import dict_row

from gplaces_parser.config import settings
from gplaces_parser.scraper import PlaywrightScraper

# A mix of dense cores + middle-density areas.
POINTS: list[tuple[float, float, str]] = [
    (24.7140, 46.6760, "Olaya / Sulaymaniyah core"),
    (24.6755, 46.7352, "Malaz historic"),
    (24.7890, 46.6460, "Al Sahafah"),
    (24.8050, 46.6100, "Al Malqa"),
]
# One category per point keeps the scrape quick (~30 s × 4 ≈ 2 min).
QUERY_AR = "مقاهي"
QUERY_EN = "coffee shops"
RADIUS_M = 500
# In-DB match: filter by category='coffee' within a bbox of RADIUS_M.
_M_PER_DEG_LAT = 111_320.0


def db_places_within(conn, lat: float, lon: float, radius_m: int, category: str):
    lat_pad = radius_m / _M_PER_DEG_LAT
    lon_pad = radius_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT place_id, COALESCE(name, name_en) AS name
            FROM places
            WHERE category = %s
              AND latitude  BETWEEN %s AND %s
              AND longitude BETWEEN %s AND %s
            """,
            (category, lat - lat_pad, lat + lat_pad, lon - lon_pad, lon + lon_pad),
        )
        return {r["place_id"]: r["name"] for r in cur.fetchall()}


def main() -> None:
    with psycopg.connect(settings.database_url) as conn, PlaywrightScraper() as scraper:
        for lat, lon, label in POINTS:
            print(f"\n=== {label}   @ {lat}, {lon}", flush=True)
            db_hits = db_places_within(conn, lat, lon, RADIUS_M, "coffee")
            print(f"  DB coffee within {RADIUS_M}m: {len(db_hits)}", flush=True)

            try:
                google_cards = scraper.search_places(query=QUERY_AR, lat=lat, lng=lon, hl="ar")
            except Exception as exc:  # noqa: BLE001
                print(f"  [skip — Google timeout/error: {exc!s:.100}]", flush=True)
                continue
            # Filter Google cards to those inside the bbox (a free side-effect
            # of the scraper is that it returns many more than 500m-relevant).
            lat_pad = RADIUS_M / _M_PER_DEG_LAT
            lon_pad = RADIUS_M / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
            google_ids = {
                rec["place_id"]: rec.get("name", "")
                for rec in google_cards
                if rec.get("latitude") is not None
                and abs(rec["latitude"] - lat) <= lat_pad
                and abs(rec["longitude"] - lon) <= lon_pad
            }
            print(f"  Google coffee within {RADIUS_M}m: {len(google_ids)}")

            missing = set(google_ids) - set(db_hits)
            extra = set(db_hits) - set(google_ids)
            overlap = set(google_ids) & set(db_hits)
            print(f"  overlap:       {len(overlap)}")
            print(f"  missing in DB: {len(missing)}")
            print(f"  only in DB:    {len(extra)}  (may have been posted but Google rank shifted)")
            if missing:
                print(f"    sample missing names:")
                for pid in list(missing)[:6]:
                    print(f"      {google_ids[pid][:50]}")


if __name__ == "__main__":
    main()
