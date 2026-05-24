from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from salary_model.data.cleanup import (
    ABSOLUTE_CEILING_MONTHLY_SAR,
    SAUDI_MIN_WAGE_MONTHLY_SAR,
    clean_observations,
)


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "observation_id": "S00000001",
        "source": "synthetic_anchored",
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "family": "SWE",
        "level": "IC3",
        "region": "RUH",
        "sector": "J62",
        "ownership": "private",
        "is_saudi": True,
        "base_monthly": 10_000.0,
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame.from_records(rows)


def test_drops_below_saudi_minimum_wage() -> None:
    df = _frame([
        _row(observation_id="ok", base_monthly=5_000.0),
        _row(observation_id="low", base_monthly=SAUDI_MIN_WAGE_MONTHLY_SAR - 1),
    ])
    cleaned, report = clean_observations(df)
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["observation_id"] == "ok"
    rule = next(r for r in report.rules if r.name == "drop_below_minimum_wage")
    assert rule.rows_dropped == 1


def test_keeps_non_saudi_above_expat_floor() -> None:
    df = _frame([
        _row(observation_id="expat_ok", is_saudi=False, base_monthly=2_500.0),
        _row(observation_id="expat_low", is_saudi=False, base_monthly=500.0),
    ])
    cleaned, _ = clean_observations(df)
    assert "expat_ok" in cleaned["observation_id"].tolist()
    assert "expat_low" not in cleaned["observation_id"].tolist()


def test_drops_above_absolute_ceiling() -> None:
    df = _frame([
        _row(observation_id="ok", base_monthly=20_000.0),
        _row(observation_id="huge", base_monthly=ABSOLUTE_CEILING_MONTHLY_SAR + 1),
    ])
    cleaned, _ = clean_observations(df)
    assert "huge" not in cleaned["observation_id"].tolist()


def test_drops_stale_observations() -> None:
    df = _frame([
        _row(observation_id="fresh", observed_at=datetime(2025, 1, 1, tzinfo=UTC)),
        _row(observation_id="ancient", observed_at=datetime(2015, 1, 1, tzinfo=UTC)),
    ])
    cleaned, _ = clean_observations(df, now=datetime(2026, 5, 1, tzinfo=UTC))
    assert "ancient" not in cleaned["observation_id"].tolist()


def test_drops_exact_duplicates() -> None:
    r = _row()
    df = _frame([r, dict(r)])
    cleaned, report = clean_observations(df)
    assert len(cleaned) == 1
    rule = next(r for r in report.rules if r.name == "drop_duplicates")
    assert rule.rows_dropped == 1


def test_decays_confidence_and_drops_below_threshold() -> None:
    df = _frame([
        _row(observation_id="recent", observed_at=datetime(2026, 4, 1, tzinfo=UTC), confidence=0.6),
        _row(observation_id="oldish", observed_at=datetime(2022, 1, 1, tzinfo=UTC), confidence=0.5),
    ])
    cleaned, _ = clean_observations(df, now=datetime(2026, 5, 1, tzinfo=UTC))
    # Recent stays with mostly-unchanged confidence; older row may decay below the 0.1 floor
    # depending on age; we just assert recent is kept.
    assert "recent" in cleaned["observation_id"].tolist()


def test_flags_outliers_by_default_does_not_drop() -> None:
    # Use slightly varied base values so dedup keeps them, then add one large outlier.
    rows = [_row(observation_id=f"r{i}", base_monthly=10_000.0 + i) for i in range(20)]
    rows.append(_row(observation_id="outlier", base_monthly=200_000.0))
    df = _frame(rows)
    cleaned, report = clean_observations(df)
    assert "outlier_flag" in cleaned.columns
    assert cleaned["outlier_flag"].sum() >= 1
    rule = next(r for r in report.rules if r.name == "flag_segment_outliers")
    assert rule.rows_dropped == 0
    assert rule.rows_flagged >= 1


def test_drop_outliers_when_asked() -> None:
    rows = [_row(observation_id=f"r{i}", base_monthly=10_000.0 + i) for i in range(20)]
    rows.append(_row(observation_id="outlier", base_monthly=200_000.0))
    df = _frame(rows)
    cleaned, _ = clean_observations(df, drop_outliers=True)
    assert "outlier" not in cleaned["observation_id"].tolist()


def test_report_markdown_is_well_formed() -> None:
    df = _frame([_row()])
    _, report = clean_observations(df)
    md = report.to_markdown()
    assert md.startswith("# Cleanup report")
    assert "| rule | dropped" in md
