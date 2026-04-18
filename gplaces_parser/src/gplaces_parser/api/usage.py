"""Per-API-key request counter.

Middleware that increments `api_usage(key_prefix, endpoint, status, day)`
on every response. The `key_prefix` is the first 8 hex chars of
`sha256(X-Api-Key)` — stable across sessions, safe to log, can't be
used to reverse-engineer the key.

Design notes:
- Endpoint is normalised to `request.url.path` (no query string), so
  `/v1/places` and `/v1/places?category=coffee` aggregate together.
- Status bucket is the HTTP code as-is (200 / 400 / 401 / 500). Tight
  groupings (2xx, 4xx, 5xx) would lose the 401-vs-400 distinction the
  operator actually cares about.
- The UPSERT runs in a fresh connection per request — contention on a
  single row is handled by Postgres's row-level locking. At our
  throughput (tens of rpm) this is trivial.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..db import connection

log = logging.getLogger(__name__)


def _key_prefix(raw: str | None) -> str:
    """SHA-256 first 8 hex chars, or `'anon'` if no key was sent."""
    if not raw:
        return "anon"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


UPSERT_SQL = """
INSERT INTO api_usage (key_prefix, endpoint, status_bucket, day, count, last_seen)
VALUES (%s, %s, %s, (now() AT TIME ZONE 'UTC')::date, 1, now())
ON CONFLICT (key_prefix, endpoint, status_bucket, day) DO UPDATE SET
    count = api_usage.count + 1,
    last_seen = now()
"""


class ApiUsageMiddleware(BaseHTTPMiddleware):
    """Non-blocking by design — if the DB is unreachable the request still
    returns normally; we log and move on. Usage stats are a reporting
    nicety, never a request-path dependency."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        # Skip the health probe to keep the table uncluttered.
        if request.url.path.startswith("/v1/health"):
            return response
        try:
            prefix = _key_prefix(request.headers.get("x-api-key"))
            endpoint = request.url.path
            with connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        UPSERT_SQL,
                        (prefix, endpoint, int(response.status_code)),
                    )
                conn.commit()
        except Exception:  # noqa: BLE001
            log.exception("api_usage upsert failed for %s", request.url.path)
        return response
