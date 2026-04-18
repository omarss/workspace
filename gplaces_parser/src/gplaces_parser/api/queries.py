"""Geo queries over the `places` table.

PostGIS isn't installed locally, so we do haversine in SQL. The WHERE
clause uses a lat/lon bounding-box first (index-backed) and only then
computes great-circle distance for the survivors — so the expensive
trig is limited to a handful of candidates even when the table grows.
"""

from __future__ import annotations

import math
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

# 1 deg latitude ≈ 111_320 m. Longitude depends on latitude.
_M_PER_DEG_LAT = 111_320.0

NEARBY_SQL = """
WITH
  q AS (SELECT
          %(lat)s::double precision AS lat0,
          %(lon)s::double precision AS lon0,
          %(radius)s::double precision AS r_m,
          %(lat_pad)s::double precision AS lat_pad,
          %(lon_pad)s::double precision AS lon_pad),
  candidates AS (
    SELECT p.*
    FROM places p, q
    WHERE p.category = %(category)s
      AND p.latitude BETWEEN q.lat0 - q.lat_pad AND q.lat0 + q.lat_pad
      AND p.longitude BETWEEN q.lon0 - q.lon_pad AND q.lon0 + q.lon_pad
      AND p.latitude IS NOT NULL
      AND p.longitude IS NOT NULL
  ),
  scored AS (
    SELECT
      c.place_id,
      c.name,
      c.name_en,
      c.latitude,
      c.longitude,
      c.full_address,
      c.full_address_en,
      c.phone,
      c.rating,
      c.reviews_count,
      c.website,
      c.category,
      c.working_hours,
      6371000.0 * 2.0 * asin(sqrt(
        power(sin(radians((c.latitude - q.lat0) / 2.0)), 2)
        + cos(radians(q.lat0)) * cos(radians(c.latitude))
          * power(sin(radians((c.longitude - q.lon0) / 2.0)), 2)
      )) AS distance_m
    FROM candidates c, q
  )
SELECT * FROM scored
WHERE distance_m <= (SELECT r_m FROM q)
ORDER BY distance_m ASC
LIMIT %(limit)s
"""


def nearby(
    conn: Connection,
    *,
    lat: float,
    lon: float,
    radius_m: int,
    category: str,
    limit: int,
) -> list[dict[str, Any]]:
    lat_pad = radius_m / _M_PER_DEG_LAT
    # cos(lat) collapses at poles; guard with a small minimum.
    lon_pad = radius_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    params = {
        "lat": lat,
        "lon": lon,
        "radius": radius_m,
        "lat_pad": lat_pad,
        "lon_pad": lon_pad,
        "category": category,
        "limit": limit,
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(NEARBY_SQL, params)
        return list(cur.fetchall())
