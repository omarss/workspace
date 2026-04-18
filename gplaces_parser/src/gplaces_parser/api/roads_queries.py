"""Geo lookup for `/v1/roads`.

Two-stage resolve:
  1. SQL: filter rows whose pre-computed bounding box contains the point.
     Cheap, index-backed, usually narrows 109k polygons → 5–20 candidates.
  2. Python: for each candidate, reconstruct the Shapely Polygon from the
     stored GeoJSON and test strict point-in-polygon. Only the rows where
     the point actually lies inside the road's polygon are returned.

We return all matches (sorted by highway rank then polygon area) because
a coordinate at an intersection genuinely belongs to more than one road.
Client decides which to surface.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from shapely.geometry import Point, shape

# Lower rank == higher priority. Mirrors how a driver perceives "which
# road am I on": intercity motorway beats arterial beats residential.
_HIGHWAY_RANK = {
    "motorway": 0, "motorway_link": 0,
    "trunk": 1, "trunk_link": 1,
    "primary": 2, "primary_link": 2,
    "secondary": 3, "secondary_link": 3,
    "tertiary": 4, "tertiary_link": 4,
    "unclassified": 5,
    "residential": 6,
    "living_street": 7,
    "service": 8,
    "road": 9,
}


BBOX_SQL = """
SELECT osm_id, name, name_en, highway, ref, maxspeed_kmh, speed_source,
       lanes, oneway, geom,
       (bbox_max_lat - bbox_min_lat) * (bbox_max_lon - bbox_min_lon) AS bbox_area
FROM roads
WHERE %(lat)s BETWEEN bbox_min_lat AND bbox_max_lat
  AND %(lon)s BETWEEN bbox_min_lon AND bbox_max_lon
ORDER BY bbox_area ASC
LIMIT 40
"""


def at_point(conn: Connection, *, lat: float, lon: float, limit: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(BBOX_SQL, {"lat": lat, "lon": lon})
        candidates = list(cur.fetchall())

    pt = Point(lon, lat)
    hits: list[dict[str, Any]] = []
    for row in candidates:
        try:
            poly = shape(row["geom"])
        except Exception:  # noqa: BLE001
            continue
        if poly.contains(pt) or poly.touches(pt):
            hits.append(row)

    # Rank: motorway first, then by polygon area (smaller = more specific
    # lane, so the local slip-road beats the huge trunk it's next to).
    hits.sort(key=lambda r: (_HIGHWAY_RANK.get(r["highway"], 99), r["bbox_area"]))
    return hits[:limit]
