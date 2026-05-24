"""Single source of truth for the 30-day filter.

Every layer of the pipeline drops postings older than this window. The
constant lives here so changing it is a one-line edit.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from .config import LOOKBACK_DAYS_DEFAULT


def lookback_days() -> int:
    """Window size in days. Env-overridable for ops tests."""
    raw = os.environ.get("JC_LOOKBACK_DAYS")
    return int(raw) if raw else LOOKBACK_DAYS_DEFAULT


def cutoff(now: datetime | None = None) -> datetime:
    """Return the UTC timestamp before which we discard postings."""
    base = now or datetime.now(UTC)
    return base - timedelta(days=lookback_days())


def is_within_window(posted_at: datetime | None, *, now: datetime | None = None) -> bool:
    """True when `posted_at` is within the window (or NULL — be permissive
    when the source doesn't tell us; we'll drop later via posted_at if needed).
    """
    if posted_at is None:
        return True
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    return posted_at >= cutoff(now)
