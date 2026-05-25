from __future__ import annotations

from datetime import UTC, datetime

import pytest

from salary_model.data.policy import (
    MAX_AGE_YEARS_FOR_ANCHOR,
    MAX_AGE_YEARS_FOR_TRENDLINE,
    StalenessError,
    assert_anchor_fresh,
    freshness,
)


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)


def test_fresh_anchor_is_ok() -> None:
    v = freshness(2025, now=_now())
    assert v.ok_as_anchor is True
    assert v.ok_as_trendline is True
    assert v.trend_factor(0.02) == 1.0


def test_fresh_anchor_boundary_2y() -> None:
    v = freshness(2024, now=_now())
    assert v.ok_as_anchor is True
    v = freshness(2023, now=_now())
    assert v.ok_as_anchor is False
    assert v.ok_as_trendline is True


def test_stale_anchor_needs_trending() -> None:
    v = freshness(2020, now=_now())  # 6 years old
    assert v.ok_as_anchor is False
    assert v.ok_as_trendline is True
    # 2% YoY compounded over 6 years ~ 1.126
    factor = v.trend_factor(0.02)
    assert 1.12 < factor < 1.13


def test_too_old_violates_trendline() -> None:
    v = freshness(1990, now=_now())  # 36 years old
    assert v.ok_as_anchor is False
    assert v.ok_as_trendline is False


def test_assert_anchor_fresh_raises_when_stale() -> None:
    with pytest.raises(StalenessError, match="2020"):
        assert_anchor_fresh(2020, source="test", now=_now())


def test_assert_anchor_fresh_silent_when_fresh() -> None:
    assert_anchor_fresh(2025, source="test", now=_now())  # no raise


def test_constants_are_what_we_documented() -> None:
    assert MAX_AGE_YEARS_FOR_ANCHOR == 2.0
    assert MAX_AGE_YEARS_FOR_TRENDLINE == 30.0
