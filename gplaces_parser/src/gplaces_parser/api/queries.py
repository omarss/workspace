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
    WHERE (
        %(categories)s::text[] IS NULL
        OR p.category = ANY(%(categories)s::text[])
      )
      AND p.latitude BETWEEN q.lat0 - q.lat_pad AND q.lat0 + q.lat_pad
      AND p.longitude BETWEEN q.lon0 - q.lon_pad AND q.lon0 + q.lon_pad
      AND p.latitude IS NOT NULL
      AND p.longitude IS NOT NULL
      -- Quality filters applied *before* limiting so the final page
      -- isn't emptied by threshold-dropped results.
      AND (%(min_rating)s::numeric = 0 OR p.rating >= %(min_rating)s::numeric)
      AND (%(min_reviews)s::int = 0 OR p.reviews_count >= %(min_reviews)s::int)
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
    categories: list[str] | None,
    limit: int,
    min_rating: float = 0.0,
    min_reviews: int = 0,
) -> list[dict[str, Any]]:
    """Nearby places within `radius_m` of (lat, lon).

    `categories=None` means "no category filter" (the FEEDBACK §9.1
    `category=all` case). Passing a single-element list is equivalent
    to the original single-category behaviour. Comma-separated input is
    parsed in the route layer.
    """
    lat_pad = radius_m / _M_PER_DEG_LAT
    # cos(lat) collapses at poles; guard with a small minimum.
    lon_pad = radius_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    params = {
        "lat": lat,
        "lon": lon,
        "radius": radius_m,
        "lat_pad": lat_pad,
        "lon_pad": lon_pad,
        "categories": categories,  # psycopg adapts Python list → text[]
        "limit": limit,
        "min_rating": min_rating,
        "min_reviews": min_reviews,
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(NEARBY_SQL, params)
        return list(cur.fetchall())
