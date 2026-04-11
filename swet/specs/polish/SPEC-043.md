# SPEC-043: Rate Limiting and Abuse Prevention

## Status
Draft

## Priority
P2

## Dependencies
- SPEC-014 (Assessment engine)

## Overview
Protect the SWET platform from abuse and excessive resource consumption by implementing rate limiting across API endpoints, with special attention to expensive operations (Claude API calls for question generation and grading) and user-facing workflows (assessment creation, answer submission). Rate limiting operates at multiple layers: per-user for authenticated endpoints, per-IP for unauthenticated endpoints, and per-resource for Claude API interactions.

## Requirements

### Functional
1. Apply per-user rate limits to authenticated API endpoints:
   - Assessment creation: 3 assessments per hour per user (cooldown prevents rapid creation)
   - Answer submission: 120 submissions per minute per user (accommodates auto-save at ~2/sec)
   - Results retrieval: 60 requests per minute per user
2. Apply per-endpoint global rate limits to prevent system overload:
   - Question generation (Claude API): 10 requests per minute globally
   - AI grading (Claude API): 20 grading calls per minute globally
3. Apply per-IP rate limits to unauthenticated endpoints:
   - Login/OAuth callback: 10 requests per minute per IP
   - Health check: 60 requests per minute per IP
4. Return standard rate limit headers on all responses:
   - `X-RateLimit-Limit`: maximum requests allowed
   - `X-RateLimit-Remaining`: requests remaining in the window
   - `X-RateLimit-Reset`: Unix timestamp when the window resets
5. Return HTTP 429 (Too Many Requests) with a `Retry-After` header when limits are exceeded
6. Implement assessment start cooldown: after completing an assessment, users must wait 15 minutes before starting a new one (prevents gaming by rapid retakes)
7. Log all rate limit violations for monitoring and alerting

### Non-Functional
1. Rate limit checks must add less than 5ms of latency per request
2. Rate limit state must survive backend restarts (use database or external store, not in-memory only)
3. Rate limiting must not block legitimate use patterns (auto-save bursts, rapid question navigation)
4. Configuration must be adjustable without code changes (environment variables or database config)

## Technical Design

### Rate Limiting Middleware

Add `src/middleware/rate_limit.py`:

```python
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global rate limiting middleware using sliding window counters."""

    async def dispatch(self, request: Request, call_next):
        key = self._get_rate_limit_key(request)
        limit = self._get_limit_for_endpoint(request)

        if not await self._check_rate_limit(key, limit):
            return self._rate_limited_response(key, limit)

        response = await call_next(request)
        self._add_rate_limit_headers(response, key, limit)
        return response
```

### Rate Limit Store

Use PostgreSQL for persistent rate limit tracking (avoids adding Redis as a new dependency):

```sql
CREATE TABLE rate_limit_entries (
    id BIGSERIAL PRIMARY KEY,
    key VARCHAR(255) NOT NULL,         -- e.g., "user:{uid}:assessments" or "ip:{addr}:auth"
    window_start TIMESTAMPTZ NOT NULL,
    request_count INTEGER DEFAULT 1,
    UNIQUE(key, window_start)
);

CREATE INDEX ix_rate_limit_key_window ON rate_limit_entries (key, window_start);
```

**Sliding Window Algorithm:**
1. Round current timestamp down to window boundary (e.g., start of current minute)
2. `INSERT ... ON CONFLICT (key, window_start) DO UPDATE SET request_count = request_count + 1`
3. Sum `request_count` across current window and previous window (weighted by overlap) to get effective count
4. Compare against limit; reject if exceeded
5. Periodic cleanup: delete entries older than 2x the largest window size

### Rate Limit Configuration

```python
# src/middleware/rate_limit_config.py

RATE_LIMITS = {
    # Per-user limits (key prefix: "user:{user_id}")
    "POST:/api/v1/assessments": RateLimit(max_requests=3, window_seconds=3600),
    "POST:/api/v1/assessments/*/answers": RateLimit(max_requests=120, window_seconds=60),
    "GET:/api/v1/results/*": RateLimit(max_requests=60, window_seconds=60),

    # Per-IP limits (key prefix: "ip:{remote_addr}")
    "POST:/api/v1/auth/*": RateLimit(max_requests=10, window_seconds=60),
    "GET:/api/health": RateLimit(max_requests=60, window_seconds=60),
}

# Global limits (key prefix: "global")
GLOBAL_RATE_LIMITS = {
    "claude:question_generation": RateLimit(max_requests=10, window_seconds=60),
    "claude:grading": RateLimit(max_requests=20, window_seconds=60),
}
```

