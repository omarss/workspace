#!/usr/bin/env python3
"""
Fetch OSM `landuse=*` and `place=*` polygons covering the built-up area of
Riyadh. The union of these polygons is the "urban mask" — segments inside
get urban inferred defaults (residential 40, secondary 60, trunk 100), and
segments outside get rural defaults (trunk 120, primary 100, secondary 80).

Landuse values we treat as urban:
    residential, commercial, industrial, retail, education, institutional,
    construction, military, cemetery, religious, garages

These cover every piece of developed ground that comes with posted urban
speeds. We deliberately do NOT include `landuse=farmland|forest|desert`
because those are the rural areas we want to distinguish.
"""
from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import requests

from fetch_roads import ENDPOINTS, RIYADH_BBOX

OUT = Path(__file__).parent / "cache" / "landuse.json.gz"
OUT.parent.mkdir(exist_ok=True)


QUERY = """
[out:json][timeout:240];
(
  way["landuse"~"^(residential|commercial|industrial|retail|education|institutional|construction|military|cemetery|religious|garages)$"]({s},{w},{n},{e});
  relation["landuse"~"^(residential|commercial|industrial|retail|education|institutional|construction|military|cemetery|religious|garages)$"]({s},{w},{n},{e});
  way["place"~"^(city|town|suburb|neighbourhood|quarter)$"]({s},{w},{n},{e});
  relation["place"~"^(city|town|suburb|neighbourhood|quarter)$"]({s},{w},{n},{e});
);
out tags geom;
"""


def main() -> None:
    if OUT.exists():
        print(f"Cache already exists: {OUT}")
        return
    s, w, n, e = RIYADH_BBOX
    q = QUERY.format(s=s, w=w, n=n, e=e)
    for attempt, ep in enumerate(ENDPOINTS * 4):
        print(f"Trying {ep} (attempt {attempt + 1}) ...")
        try:
            r = requests.post(ep, data={"data": q}, timeout=360,
                              headers={"User-Agent":
                                       "RiyadhRoadsMapper/1.0 (landuse)"})
        except requests.RequestException as exc:
            print(f"  ! {exc}")
            time.sleep(10 + attempt * 5)
            continue
        if r.status_code != 200:
            print(f"  ! HTTP {r.status_code}")
            time.sleep(10 + attempt * 10)
            continue
        data = r.json()
        with gzip.open(OUT, "wt", encoding="utf-8") as fh:
            json.dump(data, fh)
        print(f"Wrote {OUT} — {len(data.get('elements', []))} landuse/place polygons")
        return
    raise SystemExit("exhausted retries")


if __name__ == "__main__":
    main()
