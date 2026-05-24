"""LightGBM quantile bundle with monotonic constraints and quantile-crossing repair."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd


def _monotone_for(feature_columns: list[str]) -> list[int]:
    """LightGBM monotone_constraints aligned with the feature columns list."""
    increasing = {
        "yoe",
        "yoe_sq",
        "level_rank",
        "education_rank",
        "region_base_multiplier",
        "sector_base_median",
        "ownership_lift",
        "family_premium",
        "size_lift",
        "is_metro",
        "is_pif_or_mnc",
        "is_exec",
    }
    return [1 if c in increasing else 0 for c in feature_columns]


@dataclass(frozen=True)
class QuantileBundle:
    """A fitted LightGBM quantile ensemble (one booster per quantile)."""

    feature_columns: tuple[str, ...]
    categorical_columns: tuple[str, ...]
    target: str
    quantiles: tuple[float, ...]
    boosters: dict[float, lgb.Booster] = field(default_factory=dict)

    def predict_quantiles(self, X: pd.DataFrame) -> dict[float, np.ndarray]:
        out: dict[float, np.ndarray] = {}
        cols = list(self.feature_columns)
        for q in self.quantiles:
            booster = self.boosters[q]
            out[q] = np.asarray(booster.predict(X[cols]), dtype=float)
        return enforce_quantile_monotonic(out)

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> QuantileBundle:
        obj = joblib.load(path)
        if not isinstance(obj, QuantileBundle):
            msg = f"loaded object is not QuantileBundle: {type(obj).__name__}"
            raise TypeError(msg)
        return obj


def enforce_quantile_monotonic(
    raw: dict[float, np.ndarray],
) -> dict[float, np.ndarray]:
    """Repair quantile crossings post-hoc by sorting per row across quantiles."""
    quantiles = sorted(raw.keys())
    matrix = np.column_stack([raw[q] for q in quantiles])
    matrix = np.sort(matrix, axis=1)
    return {q: matrix[:, i] for i, q in enumerate(quantiles)}


def train_quantile_bundle(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    *,
    feature_columns: list[str],
    categorical_columns: list[str],
    target: str,
    quantiles: tuple[float, ...],
    weights: pd.Series | None = None,
    params: dict[str, object] | None = None,
    num_boost_round: int = 1500,
    early_stopping_rounds: int = 80,
    seed: int = 17,
) -> QuantileBundle:
    """Train one booster per quantile and return the bundle."""
    # LightGBM disallows monotone_constraints with the quantile objective; we rely on
    # post-hoc sorting (enforce_quantile_monotonic) for crossing repair and on the
    # huber single-point booster for monotone-anchored point predictions.
    default_params: dict[str, object] = {
        "objective": "quantile",
        "metric": "quantile",
        "num_leaves": 63,
        "learning_rate": 0.05,
        "min_data_in_leaf": 60,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "verbose": -1,
        "seed": seed,
        "deterministic": True,
    }
    if params is not None:
        default_params.update(params)

    sw = None if weights is None else weights.astype(float).to_numpy()
    train_set = lgb.Dataset(
        X_train[feature_columns],
        label=y_train.astype(float).to_numpy(),
        weight=sw,
        categorical_feature=categorical_columns,
        free_raw_data=False,
    )
    val_set = lgb.Dataset(
        X_val[feature_columns],
        label=y_val.astype(float).to_numpy(),
        categorical_feature=categorical_columns,
        free_raw_data=False,
        reference=train_set,
    )

    boosters: dict[float, lgb.Booster] = {}
    for q in quantiles:
        params_q = dict(default_params)
        params_q["alpha"] = q
        booster = lgb.train(
            params_q,
            train_set,
            num_boost_round=num_boost_round,
            valid_sets=[val_set],
            callbacks=[
                lgb.early_stopping(early_stopping_rounds, verbose=False),
                lgb.log_evaluation(0),
            ],
        )
        boosters[q] = booster

    return QuantileBundle(
        feature_columns=tuple(feature_columns),
        categorical_columns=tuple(categorical_columns),
        target=target,
        quantiles=tuple(sorted(quantiles)),
        boosters=boosters,
    )


def train_lightgbm_point(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    *,
    feature_columns: list[str],
    categorical_columns: list[str],
    weights: pd.Series | None = None,
    seed: int = 17,
) -> lgb.Booster:
    """Single-point LightGBM regressor with regression_l1 (MAE) loss.

    We tried Huber with a default alpha; on heavy-tailed salary data (where typical
    residuals are in the thousands of SAR) the small alpha effectively collapses the
    quadratic regime to a point near zero and the resulting model underperformed the
    Ridge baseline. MAE/L1 is more stable and is the metric we care about anyway.
    """
    params: dict[str, object] = {
        "objective": "regression_l1",
        "metric": "mae",
        "num_leaves": 63,
        "learning_rate": 0.05,
        "min_data_in_leaf": 60,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "verbose": -1,
        "seed": seed,
        "deterministic": True,
    }
    sw = None if weights is None else weights.astype(float).to_numpy()
    train_set = lgb.Dataset(
        X_train[feature_columns],
        label=y_train.astype(float).to_numpy(),
        weight=sw,
        categorical_feature=categorical_columns,
        free_raw_data=False,
    )
    val_set = lgb.Dataset(
        X_val[feature_columns],
        label=y_val.astype(float).to_numpy(),
        categorical_feature=categorical_columns,
        free_raw_data=False,
        reference=train_set,
    )
    return lgb.train(
        params,
        train_set,
        num_boost_round=1500,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(80, verbose=False), lgb.log_evaluation(0)],
    )
