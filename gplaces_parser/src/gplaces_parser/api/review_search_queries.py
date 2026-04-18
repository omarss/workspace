"""Full-text search over review bodies.

Matches reviews whose `text` contains the query tokens (FTS). Each hit
is joined to its parent place so the response carries the place name,
category, and coordinates — the client usually wants to show the
review in the context of where it was written.

`ts_headline` produces a short snippet with `<b>...</b>` around the
matched tokens, useful for UI highlighting.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

SEARCH_SQL = """
WITH q AS (
    SELECT
      websearch_to_tsquery('simple', %(q)s) AS tsq,
      %(q)s AS raw_q
)
SELECT
  r.review_id,
  r.rating                                      AS review_rating,
  r.text                                        AS review_text,
  ts_headline(
    'simple',
    COALESCE(r.text, ''),
    q.tsq,
    'StartSel=<b>,StopSel=</b>,MaxWords=40,MinWords=15,ShortWord=2'
  )                                             AS snippet,
  r.published_at,
  r.author_title                                AS author,
  r.likes,
  p.place_id,
  p.name                                        AS place_name,
  p.name_en                                     AS place_name_en,
  p.category                                    AS place_category,
  p.latitude                                    AS place_lat,
  p.longitude                                   AS place_lon,
  p.rating                                      AS place_rating,
  ts_rank(r.search_tsv, q.tsq)                  AS score
FROM reviews r
JOIN places p ON p.place_id = r.place_id
, q
WHERE r.search_tsv @@ q.tsq
  AND (%(categories)s::text[] IS NULL OR p.category = ANY(%(categories)s::text[]))
  AND (%(place_id)s::text IS NULL OR r.place_id = %(place_id)s)
  AND (%(min_review_rating)s::int = 0 OR r.rating >= %(min_review_rating)s::int)
ORDER BY score DESC, r.likes DESC NULLS LAST, r.published_at DESC NULLS LAST
LIMIT %(limit)s
"""


def search(
    conn: Connection,
    *,
    q: str,
    categories: list[str] | None = None,
    place_id: str | None = None,
    min_review_rating: int = 0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    params = {
        "q": q.strip(),
        "categories": categories,
        "place_id": place_id,
        "min_review_rating": min_review_rating,
        "limit": min(max(limit, 1), 50),
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SEARCH_SQL, params)
        return list(cur.fetchall())
