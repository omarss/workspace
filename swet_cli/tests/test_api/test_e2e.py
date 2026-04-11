"""End-to-end API tests exercising complete user journeys.

Each test simulates a real user flow: register → verify → set preferences →
get questions → answer → check stats. No mocking — uses the real DB and
inserts questions directly (skipping LLM calls).
"""

import os
import tempfile
from datetime import UTC, datetime, timedelta

# Override DB paths before importing
_tmp_api = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_api.close()
os.environ["SWET_API_DB_PATH"] = _tmp_api.name
os.environ["SWET_API_JWT_SECRET"] = "e2e-test-secret-key-must-be-at-least-32-bytes"
os.environ["SWET_API_OTP_PROVIDER"] = "console"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from swet_api.app import app  # noqa: E402
from swet_api.auth.otp import generate_otp, hash_otp  # noqa: E402
from swet_api.db import (  # noqa: E402
    add_review_item,
    get_user_by_email,
    get_user_competency_level,
    save_otp,
    save_user_question,
)

import swet_api.config  # noqa: E402

# Reset cached config so test env vars take effect
swet_api.config._config = None

client = TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup():
    """Reset API DB after each test."""
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


# --- Helpers ---


def _register_and_login(email: str) -> str:
    """Register a user, generate an OTP, verify it, and return the access token."""
    client.post("/auth/register", json={"email": email})
    user = get_user_by_email(email)
    code = generate_otp()
    expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    save_otp(user["id"], hash_otp(code), expires)
    resp = client.post("/auth/otp/verify", json={"email": email, "code": code})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth_header(token: str) -> dict:
    """Build the Authorization header."""
    return {"Authorization": f"Bearer {token}"}


