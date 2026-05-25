from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from salary_model.data.calibrate import calibrate_to_live


def _wage_index(
    *, total: float, saudi_total: float, male: float, female: float,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"year": 2020, "gender": "Males", "is_saudi": False,
             "wage_sar_monthly": male, "n_quarters_observed": 4},
            {"year": 2020, "gender": "Females", "is_saudi": False,
             "wage_sar_monthly": female, "n_quarters_observed": 4},
            {"year": 2020, "gender": "Total", "is_saudi": False,
             "wage_sar_monthly": total, "n_quarters_observed": 4},
            {"year": 2020, "gender": "Total", "is_saudi": True,
             "wage_sar_monthly": saudi_total, "n_quarters_observed": 4},
        ]
    )


def _synth(n: int = 1000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = rng.lognormal(mean=9.5, sigma=0.4, size=n)
    return pd.DataFrame(
        {
            "observed_at": [datetime(2020, 6, 1, tzinfo=UTC)] * n,
            "base_monthly": base,
            "is_saudi": rng.random(n) < 0.5,
            "gender": np.where(rng.random(n) < 0.4, "F", "M"),
            "housing_monthly": base * 0.25,
            "transport_monthly": base * 0.10,
            "other_fixed_monthly": np.zeros(n),
            "variable_monthly_eq": np.zeros(n),
            "equity_annual_ev": np.zeros(n),
        }
    )


def test_calibration_pins_overall_mean_all_employees() -> None:
    df = _synth(2000)
    idx = _wage_index(total=8000.0, saudi_total=11000.0, male=8200.0, female=7900.0)
    out, report = calibrate_to_live(
        df, idx, target_year=2020, cpi_yoy=0.0, target_population="all",
    )
    assert any(s.name == "mean" for s in report.steps)
    new_mean = float(out["base_monthly"].mean())
    assert abs(new_mean - 8000.0) / 8000.0 < 0.02


def test_calibration_pins_overall_mean_saudi_default() -> None:
    df = _synth(2000)
    idx = _wage_index(total=8000.0, saudi_total=11000.0, male=8200.0, female=7900.0)
    # Default target_population="saudi" pins to the Saudi-only mean (11_000)
    out, _ = calibrate_to_live(df, idx, target_year=2020, cpi_yoy=0.0)
    new_mean = float(out["base_monthly"].mean())
    assert abs(new_mean - 11_000.0) / 11_000.0 < 0.02


def test_calibration_pins_saudi_premium() -> None:
    df = _synth(3000)
    idx = _wage_index(total=8000.0, saudi_total=12000.0, male=8200.0, female=7900.0)
    out, _ = calibrate_to_live(df, idx, target_year=2020, cpi_yoy=0.0)
    target_premium = (12000.0 - 8000.0) / 8000.0  # 0.5
    new_all = float(out["base_monthly"].mean())
    new_saudi = float(out.loc[out["is_saudi"], "base_monthly"].mean())
    new_premium = (new_saudi - new_all) / new_all
    # Premium should be close to target
    assert abs(new_premium - target_premium) < 0.05


def test_calibration_pins_gender_gap() -> None:
    df = _synth(3000)
    idx = _wage_index(total=8000.0, saudi_total=11000.0, male=8400.0, female=7560.0)
    out, _ = calibrate_to_live(df, idx, target_year=2020, cpi_yoy=0.0)
    target_gap = (7560.0 - 8400.0) / 8400.0  # -10%
    new_male = float(out.loc[out["gender"] == "M", "base_monthly"].mean())
    new_female = float(out.loc[out["gender"] == "F", "base_monthly"].mean())
    new_gap = (new_female - new_male) / new_male
    assert abs(new_gap - target_gap) < 0.03


def test_calibration_skipped_when_index_empty() -> None:
    df = _synth(100)
    empty = pd.DataFrame()
    out, report = calibrate_to_live(df, empty)
    assert "mean" in report.skipped
    pd.testing.assert_series_equal(
        out["base_monthly"].reset_index(drop=True),
        df["base_monthly"].reset_index(drop=True),
        check_names=False,
    )


def test_calibration_recomputes_tcc() -> None:
    df = _synth(200)
    idx = _wage_index(total=10000.0, saudi_total=14000.0, male=10200.0, female=9800.0)
    out, _ = calibrate_to_live(df, idx, target_year=2020, cpi_yoy=0.0)
    assert "tcc_monthly" in out.columns
    # tcc should equal base + 35% allowances (housing 25 + transport 10)
    expected = out["base_monthly"] + out["housing_monthly"] + out["transport_monthly"]
    np.testing.assert_allclose(out["tcc_monthly"].to_numpy(), expected.to_numpy(), rtol=0.01)


def test_calibration_report_markdown() -> None:
    df = _synth(500)
    idx = _wage_index(total=8000.0, saudi_total=11000.0, male=8200.0, female=7900.0)
    _, report = calibrate_to_live(df, idx, target_year=2020, cpi_yoy=0.0)
    md = report.to_markdown()
    assert md.startswith("# Calibration report")
    assert "| step |" in md
