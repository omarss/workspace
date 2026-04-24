"""SQL queries behind the /v1/mcq endpoints.

Kept as one module so the routes file can stay focused on request
validation and response shaping. All queries use `dict_row` and return
either dicts or lists of dicts; the routes map these onto the Pydantic
response models.
"""

from __future__ import annotations

import re
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


def health(conn: Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM subjects")
        subjects = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM questions")
        questions = cur.fetchone()[0]
    return {"subjects": subjects, "questions": questions}


def list_subjects(conn: Connection) -> list[dict[str, Any]]:
    """One row per subject with total + per-type counts, round coverage, and doc_count."""
    sql = """
    SELECT
      s.slug,
      s.title,
      s.description,
      COALESCE(q.total, 0)           AS total_questions,
      COALESCE(q.knowledge, 0)       AS knowledge,
      COALESCE(q.analytical, 0)      AS analytical,
      COALESCE(q.problem_solving, 0) AS problem_solving,
      COALESCE(q.rounds_covered, 0)  AS rounds_covered,
      COALESCE(d.doc_count, 0)       AS doc_count
    FROM subjects s
    LEFT JOIN (
      SELECT
        subject_slug,
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE question_type = 'knowledge')       AS knowledge,
        COUNT(*) FILTER (WHERE question_type = 'analytical')      AS analytical,
        COUNT(*) FILTER (WHERE question_type = 'problem_solving') AS problem_solving,
        COUNT(DISTINCT round_id)                                  AS rounds_covered
      FROM questions
      GROUP BY subject_slug
    ) q ON q.subject_slug = s.slug
    LEFT JOIN (
      -- Only count docs that have been fully backfilled with content_text;
      -- stale rows (file deleted upstream) stay in the table but aren't
      -- exposed to the docs endpoints, so their count would mislead.
      SELECT subject_slug, COUNT(*) AS doc_count
      FROM source_docs
      WHERE content_text IS NOT NULL
      GROUP BY subject_slug
    ) d ON d.subject_slug = s.slug
    ORDER BY s.slug ASC
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Docs browsing (§11 of omono/FEEDBACK.md)
# ---------------------------------------------------------------------------

# A doc's display title falls through a cascade: Hugo/Jekyll YAML
# frontmatter (`title: …` inside a leading `---` block) first, then
# the first Markdown ATX H1, then the filename stem. The Kubernetes
# corpus in particular is Hugo-style `.html` files with frontmatter
# and no `# Heading`; without the frontmatter branch they'd all
# collapse to "index" titles and be indistinguishable in the list.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FRONTMATTER_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
_H1_RE = re.compile(r"^\s*#\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _extract_title(content_text: str | None, rel_path: str) -> str:
    """Best-effort display title for a source doc."""
    if content_text:
        # YAML frontmatter wins if present and carries a `title` key.
        fm = _FRONTMATTER_RE.match(content_text)
        if fm:
            t = _FRONTMATTER_TITLE_RE.search(fm.group(1))
            if t:
                title = t.group(1).strip().strip("\"'")
                if title:
                    return title
        h = _H1_RE.search(content_text)
        if h:
            return h.group(1).strip()
    stem = rel_path.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    # For Hugo-style _index / index filenames the parent folder name
    # carries the semantics. Walk up until we hit a non-index segment.
    if stem in {"index", "_index"}:
        parts = rel_path.rsplit("/", 2)
        if len(parts) >= 2 and parts[-2]:
            return parts[-2]
    return stem or rel_path


def list_docs(conn: Connection, *, subject: str) -> list[dict[str, Any]]:
    """All docs for `subject` that have a populated body.

    Stale rows (file deleted upstream, content_text left NULL because
    the ingest source disappeared before backfill) are filtered out so
    the list never advertises something the fetch endpoint would 404 on.
    """
    sql = """
    SELECT id, rel_path, byte_size, indexed_at, content_text
    FROM source_docs
    WHERE subject_slug = %s AND content_text IS NOT NULL
    ORDER BY rel_path ASC
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (subject,))
        rows = list(cur.fetchall())
    # Title extraction runs on the already-decoded body; drop the bulky
    # content_text from the payload so the list response stays tiny.
    for r in rows:
        r["title"] = _extract_title(r.get("content_text"), r["rel_path"])
        r.pop("content_text", None)
    return rows


