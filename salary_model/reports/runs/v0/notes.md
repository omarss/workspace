# v0 final — iteration journey summary

The `v0` run is the cleanest reproducible snapshot of the production-quality v2 model
after five iterations on the modeling ladder. Same seed (17), same anchored synthetic
dataset, but the iteration history is preserved under `reports/runs/v0-iter-*/notes.md`
for posterity.

## Final headline numbers (step 8 = v2_final)

| metric                          | value                          |
|---------------------------------|--------------------------------|
| mae_p50                         | **6,360 SAR/month**            |
| mape_p50                        | **32.9%**                      |
| smape_p50                       | 30.9%                          |
| 80% interval coverage           | **89.8%** (target 80% — wider than required, marginal coverage guarantee holds) |
| 80% interval width              | 22,992 SAR                     |
| descriptive gender |gap| median | 3.17% (the seeded bias surfaces correctly) |
| descriptive nationality |gap| median | 6.10%                     |
| recommendation gender |gap| median   | **0.00%** (blinded model literally cannot condition on gender) |
| recommendation nationality |gap| median | **0.00%**              |
| Bayes-only diagnostic mae       | 8,297 SAR (worse than parametric — confirmed empirically) |

## Iteration journey

| iter | hypothesis tested | mae before → after (final step) | conclusion |
|------|--------------------|-------------------------------|------------|
| v0-iter   | first full ladder run                                     | n/a → 7,774 | huber single-point underperforms ridge (bug); retrieval + Bayes blends too aggressive |
| v0-iter-2 | `regression_l1` instead of mis-α `huber`; batched retrieval; lighter shrinkage | 7,774 → 7,252 | huge fix on step 1 (-44%); retrieval 14x faster; shrinkage still hurts |
| v0-iter-3 | hard-gate retrieval to `n_cell < 30`                       | 7,252 → 7,720 | retrieval gating helped a hair; shrinkage *worse* (regression) |
| v0-iter-4 | hard-gate shrinkage to `n_cell ≤ 1`                        | 7,720 → 7,100 | better but still worse than parametric; cells with 0 train rows get the global mean |
| v0-iter-5 | Bayes shrinkage off the prediction path; diagnostic only   | 7,100 → 6,360 | converged; v2_final = parametric (Optuna+conformal) + retrieval sparse fallback |
| v0        | same as iter-5, plus serialized category-code mapping in the bundle for the API | identical → 6,360 | reproducibility + API works end-to-end |

## Headline finding worth remembering

On the *anchored synthetic* dataset, the parametric quantile model (LightGBM + Optuna +
conformal) is already at or near the data-noise floor. Empirical-Bayes shrinkage on
coarse (family, level, region) cells **adds noise** because the parametric model already
conditions on far more information than that 3-factor cell mean. **This finding is
specific to the synthetic data and may invert on real microdata** (e.g. GOSI / MUDAD)
where the parametric anchors are weaker — revisit when real microdata becomes available.

## What ships in the v0 bundle

`artifacts/model_bundle_latest.joblib` contains:

- `descriptive_bundle` — LightGBM quantile ensemble (5 quantiles), trained on full
  features including sensitive attributes; for market-descriptive output.
- `descriptive_conformal` — split-conformal widening offsets for 80% / 90% coverage.
- `recommendation_bundle` — same architecture, trained on the blinded feature view
  with sensitive-group reweighting; for fair-recommendation output.
- `recommendation_conformal` — corresponding offsets.
- `retrieval_index` — FAISS-style brute-force kNN over the training set; produces
  comparable-records lists and a sparse-cell fallback prediction.
- `bayes_shrinkage` — empirical posterior means by (family, level, region); diagnostic
  only, not blended into the headline prediction.
- `category_codes` — the per-categorical-feature integer mapping used at training time;
  the API uses this to encode incoming requests so model lookups are exact.
- `seed`, `snapshot_hash` — reproducibility provenance.

## Acceptance gates met

- ✅ `make check` (lint + typecheck + tests) clean
- ✅ `make data` and `make iterate` reproducible from seed + lockfile
- ✅ API `/v1/predict` returns calibrated quantiles + comparables + explanation +
  fairness flag for both heads
- ✅ Descriptive vs recommendation outputs cleanly separated in the API contract
- ✅ Conformal interval coverage observed = 89.8% vs target 80% (over-coverage; fine)
- ✅ Counterfactual fairness audit auto-runs; recommendation head |gap| = 0.00%
- ✅ Slice scorecard committed for every protected slice
- ✅ Wall-clock budget for the full ladder: ~190 s (within budget)
