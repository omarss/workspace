"""Blend parametric quantile predictions with retrieval-based comparables.

The policy is the one specified in §10 of the design document:

* ``n_comparables >= 50``: lean on parametric (weight 1.0); show retrieval as social proof.
* ``20 <= n_comparables < 50``: blend ``0.6 * parametric + 0.4 * retrieval``.
* ``n_comparables < 20``: blend ``0.3 * parametric + 0.7 * retrieval``.
* ``n_comparables < 5``: refuse to produce a recommendation; descriptive quantiles only.

Returned warnings carry forward to the API response.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from salary_model.config import get_settings


@dataclass(frozen=True)
class BlendedPrediction:
    quantiles: dict[float, float]
    n_comparables: int
    warnings: tuple[str, ...]
    parametric_weight: float


def blend_quantiles(
    parametric: dict[float, float],
    retrieval: dict[float, float] | None,
    *,
    n_comparables: int,
) -> BlendedPrediction:
    settings = get_settings()
    warnings: list[str] = []

    if retrieval is None or n_comparables == 0:
        return BlendedPrediction(
            quantiles=dict(parametric),
            n_comparables=0,
            warnings=("no_comparables",),
            parametric_weight=1.0,
        )

    if n_comparables >= settings.retrieval_min_strong:
        w_param = 1.0
    elif n_comparables >= settings.retrieval_min_blend:
        w_param = 0.6
    elif n_comparables >= settings.retrieval_min_recommend:
        w_param = 0.3
        warnings.append("low_n_segment")
    else:
        w_param = 1.0
        warnings.append("very_low_n_segment_no_recommendation")
        return BlendedPrediction(
            quantiles=dict(parametric),
            n_comparables=n_comparables,
            warnings=tuple(warnings),
            parametric_weight=w_param,
        )

    blended: dict[float, float] = {}
    for q, p_val in parametric.items():
        r_val = retrieval.get(q, np.nan)
        if np.isnan(r_val):
            blended[q] = p_val
        else:
            blended[q] = w_param * p_val + (1.0 - w_param) * r_val
    return BlendedPrediction(
        quantiles=blended,
        n_comparables=n_comparables,
        warnings=tuple(warnings),
        parametric_weight=w_param,
    )