def get_doc(conn: Connection, *, subject: str, doc_id: int) -> dict[str, Any] | None:
    sql = """
    SELECT id, subject_slug, rel_path, byte_size, indexed_at, content_text
    FROM source_docs
    WHERE subject_slug = %s AND id = %s AND content_text IS NOT NULL
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (subject, doc_id))
        row = cur.fetchone()
    if row is None:
        return None
    row["title"] = _extract_title(row.get("content_text"), row["rel_path"])
    return row


def subject_exists(conn: Connection, slug: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM subjects WHERE slug = %s", (slug,))
        return cur.fetchone() is not None


def list_topics(conn: Connection, *, subject: str) -> list[dict[str, Any]]:
    sql = """
    SELECT t.slug, t.title, COALESCE(cnt.n, 0) AS question_count
    FROM topics t
    LEFT JOIN (
      SELECT topic_id, COUNT(*) AS n
      FROM question_topics
      GROUP BY topic_id
    ) cnt ON cnt.topic_id = t.id
    WHERE t.subject_slug = %s
    ORDER BY cnt.n DESC NULLS LAST, t.slug ASC
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (subject,))
        return list(cur.fetchall())


_QUESTION_BASE = """
SELECT
  q.id,
  q.subject_slug,
  q.round_id,
  r.number AS round_number,
  q.question_type::text AS question_type,
  q.stem,
  q.difficulty,
  q.explanation,
  q.created_at,
  COALESCE(
    (SELECT jsonb_agg(jsonb_build_object(
        'letter', o.letter,
        'text', o.text,
        'is_correct', o.is_correct
     ) ORDER BY o.letter)
     FROM question_options o WHERE o.question_id = q.id),
    '[]'::jsonb
  ) AS options,
  COALESCE(
    (SELECT jsonb_agg(t.slug ORDER BY t.slug)
     FROM question_topics qt JOIN topics t ON t.id = qt.topic_id
     WHERE qt.question_id = q.id),
    '[]'::jsonb
  ) AS topics
FROM questions q
JOIN rounds r ON r.id = q.round_id
"""


def list_questions(
    conn: Connection,
    *,
    subject: str | None,
    qtype: str | None,
    topic: str | None,
    difficulty: int | None,
    round_number: int | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Paginated question listing. Returns (rows, has_more).

    We fetch `limit+1` and drop the overflow so `has_more` doesn't need
    a second COUNT query — same trick gplaces uses for /v1/places.
    """
    params: list[Any] = []
    where: list[str] = []
    if subject is not None:
        where.append("q.subject_slug = %s")
        params.append(subject)
    if qtype is not None:
        where.append("q.question_type = %s::question_type")
        params.append(qtype)
    if difficulty is not None:
        where.append("q.difficulty = %s")
        params.append(difficulty)
    if round_number is not None:
        where.append("r.number = %s")
        params.append(round_number)
    if topic is not None:
        where.append(
            "EXISTS (SELECT 1 FROM question_topics qt JOIN topics t ON t.id = qt.topic_id "
            "WHERE qt.question_id = q.id AND t.slug = %s)"
        )
        params.append(topic)

    sql = _QUESTION_BASE
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Random order by default so a paginated consumer rotating through
    # the bank doesn't see the same questions in the same sequence.
    # Acceptable caveat: different requests on the same filter produce
    # different pages — use `/questions/{id}` for stable addressing.
    sql += " ORDER BY random() LIMIT %s OFFSET %s"
    params.extend([limit + 1, offset])

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = list(cur.fetchall())
    has_more = len(rows) > limit
    return rows[:limit], has_more


def get_question(conn: Connection, qid: int) -> dict[str, Any] | None:
    sql = _QUESTION_BASE + " WHERE q.id = %s"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (qid,))
        return cur.fetchone()


def random_quiz(
    conn: Connection,
    *,
    subjects: list[str] | None,
    topics: list[str] | None,
    qtype: str | None,
    count: int,
) -> list[dict[str, Any]]:
    """Random sample.

    * `subjects=None` → no subject filter (bank-wide). A non-empty list
      restricts to those subject slugs.
    * `topics=None` → no topic filter. A non-empty list matches
      questions tagged with ANY of the slugs (a single question can
      span topics, so ANY is the right default).
    """
    params: list[Any] = []
    where: list[str] = []

    if subjects:
        where.append("q.subject_slug = ANY(%s::text[])")
        params.append(subjects)

    if topics:
        where.append(
            "EXISTS (SELECT 1 FROM question_topics qt JOIN topics t ON t.id = qt.topic_id "
            "WHERE qt.question_id = q.id AND t.slug = ANY(%s::text[]))"
        )
        params.append(topics)

    if qtype is not None:
        where.append("q.question_type = %s::question_type")
        params.append(qtype)

    sql = _QUESTION_BASE
    if where:
        sql += " WHERE " + " AND ".join(where)
    # ORDER BY random() is fine up to ~50k rows per filter — we're
    # nowhere near that. TABLESAMPLE was considered but skews tiny
    # subjects badly.
    sql += " ORDER BY random() LIMIT %s"
    params.append(count)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())
