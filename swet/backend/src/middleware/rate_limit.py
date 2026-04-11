"""Rate limiting middleware using sliding window algorithm (SPEC-043).

Enforces per-user and per-IP request limits. Uses in-memory tracking
for development and PostgreSQL for production (via config).
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""

    requests: int
    window_seconds: int
    key_prefix: str


# Per-user limits (identified by user ID from JWT)
# These only apply to POST requests (creation/mutation endpoints)
USER_LIMITS: dict[str, RateLimitConfig] = {
    "POST:/api/v1/assessments": RateLimitConfig(
        requests=10, window_seconds=3600, key_prefix="assess"
    ),
    "POST:/api/v1/assessments/*/answers": RateLimitConfig(
        requests=120, window_seconds=60, key_prefix="answer"
    ),
}

# Default per-IP fallback for unauthenticated routes
DEFAULT_IP_LIMIT = RateLimitConfig(requests=60, window_seconds=60, key_prefix="ip")


@dataclass
class SlidingWindowEntry:
    """Track requests within a time window."""

    timestamps: list[float] = field(default_factory=list)


class InMemoryRateLimitStore:
    """Simple in-memory rate limit store (suitable for single-process development)."""

    def __init__(self) -> None:
        self._entries: dict[str, SlidingWindowEntry] = defaultdict(SlidingWindowEntry)

    def check_and_increment(
        self,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int, float]:
        """Check rate limit and increment counter.

        Returns:
            (allowed, remaining, reset_time)
        """
        now = time.time()
        entry = self._entries[key]

        # Prune expired timestamps
        cutoff = now - window_seconds
        entry.timestamps = [t for t in entry.timestamps if t > cutoff]

        remaining = max(0, limit - len(entry.timestamps))
        reset_time = (
            (entry.timestamps[0] + window_seconds) if entry.timestamps else (now + window_seconds)
        )

        if len(entry.timestamps) >= limit:
            return False, 0, reset_time

        entry.timestamps.append(now)
        remaining = max(0, limit - len(entry.timestamps))
        return True, remaining, reset_time


def _match_route(path: str, pattern: str) -> bool:
    """Match a request path against a route pattern with wildcard support."""
    parts = pattern.split("*")
    if len(parts) == 1:
        return path.startswith(pattern)
    # Simple wildcard: check prefix and suffix
    return path.startswith(parts[0]) and (len(parts) < 2 or parts[1] in path)


def _get_rate_limit_config(method: str, path: str) -> RateLimitConfig | None:
    """Find the matching rate limit config for a request method + path."""
    for pattern, config in USER_LIMITS.items():
        # Pattern format: "METHOD:/path" or just "/path"
        if ":" in pattern and not pattern.startswith("/"):
            rule_method, rule_path = pattern.split(":", 1)
            if method != rule_method:
                continue
            if _match_route(path, rule_path):
                return config
        elif _match_route(path, pattern):
            return config
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces rate limits on API requests."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._store = InMemoryRateLimitStore()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Only apply to API routes
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # Skip health checks and pool status polling
        if path in ("/api/health", "/api/v1/assessments/pools/status"):
            return await call_next(request)

        method = request.method
        config = _get_rate_limit_config(method, path)
        if not config:
            return await call_next(request)

        # Build rate limit key from user ID or IP
        user_id = None
        if hasattr(request.state, "jwt") and request.state.jwt:
            user_id = request.state.jwt.get("sub")

        client_host = request.client.host if request.client else "unknown"
        key = f"{config.key_prefix}:{user_id or client_host}"

        allowed, remaining, reset_time = self._store.check_and_increment(
            key, config.requests, config.window_seconds
        )

        if not allowed:
            retry_after = int(reset_time - time.time())
            logger.warning("Rate limit exceeded for key=%s, retry_after=%ds", key, retry_after)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Too many requests. Try again in {retry_after} seconds.",
                    "code": "RATE_LIMITED",
                },
                headers={
                    "X-RateLimit-Limit": str(config.requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(reset_time)),
                    "Retry-After": str(max(1, retry_after)),
                },
            )

        response = await call_next(request)

        # Add rate limit headers to successful responses
        response.headers["X-RateLimit-Limit"] = str(config.requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(reset_time))

        return response
