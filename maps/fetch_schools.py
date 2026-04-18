#!/usr/bin/env python3
"""
Fetch `amenity=school|kindergarten|college|university` features in Riyadh.

We need their geometry (point for a node, way/polygon for an area) so we
can buffer a school-zone around each and apply the 30-40 km/h posted
school-zone limit to nearby roads.
"""
from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import requests

from fetch_roads import ENDPOINTS, RIYADH_BBOX

OUT = Path(__file__).parent / "cache" / "schools.json.gz"
OUT.parent.mkdir(exist_ok=True)


QUERY = """
[out:json][timeout:180];
(
  node["amenity"~"^(school|kindergarten|college|university)$"]({s},{w},{n},{e});
  way["amenity"~"^(school|kindergarten|college|university)$"]({s},{w},{n},{e});
  relation["amenity"~"^(school|kindergarten|college|university)$"]({s},{w},{n},{e});
);
out tags center geom;
"""


def main() -> None:
    if OUT.exists():
        print(f"Cache already exists: {OUT}")
        return
    s, w, n, e = RIYADH_BBOX
    q = QUERY.format(s=s, w=w, n=n, e=e)
    for attempt, ep in enumerate(ENDPOINTS * 3):
        print(f"Trying {ep} (attempt {attempt + 1}) ...")
        try:
            r = requests.post(ep, data={"data": q}, timeout=300,
                              headers={"User-Agent":
                                       "RiyadhRoadsMapper/1.0 (schools)"})
        except requests.RequestException as exc:
            print(f"  ! {exc}")
            time.sleep(5 + attempt * 5)
            continue
        if r.status_code != 200:
            print(f"  ! HTTP {r.status_code}")
            time.sleep(10 + attempt * 10)
            continue
        data = r.json()
        with gzip.open(OUT, "wt", encoding="utf-8") as fh:
            json.dump(data, fh)
        print(f"Wrote {OUT} — {len(data.get('elements', []))} amenity features")
        return
    raise SystemExit("exhausted retries")


if __name__ == "__main__":
    main()
