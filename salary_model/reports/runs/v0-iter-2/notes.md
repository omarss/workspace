# Iteration `v0-iter-2` — observations

Run timestamp: 2026-05-24, seed 17, 20k rows. Iterating on v0-iter findings.

## Changes from v0-iter

1. **Step 1 single-point model**: switched `objective=huber` (with miscalibrated alpha)
   to `objective=regression_l1`.
2. **Step 6 retrieval**: batched the kNN search (single call for the whole test set with
   k=200), filtered by region per-row, fell back to unfiltered if < 20 in-region.
3. **Step 8 shrinkage weight**: reduced from `1/(1 + n/30)` to `1/(1 + n/5)`.

## Movements

| step | metric | v0-iter | v0-iter-2 | Δ |
|------|--------|---------|-----------|---|
| 1    | mae_p50 | 11334 | 6282 | **-44%** |
| 1    | elapsed | 42.70 | 14.80 | -65% |
| 6    | mae_p50 | 6832  | 6396 | **-6.4%** |
| 6    | elapsed | 14.15 | 1.03  | **-93%** |
| 8    | mae_p50 | 7774  | 7252 | -6.7% |

Step 0 (Ridge) and steps 2-5 unchanged (same seed and feature set).

## What still does not work

- **Retrieval blend still hurts overall MAE** (6280 baseline → 6396 with blend). Two
  hypotheses:
  1. The blend policy fires too often: any row with fewer than 50 in-region neighbors
     blends with weight 0.6 parametric, 0.4 retrieval — and the retrieval estimate is
     just the recency-weighted median of nearby rows in the projected feature space,
     which is noisier than the LightGBM point estimate for dense segments.
  2. We treat retrieval as a global blend rather than a *sparse-segment fallback*. The
     §10 policy says "lean on parametric ≥ 50, blend 20-49, retrieval-heavy < 20" —
     but with 14k training rows and 13 regions, almost every test row gets 50+
     neighbors. So the blend should rarely fire — but it's still degrading MAE because
     it triggers on the unfiltered-fallback path for sparse regions.
  - Plan: gate retrieval blend behind `parametric_uncertainty_high` flag (large
    p90-p10 width relative to segment), not just neighbor count.

- **Bayes shrinkage still hurts** (6396 → 7252). With `1/(1 + n/5)`, even n=30 still
  gives 14% weight on the empirical cell mean — which only conditions on
  (family, level, region), discarding sector/ownership/yoe/skills information that the
  parametric model uses. Plan: gate shrinkage as `w_shrink = 1.0 if n_cell < 30 else
  0.0` to make it a pure sparse-cell fallback.

## Action items for iteration 3 (`v0-iter-3`)

1. Hard-gate the Bayes shrinkage to only apply when `n_cell < 30`.
2. Hard-gate the retrieval blend to only fire when the parametric interval is
   particularly wide (use a per-segment threshold).
3. Re-run and confirm MAE monotonically improves across steps 6, 7, 8.

## Open questions

- The Optuna sweep finds slightly *worse* parameters than defaults (mae 6304 vs 6280).
  Suggests the default LightGBM config is well-tuned for our anchored synthetic data;
  larger sweep won't help. Once we have real microdata this may flip.
- The fairness audit results are identical between v0-iter and v0-iter-2 because the
  recommendation head training is identical. Will only move when we change the blinded
  feature set or the reweighting scheme.

## Wall-clock

Full ladder: **~400 s** (down from 510). Optuna with 4 trials still dominates (238 s).
