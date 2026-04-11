"""Tests for the API adaptive engine (user-scoped algorithm wrappers)."""

import os
import tempfile

# Override DB path before importing
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SWET_API_DB_PATH"] = _tmp.name
os.environ["SWET_API_JWT_SECRET"] = "engine-test-secret-key-must-be-at-least-32-bytes"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest  # noqa: E402

from swet_api.db import (  # noqa: E402
    create_user,
    get_user_competency_level,
    save_user_question,
    update_user_competency_level,
)
from swet_api.engine import (  # noqa: E402
    adapt_difficulty,
    pick_competency,
    pick_format,
    should_generate_new,
    update_adaptive_level,
)
from swet_cli.data import COMPETENCY_SLUGS  # noqa: E402


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean up test database after each test."""
    yield
    try:
        os.unlink(os.environ["SWET_API_DB_PATH"])
    except FileNotFoundError:
        pass
    _tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp2.close()
    os.environ["SWET_API_DB_PATH"] = _tmp2.name
    import swet_api.config

    swet_api.config._config = None


def _make_user() -> str:
    return create_user(email="engine-test@example.com")


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
    uid = _make_user()
    comp = pick_competency(uid, ["backend_engineer"], 3)
    assert comp.slug in COMPETENCY_SLUGS


def test_pick_competency_respects_roles():
    """Multiple calls should return diverse competencies (probabilistic)."""
    uid = _make_user()
    slugs = set()
    for _ in range(30):
        comp = pick_competency(uid, ["backend_engineer"], 3)
        slugs.add(comp.slug)
    assert len(slugs) > 3


# --- pick_format ---


def test_pick_format_returns_valid():
    uid = _make_user()
    fmt = pick_format(uid, "programming_fundamentals", 3)
    assert fmt in ("mcq", "code_review", "debugging", "short_answer", "design_prompt")


def test_pick_format_respects_preferences():
    """Preferred formats should appear more often."""
    uid = _make_user()
    mcq_count = 0
    for _ in range(50):
        fmt = pick_format(uid, "programming_fundamentals", 3, preferred_formats=["mcq"])
        if fmt == "mcq":
            mcq_count += 1
    assert mcq_count > 30


# --- adapt_difficulty ---


def test_adapt_difficulty_no_data():
    """With no data, should return base difficulty."""
    uid = _make_user()
    diff = adapt_difficulty(uid, "programming_fundamentals", 3)
    assert diff == 3


def test_adapt_difficulty_uses_elo_level():
    """When competency level exists, use the estimated level."""
    uid = _make_user()
    update_user_competency_level(uid, "programming_fundamentals", 4, 1400.0, 0, 0, 10)
    diff = adapt_difficulty(uid, "programming_fundamentals", 3)
    assert diff == 4


# --- update_adaptive_level ---


def test_update_adaptive_level_initializes():
    """First attempt should initialize the competency level."""
    uid = _make_user()
    new_level = update_adaptive_level(uid, "programming_fundamentals", 0.8, 3)
    assert 1 <= new_level <= 5
    level_data = get_user_competency_level(uid, "programming_fundamentals")
    assert level_data is not None
    assert level_data["total_attempts"] == 1


def test_update_adaptive_level_promotion():
    """Consecutive high scores should promote."""
    uid = _make_user()
    update_user_competency_level(uid, "programming_fundamentals", 3, 1200.0, 2, 0, 5)
    update_adaptive_level(uid, "programming_fundamentals", 0.9, 3)
    level_data = get_user_competency_level(uid, "programming_fundamentals")
    assert level_data["consecutive_high"] == 0  # reset after promotion
    assert level_data["total_attempts"] == 6


def test_update_adaptive_level_demotion():
    """Consecutive low scores should demote."""
    uid = _make_user()
    update_user_competency_level(uid, "programming_fundamentals", 3, 1200.0, 0, 2, 5)
    update_adaptive_level(uid, "programming_fundamentals", 0.1, 3)
    level_data = get_user_competency_level(uid, "programming_fundamentals")
    assert level_data["consecutive_low"] == 0  # reset after demotion


# --- should_generate_new ---


def test_should_generate_new_empty_queue():
    """Should return True when no queued questions exist."""
    uid = _make_user()
    assert should_generate_new(uid, "programming_fundamentals", "mcq", 3) is True


def test_should_generate_new_has_queued():
    """Should return False when matching queued question exists."""
    uid = _make_user()
    save_user_question(uid, _sample_question())
    assert should_generate_new(uid, "programming_fundamentals", "mcq", 3) is False


def test_should_generate_new_level_mismatch():
    """Should regenerate when user's level changed."""
    uid = _make_user()
    save_user_question(uid, _sample_question(diff=3))
    update_user_competency_level(uid, "programming_fundamentals", 4, 1400.0, 0, 0, 10)
    assert should_generate_new(uid, "programming_fundamentals", "mcq", 3) is True
