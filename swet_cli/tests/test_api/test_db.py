"""Tests for the new user-scoped DB functions in swet_api.db."""

import os
import tempfile

# Override DB path before importing
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SWET_API_DB_PATH"] = _tmp.name
os.environ["SWET_API_JWT_SECRET"] = "db-test-secret-key-must-be-at-least-32-bytes"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest  # noqa: E402

from swet_api.db import (  # noqa: E402
    create_user,
    get_user_competency_level,
    get_user_competency_performance,
    get_user_competency_rolling_avg,
    get_user_difficulty_override,
    get_user_format_performance,
    get_user_recent_competency_slugs,
    get_user_recent_question_topics,
    save_user_attempt,
    save_user_question,
    update_user_competency_level,
    update_user_format_performance,
    update_user_streak,
)


@pytest.fixture(autouse=True)
def _cleanup():
    """Reset DB after each test."""
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
    return create_user(email="test@example.com")


def _insert_question(user_id: str, competency: str = "testing_and_quality_engineering") -> str:
    return save_user_question(
        user_id,
        {
            "competency_slug": competency,
            "format": "mcq",
            "difficulty": 3,
            "title": "Test question",
            "body": "Body",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "correct_answer": "A",
            "metadata": {"topics": ["unit-testing", "mocking"]},
        },
    )


class TestGetUserCompetencyLevel:
    def test_returns_none_for_unknown(self):
        uid = _make_user()
        assert get_user_competency_level(uid, "nonexistent") is None

    def test_returns_data_after_update(self):
        uid = _make_user()
        update_user_competency_level(uid, "testing_and_quality_engineering", 3, 1225.0, 1, 0, 5)
        data = get_user_competency_level(uid, "testing_and_quality_engineering")
        assert data is not None
        assert data["estimated_level"] == 3
        assert data["elo_rating"] == 1225.0
        assert data["consecutive_high"] == 1
        assert data["total_attempts"] == 5


class TestUpdateUserFormatPerformance:
    def test_first_entry(self):
        uid = _make_user()
        update_user_format_performance(uid, "testing_and_quality_engineering", "mcq", 0.8)
        perf = get_user_format_performance(uid, "testing_and_quality_engineering")
        assert len(perf) == 1
        assert perf[0]["format"] == "mcq"
        assert perf[0]["avg_score"] == pytest.approx(0.8)
        assert perf[0]["attempt_count"] == 1

    def test_running_average(self):
        uid = _make_user()
        update_user_format_performance(uid, "testing_and_quality_engineering", "mcq", 1.0)
        update_user_format_performance(uid, "testing_and_quality_engineering", "mcq", 0.0)
        perf = get_user_format_performance(uid, "testing_and_quality_engineering")
        assert perf[0]["avg_score"] == pytest.approx(0.5)
        assert perf[0]["attempt_count"] == 2

    def test_filter_by_competency(self):
        uid = _make_user()
        update_user_format_performance(uid, "comp_a", "mcq", 0.8)
        update_user_format_performance(uid, "comp_b", "mcq", 0.6)
        all_perf = get_user_format_performance(uid)
        assert len(all_perf) == 2
        filtered = get_user_format_performance(uid, "comp_a")
        assert len(filtered) == 1


class TestGetUserDifficultyOverride:
    def test_returns_none_when_not_set(self):
        uid = _make_user()
        assert get_user_difficulty_override(uid, "some_competency") is None


class TestGetUserCompetencyPerformance:
    def test_aggregates_attempts(self):
        uid = _make_user()
        qid = _insert_question(uid)
        save_user_attempt(uid, qid, "A", score=1.0, max_score=1, total_score=1)
        # Insert second question for same competency
        qid2 = _insert_question(uid)
        save_user_attempt(uid, qid2, "B", score=0.0, max_score=1, total_score=0)

        perf = get_user_competency_performance(uid)
        assert len(perf) == 1
        assert perf[0]["competency_slug"] == "testing_and_quality_engineering"
        assert perf[0]["attempt_count"] == 2
        assert perf[0]["avg_score"] == pytest.approx(0.5)
        assert perf[0]["last_attempt_date"] is not None


class TestGetUserCompetencyRollingAvg:
    def test_returns_none_with_no_data(self):
        uid = _make_user()
        assert get_user_competency_rolling_avg(uid, "testing_and_quality_engineering") is None

    def test_computes_rolling_average(self):
        uid = _make_user()
        for score in [1.0, 0.8, 0.6]:
            qid = _insert_question(uid)
            save_user_attempt(uid, qid, "A", score=score, max_score=1, total_score=int(score))
        avg = get_user_competency_rolling_avg(uid, "testing_and_quality_engineering", n=3)
        assert avg == pytest.approx(0.8)


class TestGetUserRecentCompetencySlugs:
    def test_returns_recent_slugs(self):
        uid = _make_user()
        qid1 = _insert_question(uid, "programming_fundamentals")
        save_user_attempt(uid, qid1, "A", score=1.0, max_score=1, total_score=1)
        qid2 = _insert_question(uid, "testing_and_quality_engineering")
        save_user_attempt(uid, qid2, "A", score=1.0, max_score=1, total_score=1)

        slugs = get_user_recent_competency_slugs(uid, n=5)
        assert len(slugs) == 2
        assert set(slugs) == {"programming_fundamentals", "testing_and_quality_engineering"}


class TestGetUserRecentQuestionTopics:
    def test_extracts_topics_from_metadata(self):
        uid = _make_user()
        qid = _insert_question(uid)
        save_user_attempt(uid, qid, "A", score=1.0, max_score=1, total_score=1)

        topics = get_user_recent_question_topics(uid, n=5)
        assert "unit-testing" in topics
        assert "mocking" in topics


class TestUpdateUserStreak:
    def test_first_day_starts_at_one(self):
        uid = _make_user()
        streak, is_new = update_user_streak(uid)
        assert streak == 1
        assert is_new is True

    def test_same_day_no_change(self):
        uid = _make_user()
        update_user_streak(uid)
        streak, is_new = update_user_streak(uid)
        assert streak == 1
        assert is_new is False
