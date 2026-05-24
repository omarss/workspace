"""Ridge baseline on log(target). Always trained; serves as the drift floor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


@dataclass(frozen=True)
class BaselineModel:
    pipeline: Pipeline
    feature_columns: tuple[str, ...]
    categorical_columns: tuple[str, ...]
    target: str

    def predict_log(self, X: pd.DataFrame) -> np.ndarray:
        return cast("np.ndarray", self.pipeline.predict(X[list(self.feature_columns)]))

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return cast("np.ndarray", np.expm1(self.predict_log(X)))

    def save(self, path: str) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: str) -> BaselineModel:
        obj = joblib.load(path)
        if not isinstance(obj, BaselineModel):
            msg = f"loaded object is not BaselineModel: {type(obj).__name__}"
            raise TypeError(msg)
        return obj


def train_baseline(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    feature_columns: list[str],
    categorical_columns: list[str],
    target: str,
    weights: pd.Series | None = None,
) -> BaselineModel:
    """Fit a one-hot + scaled-numeric + RidgeCV pipeline on log1p(y)."""
    numeric_columns = [c for c in feature_columns if c not in categorical_columns]
    from sklearn.compose import ColumnTransformer  # local to avoid heavy import at module load

    onehot = OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    pre = ColumnTransformer(
        transformers=[
            ("cat", onehot, categorical_columns),
            ("num", StandardScaler(), numeric_columns),
        ],
        remainder="drop",
    )
    pipe = Pipeline(
        [
            ("pre", pre),
            ("ridge", RidgeCV(alphas=(0.1, 0.3, 1.0, 3.0, 10.0, 30.0))),
        ]
    )
    y_log = np.log1p(y.astype(float).to_numpy())
    sw = None if weights is None else weights.astype(float).to_numpy()
    pipe.fit(X[feature_columns], y_log, ridge__sample_weight=sw)
    return BaselineModel(
        pipeline=pipe,
        feature_columns=tuple(feature_columns),
        categorical_columns=tuple(categorical_columns),
        target=target,
    )
