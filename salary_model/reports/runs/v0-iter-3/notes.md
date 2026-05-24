# Iteration `v0-iter-3` — observations

Run timestamp: 2026-05-24, seed 17, 20k rows. Hard-gated the retrieval blend and
shrinkage to sparse cells only (`n_cell < 30`).

## Movements

| step | metric | v0-iter-2 | v0-iter-3 | Δ |
|------|--------|-----------|-----------|---|
| 6    | mae_p50 | 6396  | 6398 | 0% |
| 8    | mae_p50 | 7252  | 7720 | +6.5% (regression) |

The retrieval gate worked but the **shrinkage gate did not** — MAE actually got
*worse* despite our intent to reduce blending. Diagnosis:

We have 17 families × 18 levels × 13 regions = **3,978 possible cells**; with only
~14k training rows, the average cell density is ~3.5 rows, and many cells have between
5 and 30 rows. Our `1/(1 + n/5)` weight curve still gives 14-50% blend weight in that
range — exactly the rows whose parametric prediction (using 25+ features) is *better*
than the cell mean (which uses only 3 features).

## Conclusion

**Empirical-Bayes shrinkage on synthetic anchored data does not improve over the
parametric estimator** because the parametric estimator already uses far more
conditioning information than the cell partition can recover. Two responses:

1. For the v0 final bundle we should reserve shrinkage for cells the parametric model
   has truly never seen (n_cell == 0 or 1) — i.e. it's a true *fallback*, not a blend.
2. On real microdata (GOSI / Mercer) where the parametric anchors are weaker, the cell
   mean may carry more relative information; revisit this finding then.

## Action for v0-iter-4

- Retrieval blend: only fire when `n_cell < 5`.
- Bayes shrinkage: only fire when `n_cell <= 1`.
- Expect final MAE ≈ step 5 (Optuna tuned: 6304).
