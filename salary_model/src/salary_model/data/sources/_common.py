"""Shared utilities for source fetchers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from salary_model.config import get_logger

log = get_logger("salary_model.data.sources")

DEFAULT_TIMEOUT_S: float = 8.0


@dataclass(frozen=True)
class FetchManifest:
    """Provenance record for a fetched source."""

    source: str
    url: str
    fetched_at: datetime
    ok: bool
    notes: str = ""
    rows: int = 0
    fallback: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def fetched_now() -> datetime:
    return datetime.now(tz=UTC)


def safe_get_json(url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> Any | None:
    """GET JSON with graceful failure: returns None on any error.

    All sources are public and read-only; we never block training on a fetch outage.
    """
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("source_fetch_failed", url=url, error=str(exc))
        return None
