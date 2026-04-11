"""API database: user-scoped schema extending the CLI's schema with auth tables.

Manages its own SQLite database file separate from the CLI. All assessment
tables include a user_id column for multi-user isolation.
"""

import json
import sqlite3
from datetime import date
from uuid import uuid4

from swet_api.config import get_api_config

_SCHEMA = """
-- Authentication tables
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE,
    mobile TEXT UNIQUE,
    is_verified BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (email IS NOT NULL OR mobile IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT 0,
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

-- Assessments: calibration lifecycle (Bayesian posteriors serialized to JSON)
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'in_progress',
    competency_slugs TEXT NOT NULL,
    current_comp_idx INTEGER NOT NULL DEFAULT 0,
    current_q_idx INTEGER NOT NULL DEFAULT 0,
    questions_completed INTEGER NOT NULL DEFAULT 0,
    total_questions INTEGER NOT NULL,
    posteriors TEXT NOT NULL,
    results TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Sessions: workout/training session lifecycle
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'in_progress',
    target_count INTEGER NOT NULL,
    completed_count INTEGER NOT NULL DEFAULT 0,
    current_question_id TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Session results: individual question results within a session
CREATE TABLE IF NOT EXISTS session_results (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    question_id TEXT NOT NULL REFERENCES questions(id),
    attempt_id TEXT NOT NULL REFERENCES attempts(id),
    score REAL,
    time_seconds REAL,
    sequence_num INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Review queue: spaced repetition items
CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    question_id TEXT NOT NULL REFERENCES questions(id),
    source TEXT NOT NULL,
    due_date TEXT NOT NULL,
    interval_days INTEGER NOT NULL DEFAULT 1,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    review_count INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, question_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_otp_user ON otp_codes(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_questions_user ON questions(user_id);
CREATE INDEX IF NOT EXISTS idx_questions_competency ON questions(user_id, competency_slug);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
CREATE INDEX IF NOT EXISTS idx_attempts_completed ON attempts(user_id, completed_at);
CREATE INDEX IF NOT EXISTS idx_assessments_user ON assessments(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_session_results_session ON session_results(session_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_user_due ON review_queue(user_id, due_date);
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(user_id, status);
"""

_MIGRATIONS = [
    "ALTER TABLE attempts ADD COLUMN confidence INTEGER",
    "ALTER TABLE sessions ADD COLUMN competency_slug TEXT",
    "ALTER TABLE sessions ADD COLUMN question_format TEXT",
    "ALTER TABLE sessions ADD COLUMN difficulty INTEGER",
    "ALTER TABLE assessments ADD COLUMN assessment_phase TEXT DEFAULT 'concepts'",
    "ALTER TABLE assessments ADD COLUMN primary_language TEXT",
    "ALTER TABLE assessments ADD COLUMN questions_per_comp TEXT",
]


def get_db() -> sqlite3.Connection:
    """Open (or create) the API database and ensure schema exists."""
    db_path = get_api_config().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)

    # Run migrations (safe to re-run; each is idempotent or wrapped in try)
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column/table already exists

    return conn


# --- Users ---


def create_user(email: str | None = None, mobile: str | None = None) -> str:
    """Create a new user. Returns user ID."""
    user_id = str(uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO users (id, email, mobile) VALUES (?, ?, ?)",
        (user_id, email, mobile),
    )
    conn.commit()
    conn.close()
    return user_id


def get_user_by_email(email: str) -> dict | None:
    """Find a user by email."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_mobile(mobile: str) -> dict | None:
    """Find a user by mobile number."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE mobile = ?", (mobile,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    """Find a user by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_user_verified(user_id: str) -> None:
    """Mark a user as verified after OTP verification."""
    conn = get_db()
    conn.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


# --- OTP Codes ---


def save_otp(user_id: str, code_hash: str, expires_at: str) -> str:
    """Store a hashed OTP code. Returns OTP record ID."""
    otp_id = str(uuid4())
    conn = get_db()
    # Invalidate previous unused OTPs for this user
    conn.execute(
        "UPDATE otp_codes SET verified = 1 WHERE user_id = ? AND verified = 0",
        (user_id,),
    )
    conn.execute(
        "INSERT INTO otp_codes (id, user_id, code_hash, expires_at) VALUES (?, ?, ?, ?)",
        (otp_id, user_id, code_hash, expires_at),
    )
    conn.commit()
    conn.close()
    return otp_id


def get_latest_otp(user_id: str) -> dict | None:
    """Get the latest unverified OTP for a user."""
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM otp_codes
           WHERE user_id = ? AND verified = 0
           ORDER BY created_at DESC LIMIT 1""",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_otp_verified(otp_id: str) -> None:
    """Mark an OTP as verified."""
    conn = get_db()
    conn.execute("UPDATE otp_codes SET verified = 1 WHERE id = ?", (otp_id,))
    conn.commit()
    conn.close()


# --- Refresh Tokens ---


def save_refresh_token(user_id: str, token_hash: str, expires_at: str) -> str:
    """Store a hashed refresh token."""
    token_id = str(uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at) VALUES (?, ?, ?, ?)",
        (token_id, user_id, token_hash, expires_at),
    )
    conn.commit()
    conn.close()
    return token_id


