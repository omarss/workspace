"""KSA monthly macro time series.

A single dataframe indexed by month with the headline indicators we want the model to
condition on:

- ``cpi_yoy`` — GASTAT headline CPI year-on-year
- ``policy_rate`` — SAMA repo rate
- ``brent_usd`` — monthly average Brent crude (USD/bbl)
- ``sar_to_usd`` — pegged ~0.2667
- ``brent_yoy`` — derived; YoY change in Brent
- ``cpi_yoy_lag1/3/6/12`` — derived lag columns (NaN-safe)

Source bundling: the values below are coarse but real, pulled from GASTAT monthly CPI
releases and SAMA monthly bulletins. They are good enough to demonstrate the
time-varying join; the live fetcher upgrade is documented in :func:`fetch_macro_series`.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from salary_model.data.sources._common import FetchManifest, fetched_now

# ── Bundled monthly anchors ──────────────────────────────────────────────────
#
# Compact representation: list of (year, month, cpi_yoy, policy_rate, brent_usd).
# Values rounded; track GASTAT/SAMA bulletins for refreshes.

_BUNDLED: Final[tuple[tuple[int, int, float, float, float], ...]] = (
    # 2020
    (2020, 1, 0.4, 2.25, 63.0), (2020, 2, 0.2, 1.75, 55.0), (2020, 3, 1.5, 1.00, 32.0),
    (2020, 4, 1.3, 1.00, 18.5), (2020, 5, 1.1, 1.00, 30.0), (2020, 6, 0.5, 1.00, 40.0),
    (2020, 7, 6.1, 1.00, 43.0), (2020, 8, 6.2, 1.00, 44.5), (2020, 9, 5.7, 1.00, 41.0),
    (2020, 10, 5.8, 1.00, 40.0),(2020, 11, 5.8, 1.00, 43.0),(2020, 12, 5.3, 1.00, 50.0),
    # 2021
    (2021, 1, 5.7, 1.00, 55.0), (2021, 2, 5.2, 1.00, 62.0), (2021, 3, 4.9, 1.00, 64.5),
    (2021, 4, 5.3, 1.00, 65.0), (2021, 5, 5.7, 1.00, 68.5), (2021, 6, 6.2, 1.00, 73.0),
    (2021, 7, 0.4, 1.00, 75.0), (2021, 8, 0.3, 1.00, 71.0), (2021, 9, 0.6, 1.00, 75.0),
    (2021, 10, 1.1, 1.00, 84.0),(2021, 11, 1.1, 1.00, 82.0),(2021, 12, 1.2, 1.00, 75.0),
    # 2022
    (2022, 1, 1.6, 1.00, 86.5), (2022, 2, 1.6, 1.00, 97.0), (2022, 3, 2.0, 1.25, 117.0),
    (2022, 4, 2.3, 1.75, 105.0),(2022, 5, 2.2, 2.25, 113.0),(2022, 6, 2.3, 2.75, 122.5),
    (2022, 7, 2.7, 3.00, 105.0),(2022, 8, 3.0, 3.25, 100.0),(2022, 9, 3.1, 3.75, 90.5),
    (2022, 10, 3.0, 4.50, 93.5),(2022, 11, 2.9, 4.75, 91.0),(2022, 12, 3.3, 5.00, 80.5),
    # 2023
    (2023, 1, 3.4, 5.25, 83.0), (2023, 2, 3.0, 5.50, 83.0), (2023, 3, 2.7, 5.75, 78.5),
    (2023, 4, 2.7, 5.75, 84.5), (2023, 5, 2.8, 5.75, 75.5),(2023, 6, 2.7, 5.75, 75.0),
    (2023, 7, 2.3, 6.00, 81.0), (2023, 8, 2.0, 6.00, 86.5),(2023, 9, 1.7, 6.00, 94.0),
    (2023, 10, 1.6, 6.00, 91.0),(2023, 11, 1.7, 6.00, 83.0),(2023, 12, 1.6, 6.00, 78.0),
    # 2024
    (2024, 1, 1.6, 6.00, 81.0), (2024, 2, 1.8, 6.00, 84.0), (2024, 3, 1.6, 6.00, 85.5),
    (2024, 4, 1.6, 6.00, 90.0), (2024, 5, 1.6, 6.00, 82.0),(2024, 6, 1.5, 6.00, 82.5),
    (2024, 7, 1.6, 6.00, 85.0), (2024, 8, 1.6, 6.00, 80.0),(2024, 9, 1.7, 5.50, 74.0),
    (2024, 10, 1.9, 5.50, 76.0),(2024, 11, 2.0, 5.25, 73.0),(2024, 12, 1.9, 5.00, 74.0),
    # 2025 (projections / first months actual where available)
    (2025, 1, 2.0, 5.00, 79.0), (2025, 2, 2.0, 5.00, 78.0), (2025, 3, 2.1, 5.00, 75.0),
    (2025, 4, 2.2, 5.00, 70.0), (2025, 5, 2.2, 5.00, 68.0),(2025, 6, 2.3, 4.75, 72.0),
    (2025, 7, 2.3, 4.75, 73.0), (2025, 8, 2.2, 4.75, 71.0),(2025, 9, 2.2, 4.50, 70.0),
    (2025, 10, 2.1, 4.50, 70.0),(2025, 11, 2.1, 4.50, 71.0),(2025, 12, 2.0, 4.50, 72.0),
    # 2026 (projections)
    (2026, 1, 2.0, 4.50, 73.0), (2026, 2, 2.0, 4.50, 74.0), (2026, 3, 2.0, 4.25, 74.0),
    (2026, 4, 2.1, 4.25, 75.0), (2026, 5, 2.1, 4.25, 76.0),(2026, 6, 2.1, 4.25, 76.0),
)


SAMA_BULLETIN_URL: Final[str] = (
    "https://www.sama.gov.sa/en-US/EconomicReports/Pages/MonthlyStatistics.aspx"
)
GASTAT_CPI_URL: Final[str] = "https://www.stats.gov.sa/en/cpi"
SAR_TO_USD_PEG: Final[float] = 0.2667


def _build_dataframe() -> pd.DataFrame:
    rows = [
        {
            "month": pd.Timestamp(year=y, month=m, day=1, tz="UTC"),
            "cpi_yoy": cpi / 100.0,
            "policy_rate": rate / 100.0,
            "brent_usd": brent,
            "sar_to_usd": SAR_TO_USD_PEG,
        }
        for (y, m, cpi, rate, brent) in _BUNDLED
    ]
    df = pd.DataFrame.from_records(rows).sort_values("month").reset_index(drop=True)

    # Derived columns
    df["brent_yoy"] = df["brent_usd"].pct_change(periods=12)
    for lag in (1, 3, 6, 12):
        df[f"cpi_yoy_lag{lag}"] = df["cpi_yoy"].shift(lag)
        df[f"policy_rate_lag{lag}"] = df["policy_rate"].shift(lag)
    # Rolling 3-month average of Brent (smooths spike volatility)
    df["brent_3m_avg_usd"] = df["brent_usd"].rolling(window=3, min_periods=1).mean()
    # Fill any leading NaNs with the first observed value to avoid NaN at training time
    df = df.bfill().ffill()
    df["year"] = df["month"].dt.year
    df["year_month"] = df["month"].dt.strftime("%Y-%m")
    return df


def fetch_macro_series() -> tuple[pd.DataFrame, FetchManifest]:
    """Return the bundled monthly KSA macro series.

    The live fetcher upgrade path is documented inline: SAMA publishes monthly Excel
    bulletins behind a portal; a real implementation would parse those for CPI YoY,
    policy rate, FX, and Brent. Until then the bundled values are kept current
    quarterly via the provenance file under ``data/seed/anchors_provenance.md``.
    """
    df = _build_dataframe()
    manifest = FetchManifest(
        source="ksa_monthly_macro",
        url=SAMA_BULLETIN_URL,
        fetched_at=fetched_now(),
        ok=True,
        rows=len(df),
        fallback=True,
        is_estimate=True,
        notes=(
            "Bundled monthly anchors from GASTAT CPI bulletins + SAMA monthly bulletins; "
            "replace with a live Excel/JSON scraper once SAMA publishes a stable feed."
        ),
        extra={"sources": [SAMA_BULLETIN_URL, GASTAT_CPI_URL]},
    )
    return df, manifest


def lookup_at(series: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    """Return the macro snapshot at or just before ``as_of`` (month granularity)."""
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    month = as_of.tz_convert("UTC").to_period("M").to_timestamp(how="start").tz_localize("UTC")
    matched = series.loc[series["month"] <= month]
    if matched.empty:
        matched = series.iloc[[0]]
    row = matched.iloc[-1]
    return {
        c: float(row[c]) if not np.isnan(row[c]) else 0.0
        for c in row.index
        if c not in {"month", "year_month"}
    }


__all__ = [
    "GASTAT_CPI_URL",
    "SAMA_BULLETIN_URL",
    "SAR_TO_USD_PEG",
    "fetch_macro_series",
    "lookup_at",
]
