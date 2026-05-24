"""Retrieval/comparable-records head.

A nearest-neighbor index over engineered features. We project the categorical & numeric
feature space into a unit-norm float matrix and use brute-force cosine search
(``sklearn.neighbors.NearestNeighbors``). The dataset size for v1 is small enough that
brute force is fine; swap in FAISS when we exceed a few hundred thousand rows.

The composite similarity is currently a single cosine score in the projected space, with
an exact-match filter on region applied first via a candidate-pool restriction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from salary_model.features.build import CATEGORICAL_FEATURES, NUMERIC_FEATURES


@dataclass(frozen=True)
class RetrievalIndex:
    """Pre-built nearest-neighbor index over the training set."""

    feature_columns: tuple[str, ...]
    scaler: StandardScaler
    nn: NearestNeighbors
    base_values: np.ndarray   # training targets (base_monthly)
    tcc_values: np.ndarray    # training targets (tcc_monthly)
    region_codes: np.ndarray  # for exact-filter pruning
    confidences: np.ndarray
    observed_ats: np.ndarray  # int days since epoch


def build_index(
    X_train: pd.DataFrame,
    y_base: pd.Series,
    y_tcc: pd.Series,
    *,
    region_codes: pd.Series,
    confidences: pd.Series,
    observed_at: pd.Series,
) -> RetrievalIndex:
    cols = list(CATEGORICAL_FEATURES) + list(NUMERIC_FEATURES)
    scaler = StandardScaler(with_mean=True, with_std=True)
    Z = scaler.fit_transform(X_train[cols].to_numpy(dtype=float))
    nn = NearestNeighbors(n_neighbors=50, metric="cosine", algorithm="brute")
    nn.fit(Z)
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    days = (pd.to_datetime(observed_at, utc=True) - epoch).dt.days.to_numpy()
    return RetrievalIndex(
        feature_columns=tuple(cols),
        scaler=scaler,
        nn=nn,
        base_values=y_base.astype(float).to_numpy(),
        tcc_values=y_tcc.astype(float).to_numpy(),
        region_codes=region_codes.astype(int).to_numpy(),
        confidences=confidences.astype(float).to_numpy(),
        observed_ats=days,
    )


def search(
    index: RetrievalIndex,
    X_query: pd.DataFrame,
    *,
    k: int = 50,
    query_region_code: int | None = None,
) -> list[dict[str, np.ndarray]]:
    """Return up to ``k`` neighbors per query row, optionally filtering by region."""
    cols = list(index.feature_columns)
    Z = index.scaler.transform(X_query[cols].to_numpy(dtype=float))
    distances, indices = index.nn.kneighbors(Z, n_neighbors=k)

    out: list[dict[str, np.ndarray]] = []
    for d_row, idx_row in zip(distances, indices, strict=True):
        d_sel = d_row
        idx_sel = idx_row
        if query_region_code is not None:
            mask = index.region_codes[idx_sel] == query_region_code
            if mask.any():
                idx_sel = idx_sel[mask]
                d_sel = d_sel[mask]
        out.append(
            {
                "distance": d_sel,
                "base": index.base_values[idx_sel],
                "tcc": index.tcc_values[idx_sel],
                "confidence": index.confidences[idx_sel],
                "days": index.observed_ats[idx_sel],
                "indices": idx_sel,
            }
        )
    return out


def retrieval_quantiles(
    neighbors: dict[str, np.ndarray],
    *,
    quantiles: tuple[float, ...],
    target: str = "base",
    half_life_days: float = 365.0,
) -> dict[float, float]:
    """Compute recency- and confidence-weighted quantiles over a neighbor set."""
    values = neighbors[target]
    if values.size == 0:
        return {q: float("nan") for q in quantiles}
    age_days = float(np.max(neighbors["days"])) - neighbors["days"]
    recency_w = np.power(0.5, age_days / half_life_days)
    weights = recency_w * neighbors["confidence"]
    weights = np.clip(weights, 1e-6, None)
    weights = weights / weights.sum()
    order = np.argsort(values)
    sorted_vals = values[order]
    sorted_w = weights[order]
    cum = np.cumsum(sorted_w)
    out: dict[float, float] = {}
    for q in quantiles:
        idx = int(np.searchsorted(cum, q, side="left"))
        idx = min(idx, len(sorted_vals) - 1)
        out[q] = float(sorted_vals[idx])
    return out