def get_refresh_token(token_hash: str) -> dict | None:
    """Find a refresh token by its hash."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM refresh_tokens WHERE token_hash = ? AND revoked = 0",
        (token_hash,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def revoke_refresh_token(token_id: str) -> None:
    """Revoke a refresh token."""
    conn = get_db()
    conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE id = ?", (token_id,))
    conn.commit()
    conn.close()


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


def _build_question_metadata(question_data: dict) -> dict | None:
    """Build metadata dict, merging explanation_detail if present."""
    meta = question_data.get("metadata") or {}
    explanation_detail = question_data.get("explanation_detail")
    if explanation_detail:
        meta["explanation_detail"] = explanation_detail
    return meta if meta else None


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
            json.dumps(_build_question_metadata(question_data)),
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
    metadata = json.loads(row["metadata"]) if row["metadata"] else None
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
        "explanation_detail": metadata.pop("explanation_detail", None) if metadata else None,
        "metadata": metadata,
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
    confidence: int | None = None,
) -> str:
    """Save an attempt for a user. Returns attempt ID."""
    attempt_id = str(uuid4())
    conn = get_db()
    conn.execute(
        """INSERT INTO attempts (id, user_id, question_id, answer_text, score, max_score,
                                  total_score, grade_details, feedback, time_seconds, confidence,
                                  completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
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
            confidence,
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
            "normalized_score": row["score"],
            "feedback": row["feedback"],
            "time_seconds": row["time_seconds"],
            "completed_at": row["completed_at"],
            "created_at": row["completed_at"],
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


# --- Assessments ---


def create_assessment(
    user_id: str,
    competency_slugs: list[str],
    total_questions: int,
    posteriors_json: str,
    primary_language: str | None = None,
    questions_per_comp: dict[str, int] | None = None,
) -> str:
    """Create a new assessment. Returns assessment ID."""
    assessment_id = str(uuid4())
    conn = get_db()
    conn.execute(
        """INSERT INTO assessments (id, user_id, competency_slugs, total_questions, posteriors,
                                     primary_language, questions_per_comp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            assessment_id,
            user_id,
            json.dumps(competency_slugs),
            total_questions,
            posteriors_json,
            primary_language,
            json.dumps(questions_per_comp) if questions_per_comp else None,
        ),
    )
    conn.commit()
    conn.close()
    return assessment_id


def get_assessment(user_id: str, assessment_id: str) -> dict | None:
    """Get a specific assessment for a user."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM assessments WHERE id = ? AND user_id = ?",
        (assessment_id, user_id),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "competency_slugs": json.loads(row["competency_slugs"]),
        "current_comp_idx": row["current_comp_idx"],
        "current_q_idx": row["current_q_idx"],
        "questions_completed": row["questions_completed"],
        "total_questions": row["total_questions"],
        "posteriors": json.loads(row["posteriors"]),
        "results": json.loads(row["results"]) if row["results"] else None,
        "assessment_phase": row["assessment_phase"] if "assessment_phase" in row.keys() else "concepts",
        "primary_language": row["primary_language"] if "primary_language" in row.keys() else None,
        "questions_per_comp": json.loads(row["questions_per_comp"]) if row.get("questions_per_comp") else None,
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


def get_active_assessment(user_id: str) -> dict | None:
    """Get the user's in-progress assessment, if any."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM assessments WHERE user_id = ? AND status = 'in_progress' ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "competency_slugs": json.loads(row["competency_slugs"]),
        "current_comp_idx": row["current_comp_idx"],
        "current_q_idx": row["current_q_idx"],
        "questions_completed": row["questions_completed"],
        "total_questions": row["total_questions"],
        "posteriors": json.loads(row["posteriors"]),
        "results": json.loads(row["results"]) if row["results"] else None,
        "assessment_phase": row["assessment_phase"] if "assessment_phase" in row.keys() else "concepts",
        "primary_language": row["primary_language"] if "primary_language" in row.keys() else None,
        "questions_per_comp": json.loads(row["questions_per_comp"]) if row.get("questions_per_comp") else None,
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


def update_assessment_progress(
    assessment_id: str,
    comp_idx: int,
    q_idx: int,
    questions_completed: int,
    posteriors_json: str,
    assessment_phase: str | None = None,
) -> None:
    """Update assessment progress after answering a question."""
    conn = get_db()
    if assessment_phase:
        conn.execute(
            """UPDATE assessments
               SET current_comp_idx = ?, current_q_idx = ?,
                   questions_completed = ?, posteriors = ?, assessment_phase = ?
               WHERE id = ?""",
            (comp_idx, q_idx, questions_completed, posteriors_json, assessment_phase, assessment_id),
        )
    else:
        conn.execute(
            """UPDATE assessments
               SET current_comp_idx = ?, current_q_idx = ?,
                   questions_completed = ?, posteriors = ?
               WHERE id = ?""",
            (comp_idx, q_idx, questions_completed, posteriors_json, assessment_id),
        )
    conn.commit()
    conn.close()


def finalize_assessment(assessment_id: str, results_json: str) -> None:
    """Mark an assessment as completed with results."""
    conn = get_db()
    conn.execute(
        """UPDATE assessments
           SET status = 'completed', results = ?, completed_at = datetime('now')
           WHERE id = ?""",
        (results_json, assessment_id),
    )
    conn.commit()
    conn.close()


def cancel_assessment(assessment_id: str) -> None:
    """Cancel an in-progress assessment."""
    conn = get_db()
    conn.execute(
        "UPDATE assessments SET status = 'cancelled', completed_at = datetime('now') WHERE id = ?",
        (assessment_id,),
    )
    conn.commit()
    conn.close()


def has_completed_assessment(user_id: str) -> bool:
    """Check if a user has ever completed an assessment."""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM assessments WHERE user_id = ? AND status = 'completed' LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return row is not None


# --- Sessions ---


def create_session(
    user_id: str,
    target_count: int,
    competency_slug: str | None = None,
    question_format: str | None = None,
    difficulty: int | None = None,
) -> str:
    """Create a new training session. Returns session ID."""
    session_id = str(uuid4())
    conn = get_db()
    conn.execute(
        """INSERT INTO sessions (id, user_id, target_count, competency_slug,
                                  question_format, difficulty)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, user_id, target_count, competency_slug, question_format, difficulty),
    )
    conn.commit()
    conn.close()
    return session_id


