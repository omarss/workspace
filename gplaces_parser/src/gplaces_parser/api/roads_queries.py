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

import math
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from shapely.geometry import Point, shape
from shapely.ops import transform as shp_transform

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


def at_point(
    conn: Connection,
    *,
    lat: float,
    lon: float,
    limit: int,
    snap_m: int = 0,
) -> list[dict[str, Any]]:
    """Return the road polygons the point sits inside.

    If `snap_m > 0` and no polygon contains the point, the bbox query is
    re-run with a padded radius and the *nearest* polygon within
    `snap_m` metres is returned with `snapped=True` + `snap_distance_m`
    (FEEDBACK §9.5). A snapped result signals the client that the speed
    number may not be authoritative (display as `~90 km/h`).
    """
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
            row["heading_deg"] = _polygon_heading_deg(poly, lat)
            row["snapped"] = False
            row["snap_distance_m"] = 0.0
            hits.append(row)

    if hits or snap_m <= 0:
        hits.sort(key=lambda r: (_HIGHWAY_RANK.get(r["highway"], 99), r["bbox_area"]))
        return hits[:limit]

    # No containment. Look for the nearest polygon within `snap_m` metres.
    # Widen the bbox prefilter by the snap radius so candidates that are
    # *near* the point (but not inside its tight bbox) get considered.
    pad_deg_lat = snap_m / _M_PER_DEG_LAT
    pad_deg_lon = snap_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            WIDE_BBOX_SQL,
            {"lat": lat, "lon": lon, "pad_lat": pad_deg_lat, "pad_lon": pad_deg_lon},
        )
        wide_candidates = list(cur.fetchall())

    # Convert both polygon and point to local equirectangular metres so
    # Shapely's Euclidean distance is actually in metres. Polygons in the
    # widened bbox are small enough that the projection error is sub-metre.
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)

    def _to_m(x: float, y: float, z: float | None = None) -> tuple[float, float]:
        # x = lon, y = lat. Standard equirectangular projection around
        # `lat` as the reference latitude.
        return (x * cos_lat * _M_PER_DEG_LAT, y * _M_PER_DEG_LAT)

    pt_m = Point(*_to_m(lon, lat))
    best: dict[str, Any] | None = None
    best_dist = float("inf")
    for row in wide_candidates:
        try:
            poly = shape(row["geom"])
            poly_m = shp_transform(_to_m, poly)
        except Exception:  # noqa: BLE001
            continue
        d_m = poly_m.distance(pt_m)
        if d_m < best_dist and d_m <= snap_m:
            best_dist = d_m
            row["heading_deg"] = _polygon_heading_deg(poly, lat)
            row["snapped"] = True
            row["snap_distance_m"] = round(d_m, 1)
            best = row
    return [best] if best else []


_M_PER_DEG_LAT = 111_320.0
WIDE_BBOX_SQL = """
SELECT osm_id, name, name_en, highway, ref, maxspeed_kmh, speed_source,
       lanes, oneway, geom,
       (bbox_max_lat - bbox_min_lat) * (bbox_max_lon - bbox_min_lon) AS bbox_area
FROM roads
WHERE bbox_max_lat >= %(lat)s - %(pad_lat)s
  AND bbox_min_lat <= %(lat)s + %(pad_lat)s
  AND bbox_max_lon >= %(lon)s - %(pad_lon)s
  AND bbox_min_lon <= %(lon)s + %(pad_lon)s
LIMIT 200
"""


def _polygon_heading_deg(poly: Any, center_lat: float) -> float | None:
    """Compass bearing (0=N, 90=E) of the polygon's long axis.

    The polygon is stored in WGS84 (lon,lat), so a naive atan2 on raw
    coordinate deltas skews by cos(latitude). We project to local metres
    first (equirectangular), compute the axis there, then convert back
    to a bearing. Accurate enough for per-road heading (±1°) across the
    whole Riyadh bbox.
    """
    try:
        mrr = poly.minimum_rotated_rectangle
        xs, ys = mrr.exterior.coords.xy
    except Exception:  # noqa: BLE001
        return None
    if len(xs) < 3:
        return None
    # minimum_rotated_rectangle returns a closed ring with 5 points.
    # Edge 0→1 and 1→2 are perpendicular; the longer one is the road axis.
    cos_lat = math.cos(math.radians(center_lat))
    metres_per_deg_lat = 111_320.0
    dx1 = (xs[1] - xs[0]) * cos_lat * metres_per_deg_lat
    dy1 = (ys[1] - ys[0]) * metres_per_deg_lat
    dx2 = (xs[2] - xs[1]) * cos_lat * metres_per_deg_lat
    dy2 = (ys[2] - ys[1]) * metres_per_deg_lat
    if dx1 * dx1 + dy1 * dy1 >= dx2 * dx2 + dy2 * dy2:
        dx, dy = dx1, dy1
    else:
        dx, dy = dx2, dy2
    # atan2(dx, dy) returns the angle east of north — a compass bearing.
    bearing = math.degrees(math.atan2(dx, dy))
    if bearing < 0:
        bearing += 360.0
    return round(bearing, 1)
