"""SQL queries behind the /v1/mcq endpoints.

Kept as one module so the routes file can stay focused on request
validation and response shaping. All queries use `dict_row` and return
either dicts or lists of dicts; the routes map these onto the Pydantic
response models.
"""

from __future__ import annotations

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
    """One row per subject with total + per-type counts and round coverage."""
    sql = """
    SELECT
      s.slug,
      s.title,
      s.description,
      COALESCE(q.total, 0)           AS total_questions,
      COALESCE(q.knowledge, 0)       AS knowledge,
      COALESCE(q.analytical, 0)      AS analytical,
      COALESCE(q.problem_solving, 0) AS problem_solving,
      COALESCE(q.rounds_covered, 0)  AS rounds_covered
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
    ORDER BY s.slug ASC
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


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
    subject: str,
    qtype: str | None,
    count: int,
) -> list[dict[str, Any]]:
    params: list[Any] = [subject]
    where = ["q.subject_slug = %s"]
    if qtype is not None:
        where.append("q.question_type = %s::question_type")
        params.append(qtype)

    # TABLESAMPLE would be cheaper, but it skews tiny tables.
    # ORDER BY random() is fine up to 50k rows which we won't exceed
    # per (subject, type) for the foreseeable future.
    sql = (
        _QUESTION_BASE
        + " WHERE "
        + " AND ".join(where)
        + " ORDER BY random() LIMIT %s"
    )
    params.append(count)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())
