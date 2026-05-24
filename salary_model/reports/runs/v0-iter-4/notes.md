# Iteration `v0-iter-4` — observations

Even with `n_cell <= 1` gating on the Bayes shrinkage, final MAE = 7100 vs Optuna
parametric MAE = 6304. The issue: with 14k training rows / 3978 possible cells, many
cells have 0 or 1 rows and our shrinkage there returns the global mean — which is
worse than the parametric prediction for those rows.

## Decision

The parametric model's family / level / region / sector / ownership / yoe / education /
... conditioning is **stronger** than a 3-factor cell mean for this anchored synthetic
data. Hierarchical empirical-Bayes shrinkage does not improve over the parametric
estimator here. The §7 design-doc rationale (shrinkage helps sparse cells) assumes the
parametric model has *less* prior conditioning than the empirical cell mean, which is
the opposite of our situation.

For v0-iter-5:
- **The v2 production prediction = parametric (Optuna + conformal) + retrieval sparse
  fallback** (i.e., today's step 6 output).
- Bayes shrinkage stays computed and stored on the bundle as a diagnostic but is not
  blended into the headline output.
- When we swap in real microdata (where anchors are weaker and the cell mean carries
  more relative information), re-enable shrinkage and reassess.
