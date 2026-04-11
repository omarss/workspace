"""Tests for the SQLite database layer."""

import os
import tempfile
from datetime import date, timedelta

import pytest

# Override DB path before importing db module (must happen before imports)
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SWET_CLI_DB_PATH"] = _tmp.name
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from swet_cli.db import (  # noqa: E402
    get_all_competency_levels,
    get_attempts_for_question,
    get_bookmarks,
    get_competency_level,
    get_competency_performance,
    get_competency_rolling_avg,
    get_difficulty_override,
    get_format_performance,
    get_history,
    get_preferences,
    get_recent_competency_slugs,
    get_recent_question_topics,
    get_state,
    get_stats,
    is_bookmarked,
    remove_bookmark,
    resolve_question_id,
    save_attempt,
    save_bookmark,
    save_preferences,
    save_question,
    set_difficulty_override,
    set_state,
    update_competency_level,
    update_format_performance,
    update_streak,
)


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean up test database after each test."""
    yield
    # Reset DB by removing and recreating
    try:
        os.unlink(os.environ["SWET_CLI_DB_PATH"])
    except FileNotFoundError:
        pass
    _tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp2.close()
    os.environ["SWET_CLI_DB_PATH"] = _tmp2.name
    # Reset config cache
    import swet_cli.config

    swet_cli.config._config = None


def test_preferences_roundtrip():
    """Save and retrieve preferences."""
    assert get_preferences() is None

    save_preferences(roles=["backend"], languages=["python", "go"], frameworks=["fastapi"], difficulty=3)

    prefs = get_preferences()
    assert prefs is not None
    assert prefs["roles"] == ["backend"]
    assert prefs["languages"] == ["python", "go"]
    assert prefs["frameworks"] == ["fastapi"]
    assert prefs["difficulty"] == 3
    assert prefs["question_length"] == "standard"  # default


def test_preferences_question_length():
    """Save and retrieve question length preference."""
    save_preferences(roles=["backend"], languages=["python"], frameworks=[], difficulty=3, question_length="concise")
    prefs = get_preferences()
    assert prefs["question_length"] == "concise"

    # Update to detailed
    save_preferences(roles=["backend"], languages=["python"], frameworks=[], difficulty=3, question_length="detailed")
    prefs = get_preferences()
    assert prefs["question_length"] == "detailed"


def test_preferences_multi_role():
    """Save and retrieve multiple roles."""
    save_preferences(roles=["backend", "devops"], languages=["python"], frameworks=[], difficulty=3)

    prefs = get_preferences()
    assert prefs["roles"] == ["backend", "devops"]


def test_preferences_update():
    """Update existing preferences."""
    save_preferences(roles=["backend"], languages=["python"], frameworks=[], difficulty=3)
    save_preferences(roles=["frontend"], languages=["typescript"], frameworks=["react"], difficulty=2)

    prefs = get_preferences()
    assert prefs["roles"] == ["frontend"]
    assert prefs["languages"] == ["typescript"]


def test_question_save_and_history():
    """Save a question and attempt, then check history."""
    q_data = {
        "competency_slug": "problem_solving",
        "format": "mcq",
        "difficulty": 3,
        "title": "Test Question",
        "body": "What is 2+2?",
        "options": {"A": "3", "B": "4", "C": "5", "D": "6"},
        "correct_answer": "B",
    }
    q_id = save_question(q_data)
    assert q_id

    save_attempt(
        question_id=q_id,
        answer_text="B",
        score=1.0,
        max_score=1,
        total_score=1,
        feedback="Correct!",
    )

    history = get_history(limit=10)
    assert len(history) == 1
    assert history[0]["title"] == "Test Question"
    assert history[0]["score"] == 1.0
    assert history[0]["question_id"] == q_id


def test_stats_empty():
    """Stats returns empty list when no attempts."""
    assert get_stats() == []


# --- State CRUD ---


def test_state_roundtrip():
    """Set and get a state value."""
    assert get_state("test_key") is None
    set_state("test_key", "test_value")
    assert get_state("test_key") == "test_value"


def test_state_update():
    """Update an existing state value."""
    set_state("key", "v1")
    set_state("key", "v2")
    assert get_state("key") == "v2"


# --- Streak ---


def test_streak_first_attempt():
    """First ever attempt starts streak at 1."""
    count, is_new_day = update_streak()
    assert count == 1
    assert is_new_day is True


def test_streak_same_day():
    """Second attempt same day does not change streak."""
    update_streak()
    count, is_new_day = update_streak()
    assert count == 1
    assert is_new_day is False


def test_streak_next_day():
    """Attempt the next day increments streak."""
    # Simulate yesterday's attempt
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    set_state("last_attempt_date", yesterday)
    set_state("current_streak", "3")

    count, is_new_day = update_streak()
    assert count == 4
    assert is_new_day is True


def test_streak_gap_resets():
    """Gap of more than 1 day resets streak."""
    old_date = (date.today() - timedelta(days=5)).isoformat()
    set_state("last_attempt_date", old_date)
    set_state("current_streak", "10")

    count, is_new_day = update_streak()
    assert count == 1
    assert is_new_day is True


def test_streak_tracks_longest():
    """Longest streak is tracked separately."""
    set_state("longest_streak", "5")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    set_state("last_attempt_date", yesterday)
    set_state("current_streak", "6")

    update_streak()
    assert get_state("longest_streak") == "7"


# --- Bookmarks ---


def test_bookmark_roundtrip():
    """Bookmark and retrieve a question."""
    q_id = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 2,
            "title": "Bookmark Test",
            "body": "Test body",
        }
    )

    assert not is_bookmarked(q_id)
    save_bookmark(q_id)
    assert is_bookmarked(q_id)

    bookmarks = get_bookmarks()
    assert len(bookmarks) == 1
    assert bookmarks[0]["id"] == q_id
    assert bookmarks[0]["title"] == "Bookmark Test"


def test_remove_bookmark():
    """Remove a bookmark."""
    q_id = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 2,
            "title": "Remove Test",
            "body": "Body",
        }
    )

    save_bookmark(q_id)
    assert is_bookmarked(q_id)
    remove_bookmark(q_id)
    assert not is_bookmarked(q_id)


# --- Difficulty Overrides ---


def test_difficulty_override_roundtrip():
    """Set and get difficulty override."""
    assert get_difficulty_override("testing") is None
    set_difficulty_override("testing", 4)
    assert get_difficulty_override("testing") == 4


def test_difficulty_override_update():
    """Update existing override."""
    set_difficulty_override("testing", 3)
    set_difficulty_override("testing", 5)
    assert get_difficulty_override("testing") == 5


# --- Attempt with time_seconds ---


def test_save_attempt_with_time():
    """Save an attempt with time tracking."""
    q_id = save_question(
        {
            "competency_slug": "debugging",
            "format": "short_answer",
            "difficulty": 3,
            "title": "Timed Test",
            "body": "Test body",
        }
    )

    save_attempt(
        question_id=q_id,
        answer_text="My answer",
        score=0.8,
        max_score=10,
        total_score=8,
        feedback="Good",
        time_seconds=45.7,
    )

    history = get_history(limit=1)
    assert len(history) == 1
    assert history[0]["time_seconds"] == pytest.approx(45.7)


# --- Resolve question ID ---


def test_resolve_question_id():
    """Resolve a partial question ID."""
    q_id = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 1,
            "title": "Resolve Test",
            "body": "Body",
        }
    )

    # Full ID should resolve
    assert resolve_question_id(q_id) == q_id
    # Prefix should resolve
    assert resolve_question_id(q_id[:8]) == q_id
    # Non-existent should return None
    assert resolve_question_id("nonexistent") is None


# --- Attempts for question ---


def test_get_attempts_for_question():
    """Get all attempts for a specific question."""
    q_id = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 2,
            "title": "Multi Attempt",
            "body": "Body",
        }
    )

    save_attempt(question_id=q_id, answer_text="A", score=0.0, max_score=1, total_score=0, feedback="Wrong")
    save_attempt(question_id=q_id, answer_text="B", score=1.0, max_score=1, total_score=1, feedback="Correct")

    attempts = get_attempts_for_question(q_id)
    assert len(attempts) == 2


# --- Performance queries ---


def test_competency_rolling_avg():
    """Rolling average of last N scores for a competency."""
    q_id = save_question(
        {
            "competency_slug": "debugging",
            "format": "mcq",
            "difficulty": 3,
            "title": "Avg Test",
            "body": "Body",
        }
    )

    for score in [0.6, 0.8, 1.0]:
        save_attempt(question_id=q_id, answer_text="X", score=score, max_score=1, total_score=score)

    avg = get_competency_rolling_avg("debugging", n=3)
    assert avg == pytest.approx(0.8)


def test_competency_rolling_avg_empty():
    """Rolling avg returns None when no data."""
    assert get_competency_rolling_avg("nonexistent") is None


def test_competency_performance():
    """Get per-competency performance summary."""
    q_id = save_question(
        {
            "competency_slug": "security",
            "format": "mcq",
            "difficulty": 2,
            "title": "Perf Test",
            "body": "Body",
        }
    )

    save_attempt(question_id=q_id, answer_text="A", score=0.5, max_score=1, total_score=0.5)

    perf = get_competency_performance()
    assert len(perf) == 1
    assert perf[0]["competency_slug"] == "security"
    assert perf[0]["avg_score"] == pytest.approx(0.5)
    assert perf[0]["attempt_count"] == 1


# --- Competency Level Tracking ---


def test_competency_level_roundtrip():
    """Save and retrieve per-competency level data."""
    assert get_competency_level("testing") is None

    update_competency_level(
        "testing",
        estimated_level=3,
        elo_rating=1200.0,
        consecutive_high=1,
        consecutive_low=0,
        total_attempts=10,
    )

    level = get_competency_level("testing")
    assert level is not None
    assert level["estimated_level"] == 3
    assert level["elo_rating"] == pytest.approx(1200.0)
    assert level["consecutive_high"] == 1
    assert level["consecutive_low"] == 0
    assert level["total_attempts"] == 10


def test_competency_level_update():
    """Updating a competency level overwrites previous values."""
    update_competency_level(
        "testing",
        estimated_level=2,
        elo_rating=900.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=5,
    )
    update_competency_level(
        "testing",
        estimated_level=4,
        elo_rating=1500.0,
        consecutive_high=2,
        consecutive_low=0,
        total_attempts=15,
    )

    level = get_competency_level("testing")
    assert level["estimated_level"] == 4
    assert level["elo_rating"] == pytest.approx(1500.0)
    assert level["total_attempts"] == 15


def test_get_all_competency_levels():
    """Retrieve all competency levels as a dict."""
    update_competency_level(
        "testing",
        estimated_level=3,
        elo_rating=1200.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=5,
    )
    update_competency_level(
        "security",
        estimated_level=2,
        elo_rating=900.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=3,
    )

    levels = get_all_competency_levels()
    assert len(levels) == 2
    assert "testing" in levels
    assert "security" in levels
    assert levels["testing"]["estimated_level"] == 3
    assert levels["security"]["estimated_level"] == 2


def test_get_all_competency_levels_empty():
    """Empty competency levels table returns empty dict."""
    assert get_all_competency_levels() == {}


# --- Format Performance Tracking ---


def test_format_performance_initial():
    """First score creates a new format performance record."""
    update_format_performance("testing", "mcq", 0.8)

    perf = get_format_performance("testing")
    assert len(perf) == 1
    assert perf[0]["format"] == "mcq"
    assert perf[0]["avg_score"] == pytest.approx(0.8)
    assert perf[0]["attempt_count"] == 1


def test_format_performance_running_average():
    """Running average updates incrementally."""
    update_format_performance("testing", "mcq", 0.8)
    update_format_performance("testing", "mcq", 0.6)

    perf = get_format_performance("testing")
    assert len(perf) == 1
    assert perf[0]["avg_score"] == pytest.approx(0.7)
    assert perf[0]["attempt_count"] == 2


def test_format_performance_multiple_formats():
    """Tracks different formats separately for the same competency."""
    update_format_performance("testing", "mcq", 0.9)
    update_format_performance("testing", "debugging", 0.4)
    update_format_performance("testing", "short_answer", 0.6)

    perf = get_format_performance("testing")
    assert len(perf) == 3

    perf_by_fmt = {p["format"]: p for p in perf}
    assert perf_by_fmt["mcq"]["avg_score"] == pytest.approx(0.9)
    assert perf_by_fmt["debugging"]["avg_score"] == pytest.approx(0.4)
    assert perf_by_fmt["short_answer"]["avg_score"] == pytest.approx(0.6)


def test_format_performance_multiple_competencies():
    """Tracks different competencies separately."""
    update_format_performance("testing", "mcq", 0.9)
    update_format_performance("security", "mcq", 0.3)

    perf_testing = get_format_performance("testing")
    perf_security = get_format_performance("security")
    assert len(perf_testing) == 1
    assert len(perf_security) == 1
    assert perf_testing[0]["avg_score"] == pytest.approx(0.9)
    assert perf_security[0]["avg_score"] == pytest.approx(0.3)


def test_format_performance_all():
    """Get all format performance without filtering."""
    update_format_performance("testing", "mcq", 0.9)
    update_format_performance("security", "mcq", 0.3)

    all_perf = get_format_performance()
    assert len(all_perf) == 2


def test_format_performance_running_average_many():
    """Running average stays accurate over many updates."""
    scores = [0.5, 0.7, 0.9, 0.3, 0.6, 0.8, 1.0, 0.4]
    for s in scores:
        update_format_performance("testing", "mcq", s)

    perf = get_format_performance("testing")
    expected_avg = sum(scores) / len(scores)
    assert perf[0]["avg_score"] == pytest.approx(expected_avg, abs=0.01)
    assert perf[0]["attempt_count"] == len(scores)


# --- Recent Competency Slugs ---


def test_recent_competency_slugs_empty():
    """No attempts returns empty list."""
    assert get_recent_competency_slugs() == []


def test_recent_competency_slugs_ordered():
    """Returns competency slugs in order of most recent attempt."""
    q1 = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 3,
            "title": "Q1",
            "body": "Body",
        }
    )
    save_attempt(question_id=q1, answer_text="A", score=0.5, max_score=1, total_score=0.5)

    q2 = save_question(
        {
            "competency_slug": "security",
            "format": "mcq",
            "difficulty": 3,
            "title": "Q2",
            "body": "Body",
        }
    )
    save_attempt(question_id=q2, answer_text="A", score=0.5, max_score=1, total_score=0.5)

    slugs = get_recent_competency_slugs(n=10)
    # Most recent first
    assert slugs[0] == "security"
    assert slugs[1] == "testing"


def test_recent_competency_slugs_distinct():
    """Returns distinct slugs even with multiple attempts on same competency."""
    q1 = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 3,
            "title": "Q1",
            "body": "Body",
        }
    )
    save_attempt(question_id=q1, answer_text="A", score=0.5, max_score=1, total_score=0.5)
    save_attempt(question_id=q1, answer_text="B", score=0.8, max_score=1, total_score=0.8)

    slugs = get_recent_competency_slugs(n=10)
    assert slugs == ["testing"]


def test_recent_competency_slugs_limited():
    """Respects the limit parameter."""
    for i, slug in enumerate(["testing", "security", "debugging"]):
        q = save_question(
            {
                "competency_slug": slug,
                "format": "mcq",
                "difficulty": 3,
                "title": f"Q{i}",
                "body": "Body",
            }
        )
        save_attempt(question_id=q, answer_text="A", score=0.5, max_score=1, total_score=0.5)

    slugs = get_recent_competency_slugs(n=2)
    assert len(slugs) == 2


# --- Recent Question Topics ---


def test_recent_question_topics_empty():
    """No attempts returns empty list."""
    assert get_recent_question_topics() == []


def test_recent_question_topics_extracts_from_metadata():
    """Extracts topics from question metadata."""
    q_id = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 3,
            "title": "Topic Q",
            "body": "Body",
            "metadata": {"topics": ["unit-testing", "mocking", "pytest"]},
        }
    )
    save_attempt(question_id=q_id, answer_text="A", score=0.5, max_score=1, total_score=0.5)

    topics = get_recent_question_topics(n=10)
    assert "unit-testing" in topics
    assert "mocking" in topics
    assert "pytest" in topics


def test_recent_question_topics_skips_no_metadata():
    """Questions without metadata don't crash the query."""
    q_id = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 3,
            "title": "No Meta",
            "body": "Body",
        }
    )
    save_attempt(question_id=q_id, answer_text="A", score=0.5, max_score=1, total_score=0.5)

    topics = get_recent_question_topics(n=10)
    assert topics == []


def test_recent_question_topics_aggregates_multiple():
    """Topics from multiple questions are aggregated."""
    q1 = save_question(
        {
            "competency_slug": "testing",
            "format": "mcq",
            "difficulty": 3,
            "title": "Q1",
            "body": "Body",
            "metadata": {"topics": ["jwt", "oauth"]},
        }
    )
    save_attempt(question_id=q1, answer_text="A", score=0.5, max_score=1, total_score=0.5)

    q2 = save_question(
        {
            "competency_slug": "security",
            "format": "mcq",
            "difficulty": 3,
            "title": "Q2",
            "body": "Body",
            "metadata": {"topics": ["xss", "csrf"]},
        }
    )
    save_attempt(question_id=q2, answer_text="A", score=0.5, max_score=1, total_score=0.5)

    topics = get_recent_question_topics(n=10)
    assert set(topics) == {"jwt", "oauth", "xss", "csrf"}
