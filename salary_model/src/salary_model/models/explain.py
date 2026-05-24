"""SHAP-based explanations for the descriptive quantile bundle.

We use the p50 booster as the canonical SHAP target — it represents the model's median
prediction, and SHAP contributions there are the most intuitive thing to surface to a
user ("what moved the median").

A :class:`SHAPExplainer` wraps a frozen ``shap.TreeExplainer`` built against the p50
booster. It is small enough to serialize into the model bundle. At inference time the
API calls :meth:`explain_row` to get the top-k per-feature contributions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class FeatureContribution:
    feature: str
    shap_value: float
    feature_value: object


@dataclass
class SHAPExplainer:
    """Lightweight wrapper over shap.TreeExplainer pinned to the p50 booster."""

    feature_columns: tuple[str, ...]
    explainer: Any  # shap.TreeExplainer; typed loosely because shap lacks stubs

    def explain_row(self, X: pd.DataFrame, *, top_k: int = 5) -> list[FeatureContribution]:
        cols = list(self.feature_columns)
        row = X[cols]
        try:
            shap_values = self.explainer.shap_values(row, check_additivity=False)
        except Exception:
            # Defensive: if SHAP fails for any reason (rare with TreeExplainer on lgbm),
            # return an empty list rather than 500-ing the API.
            return []
        if isinstance(shap_values, list):
            shap_values = shap_values[0]
        arr = np.asarray(shap_values).flatten()
        if arr.size != len(cols):
            return []
        order = np.argsort(np.abs(arr))[::-1][:top_k]
        return [
            FeatureContribution(
                feature=cols[i],
                shap_value=float(arr[i]),
                feature_value=row.iloc[0, i],
            )
            for i in order
        ]


def build_explainer(
    booster: Any,
    feature_columns: list[str],
) -> SHAPExplainer | None:
    """Build a TreeExplainer over the given p50 booster, or None if SHAP is unavailable."""
    try:
        import shap
    except ImportError:
        return None
    try:
        explainer = shap.TreeExplainer(booster)
    except Exception:
        return None
    return SHAPExplainer(
        feature_columns=tuple(feature_columns),
        explainer=explainer,
    )
