"""Conformal calibration on top of LightGBM quantile predictions.

Two variants:

* **Symmetric** split-conformal (legacy): one offset per coverage target, applied to
  both sides equally. Simple, but over-covers on heavy-tailed data because the worst
  tail dominates the offset.
* **Asymmetric** split-conformal (default): independent offsets per side; each side is
  calibrated at half the miscoverage budget. Marginal coverage still holds (by union
  bound, with a small conservatism penalty) but the intervals are tighter when the
  residual distribution is skewed.

Both variants emit a :class:`ConformalAdjustments` object whose :meth:`widen` applies
the offsets and repairs any quantile crossings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from salary_model.models.quantile import QuantileBundle


@dataclass(frozen=True)
class ConformalAdjustments:
    """Per-coverage-level conformal offsets.

    Symmetric variant uses ``offsets[(q_low, q_high)] = single_offset`` (applied to
    both sides). Asymmetric variant uses ``side_offsets`` instead.
    """

    quantile_pairs: tuple[tuple[float, float], ...]
    offsets: dict[tuple[float, float], float]
    side_offsets: dict[tuple[float, float], tuple[float, float]] | None = None
    asymmetric: bool = False

    def widen(self, quantiles: dict[float, np.ndarray]) -> dict[float, np.ndarray]:
        """Apply the calibration offsets to a quantile prediction dict."""
        out = {q: arr.copy() for q, arr in quantiles.items()}
        if self.asymmetric and self.side_offsets is not None:
            for (q_low, q_high), (lo_off, hi_off) in self.side_offsets.items():
                if q_low in out:
                    out[q_low] = out[q_low] - lo_off
                if q_high in out:
                    out[q_high] = out[q_high] + hi_off
        else:
            for (q_low, q_high), offset in self.offsets.items():
                if q_low in out:
                    out[q_low] = out[q_low] - offset
                if q_high in out:
                    out[q_high] = out[q_high] + offset
        # repair any crossings introduced by independent adjustment
        from salary_model.models.quantile import enforce_quantile_monotonic
        return enforce_quantile_monotonic(out)


def coverage_pairs(coverage_targets: tuple[float, ...]) -> tuple[tuple[float, float], ...]:
    """Map coverage targets (e.g. 0.8, 0.9) to quantile pairs in our bundle."""
    pairs: list[tuple[float, float]] = []
    for c in coverage_targets:
        alpha = (1.0 - c) / 2.0
        pairs.append((round(alpha, 4), round(1.0 - alpha, 4)))
    return tuple(pairs)


def _empirical_quantile(values: np.ndarray, q: float) -> float:
    """Distribution-free quantile with a small finite-sample correction.

    For a calibration set of size n, the split-conformal quantile is
    ``ceil((n+1) * q) / n`` to retain the marginal coverage guarantee. We clip to
    [0, 1] in case n is tiny.
    """
    n = values.size
    if n == 0:
        return 0.0
    rank = min(max(int(np.ceil((n + 1) * q)) - 1, 0), n - 1)
    return float(np.sort(values)[rank])


def calibrate(
    bundle: QuantileBundle,
    X_cal: pd.DataFrame,
    y_cal: pd.Series,
    coverage_targets: tuple[float, ...],
    *,
    asymmetric: bool = True,
) -> ConformalAdjustments:
    """Compute per-side (asymmetric, default) or symmetric widening offsets."""
    preds = bundle.predict_quantiles(X_cal)
    y = y_cal.astype(float).to_numpy()
    pairs = coverage_pairs(coverage_targets)

    sym_offsets: dict[tuple[float, float], float] = {}
    side_offsets: dict[tuple[float, float], tuple[float, float]] = {}

    for q_low, q_high in pairs:
        if q_low not in preds or q_high not in preds:
            continue
        lo = preds[q_low]
        hi = preds[q_high]
        coverage = q_high - q_low
        miscoverage = 1.0 - coverage
        # Asymmetric: charge each tail half the miscoverage; coverage is preserved.
        lo_residual = np.clip(lo - y, 0.0, None)
        hi_residual = np.clip(y - hi, 0.0, None)
        lo_off = _empirical_quantile(lo_residual, 1.0 - miscoverage / 2.0)
        hi_off = _empirical_quantile(hi_residual, 1.0 - miscoverage / 2.0)
        side_offsets[(q_low, q_high)] = (max(lo_off, 0.0), max(hi_off, 0.0))

        # Symmetric (legacy): single offset from the max-side residual.
        sym_residual = np.maximum(lo - y, y - hi)
        sym_target = 1.0 - miscoverage
        sym_off = _empirical_quantile(sym_residual, sym_target)
        sym_offsets[(q_low, q_high)] = max(sym_off, 0.0)

    return ConformalAdjustments(
        quantile_pairs=pairs,
        offsets=sym_offsets,
        side_offsets=side_offsets if asymmetric else None,
        asymmetric=asymmetric,
    )
