from __future__ import annotations

import numpy as np

from salary_model.models.conformal import ConformalAdjustments


def test_asymmetric_widen_uses_per_side_offsets() -> None:
    adj = ConformalAdjustments(
        quantile_pairs=((0.1, 0.9),),
        offsets={(0.1, 0.9): 100.0},
        side_offsets={(0.1, 0.9): (50.0, 200.0)},
        asymmetric=True,
    )
    raw = {0.1: np.array([10.0]), 0.5: np.array([20.0]), 0.9: np.array([30.0])}
    out = adj.widen(raw)
    assert out[0.1][0] == -40.0   # 10 - 50
    assert out[0.9][0] == 230.0   # 30 + 200


def test_symmetric_widen_unchanged_when_asymmetric_false() -> None:
    adj = ConformalAdjustments(
        quantile_pairs=((0.1, 0.9),),
        offsets={(0.1, 0.9): 100.0},
        side_offsets=None,
        asymmetric=False,
    )
    raw = {0.1: np.array([10.0]), 0.5: np.array([20.0]), 0.9: np.array([30.0])}
    out = adj.widen(raw)
    assert out[0.1][0] == -90.0
    assert out[0.9][0] == 130.0
