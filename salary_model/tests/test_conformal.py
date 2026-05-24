from __future__ import annotations

import numpy as np

from salary_model.models.conformal import (
    ConformalAdjustments,
    coverage_pairs,
)


def test_coverage_pairs_maps_correctly() -> None:
    pairs = coverage_pairs((0.8, 0.9))
    assert (0.1, 0.9) in pairs
    assert (0.05, 0.95) in pairs


def test_widen_expands_intervals_symmetrically() -> None:
    adj = ConformalAdjustments(
        quantile_pairs=((0.1, 0.9),),
        offsets={(0.1, 0.9): 100.0},
    )
    raw = {0.1: np.array([10.0]), 0.5: np.array([20.0]), 0.9: np.array([30.0])}
    out = adj.widen(raw)
    assert out[0.1][0] == -90.0
    assert out[0.9][0] == 130.0


def test_widen_respects_monotonicity_after_offset() -> None:
    adj = ConformalAdjustments(
        quantile_pairs=((0.1, 0.9),),
        offsets={(0.1, 0.9): 5.0},
    )
    raw = {0.1: np.array([1.0]), 0.5: np.array([2.0]), 0.9: np.array([3.0])}
    out = adj.widen(raw)
    assert out[0.1][0] <= out[0.5][0] <= out[0.9][0]
