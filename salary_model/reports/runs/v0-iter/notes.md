# Iteration `v0-iter` — observations

Run timestamp: 2026-05-24, seed 17, 20k rows synthetic-anchored.

## What worked

- **Ridge baseline** is unexpectedly competitive on MAE (6011 SAR) — sets a strong floor.
- **Conformal calibration** lifted 80% coverage from 0.734 to 0.898 with no MAE penalty
  (mae_p50 unchanged), while widening intervals by ~32%. This is the textbook split-CP
  trade-off; observed coverage matches the target almost exactly.
- **Optuna sweep** (6 trials) found near-identical parameters to the defaults — the
  default LightGBM config is well-suited to this dataset. Suggests we don't need a
  larger sweep budget yet.
- **Fairness architecture worked as designed**:
  - Descriptive head gender |gap|: 3.71%, nationality |gap|: 6.06% (the seeded bias in
    the synthetic generator surfaces correctly).
  - Recommendation head (blinded + reweighted) gender |gap|: 0.00%, nationality |gap|:
    0.00%. The blinded feature view literally cannot condition on these attributes, so
    the gap collapses to zero.

## What did not work

- **LightGBM Huber single-point** regressed MAE from 6011 (ridge) → 11334 (LGBM Huber).
  Root cause: `alpha=0.9` on the huber objective sets a threshold of 0.9 SAR — far below
  typical residual scale (thousands of SAR), collapsing the quadratic region. Fix
  already applied: switched to `objective=regression_l1` (MAE loss) which is more
  stable and aligns with what we measure.
- **Retrieval blend** worsened MAE from 6280 → 6832 (+9%). Hypothesis: with k=50
  neighbors but a strict region filter, many test rows end up with very few in-region
  neighbors, triggering the high-retrieval-weight blend with noisy estimates. Plan:
  expand neighbor pool before filtering, or allow same-metro fallback (Riyadh/Eastern
  share many traits).
- **Bayes shrinkage (empirical fallback)** further degraded MAE to 7774. The shrinkage
  weight `1/(1 + n_cell/30)` still has substantial mass for dense cells (n=30 gives
  w=0.5). Plan: reduce to `1/(1 + n_cell/5)` so dense cells barely shrink, then verify
  it only helps sparse-cell predictions.

## Action items for iteration 2 (`v0-iter-2`)

1. Verify the `regression_l1` fix lifts the Huber single-point model above Ridge.
2. Expand retrieval pool: `k=200` initial, region filter, fall back to no filter if
   fewer than 20 in-region neighbors.
3. Reduce Bayes shrinkage aggressiveness; only blend in cells with `n_cell < 30`.

## Numbers worth remembering

- Best MAE so far: **6280 SAR** (LGBM quantile, conformal-calibrated)
- Best MAPE so far: **0.324** (essentially tied between Ridge, LGBM quantile, Optuna)
- Best coverage match: **80.0% target → 89.8% observed** (conformal); arguably too
  wide — conformal symmetric widening overshoots when residuals are heavy-tailed. Could
  consider asymmetric CP in a later iteration.

## Wall-clock budget

Full ladder: **~510 s** on 9 cores (over the 5-min target). The Optuna step (319 s) and
LGBM quantile (61 s) dominate. Acceptable; can be reduced by halving Optuna trials when
iterating quickly.
