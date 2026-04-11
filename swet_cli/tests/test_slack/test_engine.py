"""Tests for the Slack bot adaptive engine (user-scoped algorithm wrappers)."""

import os
import tempfile

import pytest

# Override DB path before importing
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SWET_SLACK_BOT_TOKEN"] = "test-token"
os.environ["SWET_SLACK_APP_TOKEN"] = "test-app-token"
os.environ["SWET_SLACK_DB_PATH"] = _tmp.name
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from swet_cli.data import COMPETENCY_SLUGS  # noqa: E402
from swet_slack.db import (  # noqa: E402
    get_or_create_user,
    get_user_competency_level,
    save_user_question,
    update_user_competency_level,
)
from swet_slack.engine import (  # noqa: E402
    adapt_difficulty,
    pick_competency,
    pick_format,
    should_generate_new,
    update_adaptive_level,
)


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean up test database after each test."""
    yield
    try:
        os.unlink(os.environ["SWET_SLACK_DB_PATH"])
    except FileNotFoundError:
        pass
    _tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp2.close()
    os.environ["SWET_SLACK_DB_PATH"] = _tmp2.name
    import swet_slack.config

    swet_slack.config._config = None


def _sample_question(slug="programming_fundamentals", fmt="mcq", diff=3):
    return {
        "competency_slug": slug,
        "format": fmt,
        "difficulty": diff,
        "title": "Test Question",
        "body": "What is 1+1?",
        "options": {"A": "1", "B": "2"},
        "correct_answer": "B",
        "explanation": "1+1=2",
        "metadata": {"topics": ["arithmetic"]},
    }


# --- pick_competency ---


def test_pick_competency_returns_valid():
    user_id = get_or_create_user("U001")
    comp = pick_competency(user_id, ["backend_engineer"], 3)
    assert comp.slug in COMPETENCY_SLUGS


def test_pick_competency_respects_roles():
    """Multiple calls should return diverse competencies (probabilistic)."""
    user_id = get_or_create_user("U001")
    slugs = set()
    for _ in range(30):
        comp = pick_competency(user_id, ["backend_engineer"], 3)
        slugs.add(comp.slug)
    # Should pick at least a few different competencies over 30 tries
    assert len(slugs) > 3


# --- pick_format ---


def test_pick_format_returns_valid():
    user_id = get_or_create_user("U001")
    fmt = pick_format(user_id, "programming_fundamentals", 3)
    assert fmt in ("mcq", "code_review", "debugging", "short_answer", "design_prompt")


def test_pick_format_respects_preferences():
    """Preferred formats should appear more often."""
    user_id = get_or_create_user("U001")
    mcq_count = 0
    for _ in range(50):
        fmt = pick_format(user_id, "programming_fundamentals", 3, preferred_formats=["mcq"])
        if fmt == "mcq":
            mcq_count += 1
    # MCQ should dominate when preferred (at least 60% of the time)
    assert mcq_count > 30


# --- adapt_difficulty ---


def test_adapt_difficulty_no_data():
    """With no data, should return base difficulty."""
    user_id = get_or_create_user("U001")
    diff = adapt_difficulty(user_id, "programming_fundamentals", 3)
    assert diff == 3


def test_adapt_difficulty_uses_elo_level():
    """When competency level exists, use the estimated level."""
    user_id = get_or_create_user("U001")
    update_user_competency_level(user_id, "programming_fundamentals", 4, 1400.0, 0, 0, 10)
    diff = adapt_difficulty(user_id, "programming_fundamentals", 3)
    assert diff == 4


# --- update_adaptive_level ---


def test_update_adaptive_level_initializes():
    """First attempt should initialize the competency level."""
    user_id = get_or_create_user("U001")
    new_level = update_adaptive_level(user_id, "programming_fundamentals", 0.8, 3)
    assert 1 <= new_level <= 5
    level_data = get_user_competency_level(user_id, "programming_fundamentals")
    assert level_data is not None
    assert level_data["total_attempts"] == 1


def test_update_adaptive_level_promotion():
    """Consecutive high scores should promote."""
    user_id = get_or_create_user("U001")
    update_user_competency_level(user_id, "programming_fundamentals", 3, 1200.0, 2, 0, 5)
    # Third consecutive high score should trigger promotion
    update_adaptive_level(user_id, "programming_fundamentals", 0.9, 3)
    level_data = get_user_competency_level(user_id, "programming_fundamentals")
    assert level_data["consecutive_high"] == 0  # reset after promotion
    assert level_data["total_attempts"] == 6


def test_update_adaptive_level_demotion():
    """Consecutive low scores should demote."""
    user_id = get_or_create_user("U001")
    update_user_competency_level(user_id, "programming_fundamentals", 3, 1200.0, 0, 2, 5)
    # Third consecutive low score should trigger demotion
    update_adaptive_level(user_id, "programming_fundamentals", 0.1, 3)
    level_data = get_user_competency_level(user_id, "programming_fundamentals")
    assert level_data["consecutive_low"] == 0  # reset after demotion


# --- should_generate_new ---


def test_should_generate_new_empty_queue():
    """Should return True when no queued questions exist."""
    user_id = get_or_create_user("U001")
    assert should_generate_new(user_id, "programming_fundamentals", "mcq", 3) is True


def test_should_generate_new_has_queued():
    """Should return False when matching queued question exists."""
    user_id = get_or_create_user("U001")
    save_user_question(user_id, _sample_question())
    assert should_generate_new(user_id, "programming_fundamentals", "mcq", 3) is False


def test_should_generate_new_level_mismatch():
    """Should regenerate when user's level changed."""
    user_id = get_or_create_user("U001")
    save_user_question(user_id, _sample_question(diff=3))
    # User is now at level 4
    update_user_competency_level(user_id, "programming_fundamentals", 4, 1400.0, 0, 0, 10)
    assert should_generate_new(user_id, "programming_fundamentals", "mcq", 3) is True
