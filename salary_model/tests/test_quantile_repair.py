from __future__ import annotations

import numpy as np

from salary_model.models.quantile import enforce_quantile_monotonic


def test_enforce_monotonic_sorts_crossings() -> None:
    raw = {
        0.1: np.array([20.0, 30.0, 50.0]),
        0.5: np.array([15.0, 28.0, 60.0]),  # crosses with q10 in row 0
        0.9: np.array([18.0, 40.0, 70.0]),  # crosses with q50 in row 0
    }
    fixed = enforce_quantile_monotonic(raw)
    for i in range(3):
        assert fixed[0.1][i] <= fixed[0.5][i] <= fixed[0.9][i]
