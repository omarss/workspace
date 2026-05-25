"""Live GASTAT wage index, derived from KAPSARC's main-labor-market-indicators.

This module is the **first live wage anchor in the project** — every value below
comes from a published GASTAT figure pulled at runtime, not from my best-effort
recall. The manifest correctly carries ``is_estimate=False`` when the network is
reachable.

The upstream KAPSARC dataset exposes:

- "Average Monthly Wages of Paid employees (main job) (+15) years" — total, M, F
- "Average Monthly Wages of Paid Saudi employee (main job)(+15) years" — Saudi-only

We normalize to a single ``WageIndex`` table with ``(year, gender, is_saudi)``
keys + the published SAR/month average. Consumers can:

- look up an anchor: :func:`lookup_wage`
- compute the published gender gap: :func:`gender_gap_pct`
- compute the published Saudi/non-Saudi gap: :func:`saudi_gap_pct`

We use these in two places:

1. The synthetic generator can be re-anchored to the live mean (not yet wired —
   the synthetic generator stays decoupled in v0; this is a v1 hook).
2. The fairness audit compares the descriptive head's counterfactual gap to the
   published gap — if our model says the gender gap is 3% but GASTAT says 7%,
   that's a "needs investigation" signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from salary_model.config import get_logger
from salary_model.data.sources._common import FetchManifest, fetched_now
from salary_model.data.sources.kapsarc import fetch_kapsarc_main_labor

log = get_logger("salary_model.data.sources.wage_index_live")

Gender = Literal["Males", "Females", "Total"]

_WAGE_TOTAL = "Average Monthly Wages of Paid employees"
_WAGE_SAUDI = "Average Monthly Wages of Paid Saudi employee"


@dataclass(frozen=True)
class WageAnchor:
    year: int
    gender: Gender
    is_saudi: bool   # True = Saudi-only series; False = all employees (Saudi + expat)
    wage_sar_monthly: float
    n_quarters_observed: int


def _classify_indicator(name: str) -> tuple[bool, bool] | None:
    """Return ``(is_wage, is_saudi)`` if the indicator is a wage line, else None."""
    if _WAGE_SAUDI.lower() in name.lower():
        return (True, True)
    if _WAGE_TOTAL.lower() in name.lower():
        return (True, False)
    return None


def _safe_year(period: object) -> int | None:
    if pd.isna(period):
        return None
    match = re.search(r"\d{4}", str(period))
    return int(match.group(0)) if match else None


def build_wage_index() -> tuple[pd.DataFrame, FetchManifest]:
    """Pull the live KAPSARC indicators and reduce to a per-year wage table.

    Returns ``(table, manifest)`` where ``table`` has columns
    ``year, gender, is_saudi, wage_sar_monthly, n_quarters_observed``.
    """
    raw, sub_manifest = fetch_kapsarc_main_labor()
    if raw.empty or not sub_manifest.ok:
        empty = pd.DataFrame(
            columns=["year", "gender", "is_saudi", "wage_sar_monthly", "n_quarters_observed"]
        )
        manifest = FetchManifest(
            source="kapsarc_wage_index_live",
            url=sub_manifest.url,
            fetched_at=fetched_now(),
            ok=False,
            rows=0,
            fallback=True,
            is_estimate=True,
            notes="upstream KAPSARC indicators fetch failed",
        )
        return empty, manifest

    df = raw.copy()
    df["year"] = df["time_period"].apply(_safe_year)
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    df["_class"] = df["indicator"].apply(_classify_indicator)
    df = df.dropna(subset=["_class"])
    df["is_saudi"] = df["_class"].apply(lambda t: t[1])

    agg = (
        df.groupby(["year", "gender", "is_saudi"], dropna=False)
        .agg(wage_sar_monthly=("indicator_value", "mean"),
             n_quarters_observed=("indicator_value", "size"))
        .reset_index()
        .sort_values(["year", "is_saudi", "gender"])
    )
    manifest = FetchManifest(
        source="kapsarc_wage_index_live",
        url=sub_manifest.url,
        fetched_at=fetched_now(),
        ok=True,
        rows=len(agg),
        fallback=False,
        is_estimate=False,
        notes=(
            f"derived from {len(df)} wage rows in main-labor-market-indicators; "
            f"years {int(agg['year'].min())}-{int(agg['year'].max())}"
        ),
    )
    return agg, manifest


def lookup_wage(
    table: pd.DataFrame, *, year: int, gender: Gender, is_saudi: bool,
) -> float | None:
    """Return SAR/month for the requested cell, or None if missing."""
    if table.empty:
        return None
    mask = (
        (table["year"] == year)
        & (table["gender"] == gender)
        & (table["is_saudi"] == is_saudi)
    )
    sub = table.loc[mask, "wage_sar_monthly"]
    if sub.empty:
        # Fallback: most-recent year for that (gender, is_saudi) pair
        fallback = table.loc[
            (table["gender"] == gender) & (table["is_saudi"] == is_saudi),
            "wage_sar_monthly",
        ]
        if fallback.empty:
            return None
        return float(fallback.iloc[-1])
    return float(sub.iloc[0])


def gender_gap_pct(
    table: pd.DataFrame, *, year: int | None = None, saudi_only: bool = False,
) -> float | None:
    """Published female-vs-male wage gap. Negative = female earns less.

    Args:
        year: defaults to the most recent year present in the table.
        saudi_only: when True, computes the gap for the Saudi-only series rather
            than the all-employees aggregate. KSA's all-population gap is small
            (~1% in 2020) but the Saudi-only gap is much larger (~16%), so the
            choice matters for the truth-check interpretation.
    """
    if table.empty:
        return None
    use_year = year if year is not None else int(table["year"].max())
    male = lookup_wage(table, year=use_year, gender="Males", is_saudi=saudi_only)
    female = lookup_wage(table, year=use_year, gender="Females", is_saudi=saudi_only)
    if male is None or female is None or male == 0:
        return None
    return float((female - male) / male)


def saudi_gap_pct(table: pd.DataFrame, *, year: int | None = None) -> float | None:
    """Published Saudi-vs-non-Saudi wage gap (Saudi vs full-population avg).

    KAPSARC publishes Saudi-only and total (Saudi + non-Saudi) wage series. We
    derive the Saudi-vs-non-Saudi gap by treating the Saudi series as one cohort
    and inferring the non-Saudi mean from the total + Saudi headcount weights.
    For v0 we report ``(saudi_total - all_total) / all_total`` as a simpler proxy.
    """
    if table.empty:
        return None
    use_year = year if year is not None else int(table["year"].max())
    saudi_total = lookup_wage(table, year=use_year, gender="Total", is_saudi=True)
    all_total = lookup_wage(table, year=use_year, gender="Total", is_saudi=False)
    if saudi_total is None or all_total is None or all_total == 0:
        return None
    return float((saudi_total - all_total) / all_total)


__all__ = [
    "WageAnchor",
    "build_wage_index",
    "gender_gap_pct",
    "lookup_wage",
    "saudi_gap_pct",
]
