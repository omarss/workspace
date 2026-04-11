"""Tests for rate limiting middleware (SPEC-043)."""

import time

from src.middleware.rate_limit import InMemoryRateLimitStore, _match_route


class TestSlidingWindowStore:
    """Tests for the in-memory rate limit store."""

    def test_allows_under_limit(self):
        store = InMemoryRateLimitStore()
        allowed, remaining, _ = store.check_and_increment("key1", limit=5, window_seconds=60)
        assert allowed is True
        assert remaining == 4

    def test_rejects_at_limit(self):
        store = InMemoryRateLimitStore()
        for _ in range(5):
            store.check_and_increment("key1", limit=5, window_seconds=60)

        allowed, remaining, _ = store.check_and_increment("key1", limit=5, window_seconds=60)
        assert allowed is False
        assert remaining == 0

    def test_different_keys_independent(self):
        store = InMemoryRateLimitStore()
        for _ in range(5):
            store.check_and_increment("user1", limit=5, window_seconds=60)

        # Different key should still be allowed
        allowed, _, _ = store.check_and_increment("user2", limit=5, window_seconds=60)
        assert allowed is True

    def test_expired_entries_pruned(self):
        store = InMemoryRateLimitStore()
        for _ in range(5):
            store.check_and_increment("key1", limit=5, window_seconds=0.1)

        # Wait for window to expire
        time.sleep(0.15)

        allowed, remaining, _ = store.check_and_increment("key1", limit=5, window_seconds=0.1)
        assert allowed is True
        assert remaining == 4

    def test_remaining_decrements(self):
        store = InMemoryRateLimitStore()
        _, r1, _ = store.check_and_increment("key1", limit=3, window_seconds=60)
        _, r2, _ = store.check_and_increment("key1", limit=3, window_seconds=60)
        _, r3, _ = store.check_and_increment("key1", limit=3, window_seconds=60)
        assert r1 == 2
        assert r2 == 1
        assert r3 == 0

    def test_reset_time_is_in_future(self):
        store = InMemoryRateLimitStore()
        _, _, reset = store.check_and_increment("key1", limit=5, window_seconds=60)
        assert reset > time.time()


class TestRouteMatching:
    """Tests for route pattern matching."""

    def test_exact_prefix_match(self):
        assert _match_route("/api/v1/results/123", "/api/v1/results") is True

    def test_no_match(self):
        assert _match_route("/api/v1/health", "/api/v1/results") is False

    def test_wildcard_match(self):
        assert (
            _match_route("/api/v1/assessments/abc/answers", "/api/v1/assessments/*/answers") is True
        )

    def test_wildcard_no_match(self):
        assert (
            _match_route("/api/v1/assessments/abc/progress", "/api/v1/assessments/*/answers")
            is False
        )
