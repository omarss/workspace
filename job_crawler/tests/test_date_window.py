"""Unit tests for `core.date_window.is_within_window`.

Single-statement gate, but the dual-timestamp semantics it picked up
warrant explicit regression coverage. The fix below was driven by a
live regression: Tamara's "Application Support Engineer" Greenhouse
job had `first_published=2025-11-13` (6+ months ago) but
`updated_at=2026-05-19` (8 days ago) — the role was actively being
refreshed but our `is_within_window` only looked at `posted_at` and
dropped it, costing us 26 of Tamara's 37 jobs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from job_crawler.core.date_window import is_within_window


def _now() -> datetime:
    return datetime.now(UTC)


def test_both_none_passes() -> None:
    assert is_within_window(None) is True
    assert is_within_window(None, source_updated_at=None) is True


def test_fresh_posted_at_passes() -> None:
    now = _now()
    assert is_within_window(now - timedelta(days=5), now=now) is True


def test_stale_posted_at_dropped() -> None:
    now = _now()
    assert is_within_window(now - timedelta(days=60), now=now) is False


def test_stale_posted_at_but_fresh_updated_at_passes() -> None:
    """The Tamara regression: posted long ago, refreshed recently."""
    now = _now()
    assert (
        is_within_window(
            now - timedelta(days=180),
            source_updated_at=now - timedelta(days=8),
            now=now,
        )
        is True
    )


def test_both_stale_dropped() -> None:
    now = _now()
    assert (
        is_within_window(
            now - timedelta(days=180),
            source_updated_at=now - timedelta(days=60),
            now=now,
        )
        is False
    )


def test_naive_timestamp_treated_as_utc() -> None:
    """Bayt produces tz-naive datetimes — the function coerces them."""
    now = _now()
    naive = (now - timedelta(days=3)).replace(tzinfo=None)
    assert is_within_window(naive, now=now) is True


def test_only_updated_at_present() -> None:
    """A source that reports updated_at but no posted_at should still pass
    when the update is fresh."""
    now = _now()
    assert (
        is_within_window(
            None,
            source_updated_at=now - timedelta(days=5),
            now=now,
        )
        is True
    )
