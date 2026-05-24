"""Fairness reweighting and counterfactual audit.

Reweighting follows the principle: for the recommendation head, we want sensitive groups
to be represented equally within each (family, level) cell. We compute inverse-density
weights and clip extremes to avoid blowing up by groups with tiny counts.

The counterfactual audit flips gender and is_saudi for each row, re-predicts, and
reports the gap distribution.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FairnessReport:
    median_abs_gap_pct_gender: float
    median_abs_gap_pct_nationality: float
    p90_abs_gap_pct_gender: float
    p90_abs_gap_pct_nationality: float
    per_segment: pd.DataFrame

    def to_markdown(self) -> str:
        head = (
            f"- gender median |gap|: {self.median_abs_gap_pct_gender:.2%}\n"
            f"- gender p90 |gap|: {self.p90_abs_gap_pct_gender:.2%}\n"
            f"- nationality median |gap|: {self.median_abs_gap_pct_nationality:.2%}\n"
            f"- nationality p90 |gap|: {self.p90_abs_gap_pct_nationality:.2%}\n"
        )
        return head + "\n" + self.per_segment.to_markdown(index=False)


def reweight_sensitive(
    df: pd.DataFrame,
    *,
    family_col: str = "family",
    level_col: str = "level",
    sensitive_cols: tuple[str, ...] = ("gender", "is_saudi"),
    clip: float = 5.0,
) -> pd.Series:
    """Return per-row weights that equalize sensitive groups within (family, level)."""
    counts = (
        df.groupby([family_col, level_col, *sensitive_cols])
        .size()
        .rename("n_cell")
        .reset_index()
    )
    cell_totals = counts.groupby([family_col, level_col])["n_cell"].sum().rename("n_total")
    counts = counts.merge(cell_totals, on=[family_col, level_col], how="left")
    # number of sensitive-group combinations present in each (family, level)
    n_groups = counts.groupby([family_col, level_col])[sensitive_cols[0]].transform("size")
    counts["weight"] = counts["n_total"] / (counts["n_cell"] * n_groups)
    merged = df.merge(
        counts[[family_col, level_col, *sensitive_cols, "weight"]],
        on=[family_col, level_col, *sensitive_cols],
        how="left",
    )
    weight = merged["weight"].clip(lower=1.0 / clip, upper=clip).fillna(1.0)
    return weight.astype(float).reset_index(drop=True)


def counterfactual_audit(
    predict_p50: pd.Series,
    flipped_predict_p50_gender: pd.Series,
    flipped_predict_p50_nationality: pd.Series,
    *,
    family: pd.Series,
    level: pd.Series,
) -> FairnessReport:
    """Compare predictions before and after flipping a sensitive attribute."""
    gap_gender = (flipped_predict_p50_gender - predict_p50) / predict_p50
    gap_nat = (flipped_predict_p50_nationality - predict_p50) / predict_p50
    seg = pd.DataFrame(
        {
            "family": family.values,
            "level": level.values,
            "abs_gap_gender": gap_gender.abs().values,
            "abs_gap_nationality": gap_nat.abs().values,
        }
    )
    per_segment = (
        seg.groupby(["family", "level"])
        .agg(
            median_gender=("abs_gap_gender", "median"),
            median_nat=("abs_gap_nationality", "median"),
            n=("abs_gap_gender", "size"),
        )
        .reset_index()
        .sort_values("median_gender", ascending=False)
    )
    return FairnessReport(
        median_abs_gap_pct_gender=float(np.nanmedian(gap_gender.abs())),
        median_abs_gap_pct_nationality=float(np.nanmedian(gap_nat.abs())),
        p90_abs_gap_pct_gender=float(np.nanquantile(gap_gender.abs(), 0.9)),
        p90_abs_gap_pct_nationality=float(np.nanquantile(gap_nat.abs(), 0.9)),
        per_segment=per_segment,
    )
