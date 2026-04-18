"""Free-text search over `places` — Postgres FTS + trigram fuzzy.

Scoring combines three signals per candidate row:
  fts_rank     — ts_rank over the weighted tsvector (name/category/address)
  trgm_ar      — trigram similarity between query and Arabic `name`
  trgm_en      — trigram similarity between query and `name_en`

Final score = ts_rank * 2.0 + max(trgm_ar, trgm_en)
The 2.0 weight on FTS biases exact/stemmed matches over fuzzy ones; if
FTS has nothing (pure typo), the trigram score carries the row.

Query candidates come from `@@` on the tsvector OR `%` trigram on either
name column. `@@` is the GIN FTS operator; `%` is pg_trgm's fuzzy
operator (default threshold 0.3 via `pg_trgm.similarity_threshold`).
"""

from __future__ import annotations

import math
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from . import search_synonyms

# Same metres-per-degree constant as the /v1/places query; keep duplicated
# to avoid cross-module imports for a pair of one-liners.
_M_PER_DEG_LAT = 111_320.0


SEARCH_SQL = """
WITH q AS (
    SELECT
      -- Synonym-expanded query for recall. Tokens OR'd with their
      -- group members, joined by AND; see search_synonyms.build_tsquery.
      to_tsquery('simple', %(tsq)s)                                  AS tsq,
      -- Phrase query over the user's original words in order. Uses the
      -- `<->` adjacency operator so "coffee shop" demands the two words
      -- appear consecutively — that's the "closest phrase" signal.
      phraseto_tsquery('simple', ar_normalize(%(raw_q)s))             AS tsq_phrase,
      -- Arabic-normalised original string for trigram + exact/prefix/substring.
      ar_normalize(%(raw_q)s)                                         AS raw_q
),
cand AS (
    SELECT
      p.place_id, p.name, p.name_en, p.category, p.latitude, p.longitude,
      p.full_address, p.full_address_en, p.phone, p.rating, p.reviews_count,
      p.website, p.business_status, p.open_now,
      ts_rank(p.search_tsv, q.tsq)                                    AS fts_rank_syn,
      ts_rank(p.search_tsv, q.tsq_phrase)                             AS fts_rank_phrase,
      GREATEST(
        similarity(ar_normalize(COALESCE(p.name,    '')), q.raw_q),
        similarity(ar_normalize(COALESCE(p.name_en, '')), q.raw_q)
      )                                                               AS trgm_score,
      -- Exact / prefix / substring bonus on either name column. Tiered
      -- so an exact match dominates a "contains" match.
      CASE
        WHEN ar_normalize(COALESCE(p.name,'')) = q.raw_q
          OR ar_normalize(COALESCE(p.name_en,'')) = q.raw_q            THEN 10.0
        WHEN ar_normalize(COALESCE(p.name,'')) LIKE q.raw_q || '%%'
          OR ar_normalize(COALESCE(p.name_en,'')) LIKE q.raw_q || '%%' THEN 4.0
        WHEN q.raw_q <> ''
         AND (ar_normalize(COALESCE(p.name,''))    LIKE '%%' || q.raw_q || '%%'
           OR ar_normalize(COALESCE(p.name_en,'')) LIKE '%%' || q.raw_q || '%%') THEN 2.0
        ELSE 0.0
      END                                                              AS exact_bonus
    FROM places p, q
    WHERE
      (
        p.search_tsv @@ q.tsq
        OR p.search_tsv @@ q.tsq_phrase
        OR ar_normalize(p.name)    %% q.raw_q
        OR ar_normalize(p.name_en) %% q.raw_q
        OR ar_normalize(COALESCE(p.name, ''))    LIKE '%%' || q.raw_q || '%%'
        OR ar_normalize(COALESCE(p.name_en, '')) LIKE '%%' || q.raw_q || '%%'
      )
      AND (%(category)s::text IS NULL OR p.category = %(category)s)
      AND (%(min_rating)s::numeric = 0
           OR (p.rating IS NOT NULL AND p.rating >= %(min_rating)s::numeric))
      AND (%(min_reviews)s::int = 0
           OR (p.reviews_count IS NOT NULL AND p.reviews_count >= %(min_reviews)s::int))
      AND (
        %(has_geo)s = false OR (
          p.latitude  BETWEEN %(lat)s - %(lat_pad)s AND %(lat)s + %(lat_pad)s
          AND p.longitude BETWEEN %(lon)s - %(lon_pad)s AND %(lon)s + %(lon_pad)s
        )
      )
)
SELECT *,
  (
    exact_bonus                       -- exact / prefix / substring (dominant signal)
    + fts_rank_phrase * 5.0           -- adjacent-word phrase match
    + fts_rank_syn    * 2.0           -- synonym-expanded token match
    + trgm_score      * 1.0           -- fuzzy / typo tolerance
  ) AS score
FROM cand
ORDER BY score DESC, reviews_count DESC NULLS LAST
LIMIT %(limit_plus_one)s OFFSET %(offset)s
"""


def search(
    conn: Connection,
    *,
    q: str,
    category: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int | None = None,
    limit: int = 20,
    min_rating: float = 0.0,
    min_reviews: int = 0,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    has_geo = lat is not None and lon is not None and radius_m is not None
    if has_geo:
        lat_pad = radius_m / _M_PER_DEG_LAT
        lon_pad = radius_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    else:
        lat_pad = lon_pad = 0.0

    # `tsq` is the synonym-expanded tsquery string; `raw_q` is the
    # ar-normalised original for trigram fuzzy ranking (score + match).
    params = {
        "tsq": search_synonyms.build_tsquery(q),
        "raw_q": q.strip(),
        "category": category,
        "lat": lat or 0.0,
        "lon": lon or 0.0,
        "lat_pad": lat_pad,
        "lon_pad": lon_pad,
        "has_geo": has_geo,
        "min_rating": min_rating,
        "min_reviews": min_reviews,
        "limit_plus_one": min(max(limit, 1), 50) + 1,
        "offset": max(offset, 0),
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SEARCH_SQL, params)
        rows = list(cur.fetchall())
    capped = min(max(limit, 1), 50)
    has_more = len(rows) > capped
    return (rows[:capped], has_more)
