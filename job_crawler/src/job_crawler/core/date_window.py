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


def is_within_window(
    posted_at: datetime | None,
    *,
    source_updated_at: datetime | None = None,
    now: datetime | None = None,
) -> bool:
    """True when `posted_at` OR `source_updated_at` is within the window.

    The dual-timestamp check catches long-lived ATS roles whose
    `first_published` is months old but whose `updated_at` is fresh
    (the role got bumped, refreshed, or its details edited). Live
    Greenhouse data: Tamara's "Application Support Engineer" had
    `first_published=2025-11-13` (>6 months ago) but
    `updated_at=2026-05-19` (8 days ago) — clearly active, but the
    pre-fix runner dropped it because the single posted_at check
    failed. 26 of Tamara's 37 jobs were filtered out the same way.

    Behaviour:
      * Both NULL → True (permissive when the source is silent).
      * `posted_at` fresh → True (legacy path).
      * `posted_at` stale BUT `source_updated_at` fresh → True (new).
      * Both stale → False.
    """
    cutoff_ts = cutoff(now)
    seen_any = False
    for ts in (posted_at, source_updated_at):
        if ts is None:
            continue
        seen_any = True
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts >= cutoff_ts:
            return True
    # Both timestamps were stale, OR both were None. Permissive on
    # full-NULL inputs (legacy contract), strict on dual-stale.
    return not seen_any
