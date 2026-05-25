"""Data-freshness policy.

The user's hard rule (documented in CLAUDE.md):

- **Anchors / "current level" inputs**: never use data older than 2 years. If the
  freshest authoritative source is older than that, *trend it forward* via
  compound CPI (or refuse to use it for an absolute anchor).
- **Trend / forecasting inputs**: 20-30 year history is acceptable for fitting
  trend models, computing rolling features, or backtesting.

Every module that consumes external data should call into this policy module so
the rule is enforced uniformly. Adding a new fetcher? Tag the resulting
DataFrame with ``anchor_year`` and call :func:`assert_anchor_fresh` before
using it as a current-level anchor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

# Policy constants. Change these only with a deliberate review (CLAUDE.md).
MAX_AGE_YEARS_FOR_ANCHOR: Final[float] = 2.0
MAX_AGE_YEARS_FOR_TRENDLINE: Final[float] = 30.0


@dataclass(frozen=True)
class FreshnessVerdict:
    """The freshness of an anchor source relative to today."""

    anchor_year: int
    age_years: float
    ok_as_anchor: bool
    ok_as_trendline: bool
    reason: str

    def trend_factor(self, cpi_yoy: float) -> float:
        """Multiplier needed to lift an anchor by ``age_years`` of inflation.

        Returns 1.0 when fresh (no trending needed). Compound annual CPI.
        """
        if self.ok_as_anchor:
            return 1.0
        n = max(self.age_years, 0.0)
        return float((1.0 + cpi_yoy) ** n)


def today() -> datetime:
    """Anchor for "now". Wrapped so tests can patch."""
    return datetime.now(tz=UTC)


def freshness(anchor_year: int, *, now: datetime | None = None) -> FreshnessVerdict:
    """Decide whether an anchor year is fresh enough to use, and how stale it is."""
    now = now or today()
    age = float(now.year - anchor_year)
    if age <= MAX_AGE_YEARS_FOR_ANCHOR:
        return FreshnessVerdict(
            anchor_year=anchor_year,
            age_years=age,
            ok_as_anchor=True,
            ok_as_trendline=True,
            reason="fresh",
        )
    if age <= MAX_AGE_YEARS_FOR_TRENDLINE:
        return FreshnessVerdict(
            anchor_year=anchor_year,
            age_years=age,
            ok_as_anchor=False,
            ok_as_trendline=True,
            reason=(
                f"stale: {age:.1f}y old (max {MAX_AGE_YEARS_FOR_ANCHOR:.0f}y for anchor); "
                "trend forward via CPI before using as a current-level anchor"
            ),
        )
    return FreshnessVerdict(
        anchor_year=anchor_year,
        age_years=age,
        ok_as_anchor=False,
        ok_as_trendline=False,
        reason=(
            f"too old: {age:.1f}y old (max {MAX_AGE_YEARS_FOR_TRENDLINE:.0f}y); "
            "do not use as anchor or trend input"
        ),
    )


def assert_anchor_fresh(anchor_year: int, *, source: str, now: datetime | None = None) -> None:
    """Raise if the anchor is too old for current-level use without trending.

    Use this only when you genuinely cannot fall back to trending — most callers
    should instead call :func:`freshness` and apply the trend factor.
    """
    verdict = freshness(anchor_year, now=now)
    if not verdict.ok_as_anchor:
        msg = (
            f"{source}: anchor year {anchor_year} is {verdict.age_years:.1f}y old "
            f"(max {MAX_AGE_YEARS_FOR_ANCHOR:.0f}y). {verdict.reason}"
        )
        raise StalenessError(msg)


class StalenessError(ValueError):
    """Raised when a data source's anchor year violates the freshness policy."""


__all__ = [
    "MAX_AGE_YEARS_FOR_ANCHOR",
    "MAX_AGE_YEARS_FOR_TRENDLINE",
    "FreshnessVerdict",
    "StalenessError",
    "assert_anchor_fresh",
    "freshness",
    "today",
]