def _set_preferences(token: str) -> dict:
    """Set default preferences and return the response."""
    resp = client.put(
        "/preferences",
        json={
            "roles": ["backend_engineer"],
            "languages": ["Python", "Go"],
            "frameworks": ["FastAPI", "PostgreSQL"],
            "preferred_formats": ["mcq", "debugging"],
        },
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    return resp.json()


def _insert_mcq_question(user_id: str, competency: str = "programming_fundamentals") -> str:
    """Insert an MCQ question directly into the DB. Returns question ID."""
    return save_user_question(
        user_id,
        {
            "competency_slug": competency,
            "format": "mcq",
            "difficulty": 3,
            "title": "What is the time complexity of binary search?",
            "body": "Given a sorted array, what is the time complexity of binary search?",
            "options": {
                "A": "O(n)",
                "B": "O(log n)",
                "C": "O(n log n)",
                "D": "O(1)",
            },
            "correct_answer": "B",
            "explanation": "Binary search halves the search space each step, giving O(log n).",
            "metadata": {"topics": ["algorithms", "binary-search"], "estimated_time_minutes": 2},
        },
    )


def _insert_code_review_question(user_id: str) -> str:
    """Insert a code review question directly into the DB. Returns question ID."""
    return save_user_question(
        user_id,
        {
            "competency_slug": "clean_code_and_maintainability",
            "format": "code_review",
            "difficulty": 3,
            "title": "Review this Python function",
            "body": "Review the following function and identify issues.",
            "code_snippet": "def calc(x,y,z):\n  return x+y*z",
            "language": "python",
            "correct_answer": None,
            "grading_rubric": {
                "criteria": [
                    {"name": "Issue ID", "description": "Find issues", "max_points": 5, "key_indicators": []},
                    {"name": "Fix Quality", "description": "Suggest fixes", "max_points": 5, "key_indicators": []},
                ],
                "max_score": 10,
                "passing_threshold": 6,
            },
            "explanation": "Function lacks descriptive naming, parentheses for precedence, type hints.",
            "metadata": {"topics": ["clean-code", "naming"], "estimated_time_minutes": 5},
        },
    )


# =========================================================================
# E2E Journey 1: New user complete onboarding flow
# =========================================================================


class TestNewUserOnboarding:
    """Full journey: register → verify → set preferences → view competencies."""

    def test_register_verify_and_set_preferences(self):
        """New user registers, verifies OTP, and configures preferences."""
        # Step 1: Register
        resp = client.post("/auth/register", json={"email": "newuser@test.com"})
        assert resp.status_code == 201

        # Step 2: Get token
        token = _register_and_login("newuser2@test.com")
        assert token

        # Step 3: No preferences yet
        resp = client.get("/preferences", headers=_auth_header(token))
        assert resp.status_code == 404

        # Step 4: Set preferences
        prefs = _set_preferences(token)
        assert prefs["roles"] == ["backend_engineer"]
        assert prefs["languages"] == ["Python", "Go"]
        assert prefs["preferred_formats"] == ["mcq", "debugging"]
        assert prefs["difficulty"] == 3  # default
        assert prefs["question_length"] == "standard"  # default

        # Step 5: Read back preferences
        resp = client.get("/preferences", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["roles"] == ["backend_engineer"]

    def test_update_preferences(self):
        """User can update preferences at any time."""
        token = _register_and_login("update@test.com")
        _set_preferences(token)

        # Update roles, formats, and question length
        resp = client.put(
            "/preferences",
            json={
                "roles": ["backend_engineer", "ai_engineer"],
                "languages": ["Python", "TypeScript"],
                "frameworks": ["FastAPI", "LangChain"],
                "preferred_formats": ["mcq"],
                "question_length": "concise",
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ai_engineer" in data["roles"]
        assert data["preferred_formats"] == ["mcq"]
        assert data["question_length"] == "concise"

    def test_invalid_question_length_rejected(self):
        """Setting an invalid question_length returns 400."""
        token = _register_and_login("badlength@test.com")
        resp = client.put(
            "/preferences",
            json={
                "roles": ["backend_engineer"],
                "languages": [],
                "frameworks": [],
                "question_length": "verbose",
            },
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert "Invalid question_length" in resp.json()["detail"]

    def test_invalid_role_rejected(self):
        """Setting an invalid role returns 400."""
        token = _register_and_login("badrole@test.com")
        resp = client.put(
            "/preferences",
            json={"roles": ["nonexistent_role"], "languages": [], "frameworks": []},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400
        assert "Invalid role" in resp.json()["detail"]

    def test_empty_roles_rejected(self):
        """Setting empty roles returns 400."""
        token = _register_and_login("norole@test.com")
        resp = client.put(
            "/preferences",
            json={"roles": [], "languages": [], "frameworks": []},
            headers=_auth_header(token),
        )
        assert resp.status_code == 400

    def test_view_competencies(self):
        """User can view all competencies and their levels."""
        token = _register_and_login("comps@test.com")
        resp = client.get("/stats/competencies", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 29  # all competencies
        # None assessed yet
        assert all(c["estimated_level"] is None for c in data)
        assert all(c["total_attempts"] == 0 for c in data)


# =========================================================================
# E2E Journey 2: Practice session — get questions, answer, check results
# =========================================================================


class TestPracticeSession:
    """Full journey: set preferences → get question → answer → check stats."""

    def test_answer_mcq_correctly(self):
        """User answers an MCQ question correctly and gets graded."""
        token = _register_and_login("mcq@test.com")
        _set_preferences(token)

        user = get_user_by_email("mcq@test.com")
        q_id = _insert_mcq_question(user["id"])

        # Get the question
        resp = client.get(f"/questions/{q_id}", headers=_auth_header(token))
        assert resp.status_code == 200
        question = resp.json()
        assert question["format"] == "mcq"
        assert question["options"] is not None
        # correct_answer should NOT be exposed
        assert "correct_answer" not in question or question.get("correct_answer") is None

        # Submit correct answer
        resp = client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 201
        grade = resp.json()
        assert grade["normalized_score"] == 1.0
        assert grade["correct_answer"] == "B"
        assert grade["overall_feedback"]
        assert grade["attempt_id"]

    def test_answer_mcq_incorrectly(self):
        """User answers an MCQ incorrectly and gets feedback."""
        token = _register_and_login("wrong@test.com")
        _set_preferences(token)

        user = get_user_by_email("wrong@test.com")
        q_id = _insert_mcq_question(user["id"])

        resp = client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "A"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 201
        grade = resp.json()
        assert grade["normalized_score"] == 0.0
        assert grade["correct_answer"] == "B"

    def test_answer_with_time_tracking(self):
        """User submits answer with time tracking."""
        token = _register_and_login("timed@test.com")
        _set_preferences(token)

        user = get_user_by_email("timed@test.com")
        q_id = _insert_mcq_question(user["id"])

        resp = client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B", "time_seconds": 42.5},
            headers=_auth_header(token),
        )
        assert resp.status_code == 201

        # Verify time is recorded in history
        resp = client.get("/attempts/history", headers=_auth_header(token))
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 1
        assert history[0]["time_seconds"] == pytest.approx(42.5)

    def test_answer_nonexistent_question(self):
        """Answering a question that doesn't exist returns 404."""
        token = _register_and_login("noq@test.com")
        resp = client.post(
            "/attempts",
            json={"question_id": "nonexistent-id", "answer_text": "A"},
            headers=_auth_header(token),
        )
        assert resp.status_code == 404

    def test_get_next_queued_question(self):
        """User gets the next unanswered question from the queue."""
        token = _register_and_login("queue@test.com")
        _set_preferences(token)

        user = get_user_by_email("queue@test.com")
        q_id1 = _insert_mcq_question(user["id"], "programming_fundamentals")
        _insert_mcq_question(user["id"], "security_engineering")

        # Get next question (should be the first one inserted)
        resp = client.get("/questions/next", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == q_id1

        # Answer it
        client.post(
            "/attempts",
            json={"question_id": q_id1, "answer_text": "B"},
            headers=_auth_header(token),
        )

        # Next question should be the second one
        resp = client.get("/questions/next", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["competency_slug"] == "security_engineering"

    def test_no_queued_questions(self):
        """Getting next question when queue is empty returns null."""
        token = _register_and_login("empty@test.com")
        resp = client.get("/questions/next", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json() is None

    def test_filter_queued_by_competency(self):
        """User can filter queued questions by competency slug."""
        token = _register_and_login("filter@test.com")
        _set_preferences(token)

        user = get_user_by_email("filter@test.com")
        _insert_mcq_question(user["id"], "programming_fundamentals")
        q_id2 = _insert_mcq_question(user["id"], "security_engineering")

        # Filter by security
        resp = client.get(
            "/questions/next?competency=security_engineering",
            headers=_auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == q_id2


# =========================================================================
# E2E Journey 3: Stats and history tracking
# =========================================================================


class TestStatsAndHistory:
    """Full journey: answer multiple questions → check stats/history/streak."""

    def test_history_records_attempts(self):
        """Attempt history shows all graded answers."""
        token = _register_and_login("hist@test.com")
        _set_preferences(token)

        user = get_user_by_email("hist@test.com")
        q1 = _insert_mcq_question(user["id"], "programming_fundamentals")
        q2 = _insert_mcq_question(user["id"], "security_engineering")

        # Answer both
        client.post("/attempts", json={"question_id": q1, "answer_text": "B"}, headers=_auth_header(token))
        client.post("/attempts", json={"question_id": q2, "answer_text": "A"}, headers=_auth_header(token))

        resp = client.get("/attempts/history", headers=_auth_header(token))
        assert resp.status_code == 200
        history = resp.json()
        assert len(history) == 2
        slugs = {h["competency_slug"] for h in history}
        assert "programming_fundamentals" in slugs
        assert "security_engineering" in slugs

    def test_history_respects_limit(self):
        """History limit parameter works."""
        token = _register_and_login("limit@test.com")
        _set_preferences(token)

        user = get_user_by_email("limit@test.com")
        for i in range(5):
            q_id = _insert_mcq_question(user["id"])
            client.post("/attempts", json={"question_id": q_id, "answer_text": "B"}, headers=_auth_header(token))

        resp = client.get("/attempts/history?limit=3", headers=_auth_header(token))
        assert len(resp.json()) == 3

    def test_stats_aggregate_by_competency(self):
        """Stats show per-competency aggregates after answering questions."""
        token = _register_and_login("stats@test.com")
        _set_preferences(token)

        user = get_user_by_email("stats@test.com")

        # Answer 2 programming questions (1 correct, 1 wrong)
        q1 = _insert_mcq_question(user["id"], "programming_fundamentals")
        q2 = _insert_mcq_question(user["id"], "programming_fundamentals")
        client.post("/attempts", json={"question_id": q1, "answer_text": "B"}, headers=_auth_header(token))
        client.post("/attempts", json={"question_id": q2, "answer_text": "A"}, headers=_auth_header(token))

        resp = client.get("/stats", headers=_auth_header(token))
        assert resp.status_code == 200
        stats = resp.json()
        assert len(stats) == 1
        assert stats[0]["competency_slug"] == "programming_fundamentals"
        assert stats[0]["total_attempts"] == 2
        assert stats[0]["avg_score"] == pytest.approx(0.5)
        assert stats[0]["max_score"] == 1.0
        assert stats[0]["min_score"] == 0.0

    def test_stats_empty_before_attempts(self):
        """Stats returns empty list when no attempts exist."""
        token = _register_and_login("nostats@test.com")
        resp = client.get("/stats", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_streak_starts_at_zero(self):
        """Streak is 0 before any attempts."""
        token = _register_and_login("streak@test.com")
        resp = client.get("/stats/streak", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_streak"] == 0
        assert data["longest_streak"] == 0


# =========================================================================
# E2E Journey 4: Bookmarks lifecycle
# =========================================================================


class TestBookmarksLifecycle:
    """Full journey: bookmark questions → list → remove."""

    def test_bookmark_lifecycle(self):
        """User bookmarks a question, lists bookmarks, then removes it."""
        token = _register_and_login("bmark@test.com")
        _set_preferences(token)

        user = get_user_by_email("bmark@test.com")
        q_id = _insert_mcq_question(user["id"])

        # No bookmarks initially
        resp = client.get("/bookmarks", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json() == []

        # Bookmark the question
        resp = client.post(f"/bookmarks/{q_id}", headers=_auth_header(token))
        assert resp.status_code == 201

        # List bookmarks
        resp = client.get("/bookmarks", headers=_auth_header(token))
        assert resp.status_code == 200
        bookmarks = resp.json()
        assert len(bookmarks) == 1
        assert bookmarks[0]["id"] == q_id
        assert bookmarks[0]["title"] == "What is the time complexity of binary search?"

        # Remove bookmark
        resp = client.delete(f"/bookmarks/{q_id}", headers=_auth_header(token))
        assert resp.status_code == 204

        # Verify removed
        resp = client.get("/bookmarks", headers=_auth_header(token))
        assert resp.json() == []

    def test_bookmark_nonexistent_question(self):
        """Bookmarking a nonexistent question returns 404."""
        token = _register_and_login("nobm@test.com")
        resp = client.post("/bookmarks/nonexistent-id", headers=_auth_header(token))
        assert resp.status_code == 404

    def test_bookmark_idempotent(self):
        """Bookmarking the same question twice doesn't create duplicates."""
        token = _register_and_login("idem@test.com")
        _set_preferences(token)

        user = get_user_by_email("idem@test.com")
        q_id = _insert_mcq_question(user["id"])

        client.post(f"/bookmarks/{q_id}", headers=_auth_header(token))
        client.post(f"/bookmarks/{q_id}", headers=_auth_header(token))

        resp = client.get("/bookmarks", headers=_auth_header(token))
        assert len(resp.json()) == 1


# =========================================================================
# E2E Journey 5: Multi-user isolation
# =========================================================================


class TestMultiUserIsolation:
    """Verify that users cannot see each other's data."""

    def test_users_see_only_their_questions(self):
        """User A's questions are not visible to User B."""
        token_a = _register_and_login("usera@test.com")
        token_b = _register_and_login("userb@test.com")

        _set_preferences(token_a)
        _set_preferences(token_b)

        user_a = get_user_by_email("usera@test.com")
        user_b = get_user_by_email("userb@test.com")

        q_a = _insert_mcq_question(user_a["id"])
        q_b = _insert_mcq_question(user_b["id"])

        # User A sees their question
        resp = client.get(f"/questions/{q_a}", headers=_auth_header(token_a))
        assert resp.status_code == 200

        # User A cannot see User B's question
        resp = client.get(f"/questions/{q_b}", headers=_auth_header(token_a))
        assert resp.status_code == 404

        # User B cannot see User A's question
        resp = client.get(f"/questions/{q_a}", headers=_auth_header(token_b))
        assert resp.status_code == 404

    def test_users_see_only_their_history(self):
        """User A's attempts don't appear in User B's history."""
        token_a = _register_and_login("hista@test.com")
        token_b = _register_and_login("histb@test.com")

        _set_preferences(token_a)
        _set_preferences(token_b)

        user_a = get_user_by_email("hista@test.com")
        q_a = _insert_mcq_question(user_a["id"])

        # User A answers
        client.post("/attempts", json={"question_id": q_a, "answer_text": "B"}, headers=_auth_header(token_a))

        # User A has history
        resp = client.get("/attempts/history", headers=_auth_header(token_a))
        assert len(resp.json()) == 1

        # User B has no history
        resp = client.get("/attempts/history", headers=_auth_header(token_b))
        assert len(resp.json()) == 0

    def test_users_see_only_their_bookmarks(self):
        """User A's bookmarks don't appear in User B's list."""
        token_a = _register_and_login("bma@test.com")
        token_b = _register_and_login("bmb@test.com")

        _set_preferences(token_a)

        user_a = get_user_by_email("bma@test.com")
        q_a = _insert_mcq_question(user_a["id"])

        client.post(f"/bookmarks/{q_a}", headers=_auth_header(token_a))

        resp = client.get("/bookmarks", headers=_auth_header(token_a))
        assert len(resp.json()) == 1

        resp = client.get("/bookmarks", headers=_auth_header(token_b))
        assert len(resp.json()) == 0

    def test_users_see_only_their_stats(self):
        """User A's stats don't leak into User B's view."""
        token_a = _register_and_login("stata@test.com")
        token_b = _register_and_login("statb@test.com")

        _set_preferences(token_a)

        user_a = get_user_by_email("stata@test.com")
        q_a = _insert_mcq_question(user_a["id"])
        client.post("/attempts", json={"question_id": q_a, "answer_text": "B"}, headers=_auth_header(token_a))

        resp = client.get("/stats", headers=_auth_header(token_a))
        assert len(resp.json()) == 1

        resp = client.get("/stats", headers=_auth_header(token_b))
        assert len(resp.json()) == 0

    def test_users_have_independent_preferences(self):
        """User A's preferences don't affect User B."""
        token_a = _register_and_login("prefa@test.com")
        token_b = _register_and_login("prefb@test.com")

        # User A sets backend preferences
        client.put(
            "/preferences",
            json={"roles": ["backend_engineer"], "languages": ["Python"], "frameworks": ["FastAPI"]},
            headers=_auth_header(token_a),
        )

        # User B sets frontend preferences
        client.put(
            "/preferences",
            json={"roles": ["frontend_engineer"], "languages": ["TypeScript"], "frameworks": ["React"]},
            headers=_auth_header(token_b),
        )

        resp_a = client.get("/preferences", headers=_auth_header(token_a))
        resp_b = client.get("/preferences", headers=_auth_header(token_b))

        assert resp_a.json()["roles"] == ["backend_engineer"]
        assert resp_b.json()["roles"] == ["frontend_engineer"]


# =========================================================================
# E2E Journey 6: Auth edge cases
# =========================================================================


class TestAuthEdgeCases:
    """Auth flow edge cases and error handling."""

    def test_expired_token_rejected(self):
        """An expired JWT is rejected."""
        import jwt as pyjwt

        expired_payload = {
            "sub": "some-user-id",
            "type": "access",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        expired_token = pyjwt.encode(
            expired_payload,
            os.environ["SWET_API_JWT_SECRET"],
            algorithm="HS256",
        )

        resp = client.get("/preferences", headers=_auth_header(expired_token))
        assert resp.status_code == 401

    def test_tampered_token_rejected(self):
        """A JWT signed with a wrong secret is rejected."""
        import jwt as pyjwt

        payload = {
            "sub": "some-user-id",
            "type": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        bad_token = pyjwt.encode(payload, "wrong-secret-that-is-32-bytes-long!!", algorithm="HS256")

        resp = client.get("/preferences", headers=_auth_header(bad_token))
        assert resp.status_code == 401

    def test_refresh_token_cannot_access_endpoints(self):
        """A refresh token (type=refresh) cannot be used as an access token."""
        _register_and_login("refresh-abuse@test.com")

        # Get a refresh token
        user = get_user_by_email("refresh-abuse@test.com")
        code = generate_otp()
        expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        save_otp(user["id"], hash_otp(code), expires)
        resp = client.post("/auth/otp/verify", json={"email": "refresh-abuse@test.com", "code": code})
        refresh_token = resp.json()["refresh_token"]

        # Try to use refresh token as access token
        resp = client.get("/preferences", headers=_auth_header(refresh_token))
        assert resp.status_code == 401

    def test_register_with_mobile_then_login(self):
        """User registers with mobile and completes full OTP flow."""
        mobile = "+15551234567"
        resp = client.post("/auth/register", json={"mobile": mobile})
        assert resp.status_code == 201

        from swet_api.db import get_user_by_mobile

        user = get_user_by_mobile(mobile)
        code = generate_otp()
        expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        save_otp(user["id"], hash_otp(code), expires)

        resp = client.post("/auth/otp/verify", json={"mobile": mobile, "code": code})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_expired_otp_rejected(self):
        """An expired OTP is rejected."""
        email = "expired-otp@test.com"
        client.post("/auth/register", json={"email": email})
        user = get_user_by_email(email)

        code = generate_otp()
        # Expired 1 minute ago
        expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        save_otp(user["id"], hash_otp(code), expired)

        resp = client.post("/auth/otp/verify", json={"email": email, "code": code})
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()


# =========================================================================
# E2E Journey 7: Complete practice flow with multiple competencies
# =========================================================================


class TestCompletePracticeFlow:
    """Full multi-competency practice flow with stats verification."""

    def test_multi_competency_practice(self):
        """User practices across multiple competencies, stats reflect results."""
        token = _register_and_login("practice@test.com")
        _set_preferences(token)
        user = get_user_by_email("practice@test.com")

        # Insert questions across 3 competencies
        q_prog = _insert_mcq_question(user["id"], "programming_fundamentals")
        q_sec = _insert_mcq_question(user["id"], "security_engineering")
        q_api = _insert_mcq_question(user["id"], "api_design_and_integration")

        # Answer: correct, wrong, correct
        client.post("/attempts", json={"question_id": q_prog, "answer_text": "B"}, headers=_auth_header(token))
        client.post("/attempts", json={"question_id": q_sec, "answer_text": "A"}, headers=_auth_header(token))
        client.post("/attempts", json={"question_id": q_api, "answer_text": "B"}, headers=_auth_header(token))

        # Check stats
        resp = client.get("/stats", headers=_auth_header(token))
        stats = resp.json()
        assert len(stats) == 3

        stats_by_slug = {s["competency_slug"]: s for s in stats}
        assert stats_by_slug["programming_fundamentals"]["avg_score"] == 1.0
        assert stats_by_slug["security_engineering"]["avg_score"] == 0.0
        assert stats_by_slug["api_design_and_integration"]["avg_score"] == 1.0

        # Check history contains all 3 attempts
        resp = client.get("/attempts/history", headers=_auth_header(token))
        history = resp.json()
        assert len(history) == 3
        history_slugs = {h["competency_slug"] for h in history}
        assert history_slugs == {"programming_fundamentals", "security_engineering", "api_design_and_integration"}

    def test_bookmark_and_review_workflow(self):
        """User answers a question, bookmarks it, and reviews via bookmark list."""
        token = _register_and_login("review@test.com")
        _set_preferences(token)
        user = get_user_by_email("review@test.com")

        q_id = _insert_mcq_question(user["id"])

        # Answer incorrectly
        resp = client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "A"},
            headers=_auth_header(token),
        )
        assert resp.json()["normalized_score"] == 0.0

        # Bookmark for later review
        client.post(f"/bookmarks/{q_id}", headers=_auth_header(token))

        # Find it in bookmarks
        resp = client.get("/bookmarks", headers=_auth_header(token))
        bookmarks = resp.json()
        assert len(bookmarks) == 1
        bookmarked_id = bookmarks[0]["id"]

        # Review the question via its ID
        resp = client.get(f"/questions/{bookmarked_id}", headers=_auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["title"] == "What is the time complexity of binary search?"


# =========================================================================
# E2E Journey 8: Post-attempt adaptive updates
# =========================================================================


class TestAdaptiveUpdates:
    """Verify that submitting an answer updates ELO, streak, and format performance."""

    def test_attempt_updates_competency_level(self):
        """Submitting an answer should create/update the competency level."""
        token = _register_and_login("adaptive@test.com")
        _set_preferences(token)
        user = get_user_by_email("adaptive@test.com")

        q_id = _insert_mcq_question(user["id"], "programming_fundamentals")
        client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B"},
            headers=_auth_header(token),
        )

        # Competency level should exist now
        level_data = get_user_competency_level(user["id"], "programming_fundamentals")
        assert level_data is not None
        assert level_data["total_attempts"] == 1
        assert level_data["estimated_level"] >= 1

        # Stats endpoint should reflect the level
        resp = client.get("/stats/competencies", headers=_auth_header(token))
        competencies = resp.json()
        prog = next(c for c in competencies if c["slug"] == "programming_fundamentals")
        assert prog["estimated_level"] is not None
        assert prog["total_attempts"] == 1

    def test_attempt_updates_streak(self):
        """Submitting an answer should update the streak."""
        token = _register_and_login("streak@test.com")
        _set_preferences(token)
        user = get_user_by_email("streak@test.com")

        q_id = _insert_mcq_question(user["id"])
        client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B"},
            headers=_auth_header(token),
        )

        resp = client.get("/stats/streak", headers=_auth_header(token))
        assert resp.json()["current_streak"] >= 1

    def test_multiple_attempts_track_elo(self):
        """Multiple correct answers should update total_attempts."""
        token = _register_and_login("elo@test.com")
        _set_preferences(token)
        user = get_user_by_email("elo@test.com")

        for _ in range(3):
            q_id = _insert_mcq_question(user["id"], "programming_fundamentals")
            client.post(
                "/attempts",
                json={"question_id": q_id, "answer_text": "B"},
                headers=_auth_header(token),
            )

        level_data = get_user_competency_level(user["id"], "programming_fundamentals")
        assert level_data["total_attempts"] == 3


# =========================================================================
# E2E Journey 9: Contract bug fixes verification
# =========================================================================


class TestContractFixes:
    """Verify the field name fixes between backend and frontend."""

    def test_grade_response_criteria_fields(self):
        """Criteria scores should use 'criterion' and 'max_score' field names."""
        token = _register_and_login("criteria@test.com")
        _set_preferences(token)
        user = get_user_by_email("criteria@test.com")

        q_id = _insert_mcq_question(user["id"])
        resp = client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B"},
            headers=_auth_header(token),
        )
        grade = resp.json()

        # Criteria should use frontend-expected field names
        assert grade["criteria_scores"] is not None
        for cs in grade["criteria_scores"]:
            assert "criterion" in cs, f"Missing 'criterion' field, got: {cs.keys()}"
            assert "max_score" in cs, f"Missing 'max_score' field, got: {cs.keys()}"
            assert "name" not in cs, "Should not have 'name' field"
            assert "max_points" not in cs, "Should not have 'max_points' field"

    def test_grade_response_score_is_raw_points(self):
        """GradeResponse.score should be raw points (total_score), not normalized."""
        token = _register_and_login("score@test.com")
        _set_preferences(token)
        user = get_user_by_email("score@test.com")

        q_id = _insert_mcq_question(user["id"])
        # Correct answer
        resp = client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B"},
            headers=_auth_header(token),
        )
        grade = resp.json()

        # For MCQ: total_score=1 when correct, normalized_score=1.0
        assert grade["score"] == grade["total_score"]
        assert grade["normalized_score"] == 1.0

    def test_history_has_normalized_score_and_created_at(self):
        """History entries should include normalized_score and created_at fields."""
        token = _register_and_login("history@test.com")
        _set_preferences(token)
        user = get_user_by_email("history@test.com")

        q_id = _insert_mcq_question(user["id"])
        client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B"},
            headers=_auth_header(token),
        )

        resp = client.get("/attempts/history", headers=_auth_header(token))
        history = resp.json()
        assert len(history) > 0
        entry = history[0]
        assert "normalized_score" in entry, f"Missing 'normalized_score', got: {entry.keys()}"
        assert "created_at" in entry, f"Missing 'created_at', got: {entry.keys()}"
        assert entry["normalized_score"] == entry["score"]
        assert entry["created_at"] == entry["completed_at"]


# =========================================================================
# E2E Journey 10: Dashboard endpoint
# =========================================================================


class TestDashboard:
    """Test the aggregated dashboard endpoint."""

    def test_dashboard_returns_data(self):
        """Dashboard should return streak, review count, and assessment status."""
        token = _register_and_login("dashboard@test.com")
        _set_preferences(token)

        resp = client.get("/dashboard", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "streak" in data
        assert data["streak"]["current_streak"] >= 0
        assert "review_due_count" in data
        assert "has_completed_assessment" in data
        assert data["has_completed_assessment"] is False
        assert "total_attempts" in data
        assert "competencies_assessed" in data

    def test_dashboard_after_attempt(self):
        """Dashboard should reflect updated stats after an attempt."""
        token = _register_and_login("dash-attempt@test.com")
        _set_preferences(token)
        user = get_user_by_email("dash-attempt@test.com")

        q_id = _insert_mcq_question(user["id"])
        client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B"},
            headers=_auth_header(token),
        )

        resp = client.get("/dashboard", headers=_auth_header(token))
        data = resp.json()
        assert data["total_attempts"] == 1
        assert data["streak"]["current_streak"] >= 1
        assert data["competencies_assessed"] >= 1


# =========================================================================
# E2E Journey 11: Review queue
# =========================================================================


class TestReviewQueue:
    """Test the review queue endpoints."""

    def test_review_count_starts_empty(self):
        """New user should have no reviews due."""
        token = _register_and_login("review-empty@test.com")
        _set_preferences(token)

        resp = client.get("/reviews/count", headers=_auth_header(token))
        assert resp.status_code == 200
        counts = resp.json()
        assert counts["due_today"] == 0
        assert counts["total_pending"] == 0

    def test_incorrect_answer_enqueues_review(self):
        """Answering incorrectly should add the question to the review queue."""
        token = _register_and_login("review-enqueue@test.com")
        _set_preferences(token)
        user = get_user_by_email("review-enqueue@test.com")

        q_id = _insert_mcq_question(user["id"])
        # Wrong answer
        client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "A"},
            headers=_auth_header(token),
        )

        # Review count should have increased (due tomorrow, not today)
        resp = client.get("/reviews/count", headers=_auth_header(token))
        counts = resp.json()
        assert counts["total_pending"] >= 1

    def test_bookmark_enqueues_review(self):
        """Bookmarking a question should add it to the review queue."""
        token = _register_and_login("review-bookmark@test.com")
        _set_preferences(token)
        user = get_user_by_email("review-bookmark@test.com")

        q_id = _insert_mcq_question(user["id"])
        client.post(f"/bookmarks/{q_id}", headers=_auth_header(token))

        resp = client.get("/reviews/count", headers=_auth_header(token))
        counts = resp.json()
        assert counts["total_pending"] >= 1

    def test_dismiss_review(self):
        """Dismissing a review should remove it from the queue."""
        token = _register_and_login("review-dismiss@test.com")
        _set_preferences(token)
        user = get_user_by_email("review-dismiss@test.com")

        q_id = _insert_mcq_question(user["id"])
        # Add directly with today's date so it shows up in GET /reviews
        from datetime import date

        add_review_item(user["id"], q_id, "manual", date.today().isoformat())

        # Get the review items
        resp = client.get("/reviews", headers=_auth_header(token))
        items = resp.json()
        assert len(items) >= 1

        # Dismiss it
        review_id = items[0]["id"]
        resp = client.delete(f"/reviews/{review_id}", headers=_auth_header(token))
        assert resp.status_code == 204

        # Should be gone
        resp = client.get("/reviews/count", headers=_auth_header(token))
        assert resp.json()["due_today"] == 0


# =========================================================================
# E2E Journey 12: Enhanced stats
# =========================================================================


class TestEnhancedStats:
    """Test the new stats endpoints."""

    def test_calendar_returns_data(self):
        """Calendar endpoint should return active days for current month."""
        token = _register_and_login("calendar@test.com")
        _set_preferences(token)

        resp = client.get("/stats/calendar", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert "year" in data
        assert "month" in data
        assert "active_days" in data

    def test_format_performance_after_attempts(self):
        """Format performance should reflect answered questions."""
        token = _register_and_login("format-perf@test.com")
        _set_preferences(token)
        user = get_user_by_email("format-perf@test.com")

        q_id = _insert_mcq_question(user["id"])
        client.post(
            "/attempts",
            json={"question_id": q_id, "answer_text": "B"},
            headers=_auth_header(token),
        )

        resp = client.get("/stats/format-performance", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        mcq = next((f for f in data if f["format"] == "mcq"), None)
        assert mcq is not None
        assert mcq["total_attempts"] >= 1

    def test_weak_areas(self):
        """Weak areas should return competencies with lowest scores."""
        token = _register_and_login("weak@test.com")
        _set_preferences(token)
        user = get_user_by_email("weak@test.com")

        # Answer 2 questions incorrectly for same competency
        for _ in range(2):
            q_id = _insert_mcq_question(user["id"])
            client.post(
                "/attempts",
                json={"question_id": q_id, "answer_text": "A"},
                headers=_auth_header(token),
            )

        resp = client.get("/stats/weak-areas", headers=_auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["avg_score"] < 0.5
