"""Circuit breaker for Claude API calls (SPEC-041).

Protects against cascading failures when the Claude API is unreachable
or returning errors. Trips after a configurable number of failures,
then periodically allows a single probe request to test recovery.
"""

import logging
import time
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Rejecting requests
    HALF_OPEN = "half_open"  # Probing for recovery


class CircuitBreakerError(Exception):
    """Raised when the circuit breaker is open and rejecting requests."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker is open. Retry after {retry_after:.0f}s.")


class CircuitBreaker:
    """Simple circuit breaker with failure counting and timed recovery.

    Args:
        failure_threshold: Number of failures before opening the circuit.
        failure_window: Time window (seconds) in which failures are counted.
        recovery_timeout: Seconds to wait before probing (half-open state).
        name: Identifier for logging.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        failure_window: float = 60.0,
        recovery_timeout: float = 30.0,
        name: str = "claude_api",
    ):
        self.failure_threshold = failure_threshold
        self.failure_window = failure_window
        self.recovery_timeout = recovery_timeout
        self.name = name

        self._state = CircuitState.CLOSED
        self._failures: list[float] = []  # Timestamps of recent failures
        self._last_failure_time: float = 0.0
        self._half_open_in_progress = False

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, transitioning OPEN -> HALF_OPEN if recovery timeout elapsed."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_in_progress = False
                logger.info("Circuit breaker '%s' transitioning to HALF_OPEN", self.name)
        return self._state

    def check(self) -> None:
        """Check if the circuit allows a request. Raises CircuitBreakerError if not."""
        current_state = self.state

        if current_state == CircuitState.CLOSED:
            return

        if current_state == CircuitState.HALF_OPEN:
            if self._half_open_in_progress:
                # Only one probe at a time
                raise CircuitBreakerError(self.recovery_timeout)
            self._half_open_in_progress = True
            return

        # OPEN state
        retry_after = self.recovery_timeout - (time.monotonic() - self._last_failure_time)
        raise CircuitBreakerError(max(0, retry_after))

    def record_success(self) -> None:
        """Record a successful request, potentially closing the circuit."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failures.clear()
            self._half_open_in_progress = False
            logger.info("Circuit breaker '%s' closed (recovered)", self.name)

    def record_failure(self) -> None:
        """Record a failed request, potentially opening the circuit."""
        now = time.monotonic()
        self._last_failure_time = now

        # Prune old failures outside the window
        cutoff = now - self.failure_window
        self._failures = [t for t in self._failures if t > cutoff]
        self._failures.append(now)

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed, back to OPEN
            self._state = CircuitState.OPEN
            self._half_open_in_progress = False
            logger.warning("Circuit breaker '%s' probe failed, reopening", self.name)
            return

        if len(self._failures) >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker '%s' opened after %d failures in %.0fs",
                self.name,
                len(self._failures),
                self.failure_window,
            )

    async def execute(self, coro: Any) -> Any:
        """Execute an async callable through the circuit breaker.

        Usage:
            result = await breaker.execute(some_async_function())
        """
        try:
            self.check()
        except CircuitBreakerError:
            # Close the unawaited coroutine to prevent RuntimeWarning
            if hasattr(coro, "close"):
                coro.close()
            raise
        try:
            result = await coro
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failures.clear()
        self._half_open_in_progress = False


# Shared instances for the two Claude API use cases
grading_breaker = CircuitBreaker(name="grading_api")
generation_breaker = CircuitBreaker(
    name="generation_api",
    failure_threshold=10,  # More lenient for long-running batch generation
    failure_window=120.0,
    recovery_timeout=15.0,  # Recover faster
)
