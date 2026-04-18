#!/usr/bin/env python3
"""
Fetch all `highway=*` ways in Riyadh from the OpenStreetMap Overpass API.

Strategy:
  * Tile the Riyadh governorate bbox into ~0.2° cells.
  * For each tile, POST an Overpass QL query with `out geom;`.
  * Cache each tile's response as JSONL under ./cache/ so re-runs are cheap.
  * Deduplicate ways by OSM id at build-time (tile overlap is fine).

We pull only drivable highways (exclude footways, paths, cycleways, steps, etc).
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
from pathlib import Path

import requests

# Full Riyadh Governorate bbox (OSM relation 12423679).
RIYADH_BBOX = (24.22, 46.31679, 25.2672799, 47.74305)  # south, west, north, east

# Tile step in degrees (~22 km per 0.2°).
TILE_STEP = 0.20

# Highway values we *keep*. Everything drivable + unclassified/residential.
DRIVABLE = [
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "road",  # unknown classification
]

# Overpass endpoints (rotate if rate-limited).
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def build_query(south: float, west: float, north: float, east: float) -> str:
    hw_filter = "|".join(DRIVABLE)
    return f"""
[out:json][timeout:180];
(
  way["highway"~"^({hw_filter})$"]({south},{west},{north},{east});
);
out tags geom;
""".strip()


def tile_key(s: float, w: float, n: float, e: float) -> str:
    return f"tile_{s:.3f}_{w:.3f}_{n:.3f}_{e:.3f}.json.gz"


def fetch_tile(south: float, west: float, north: float, east: float,
               attempt: int = 0) -> dict:
    """Fetch one tile, retrying across endpoints on failure."""
    path = CACHE_DIR / tile_key(south, west, north, east)
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)

    query = build_query(south, west, north, east)
    endpoint = ENDPOINTS[attempt % len(ENDPOINTS)]
    try:
        r = requests.post(
            endpoint,
            data={"data": query},
            timeout=300,
            headers={"User-Agent": "RiyadhRoadsMapper/1.0 (personal research)"},
        )
    except requests.RequestException as exc:
        print(f"  ! {endpoint}: {exc}", file=sys.stderr)
        if attempt >= 6:
            raise
        time.sleep(5 + attempt * 5)
        return fetch_tile(south, west, north, east, attempt + 1)

    if r.status_code != 200:
        print(f"  ! HTTP {r.status_code} on {endpoint}", file=sys.stderr)
        if attempt >= 6:
            r.raise_for_status()
        time.sleep(10 + attempt * 10)
        return fetch_tile(south, west, north, east, attempt + 1)

    data = r.json()
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def iter_tiles(bbox: tuple[float, float, float, float], step: float):
    s, w, n, e = bbox
    lat = s
    while lat < n:
        lon = w
        while lon < e:
            yield (lat, lon, min(lat + step, n), min(lon + step, e))
            lon += step
        lat += step


def main() -> None:
    tiles = list(iter_tiles(RIYADH_BBOX, TILE_STEP))
    print(f"Fetching {len(tiles)} tiles covering Riyadh governorate...")
    total_ways = 0
    for i, (s, w, n, e) in enumerate(tiles, 1):
        cached = (CACHE_DIR / tile_key(s, w, n, e)).exists()
        tag = "cache" if cached else "fetch"
        t0 = time.time()
        data = fetch_tile(s, w, n, e)
        ways = len(data.get("elements", []))
        total_ways += ways
        print(f"  [{i:3d}/{len(tiles)}] {tag} ({s:.2f},{w:.2f}) ways={ways:>6} "
              f"elapsed={time.time() - t0:.1f}s")
        if not cached:
            time.sleep(1.0)  # polite pacing
    print(f"Done. Raw way-rows (pre-dedup): {total_ways}")


if __name__ == "__main__":
    main()
