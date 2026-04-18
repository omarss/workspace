#!/usr/bin/env python3
"""
Load maps/roads.json (a FeatureCollection of Polygon features produced
by the other agent's build_roads.py) into the `roads` table so the
FastAPI service can serve /v1/roads without keeping 87 MB of GeoJSON
in RAM.

Idempotent — ON CONFLICT DO UPDATE means re-running after a rebuild of
roads.json just refreshes the rows. We batch inserts to keep the wire
traffic reasonable on 100k+ rows.

Usage:
    .venv/bin/python scripts/load_roads.py [path/to/roads.json]
Defaults to ../maps/roads.json relative to the gplaces_parser root.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT.parent / "maps" / "roads.json"

BATCH = 500


def bbox_of(coords: list) -> tuple[float, float, float, float] | None:
    """Polygon coords → (min_lat, max_lat, min_lon, max_lon).

    GeoJSON Polygons have shape [[[lon, lat], [lon, lat], ...]] where the
    first ring is the outer and the rest are holes. Bounding box over
    the outer ring is sufficient.
    """
    if not coords or not coords[0]:
        return None
    ring = coords[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return (min(lats), max(lats), min(lons), max(lons))


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    if not path.exists():
        sys.exit(f"roads.json not found at {path}")

    # Database URL comes from .env via our settings loader — avoid a
    # second source of truth, but we don't want to pull the whole config
    # dependency tree for a one-shot loader, so read it minimally.
    db_url = _database_url()
    print(f"Loading {path} → {db_url.split('@')[-1]} ...")

    t0 = time.monotonic()
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    feats = data.get("features", [])
    print(f"  parsed {len(feats):,} features in {time.monotonic() - t0:.1f}s")

    insert_sql = """
        INSERT INTO roads (
          osm_id, name, name_en, highway, ref,
          maxspeed_kmh, speed_source, speed_confidence,
          lanes, width_m, oneway,
          bbox_min_lat, bbox_max_lat, bbox_min_lon, bbox_max_lon,
          geom, loaded_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (osm_id) DO UPDATE SET
          name             = EXCLUDED.name,
          name_en          = EXCLUDED.name_en,
          highway          = EXCLUDED.highway,
          ref              = EXCLUDED.ref,
          maxspeed_kmh     = EXCLUDED.maxspeed_kmh,
          speed_source     = EXCLUDED.speed_source,
          speed_confidence = EXCLUDED.speed_confidence,
          lanes            = EXCLUDED.lanes,
          width_m          = EXCLUDED.width_m,
          oneway           = EXCLUDED.oneway,
          bbox_min_lat     = EXCLUDED.bbox_min_lat,
          bbox_max_lat     = EXCLUDED.bbox_max_lat,
          bbox_min_lon     = EXCLUDED.bbox_min_lon,
          bbox_max_lon     = EXCLUDED.bbox_max_lon,
          geom             = EXCLUDED.geom,
          loaded_at        = now()
    """

    written = 0
    skipped = 0
    with psycopg.connect(db_url, autocommit=False) as conn:
        batch: list[tuple] = []
        for f in feats:
            geom = f.get("geometry") or {}
            if geom.get("type") != "Polygon":
                skipped += 1
                continue
            bb = bbox_of(geom.get("coordinates") or [])
            if bb is None:
                skipped += 1
                continue
            p = f.get("properties") or {}
            if "osm_id" not in p or "highway" not in p or "maxspeed_kmh" not in p:
                skipped += 1
                continue
            min_lat, max_lat, min_lon, max_lon = bb
            batch.append((
                int(p["osm_id"]),
                p.get("name"),
                p.get("name_en"),
                p["highway"],
                p.get("ref"),
                int(p["maxspeed_kmh"]),
                p.get("speed_source"),
                p.get("speed_confidence"),
                p.get("lanes"),
                p.get("width_m"),
                p.get("oneway"),
                min_lat, max_lat, min_lon, max_lon,
                Jsonb(geom),
            ))
            if len(batch) >= BATCH:
                _flush(conn, insert_sql, batch)
                written += len(batch)
                batch.clear()
                if written % 10_000 == 0:
                    print(f"  upserted {written:,}")
        if batch:
            _flush(conn, insert_sql, batch)
            written += len(batch)
        conn.commit()

    print(f"Done. upserted {written:,} rows, skipped {skipped:,}, {time.monotonic() - t0:.1f}s total.")


def _flush(conn: psycopg.Connection, sql: str, batch: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(sql, batch)
    conn.commit()


def _database_url() -> str:
    """Read DATABASE_URL from .env without importing the full settings.

    `load_roads.py` may run before the full package is importable (e.g.
    inside the release tarball before `pip install -e .`), so we keep
    its dependency surface minimal.
    """
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    import os
    v = os.environ.get("DATABASE_URL")
    if not v:
        sys.exit("DATABASE_URL not set (not in .env, not in env)")
    return v


if __name__ == "__main__":
    main()