### Assessment Cooldown

Add cooldown check in the assessment creation service:

```python
async def check_assessment_cooldown(
    db: AsyncSession,
    user_id: uuid.UUID,
    cooldown_minutes: int = 15,
) -> None:
    """Raise if user completed an assessment too recently."""
    result = await db.execute(
        select(Assessment)
        .where(
            Assessment.user_id == user_id,
            Assessment.status == "completed",
            Assessment.completed_at > datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes),
        )
        .limit(1)
    )
    if result.scalar_one_or_none():
        raise AppError(
            f"Please wait {cooldown_minutes} minutes between assessments",
            status_code=429,
        )
```

### Claude API Rate Limiting

Wrap the Anthropic client with a global rate limiter:

```python
class RateLimitedClaudeClient:
    """Wraps the Anthropic async client with global rate limiting."""

    def __init__(self, client: AsyncAnthropic, limiter: RateLimitStore):
        self._client = client
        self._limiter = limiter

    async def create_message(self, **kwargs):
        allowed = await self._limiter.check("claude:api", max_requests=30, window=60)
        if not allowed:
            raise RateLimitError("Claude API rate limit exceeded")
        return await self._client.messages.create(**kwargs)
```

### Frontend Handling

Handle 429 responses in the API client:

```typescript
// app/src/lib/api-client.ts
async function handleResponse(response: Response) {
  if (response.status === 429) {
    const retryAfter = response.headers.get("Retry-After");
    const seconds = retryAfter ? parseInt(retryAfter, 10) : 60;
    throw new RateLimitError(
      `Too many requests. Please try again in ${seconds} seconds.`,
      seconds
    );
  }
  ...
}
```

Display a user-friendly toast notification when rate limited, with countdown to retry.

## Implementation Notes
- Using PostgreSQL for rate limit storage is simpler than adding Redis but introduces write load; monitor and consider Redis if the rate limit table becomes a bottleneck
- The sliding window algorithm provides smoother rate limiting than fixed windows (avoids burst-at-boundary issues)
- Cleanup of expired rate limit entries should run as a periodic background task (every 5 minutes)
- Be careful with IP-based limiting behind reverse proxies; use `X-Forwarded-For` header with a trusted proxy configuration
- Auto-save submissions happen every 30 seconds per question; the 120/min limit accommodates up to 2 concurrent tabs
- The assessment cooldown timer should be shown in the UI so users know when they can start a new assessment
- Rate limit configuration should be loaded at startup and cached; avoid per-request config lookups

## Testing Strategy
- Unit tests for: sliding window counter logic (within limit, at limit, over limit, window rollover), cooldown check (recent completion blocks, old completion allows), rate limit key generation per endpoint
- Integration tests for: middleware returns 429 with correct headers when limit exceeded, rate limit state persists across requests, cleanup removes expired entries, Claude API calls are rate limited globally
- E2E tests for: submitting answers rapidly does not trigger rate limiting under normal use, creating assessments too quickly shows cooldown message, 429 response shows user-friendly toast in the UI

## Acceptance Criteria
- [ ] Authenticated endpoints enforce per-user rate limits
- [ ] Unauthenticated endpoints enforce per-IP rate limits
- [ ] Claude API calls are globally rate limited (10 generation/min, 20 grading/min)
- [ ] All responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
- [ ] HTTP 429 responses include a `Retry-After` header
- [ ] Assessment creation enforces a 15-minute cooldown after completion
- [ ] Rate limit checks add less than 5ms latency per request
- [ ] Rate limit state persists across backend restarts
- [ ] Rate limit violations are logged with user/IP, endpoint, and timestamp
- [ ] Frontend displays a user-friendly message on 429 responses
- [ ] Normal usage patterns (auto-save, navigation) do not trigger rate limits
- [ ] Rate limit configuration is adjustable via environment variables
