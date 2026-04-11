"""WhatsApp bot database: user-scoped schema for multi-user isolation.

Manages its own SQLite database file separate from the CLI, API, and Telegram bot.
All assessment tables include a user_id column scoped to WhatsApp phone numbers.
"""

import json
import sqlite3
from datetime import date
from uuid import uuid4

from swet_whatsapp.config import get_whatsapp_config

_SCHEMA = """
-- WhatsApp users (phone number as primary key)
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- User-scoped assessment tables (mirrors swet_cli schema + user_id)
CREATE TABLE IF NOT EXISTS preferences (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    role TEXT NOT NULL,
    languages TEXT NOT NULL,
    frameworks TEXT NOT NULL,
    difficulty INTEGER NOT NULL DEFAULT 3,
    preferred_formats TEXT,
    question_length TEXT DEFAULT 'standard',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
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
    user_id TEXT NOT NULL REFERENCES users(id),
    question_id TEXT NOT NULL REFERENCES questions(id),
    answer_text TEXT NOT NULL,
    score REAL,
    max_score INTEGER,
    total_score REAL,
    grade_details TEXT,
    feedback TEXT,
    time_seconds REAL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS state (
    user_id TEXT NOT NULL REFERENCES users(id),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS bookmarks (
    user_id TEXT NOT NULL REFERENCES users(id),
    question_id TEXT NOT NULL REFERENCES questions(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, question_id)
);

CREATE TABLE IF NOT EXISTS difficulty_overrides (
    user_id TEXT NOT NULL REFERENCES users(id),
    competency_slug TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, competency_slug)
);

CREATE TABLE IF NOT EXISTS competency_levels (
    user_id TEXT NOT NULL REFERENCES users(id),
    competency_slug TEXT NOT NULL,
    estimated_level INTEGER NOT NULL DEFAULT 1,
    elo_rating REAL NOT NULL DEFAULT 1000.0,
    consecutive_high INTEGER NOT NULL DEFAULT 0,
    consecutive_low INTEGER NOT NULL DEFAULT 0,
    total_attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, competency_slug)
);

CREATE TABLE IF NOT EXISTS format_performance (
    user_id TEXT NOT NULL REFERENCES users(id),
    competency_slug TEXT NOT NULL,
    format TEXT NOT NULL,
    avg_score REAL NOT NULL DEFAULT 0.0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, competency_slug, format)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_questions_user ON questions(user_id);
CREATE INDEX IF NOT EXISTS idx_questions_competency ON questions(user_id, competency_slug);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
"""


def get_db() -> sqlite3.Connection:
    """Open (or create) the WhatsApp bot database and ensure schema exists."""
    db_path = get_whatsapp_config().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


# --- Users ---


def get_or_create_user(phone_number: str, display_name: str | None = None) -> str:
    """Get or create a WhatsApp user. Returns user_id (phone_number string).

    Phone numbers are already strings (e.g. "whatsapp:+1234567890"),
    used directly as user_id without conversion.
    """
    user_id = phone_number
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (id, username, first_name) VALUES (?, ?, ?)",
            (user_id, None, display_name),
        )
        conn.commit()
    elif display_name:
        # Update display_name if changed
        conn.execute(
            "UPDATE users SET first_name = COALESCE(?, first_name) WHERE id = ?",
            (display_name, user_id),
        )
        conn.commit()
    conn.close()
    return user_id


# --- User-Scoped Preferences ---