def get_session(user_id: str, session_id: str) -> dict | None:
    """Get a specific session for a user."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_active_session(user_id: str) -> dict | None:
    """Get the user's in-progress session, if any."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? AND status = 'in_progress' ORDER BY started_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_session_progress(session_id: str, completed_count: int, current_question_id: str | None) -> None:
    """Update session progress."""
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET completed_count = ?, current_question_id = ? WHERE id = ?",
        (completed_count, current_question_id, session_id),
    )
    conn.commit()
    conn.close()


def complete_session(session_id: str) -> None:
    """Mark a session as completed."""
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET status = 'completed', completed_at = datetime('now') WHERE id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def add_session_result(
    session_id: str,
    question_id: str,
    attempt_id: str,
    score: float | None,
    time_seconds: float | None,
    sequence_num: int,
) -> str:
    """Add a question result to a session."""
    result_id = str(uuid4())
    conn = get_db()
    conn.execute(
        """INSERT INTO session_results (id, session_id, question_id, attempt_id, score, time_seconds, sequence_num)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (result_id, session_id, question_id, attempt_id, score, time_seconds, sequence_num),
    )
    conn.commit()
    conn.close()
    return result_id


def get_session_results(session_id: str) -> list[dict]:
    """Get all results for a session."""
    conn = get_db()
    rows = conn.execute(
        """SELECT sr.*, q.title, q.competency_slug, q.format
           FROM session_results sr
           JOIN questions q ON sr.question_id = q.id
           WHERE sr.session_id = ?
           ORDER BY sr.sequence_num""",
        (session_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "question_id": row["question_id"],
            "attempt_id": row["attempt_id"],
            "title": row["title"],
            "competency_slug": row["competency_slug"],
            "format": row["format"],
            "score": row["score"],
            "time_seconds": row["time_seconds"],
            "sequence_num": row["sequence_num"],
        }
        for row in rows
    ]


def get_session_history(user_id: str, limit: int = 20) -> list[dict]:
    """List past sessions for a user."""
    conn = get_db()
    rows = conn.execute(
        """SELECT s.*, COUNT(sr.id) as result_count,
                  AVG(sr.score) as avg_score
           FROM sessions s
           LEFT JOIN session_results sr ON sr.session_id = s.id
           WHERE s.user_id = ?
           GROUP BY s.id
           ORDER BY s.started_at DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [
        {
            "session_id": row["id"],
            "status": row["status"],
            "target_count": row["target_count"],
            "completed_count": row["completed_count"],
            "avg_score": row["avg_score"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }
        for row in rows
    ]


# --- Review Queue ---


def add_review_item(user_id: str, question_id: str, source: str, due_date: str) -> str:
    """Add a question to the review queue. Idempotent (upserts)."""
    review_id = str(uuid4())
    conn = get_db()
    conn.execute(
        """INSERT INTO review_queue (id, user_id, question_id, source, due_date)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, question_id) DO UPDATE SET
               due_date = CASE
                   WHEN excluded.due_date < review_queue.due_date THEN excluded.due_date
                   ELSE review_queue.due_date
               END,
               status = 'pending'""",
        (review_id, user_id, question_id, source, due_date),
    )
    conn.commit()
    conn.close()
    return review_id


def get_due_reviews(user_id: str, limit: int = 20) -> list[dict]:
    """Get review items due today or earlier."""
    today = date.today().isoformat()
    conn = get_db()
    rows = conn.execute(
        """SELECT rq.*, q.title, q.competency_slug, q.format, q.difficulty
           FROM review_queue rq
           JOIN questions q ON rq.question_id = q.id
           WHERE rq.user_id = ? AND rq.status = 'pending' AND rq.due_date <= ?
           ORDER BY rq.due_date ASC LIMIT ?""",
        (user_id, today, limit),
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
            "source": row["source"],
            "due_date": row["due_date"],
            "interval_days": row["interval_days"],
            "review_count": row["review_count"],
        }
        for row in rows
    ]


def get_review_counts(user_id: str) -> dict:
    """Get review queue counts: due today, due this week, total pending."""
    today = date.today()
    today_str = today.isoformat()
    week_end = date.fromordinal(today.toordinal() + 7).isoformat()
    conn = get_db()
    row = conn.execute(
        """SELECT
               SUM(CASE WHEN due_date <= ? THEN 1 ELSE 0 END) as due_today,
               SUM(CASE WHEN due_date <= ? THEN 1 ELSE 0 END) as due_this_week,
               COUNT(*) as total_pending
           FROM review_queue
           WHERE user_id = ? AND status = 'pending'""",
        (today_str, week_end, user_id),
    ).fetchone()
    conn.close()
    return {
        "due_today": row["due_today"] or 0,
        "due_this_week": row["due_this_week"] or 0,
        "total_pending": row["total_pending"] or 0,
    }


def get_review_item(user_id: str, review_id: str) -> dict | None:
    """Get a specific review item."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM review_queue WHERE id = ? AND user_id = ?",
        (review_id, user_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_review_item_with_question(user_id: str, review_id: str) -> dict | None:
    """Get a review item with its associated question data."""
    conn = get_db()
    row = conn.execute(
        """SELECT rq.*, q.title, q.competency_slug, q.format, q.difficulty
           FROM review_queue rq
           JOIN questions q ON rq.question_id = q.id
           WHERE rq.id = ? AND rq.user_id = ?""",
        (review_id, user_id),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "question_id": row["question_id"],
        "title": row["title"],
        "competency_slug": row["competency_slug"],
        "format": row["format"],
        "difficulty": row["difficulty"],
        "source": row["source"],
        "due_date": row["due_date"],
        "interval_days": row["interval_days"],
        "review_count": row["review_count"],
    }


def update_review_item(
    review_id: str,
    due_date: str,
    interval_days: int,
    ease_factor: float,
    review_count: int,
    status: str = "pending",
) -> None:
    """Update a review item after completion or snooze."""
    conn = get_db()
    conn.execute(
        """UPDATE review_queue
           SET due_date = ?, interval_days = ?, ease_factor = ?,
               review_count = ?, status = ?, last_reviewed_at = datetime('now')
           WHERE id = ?""",
        (due_date, interval_days, ease_factor, review_count, status, review_id),
    )
    conn.commit()
    conn.close()


def dismiss_review_item(review_id: str) -> None:
    """Dismiss a review item."""
    conn = get_db()
    conn.execute("UPDATE review_queue SET status = 'dismissed' WHERE id = ?", (review_id,))
    conn.commit()
    conn.close()


def auto_enqueue_review(user_id: str, question_id: str, score: float) -> None:
    """Auto-add to review queue if score is low enough."""
    if score < 0.6:
        tomorrow = date.fromordinal(date.today().toordinal() + 1).isoformat()
        add_review_item(user_id, question_id, "incorrect", tomorrow)


# --- Enhanced Stats ---


def get_streak_calendar(user_id: str, year: int, month: int) -> list[int]:
    """Get days of the month that had attempts."""
    month_str = f"{year}-{month:02d}"
    conn = get_db()
    rows = conn.execute(
        """SELECT DISTINCT CAST(strftime('%d', completed_at) AS INTEGER) as day
           FROM attempts
           WHERE user_id = ? AND strftime('%Y-%m', completed_at) = ?""",
        (user_id, month_str),
    ).fetchall()
    conn.close()
    return [row["day"] for row in rows]


def get_format_performance_stats(user_id: str) -> list[dict]:
    """Get aggregate performance by format across all competencies."""
    conn = get_db()
    rows = conn.execute(
        """SELECT q.format,
                  COUNT(*) as total_attempts,
                  AVG(a.score) as avg_score
           FROM attempts a
           JOIN questions q ON a.question_id = q.id
           WHERE a.user_id = ? AND a.score IS NOT NULL
           GROUP BY q.format""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [
        {"format": row["format"], "total_attempts": row["total_attempts"], "avg_score": row["avg_score"]}
        for row in rows
    ]


def get_weak_areas(user_id: str, limit: int = 5) -> list[dict]:
    """Get the weakest competencies by average score."""
    conn = get_db()
    rows = conn.execute(
        """SELECT q.competency_slug,
                  AVG(a.score) as avg_score,
                  COUNT(*) as total_attempts
           FROM attempts a
           JOIN questions q ON a.question_id = q.id
           WHERE a.user_id = ? AND a.score IS NOT NULL
           GROUP BY q.competency_slug
           HAVING total_attempts >= 2
           ORDER BY avg_score ASC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [
        {
            "competency_slug": row["competency_slug"],
            "avg_score": row["avg_score"],
            "total_attempts": row["total_attempts"],
        }
        for row in rows
    ]


# --- Dashboard ---


def get_dashboard_data(user_id: str) -> dict:
    """Get aggregated data for the Today page."""
    streak_str = get_user_state(user_id, "current_streak")
    longest_str = get_user_state(user_id, "longest_streak")

    review_counts = get_review_counts(user_id)
    assessed = has_completed_assessment(user_id)

    # Focus competency: weakest area with at least 2 attempts
    weak = get_weak_areas(user_id, limit=1)
    focus_slug = weak[0]["competency_slug"] if weak else None

    # Total attempts and competencies assessed (single connection)
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) as total FROM attempts WHERE user_id = ?", (user_id,)).fetchone()
        total_attempts = row["total"] if row else 0

        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM competency_levels WHERE user_id = ?", (user_id,)
        ).fetchone()
        competencies_assessed = row["cnt"] if row else 0
    finally:
        conn.close()

    return {
        "streak": {
            "current_streak": int(streak_str) if streak_str else 0,
            "longest_streak": int(longest_str) if longest_str else 0,
        },
        "review_due_count": review_counts["due_today"],
        "has_completed_assessment": assessed,
        "focus_competency": focus_slug,
        "total_attempts": total_attempts,
        "competencies_assessed": competencies_assessed,
    }


def reset_user_levels(user_id: str) -> None:
    """Reset all competency levels and assessment data for a user."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM competency_levels WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM format_performance WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM assessments WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def clear_user_data(user_id: str) -> None:
    """Delete all training data for a user (keeps account and preferences)."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM review_queue WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM bookmarks WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM session_results WHERE session_id IN (SELECT id FROM sessions WHERE user_id = ?)", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM attempts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM questions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM competency_levels WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM format_performance WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM assessments WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM state WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
