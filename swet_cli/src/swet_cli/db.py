"""SQLite database: schema creation and CRUD operations.

Stores user preferences, generated questions, attempt history, and per-competency
adaptive level tracking. The database file lives at ~/.local/share/swet_cli/swet.db
by default.
"""

import json
import sqlite3
from datetime import date
from uuid import uuid4

from swet_cli.config import get_config

# Schema definition — new tables are added at the end; columns added via _migrate()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    role TEXT NOT NULL,
    languages TEXT NOT NULL,
    frameworks TEXT NOT NULL,
    difficulty INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    competency_slug TEXT NOT NULL,
    format TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    code_snippet TEXT,
    language TEXT,
    options TEXT,
    correct_answer TEXT,
    grading_rubric TEXT,
    explanation TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(id),
    answer_text TEXT NOT NULL,
    score REAL,
    max_score INTEGER,
    total_score REAL,
    grade_details TEXT,
    feedback TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmarks (
    question_id TEXT PRIMARY KEY REFERENCES questions(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS difficulty_overrides (
    competency_slug TEXT PRIMARY KEY,
    difficulty INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-competency adaptive level tracking (ELO-like rating)
CREATE TABLE IF NOT EXISTS competency_levels (
    competency_slug TEXT PRIMARY KEY,
    estimated_level INTEGER NOT NULL DEFAULT 1,
    elo_rating REAL NOT NULL DEFAULT 1000.0,
    consecutive_high INTEGER NOT NULL DEFAULT 0,
    consecutive_low INTEGER NOT NULL DEFAULT 0,
    total_attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-competency per-format performance tracking
CREATE TABLE IF NOT EXISTS format_performance (
    competency_slug TEXT NOT NULL,
    format TEXT NOT NULL,
    avg_score REAL NOT NULL DEFAULT 0.0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (competency_slug, format)
);

CREATE INDEX IF NOT EXISTS idx_questions_competency ON questions(competency_slug);
CREATE INDEX IF NOT EXISTS idx_questions_format ON questions(format);
CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
CREATE INDEX IF NOT EXISTS idx_attempts_completed ON attempts(completed_at);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply schema migrations for columns that CREATE TABLE IF NOT EXISTS won't add."""
    # Attempts table: add time_seconds column
    attempt_cols = {row[1] for row in conn.execute("PRAGMA table_info(attempts)").fetchall()}
    if "time_seconds" not in attempt_cols:
        conn.execute("ALTER TABLE attempts ADD COLUMN time_seconds REAL")
        conn.commit()

    # Preferences table: add preferred_formats column
    pref_cols = {row[1] for row in conn.execute("PRAGMA table_info(preferences)").fetchall()}
    if "preferred_formats" not in pref_cols:
        conn.execute("ALTER TABLE preferences ADD COLUMN preferred_formats TEXT")
        conn.commit()

    # Preferences table: add question_length column
    if "question_length" not in pref_cols:
        conn.execute("ALTER TABLE preferences ADD COLUMN question_length TEXT DEFAULT 'standard'")
        conn.commit()


def _get_connection() -> sqlite3.Connection:
    """Open (or create) the database and ensure schema exists."""
    db_path = get_config().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def get_db() -> sqlite3.Connection:
    """Public accessor for a database connection."""
    return _get_connection()


# --- State (key-value) ---


def set_state(key: str, value: str) -> None:
    """Insert or update a key-value pair in the state table."""
    conn = get_db()
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_state(key: str) -> str | None:
    """Get a value from the state table, or None if the key does not exist."""
    conn = get_db()
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


# --- Streak ---


def update_streak() -> tuple[int, bool]:
    """Update the daily streak after an attempt. Returns (current_streak, is_new_day).

    Logic: if last attempt was today, no change. If yesterday, increment.
    If older or missing, reset to 1.
    """
    today = date.today().isoformat()
    last_date = get_state("last_attempt_date")
    streak_str = get_state("current_streak")
    current_streak = int(streak_str) if streak_str else 0

    if last_date == today:
        return current_streak, False

    yesterday = date.today().toordinal() - 1

    if last_date:
        try:
            last_ordinal = date.fromisoformat(last_date).toordinal()
        except ValueError:
            last_ordinal = 0
    else:
        last_ordinal = 0

    if last_ordinal == yesterday:
        current_streak += 1
    else:
        current_streak = 1

    set_state("current_streak", str(current_streak))
    set_state("last_attempt_date", today)

    longest_str = get_state("longest_streak")
    longest = int(longest_str) if longest_str else 0
    if current_streak > longest:
        set_state("longest_streak", str(current_streak))

    return current_streak, True


# --- Preferences ---


def save_preferences(
    roles: list[str],
    languages: list[str],
    frameworks: list[str],
    difficulty: int = 3,
    preferred_formats: list[str] | None = None,
    question_length: str = "standard",
) -> None:
    """Insert or update the singleton preferences row."""
    conn = get_db()
    conn.execute(
        """
        INSERT INTO preferences (id, role, languages, frameworks, difficulty, preferred_formats,
                                 question_length)
        VALUES (1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            role = excluded.role,
            languages = excluded.languages,
            frameworks = excluded.frameworks,
            difficulty = excluded.difficulty,
            preferred_formats = excluded.preferred_formats,
            question_length = excluded.question_length,
            updated_at = datetime('now')
        """,
        (
            json.dumps(roles),
            json.dumps(languages),
            json.dumps(frameworks),
            difficulty,
            json.dumps(preferred_formats) if preferred_formats else None,
            question_length,
        ),
    )
    conn.commit()
    conn.close()


def get_preferences() -> dict | None:
    """Return the user's preferences or None if not set up."""
    conn = get_db()
    row = conn.execute("SELECT * FROM preferences WHERE id = 1").fetchone()
    conn.close()
    if row is None:
        return None

    # Backward compat: role was stored as plain string, now as JSON array
    raw_role = row["role"]
    try:
        roles = json.loads(raw_role)
        if isinstance(roles, str):
            roles = [roles]
    except json.JSONDecodeError:
        roles = [raw_role]

    # Parse preferred_formats (may be NULL for older databases)
    raw_formats = row["preferred_formats"] if "preferred_formats" in row.keys() else None
    preferred_formats = json.loads(raw_formats) if raw_formats else None

    # Parse question_length (may be missing for older databases)
    question_length = row["question_length"] if "question_length" in row.keys() else "standard"

    return {
        "roles": roles,
        "languages": json.loads(row["languages"]),
        "frameworks": json.loads(row["frameworks"]),
        "difficulty": row["difficulty"],
        "preferred_formats": preferred_formats,
        "question_length": question_length or "standard",
    }


# --- Questions ---


def save_question(question_data: dict) -> str:
    """Save a generated question and return its ID."""
    question_id = question_data.get("id", str(uuid4()))
    conn = get_db()
    conn.execute(
        """
        INSERT INTO questions (id, competency_slug, format, difficulty, title, body,
                               code_snippet, language, options, correct_answer,
                               grading_rubric, explanation, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_id,
            question_data["competency_slug"],
            question_data["format"],
            question_data["difficulty"],
            question_data["title"],
            question_data["body"],
            question_data.get("code_snippet"),
            question_data.get("language"),
            json.dumps(question_data.get("options")) if question_data.get("options") else None,
            question_data.get("correct_answer"),
            json.dumps(question_data.get("grading_rubric")) if question_data.get("grading_rubric") else None,
            question_data.get("explanation"),
            json.dumps(question_data.get("metadata")) if question_data.get("metadata") else None,
        ),
    )
    conn.commit()
    conn.close()
    return question_id


def get_question(question_id: str) -> dict | None:
    """Fetch a question by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_question(row)


def get_queued_question(
    competency_slug: str | None = None,
    question_format: str | None = None,
    difficulty: int | None = None,
) -> dict | None:
    """Get an unanswered question from the queue (no attempts yet).

    Optionally filters by competency, format, and difficulty.
    Returns the oldest queued question matching the criteria, or None.
    """
    conn = get_db()
    query = """
        SELECT q.*
        FROM questions q
        LEFT JOIN attempts a ON a.question_id = q.id
        WHERE a.id IS NULL
    """
    params: list = []
    if competency_slug:
        query += " AND q.competency_slug = ?"
        params.append(competency_slug)
    if question_format:
        query += " AND q.format = ?"
        params.append(question_format)
    if difficulty:
        query += " AND q.difficulty = ?"
        params.append(difficulty)
    query += " ORDER BY q.created_at ASC LIMIT 1"

    row = conn.execute(query, params).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_question(row)


def count_queued_questions() -> int:
    """Count how many unanswered questions are in the queue."""
    conn = get_db()
    row = conn.execute(
        """
        SELECT COUNT(*) as cnt
        FROM questions q
        LEFT JOIN attempts a ON a.question_id = q.id
        WHERE a.id IS NULL
        """
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def resolve_question_id(partial: str) -> str | None:
    """Resolve a partial question ID (prefix match). Returns full ID or None if ambiguous/missing."""
    conn = get_db()
    rows = conn.execute("SELECT id FROM questions WHERE id LIKE ?", (partial + "%",)).fetchall()
    conn.close()
    if len(rows) == 1:
        return rows[0]["id"]
    return None


def _row_to_question(row: sqlite3.Row) -> dict:
    """Convert a database row to a question dict."""
    return {
        "id": row["id"],
        "competency_slug": row["competency_slug"],
        "format": row["format"],
        "difficulty": row["difficulty"],
        "title": row["title"],
        "body": row["body"],
        "code_snippet": row["code_snippet"],
        "language": row["language"],
        "options": json.loads(row["options"]) if row["options"] else None,
        "correct_answer": row["correct_answer"],
        "grading_rubric": json.loads(row["grading_rubric"]) if row["grading_rubric"] else None,
        "explanation": row["explanation"],
        "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
    }


# --- Attempts ---


def save_attempt(
    question_id: str,
    answer_text: str,
    score: float | None = None,
    max_score: int | None = None,
    total_score: float | None = None,
    grade_details: dict | None = None,
    feedback: str | None = None,
    time_seconds: float | None = None,
) -> str:
    """Save an attempt (answer + grade) and return its ID."""
    attempt_id = str(uuid4())
    conn = get_db()
    conn.execute(
        """
        INSERT INTO attempts (id, question_id, answer_text, score, max_score, total_score,
                              grade_details, feedback, time_seconds, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            attempt_id,
            question_id,
            answer_text,
            score,
            max_score,
            total_score,
            json.dumps(grade_details) if grade_details else None,
            feedback,
            time_seconds,
        ),
    )
    conn.commit()
    conn.close()
    return attempt_id


def get_history(limit: int = 20) -> list[dict]:
    """Get recent attempts with question details, most recent first."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT a.id, a.question_id, a.answer_text, a.score, a.max_score, a.total_score,
               a.feedback, a.time_seconds, a.completed_at,
               q.title, q.competency_slug, q.format, q.difficulty
        FROM attempts a
        JOIN questions q ON a.question_id = q.id
        ORDER BY a.completed_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "question_id": row["question_id"],
            "title": row["title"],
            "competency_slug": row["competency_slug"],
            "format": row["format"],
            "difficulty": row["difficulty"],
            "score": row["score"],
            "max_score": row["max_score"],
            "total_score": row["total_score"],
            "feedback": row["feedback"],
            "time_seconds": row["time_seconds"],
            "completed_at": row["completed_at"],
        }
        for row in rows
    ]


def get_attempts_for_question(question_id: str) -> list[dict]:
    """Get all attempts for a specific question, most recent first."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, answer_text, score, max_score, total_score, feedback,
               time_seconds, completed_at
        FROM attempts
        WHERE question_id = ?
        ORDER BY completed_at DESC
        """,
        (question_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "answer_text": row["answer_text"],
            "score": row["score"],
            "max_score": row["max_score"],
            "total_score": row["total_score"],
            "feedback": row["feedback"],
            "time_seconds": row["time_seconds"],
            "completed_at": row["completed_at"],
        }
        for row in rows
    ]


def get_stats() -> list[dict]:
    """Get aggregate stats by competency."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT q.competency_slug,
               COUNT(*) as total_attempts,
               AVG(a.score) as avg_score,
               MIN(a.score) as min_score,
               MAX(a.score) as max_score
        FROM attempts a
        JOIN questions q ON a.question_id = q.id
        WHERE a.score IS NOT NULL
        GROUP BY q.competency_slug
        ORDER BY avg_score DESC
        """,
    ).fetchall()
    conn.close()
    return [
        {
            "competency_slug": row["competency_slug"],
            "total_attempts": row["total_attempts"],
            "avg_score": row["avg_score"],
            "min_score": row["min_score"],
            "max_score": row["max_score"],
        }
        for row in rows
    ]


# --- Bookmarks ---


def save_bookmark(question_id: str) -> None:
    """Bookmark a question."""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO bookmarks (question_id) VALUES (?)",
        (question_id,),
    )
    conn.commit()
    conn.close()


def remove_bookmark(question_id: str) -> None:
    """Remove a bookmark."""
    conn = get_db()
    conn.execute("DELETE FROM bookmarks WHERE question_id = ?", (question_id,))
    conn.commit()
    conn.close()


def is_bookmarked(question_id: str) -> bool:
    """Check if a question is bookmarked."""
    conn = get_db()
    row = conn.execute("SELECT 1 FROM bookmarks WHERE question_id = ?", (question_id,)).fetchone()
    conn.close()
    return row is not None


def get_bookmarks(limit: int = 50) -> list[dict]:
    """Get bookmarked questions with details."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT b.created_at as bookmarked_at,
               q.id, q.title, q.competency_slug, q.format, q.difficulty
        FROM bookmarks b
        JOIN questions q ON b.question_id = q.id
        ORDER BY b.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "competency_slug": row["competency_slug"],
            "format": row["format"],
            "difficulty": row["difficulty"],
            "bookmarked_at": row["bookmarked_at"],
        }
        for row in rows
    ]


# --- Difficulty Overrides ---


def get_difficulty_override(competency_slug: str) -> int | None:
    """Get the difficulty override for a competency, or None if not set."""
    conn = get_db()
    row = conn.execute(
        "SELECT difficulty FROM difficulty_overrides WHERE competency_slug = ?",
        (competency_slug,),
    ).fetchone()
    conn.close()
    return row["difficulty"] if row else None


def set_difficulty_override(competency_slug: str, difficulty: int) -> None:
    """Set a difficulty override for a competency."""
    conn = get_db()
    conn.execute(
        """
        INSERT INTO difficulty_overrides (competency_slug, difficulty)
        VALUES (?, ?)
        ON CONFLICT(competency_slug) DO UPDATE SET
            difficulty = excluded.difficulty,
            updated_at = datetime('now')
        """,
        (competency_slug, difficulty),
    )
    conn.commit()
    conn.close()


def get_all_difficulty_overrides() -> dict[str, int]:
    """Get all difficulty overrides as a slug -> difficulty mapping."""
    conn = get_db()
    rows = conn.execute("SELECT competency_slug, difficulty FROM difficulty_overrides").fetchall()
    conn.close()
    return {row["competency_slug"]: row["difficulty"] for row in rows}


# --- Per-Competency Adaptive Level Tracking ---


def get_competency_level(competency_slug: str) -> dict | None:
    """Get the adaptive level data for a competency."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM competency_levels WHERE competency_slug = ?",
        (competency_slug,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "competency_slug": row["competency_slug"],
        "estimated_level": row["estimated_level"],
        "elo_rating": row["elo_rating"],
        "consecutive_high": row["consecutive_high"],
        "consecutive_low": row["consecutive_low"],
        "total_attempts": row["total_attempts"],
    }


def get_all_competency_levels() -> dict[str, dict]:
    """Get all per-competency level data."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM competency_levels").fetchall()
    conn.close()
    return {
        row["competency_slug"]: {
            "estimated_level": row["estimated_level"],
            "elo_rating": row["elo_rating"],
            "consecutive_high": row["consecutive_high"],
            "consecutive_low": row["consecutive_low"],
            "total_attempts": row["total_attempts"],
        }
        for row in rows
    }


def update_competency_level(
    competency_slug: str,
    estimated_level: int,
    elo_rating: float,
    consecutive_high: int,
    consecutive_low: int,
    total_attempts: int,
) -> None:
    """Update the adaptive level tracking for a competency."""
    conn = get_db()
    conn.execute(
        """
        INSERT INTO competency_levels (competency_slug, estimated_level, elo_rating,
                                        consecutive_high, consecutive_low, total_attempts)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(competency_slug) DO UPDATE SET
            estimated_level = excluded.estimated_level,
            elo_rating = excluded.elo_rating,
            consecutive_high = excluded.consecutive_high,
            consecutive_low = excluded.consecutive_low,
            total_attempts = excluded.total_attempts,
            updated_at = datetime('now')
        """,
        (competency_slug, estimated_level, elo_rating, consecutive_high, consecutive_low, total_attempts),
    )
    conn.commit()
    conn.close()


# --- Format Performance Tracking ---


def update_format_performance(competency_slug: str, fmt: str, score: float) -> None:
    """Update running average for a competency+format pair."""
    conn = get_db()
    row = conn.execute(
        "SELECT avg_score, attempt_count FROM format_performance WHERE competency_slug = ? AND format = ?",
        (competency_slug, fmt),
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO format_performance (competency_slug, format, avg_score, attempt_count) VALUES (?, ?, ?, 1)",
            (competency_slug, fmt, score),
        )
    else:
        # Incremental running average
        old_avg = row["avg_score"]
        old_count = row["attempt_count"]
        new_count = old_count + 1
        new_avg = old_avg + (score - old_avg) / new_count
        conn.execute(
            """UPDATE format_performance
               SET avg_score = ?, attempt_count = ?, updated_at = datetime('now')
               WHERE competency_slug = ? AND format = ?""",
            (new_avg, new_count, competency_slug, fmt),
        )

    conn.commit()
    conn.close()


def get_format_performance(competency_slug: str | None = None) -> list[dict]:
    """Get format performance data, optionally filtered by competency."""
    conn = get_db()
    if competency_slug:
        rows = conn.execute(
            "SELECT * FROM format_performance WHERE competency_slug = ?",
            (competency_slug,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM format_performance").fetchall()
    conn.close()
    return [
        {
            "competency_slug": row["competency_slug"],
            "format": row["format"],
            "avg_score": row["avg_score"],
            "attempt_count": row["attempt_count"],
        }
        for row in rows
    ]


# --- Performance Queries (for spaced repetition & difficulty auto-adjust) ---


def get_competency_rolling_avg(competency_slug: str, n: int = 5) -> float | None:
    """Get the rolling average score for the last N attempts of a competency."""
    conn = get_db()
    row = conn.execute(
        """
        SELECT AVG(a.score) as avg_score
        FROM (
            SELECT a.score
            FROM attempts a
            JOIN questions q ON a.question_id = q.id
            WHERE q.competency_slug = ? AND a.score IS NOT NULL
            ORDER BY a.completed_at DESC
            LIMIT ?
        ) a
        """,
        (competency_slug, n),
    ).fetchone()
    conn.close()
    return row["avg_score"] if row and row["avg_score"] is not None else None


def get_competency_performance() -> list[dict]:
    """Get per-competency performance data for spaced repetition weighting."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT q.competency_slug,
               AVG(a.score) as avg_score,
               COUNT(*) as attempt_count,
               MAX(a.completed_at) as last_attempt_date
        FROM attempts a
        JOIN questions q ON a.question_id = q.id
        WHERE a.score IS NOT NULL
        GROUP BY q.competency_slug
        """,
    ).fetchall()
    conn.close()
    return [
        {
            "competency_slug": row["competency_slug"],
            "avg_score": row["avg_score"],
            "attempt_count": row["attempt_count"],
            "last_attempt_date": row["last_attempt_date"],
        }
        for row in rows
    ]


def get_recent_competency_slugs(n: int = 10) -> list[str]:
    """Get the N most recently attempted competency slugs (for diversity)."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT DISTINCT q.competency_slug
        FROM attempts a
        JOIN questions q ON a.question_id = q.id
        ORDER BY a.completed_at DESC
        LIMIT ?
        """,
        (n,),
    ).fetchall()
    conn.close()
    return [row["competency_slug"] for row in rows]


def get_recent_question_topics(n: int = 20) -> list[str]:
    """Get topics from the N most recent questions to avoid repetition."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT q.metadata
        FROM questions q
        JOIN attempts a ON a.question_id = q.id
        ORDER BY a.completed_at DESC
        LIMIT ?
        """,
        (n,),
    ).fetchall()
    conn.close()
    topics: list[str] = []
    for row in rows:
        if row["metadata"]:
            meta = json.loads(row["metadata"])
            if isinstance(meta, dict) and "topics" in meta:
                topics.extend(meta["topics"])
    return topics
