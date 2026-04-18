#!/usr/bin/env python3
"""
Fetch Mapillary speed-limit sign detections for Riyadh.

Mapillary exposes detected traffic-sign objects via the graph API. Each
detection has a `geometry` (point), a `value` (e.g.
`regulatory--maximum-speed-limit-80`), and a `first_seen_at` timestamp.

This script pulls every `regulatory--maximum-speed-limit-*` detection in
the Riyadh bbox, saves them to `cache/mapillary_signs.json.gz`, and the
builder loads the result as an independent speed-limit source at
priority 95 (just above directional OSM tags).

Authentication: Mapillary's API requires a client token. Set one via
`export MAPILLARY_TOKEN=MLY|…` before running. Without a token the
script exits cleanly with a skip message — the builder works without it.

API reference:
  https://www.mapillary.com/developer/api-documentation
  https://graph.mapillary.com/map_features
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time
from pathlib import Path

import requests

from fetch_roads import RIYADH_BBOX

OUT = Path(__file__).parent / "cache" / "mapillary_signs.json.gz"
OUT.parent.mkdir(exist_ok=True)

TOKEN_ENV = "MAPILLARY_TOKEN"
GRAPH_URL = "https://graph.mapillary.com/map_features"

# The API requires the bbox as a CSV of `min_lon,min_lat,max_lon,max_lat`.
# object_values filters to the specific traffic-sign categories we want.
SIGN_VALUES = [
    "regulatory--maximum-speed-limit-20",
    "regulatory--maximum-speed-limit-25",
    "regulatory--maximum-speed-limit-30",
    "regulatory--maximum-speed-limit-40",
    "regulatory--maximum-speed-limit-50",
    "regulatory--maximum-speed-limit-60",
    "regulatory--maximum-speed-limit-70",
    "regulatory--maximum-speed-limit-80",
    "regulatory--maximum-speed-limit-90",
    "regulatory--maximum-speed-limit-100",
    "regulatory--maximum-speed-limit-110",
    "regulatory--maximum-speed-limit-120",
    "regulatory--maximum-speed-limit-130",
    "regulatory--maximum-speed-limit-140",
]
FIELDS = "id,object_value,geometry,first_seen_at,last_seen_at"
PAGE_LIMIT = 1000


def main() -> None:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"SKIP: set {TOKEN_ENV} to enable Mapillary. "
              f"The builder will skip this source.")
        return
    if OUT.exists():
        print(f"Cache already exists: {OUT}")
        return

    s, w, n, e = RIYADH_BBOX
    bbox_csv = f"{w},{s},{e},{n}"

    all_features: list[dict] = []
    for value in SIGN_VALUES:
        params = {
            "access_token": token,
            "bbox": bbox_csv,
            "object_values": value,
            "fields": FIELDS,
            "limit": PAGE_LIMIT,
        }
        print(f"Fetching {value} ...")
        while True:
            try:
                r = requests.get(GRAPH_URL, params=params, timeout=120)
            except requests.RequestException as exc:
                print(f"  ! network error: {exc}", file=sys.stderr)
                time.sleep(5); continue
            if r.status_code == 429:
                print("  ! rate-limited, sleeping 30s")
                time.sleep(30); continue
            if r.status_code != 200:
                print(f"  ! HTTP {r.status_code}: {r.text[:200]}",
                      file=sys.stderr)
                break
            payload = r.json()
            data = payload.get("data", [])
            all_features.extend(data)
            print(f"  got {len(data)} (running total: {len(all_features)})")
            nxt = (payload.get("paging") or {}).get("next")
            if not nxt or not data:
                break
            # graph-style pagination: replace all params with cursor URL
            params = None
            try:
                r = requests.get(nxt, timeout=120)
            except requests.RequestException as exc:
                print(f"  ! cursor error: {exc}"); break
            if r.status_code != 200:
                print(f"  ! cursor HTTP {r.status_code}"); break
            payload = r.json()
            all_features.extend(payload.get("data", []))

    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump({"features": all_features}, fh)
    print(f"Wrote {OUT} — {len(all_features)} sign detections")


if __name__ == "__main__":
    main()
