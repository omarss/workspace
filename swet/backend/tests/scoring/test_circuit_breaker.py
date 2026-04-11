"""Tests for the circuit breaker (SPEC-041)."""

import time

import pytest

from src.scoring.circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitState


class TestCircuitBreakerStateMachine:
    """Verify the circuit breaker state transitions."""

    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_under_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, failure_window=60.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_requests(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=30.0)
        cb.record_failure()
        cb.record_failure()
        with pytest.raises(CircuitBreakerError) as exc_info:
            cb.check()
        assert exc_info.value.retry_after > 0

    def test_transitions_to_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_one_probe(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)

        # First check should pass (probe)
        cb.check()

        # Second check should be rejected (probe in progress)
        with pytest.raises(CircuitBreakerError):
            cb.check()

    def test_half_open_closes_on_success(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)

        cb.check()  # Probe allowed
        cb.record_success()  # Probe succeeded
        assert cb.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)

        cb.check()  # Probe allowed
        cb.record_failure()  # Probe failed
        assert cb.state == CircuitState.OPEN

    def test_success_resets_in_closed_state(self):
        """Success in closed state doesn't change anything."""
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_success()
        # Still closed, and the failure is still in the window
        assert cb.state == CircuitState.CLOSED

    def test_old_failures_expire(self):
        """Failures outside the window should not count."""
        cb = CircuitBreaker(failure_threshold=3, failure_window=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        # Old failures expired, this is the first in the new window
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_reset_clears_state(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_execute_success():
    """Execute should pass through on success and record it."""
    cb = CircuitBreaker(failure_threshold=3)

    async def success_fn():
        return "ok"

    result = await cb.execute(success_fn())
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_execute_failure():
    """Execute should record failure on exception."""
    cb = CircuitBreaker(failure_threshold=2)

    async def fail_fn():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await cb.execute(fail_fn())

    assert len(cb._failures) == 1

    with pytest.raises(ValueError):
        await cb.execute(fail_fn())

    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_execute_rejects_when_open():
    """Execute should raise CircuitBreakerError when circuit is open."""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    cb.record_failure()

    async def fn():
        return "should not run"

    with pytest.raises(CircuitBreakerError):
        await cb.execute(fn())