def save_user_preferences(
    user_id: str,
    roles: list[str],
    languages: list[str],
    frameworks: list[str],
    difficulty: int = 3,
    preferred_formats: list[str] | None = None,
    question_length: str = "standard",
) -> None:
    """Insert or update user preferences."""
    conn = get_db()
    conn.execute(
        """INSERT INTO preferences (user_id, role, languages, frameworks, difficulty, preferred_formats,
                                    question_length)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               role = excluded.role,
               languages = excluded.languages,
               frameworks = excluded.frameworks,
               difficulty = excluded.difficulty,
               preferred_formats = excluded.preferred_formats,
               question_length = excluded.question_length,
               updated_at = datetime('now')""",
        (
            user_id,
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


def get_user_preferences(user_id: str) -> dict | None:
    """Get a user's preferences."""
    conn = get_db()
    row = conn.execute("SELECT * FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        return None

    raw_role = row["role"]
    try:
        roles = json.loads(raw_role)
        if isinstance(roles, str):
            roles = [roles]
    except json.JSONDecodeError:
        roles = [raw_role]

    raw_formats = row["preferred_formats"]
    preferred_formats = json.loads(raw_formats) if raw_formats else None
    question_length = row["question_length"] if "question_length" in row.keys() else "standard"

    return {
        "roles": roles,
        "languages": json.loads(row["languages"]),
        "frameworks": json.loads(row["frameworks"]),
        "difficulty": row["difficulty"],
        "preferred_formats": preferred_formats,
        "question_length": question_length or "standard",
    }


# --- User-Scoped Questions ---


def save_user_question(user_id: str, question_data: dict) -> str:
    """Save a generated question for a user. Returns question ID."""
    question_id = question_data.get("id", str(uuid4()))
    conn = get_db()
    conn.execute(
        """INSERT INTO questions (id, user_id, competency_slug, format, difficulty, title, body,
                                   code_snippet, language, options, correct_answer,
                                   grading_rubric, explanation, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            question_id,
            user_id,
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


def get_user_question(user_id: str, question_id: str) -> dict | None:
    """Get a question belonging to a user."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM questions WHERE id = ? AND user_id = ?",
        (question_id, user_id),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_question(row)


def get_user_queued_question(
    user_id: str,
    competency_slug: str | None = None,
    question_format: str | None = None,
    difficulty: int | None = None,
) -> dict | None:
    """Get an unanswered question for a user."""
    conn = get_db()
    query = """
        SELECT q.* FROM questions q
        LEFT JOIN attempts a ON a.question_id = q.id
        WHERE a.id IS NULL AND q.user_id = ?
    """
    params: list = [user_id]
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
    return _row_to_question(row) if row else None


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


# --- User-Scoped Attempts ---


def save_user_attempt(
    user_id: str,
    question_id: str,
    answer_text: str,
    score: float | None = None,
    max_score: int | None = None,
    total_score: float | None = None,
    grade_details: dict | None = None,
    feedback: str | None = None,
    time_seconds: float | None = None,
) -> str:
    """Save an attempt for a user. Returns attempt ID."""
    attempt_id = str(uuid4())
    conn = get_db()
    conn.execute(
        """INSERT INTO attempts (id, user_id, question_id, answer_text, score, max_score,
                                  total_score, grade_details, feedback, time_seconds, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            attempt_id,
            user_id,
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


def get_user_history(user_id: str, limit: int = 20) -> list[dict]:
    """Get recent attempts for a user."""
    conn = get_db()
    rows = conn.execute(
        """SELECT a.id, a.question_id, a.score, a.max_score, a.total_score,
                  a.feedback, a.time_seconds, a.completed_at,
                  q.title, q.competency_slug, q.format, q.difficulty
           FROM attempts a
           JOIN questions q ON a.question_id = q.id
           WHERE a.user_id = ?
           ORDER BY a.completed_at DESC LIMIT ?""",
        (user_id, limit),
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


def get_user_stats(user_id: str) -> list[dict]:
    """Get aggregate stats by competency for a user."""
    conn = get_db()
    rows = conn.execute(
        """SELECT q.competency_slug,
                  COUNT(*) as total_attempts,
                  AVG(a.score) as avg_score,
                  MIN(a.score) as min_score,
                  MAX(a.score) as max_score
           FROM attempts a
           JOIN questions q ON a.question_id = q.id
           WHERE a.user_id = ? AND a.score IS NOT NULL
           GROUP BY q.competency_slug
           ORDER BY avg_score DESC""",
        (user_id,),
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


# --- User-Scoped Bookmarks ---


def save_user_bookmark(user_id: str, question_id: str) -> None:
    """Bookmark a question for a user."""
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO bookmarks (user_id, question_id) VALUES (?, ?)",
        (user_id, question_id),
    )
    conn.commit()
    conn.close()


def remove_user_bookmark(user_id: str, question_id: str) -> None:
    """Remove a bookmark for a user."""
    conn = get_db()
    conn.execute(
        "DELETE FROM bookmarks WHERE user_id = ? AND question_id = ?",
        (user_id, question_id),
    )
    conn.commit()
    conn.close()


def get_user_bookmarks(user_id: str, limit: int = 50) -> list[dict]:
    """Get bookmarked questions for a user."""
    conn = get_db()
    rows = conn.execute(
        """SELECT b.created_at as bookmarked_at,
                  q.id, q.title, q.competency_slug, q.format, q.difficulty
           FROM bookmarks b
           JOIN questions q ON b.question_id = q.id
           WHERE b.user_id = ?
           ORDER BY b.created_at DESC LIMIT ?""",
        (user_id, limit),
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


# --- User-Scoped State ---


def set_user_state(user_id: str, key: str, value: str) -> None:
    """Set a state value for a user."""
    conn = get_db()
    conn.execute(
        """INSERT INTO state (user_id, key, value) VALUES (?, ?, ?)
           ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value""",
        (user_id, key, value),
    )
    conn.commit()
    conn.close()


def get_user_state(user_id: str, key: str) -> str | None:
    """Get a state value for a user."""
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM state WHERE user_id = ? AND key = ?",
        (user_id, key),
    ).fetchone()
    conn.close()
    return row["value"] if row else None


def delete_user_state(user_id: str, key: str) -> None:
    """Delete a state value for a user."""
    conn = get_db()
    conn.execute(
        "DELETE FROM state WHERE user_id = ? AND key = ?",
        (user_id, key),
    )
    conn.commit()
    conn.close()


def clear_user_conversation_state(user_id: str) -> None:
    """Clear all conversation state keys (conv:*) for a user."""
    conn = get_db()
    conn.execute(
        "DELETE FROM state WHERE user_id = ? AND key LIKE 'conv:%'",
        (user_id,),
    )
    conn.commit()
    conn.close()


# --- User-Scoped Competency Levels ---


def get_user_competency_levels(user_id: str) -> dict[str, dict]:
    """Get all competency levels for a user."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM competency_levels WHERE user_id = ?",
        (user_id,),
    ).fetchall()
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


def get_user_competency_level(user_id: str, competency_slug: str) -> dict | None:
    """Get the adaptive level data for a single competency."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM competency_levels WHERE user_id = ? AND competency_slug = ?",
        (user_id, competency_slug),
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


def update_user_competency_level(
    user_id: str,
    competency_slug: str,
    estimated_level: int,
    elo_rating: float,
    consecutive_high: int,
    consecutive_low: int,
    total_attempts: int,
) -> None:
    """Update competency level tracking for a user."""
    conn = get_db()
    conn.execute(
        """INSERT INTO competency_levels (user_id, competency_slug, estimated_level, elo_rating,
                                           consecutive_high, consecutive_low, total_attempts)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, competency_slug) DO UPDATE SET
               estimated_level = excluded.estimated_level,
               elo_rating = excluded.elo_rating,
               consecutive_high = excluded.consecutive_high,
               consecutive_low = excluded.consecutive_low,
               total_attempts = excluded.total_attempts,
               updated_at = datetime('now')""",
        (user_id, competency_slug, estimated_level, elo_rating, consecutive_high, consecutive_low, total_attempts),
    )
    conn.commit()
    conn.close()


# --- User-Scoped Format Performance ---


def update_user_format_performance(user_id: str, competency_slug: str, fmt: str, score: float) -> None:
    """Update running average for a user's competency+format pair."""
    conn = get_db()
    row = conn.execute(
        """SELECT avg_score, attempt_count FROM format_performance
           WHERE user_id = ? AND competency_slug = ? AND format = ?""",
        (user_id, competency_slug, fmt),
    ).fetchone()

    if row is None:
        conn.execute(
            """INSERT INTO format_performance
               (user_id, competency_slug, format, avg_score, attempt_count)
               VALUES (?, ?, ?, ?, 1)""",
            (user_id, competency_slug, fmt, score),
        )
    else:
        old_avg = row["avg_score"]
        old_count = row["attempt_count"]
        new_count = old_count + 1
        new_avg = old_avg + (score - old_avg) / new_count
        conn.execute(
            """UPDATE format_performance
               SET avg_score = ?, attempt_count = ?, updated_at = datetime('now')
               WHERE user_id = ? AND competency_slug = ? AND format = ?""",
            (new_avg, new_count, user_id, competency_slug, fmt),
        )

    conn.commit()
    conn.close()


def get_user_format_performance(user_id: str, competency_slug: str | None = None) -> list[dict]:
    """Get format performance data for a user, optionally filtered by competency."""
    conn = get_db()
    if competency_slug:
        rows = conn.execute(
            "SELECT * FROM format_performance WHERE user_id = ? AND competency_slug = ?",
            (user_id, competency_slug),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM format_performance WHERE user_id = ?",
            (user_id,),
        ).fetchall()
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


# --- User-Scoped Difficulty Overrides ---


def get_user_difficulty_override(user_id: str, competency_slug: str) -> int | None:
    """Get the difficulty override for a user's competency, or None if not set."""
    conn = get_db()
    row = conn.execute(
        "SELECT difficulty FROM difficulty_overrides WHERE user_id = ? AND competency_slug = ?",
        (user_id, competency_slug),
    ).fetchone()
    conn.close()
    return row["difficulty"] if row else None


# --- User-Scoped Performance Queries (for adaptive algorithm) ---


def get_user_competency_performance(user_id: str) -> list[dict]:
    """Get per-competency performance data for spaced repetition weighting."""
    conn = get_db()
    rows = conn.execute(
        """SELECT q.competency_slug,
                  AVG(a.score) as avg_score,
                  COUNT(*) as attempt_count,
                  MAX(a.completed_at) as last_attempt_date
           FROM attempts a
           JOIN questions q ON a.question_id = q.id
           WHERE a.user_id = ? AND a.score IS NOT NULL
           GROUP BY q.competency_slug""",
        (user_id,),
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


def get_user_competency_rolling_avg(user_id: str, competency_slug: str, n: int = 5) -> float | None:
    """Get the rolling average score for a user's last N attempts of a competency."""
    conn = get_db()
    row = conn.execute(
        """SELECT AVG(a.score) as avg_score
           FROM (
               SELECT a.score
               FROM attempts a
               JOIN questions q ON a.question_id = q.id
               WHERE q.competency_slug = ? AND a.user_id = ? AND a.score IS NOT NULL
               ORDER BY a.completed_at DESC
               LIMIT ?
           ) a""",
        (competency_slug, user_id, n),
    ).fetchone()
    conn.close()
    return row["avg_score"] if row and row["avg_score"] is not None else None


def get_user_recent_competency_slugs(user_id: str, n: int = 10) -> list[str]:
    """Get the N most recently attempted competency slugs for diversity."""
    conn = get_db()
    rows = conn.execute(
        """SELECT DISTINCT q.competency_slug
           FROM attempts a
           JOIN questions q ON a.question_id = q.id
           WHERE a.user_id = ?
           ORDER BY a.completed_at DESC
           LIMIT ?""",
        (user_id, n),
    ).fetchall()
    conn.close()
    return [row["competency_slug"] for row in rows]


def get_user_recent_question_topics(user_id: str, n: int = 20) -> list[str]:
    """Get topics from a user's N most recent questions to avoid repetition."""
    conn = get_db()
    rows = conn.execute(
        """SELECT q.metadata
           FROM questions q
           JOIN attempts a ON a.question_id = q.id
           WHERE a.user_id = ?
           ORDER BY a.completed_at DESC
           LIMIT ?""",
        (user_id, n),
    ).fetchall()
    conn.close()
    topics: list[str] = []
    for row in rows:
        if row["metadata"]:
            meta = json.loads(row["metadata"])
            if isinstance(meta, dict) and "topics" in meta:
                topics.extend(meta["topics"])
    return topics


# --- User-Scoped Streak ---


def update_user_streak(user_id: str) -> tuple[int, bool]:
    """Update the daily streak after an attempt. Returns (current_streak, is_new_day)."""
    today = date.today().isoformat()
    last_date = get_user_state(user_id, "last_attempt_date")
    streak_str = get_user_state(user_id, "current_streak")
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

    set_user_state(user_id, "current_streak", str(current_streak))
    set_user_state(user_id, "last_attempt_date", today)

    longest_str = get_user_state(user_id, "longest_streak")
    longest = int(longest_str) if longest_str else 0
    if current_streak > longest:
        set_user_state(user_id, "longest_streak", str(current_streak))

    return current_streak, True
