"""Per-API-key request counter (matches gplaces_parser)."""

from __future__ import annotations

import hashlib
import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..db import connection

log = logging.getLogger(__name__)


def _key_prefix(raw: str | None) -> str:
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
    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        # Don't count the health probe — it would dominate the table.
        if request.url.path.rstrip("/").endswith("/health"):
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
