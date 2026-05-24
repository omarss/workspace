"""Evaluation metrics and slice scorecards.

Implements the metrics in §12 of the design doc. Each function takes plain numpy arrays
where possible and is fully typed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def mape(y_true: np.ndarray, y_pred: np.ndarray, *, eps: float = 1.0) -> float:
    return float(np.mean(np.abs(y_true - y_pred) / np.maximum(np.abs(y_true), eps)))


def smape(y_true: np.ndarray, y_pred: np.ndarray, *, eps: float = 1.0) -> float:
    num = np.abs(y_true - y_pred)
    den = (np.abs(y_true) + np.abs(y_pred)) / 2.0
    return float(np.mean(num / np.maximum(den, eps)))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def pinball(y_true: np.ndarray, y_pred: np.ndarray, *, quantile: float) -> float:
    diff = y_true - y_pred
    loss = np.where(diff >= 0, quantile * diff, (quantile - 1.0) * diff)
    return float(np.mean(loss))


def interval_coverage(
    y_true: np.ndarray, y_low: np.ndarray, y_high: np.ndarray
) -> float:
    return float(np.mean((y_true >= y_low) & (y_true <= y_high)))


def interval_width(y_low: np.ndarray, y_high: np.ndarray) -> float:
    return float(np.mean(y_high - y_low))


@dataclass(frozen=True)
class SliceMetrics:
    name: str
    n: int
    mae: float
    mape: float
    pinball_p50: float


def slice_scorecard(
    df: pd.DataFrame,
    *,
    y_true: pd.Series,
    p50: pd.Series,
    slice_cols: list[str],
) -> pd.DataFrame:
    """Compute MAE / MAPE / pinball for each unique combination of ``slice_cols``."""
    work = pd.DataFrame(
        {
            "y_true": y_true.to_numpy(dtype=float),
            "p50": p50.to_numpy(dtype=float),
            **{c: df[c].to_numpy() for c in slice_cols},
        }
    )
    rows: list[dict[str, object]] = []
    for keys, grp in work.groupby(slice_cols, dropna=False):
        key_tuple = keys if isinstance(keys, tuple) else (keys,)
        rows.append(
            {
                **dict(zip(slice_cols, key_tuple, strict=False)),
                "n": len(grp),
                "mae": mae(grp["y_true"].to_numpy(), grp["p50"].to_numpy()),
                "mape": mape(grp["y_true"].to_numpy(), grp["p50"].to_numpy()),
                "pinball_p50": pinball(
                    grp["y_true"].to_numpy(), grp["p50"].to_numpy(), quantile=0.5
                ),
            }
        )
    return pd.DataFrame.from_records(rows).sort_values("mae", ascending=False)


def evaluate_quantiles(
    y_true: np.ndarray,
    quantile_preds: dict[float, np.ndarray],
    coverage_targets: tuple[float, ...],
) -> dict[str, float]:
    """Headline metrics across the quantile bundle."""
    out: dict[str, float] = {}
    for q, pred in quantile_preds.items():
        out[f"pinball_q{int(q * 100)}"] = pinball(y_true, pred, quantile=q)
    if 0.5 in quantile_preds:
        out["mae_p50"] = mae(y_true, quantile_preds[0.5])
        out["mape_p50"] = mape(y_true, quantile_preds[0.5])
        out["smape_p50"] = smape(y_true, quantile_preds[0.5])
        out["rmse_p50"] = rmse(y_true, quantile_preds[0.5])
    for cov in coverage_targets:
        alpha = (1.0 - cov) / 2.0
        ql, qh = round(alpha, 4), round(1.0 - alpha, 4)
        if ql in quantile_preds and qh in quantile_preds:
            out[f"coverage_{int(cov * 100)}"] = interval_coverage(
                y_true, quantile_preds[ql], quantile_preds[qh]
            )
            out[f"width_{int(cov * 100)}"] = interval_width(
                quantile_preds[ql], quantile_preds[qh]
            )
    return out
