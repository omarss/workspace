"""Tests for the Telegram bot database layer."""

import os
import tempfile

import pytest

# Override DB path before importing db module
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SWET_TELEGRAM_BOT_TOKEN"] = "test-token"
os.environ["SWET_TELEGRAM_DB_PATH"] = _tmp.name
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from swet_telegram.db import (  # noqa: E402
    get_or_create_user,
    get_user_bookmarks,
    get_user_competency_level,
    get_user_competency_levels,
    get_user_competency_performance,
    get_user_competency_rolling_avg,
    get_user_difficulty_override,
    get_user_format_performance,
    get_user_history,
    get_user_preferences,
    get_user_queued_question,
    get_user_recent_competency_slugs,
    get_user_recent_question_topics,
    get_user_state,
    get_user_stats,
    remove_user_bookmark,
    save_user_attempt,
    save_user_bookmark,
    save_user_preferences,
    save_user_question,
    set_user_state,
    update_user_competency_level,
    update_user_format_performance,
    update_user_streak,
)


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean up test database after each test."""
    yield
    try:
        os.unlink(os.environ["SWET_TELEGRAM_DB_PATH"])
    except FileNotFoundError:
        pass
    _tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp2.close()
    os.environ["SWET_TELEGRAM_DB_PATH"] = _tmp2.name
    # Reset config cache
    import swet_telegram.config

    swet_telegram.config._config = None


# --- Users ---


def test_get_or_create_user_creates():
    user_id = get_or_create_user(chat_id=12345, username="testuser", first_name="Test")
    assert user_id == "12345"


def test_get_or_create_user_idempotent():
    uid1 = get_or_create_user(chat_id=12345, username="testuser")
    uid2 = get_or_create_user(chat_id=12345, username="updated")
    assert uid1 == uid2 == "12345"


# --- Preferences ---


def test_save_and_get_preferences():
    user_id = get_or_create_user(chat_id=1)
    save_user_preferences(
        user_id=user_id,
        roles=["backend_engineer"],
        languages=["Python", "Go"],
        frameworks=["Django"],
        difficulty=3,
        preferred_formats=["mcq", "debugging"],
        question_length="concise",
    )
    prefs = get_user_preferences(user_id)
    assert prefs is not None
    assert prefs["roles"] == ["backend_engineer"]
    assert prefs["languages"] == ["Python", "Go"]
    assert prefs["frameworks"] == ["Django"]
    assert prefs["difficulty"] == 3
    assert prefs["preferred_formats"] == ["mcq", "debugging"]
    assert prefs["question_length"] == "concise"


def test_get_preferences_none():
    user_id = get_or_create_user(chat_id=1)
    assert get_user_preferences(user_id) is None


def test_preferences_update():
    user_id = get_or_create_user(chat_id=1)
    save_user_preferences(user_id, ["backend_engineer"], ["Python"], [], 3)
    save_user_preferences(user_id, ["frontend_engineer"], ["TypeScript"], ["React"], 4)
    prefs = get_user_preferences(user_id)
    assert prefs["roles"] == ["frontend_engineer"]
    assert prefs["languages"] == ["TypeScript"]


# --- Questions ---


def _sample_question(slug="programming_fundamentals", fmt="mcq", diff=3):
    return {
        "competency_slug": slug,
        "format": fmt,
        "difficulty": diff,
        "title": "Test Question",
        "body": "What is 1+1?",
        "code_snippet": None,
        "language": None,
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "correct_answer": "B",
        "grading_rubric": None,
        "explanation": "1+1=2",
        "metadata": {"topics": ["arithmetic"]},
    }


def test_save_and_get_question():
    user_id = get_or_create_user(chat_id=1)
    q_id = save_user_question(user_id, _sample_question())
    from swet_telegram.db import get_user_question

    question = get_user_question(user_id, q_id)
    assert question is not None
    assert question["title"] == "Test Question"
    assert question["options"] == {"A": "1", "B": "2", "C": "3", "D": "4"}


def test_queued_question():
    user_id = get_or_create_user(chat_id=1)
    save_user_question(user_id, _sample_question())
    queued = get_user_queued_question(user_id, "programming_fundamentals", "mcq", 3)
    assert queued is not None
    assert queued["competency_slug"] == "programming_fundamentals"


def test_queued_question_answered():
    """Answered questions should not appear in queue."""
    user_id = get_or_create_user(chat_id=1)
    q_id = save_user_question(user_id, _sample_question())
    save_user_attempt(user_id, q_id, "B", score=1.0, max_score=1, total_score=1.0)
    queued = get_user_queued_question(user_id, "programming_fundamentals", "mcq", 3)
    assert queued is None


def test_user_isolation():
    """Questions from one user should not be visible to another."""
    user1 = get_or_create_user(chat_id=1)
    user2 = get_or_create_user(chat_id=2)
    save_user_question(user1, _sample_question())
    queued = get_user_queued_question(user2, "programming_fundamentals", "mcq", 3)
    assert queued is None


# --- Attempts ---


def test_save_and_get_history():
    user_id = get_or_create_user(chat_id=1)
    q_id = save_user_question(user_id, _sample_question())
    save_user_attempt(user_id, q_id, "B", score=1.0, max_score=1, total_score=1.0)
    history = get_user_history(user_id)
    assert len(history) == 1
    assert history[0]["score"] == 1.0


def test_stats():
    user_id = get_or_create_user(chat_id=1)
    q_id = save_user_question(user_id, _sample_question())
    save_user_attempt(user_id, q_id, "B", score=0.8, max_score=1, total_score=0.8)
    stats = get_user_stats(user_id)
    assert len(stats) == 1
    assert stats[0]["competency_slug"] == "programming_fundamentals"
    assert stats[0]["avg_score"] == 0.8


# --- Bookmarks ---


def test_bookmarks():
    user_id = get_or_create_user(chat_id=1)
    q_id = save_user_question(user_id, _sample_question())
    save_user_bookmark(user_id, q_id)
    bookmarks = get_user_bookmarks(user_id)
    assert len(bookmarks) == 1
    assert bookmarks[0]["id"] == q_id


def test_remove_bookmark():
    user_id = get_or_create_user(chat_id=1)
    q_id = save_user_question(user_id, _sample_question())
    save_user_bookmark(user_id, q_id)
    remove_user_bookmark(user_id, q_id)
    assert len(get_user_bookmarks(user_id)) == 0


# --- State ---


def test_state():
    user_id = get_or_create_user(chat_id=1)
    set_user_state(user_id, "test_key", "test_value")
    assert get_user_state(user_id, "test_key") == "test_value"
    assert get_user_state(user_id, "nonexistent") is None


# --- Competency Levels ---


def test_competency_levels():
    user_id = get_or_create_user(chat_id=1)
    update_user_competency_level(user_id, "programming_fundamentals", 3, 1200.0, 0, 0, 5)
    level = get_user_competency_level(user_id, "programming_fundamentals")
    assert level is not None
    assert level["estimated_level"] == 3
    assert level["elo_rating"] == 1200.0
    assert level["total_attempts"] == 5


def test_all_competency_levels():
    user_id = get_or_create_user(chat_id=1)
    update_user_competency_level(user_id, "programming_fundamentals", 3, 1200.0, 0, 0, 5)
    update_user_competency_level(user_id, "data_structures_and_algorithms", 2, 900.0, 0, 0, 3)
    levels = get_user_competency_levels(user_id)
    assert len(levels) == 2
    assert "programming_fundamentals" in levels
    assert "data_structures_and_algorithms" in levels


# --- Format Performance ---


def test_format_performance():
    user_id = get_or_create_user(chat_id=1)
    update_user_format_performance(user_id, "programming_fundamentals", "mcq", 0.8)
    update_user_format_performance(user_id, "programming_fundamentals", "mcq", 0.6)
    perf = get_user_format_performance(user_id, "programming_fundamentals")
    assert len(perf) == 1
    assert perf[0]["format"] == "mcq"
    assert perf[0]["attempt_count"] == 2
    # Running average: (0.8 + 0.6) / 2 = 0.7
    assert abs(perf[0]["avg_score"] - 0.7) < 0.01


# --- Performance Queries ---


def test_competency_performance():
    user_id = get_or_create_user(chat_id=1)
    q_id = save_user_question(user_id, _sample_question())
    save_user_attempt(user_id, q_id, "B", score=0.8, max_score=1, total_score=0.8)
    perf = get_user_competency_performance(user_id)
    assert len(perf) == 1
    assert perf[0]["avg_score"] == 0.8


def test_rolling_avg():
    user_id = get_or_create_user(chat_id=1)
    for score in [0.6, 0.7, 0.8]:
        q_id = save_user_question(user_id, _sample_question())
        save_user_attempt(user_id, q_id, "B", score=score, max_score=1, total_score=score)
    avg = get_user_competency_rolling_avg(user_id, "programming_fundamentals", n=3)
    assert avg is not None
    assert abs(avg - 0.7) < 0.01


def test_recent_competency_slugs():
    user_id = get_or_create_user(chat_id=1)
    for slug in ["programming_fundamentals", "data_structures_and_algorithms"]:
        q_id = save_user_question(user_id, _sample_question(slug=slug))
        save_user_attempt(user_id, q_id, "B", score=0.8)
    slugs = get_user_recent_competency_slugs(user_id, n=5)
    assert len(slugs) == 2


def test_recent_question_topics():
    user_id = get_or_create_user(chat_id=1)
    q_id = save_user_question(user_id, _sample_question())
    save_user_attempt(user_id, q_id, "B", score=0.8)
    topics = get_user_recent_question_topics(user_id, n=5)
    assert "arithmetic" in topics


# --- Streak ---


def test_streak_new_day():
    user_id = get_or_create_user(chat_id=1)
    count, is_new = update_user_streak(user_id)
    assert count == 1
    assert is_new is True


def test_streak_same_day():
    user_id = get_or_create_user(chat_id=1)
    update_user_streak(user_id)
    count, is_new = update_user_streak(user_id)
    assert count == 1
    assert is_new is False


# --- Difficulty Override ---


def test_difficulty_override_none():
    user_id = get_or_create_user(chat_id=1)
    assert get_user_difficulty_override(user_id, "programming_fundamentals") is None
