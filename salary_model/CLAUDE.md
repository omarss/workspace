# CLAUDE.md — Claude-specific operating notes for this repository

> Read `AGENTS.md` first. This file adds Claude-specific operational guidance on top of
> it. Where the two conflict, `AGENTS.md` wins.

## What this repo is

A Saudi salary-distribution model — quantile predictions, calibrated intervals, comparable
records, fairness-aware. Open KSA data + anchored synthetic observations. Strict typing,
reproducible training, MLflow-tracked iteration ladder. See `README.md`.

## How to work here

### Always use the Makefile
The user has a global rule: build, lint, test, and run via Makefile. Direct `python ...`
calls are wrong. If a target is missing, add it to the Makefile rather than running
ad hoc.

### Strict typing is non-negotiable
`mypy --strict` must pass on every change. If a third-party library lacks stubs, add it
to the `[[tool.mypy.overrides]]` section in `pyproject.toml` and explain why in the PR.

### Reproducibility before cleverness
Prefer a slightly less accurate but reproducible-from-seed approach over a clever model
that depends on hidden state. Every model in the ladder accepts `seed: int` and a frozen
data hash.

### Synthetic data labels
Every observation we generate ourselves carries `source = "synthetic_anchored"` and
`confidence = 0.6` (hard-capped at `≤ 0.7` for any future generator variant). The API
metadata block surfaces the share of synthetic data in training. Never let a downstream
surface (UI, report) imply that synthetic data is real microdata.

## Iteration loop discipline

When the user asks to "improve and retrain":

1. `TaskList` — read the existing iteration tasks.
2. Read the latest `reports/runs/<RUN_ID>/summary.md` to know where we are.
3. State a single hypothesis (one sentence) and the metric you expect to move.
4. Implement the smallest change.
5. `make iterate RUN_ID=<new>`; do not hand-roll training scripts in the chat.
6. Diff the two `summary.md` files and write a short note in
   `reports/runs/<new>/notes.md`: what changed, what moved, what surprised you.
7. If a protected slice regressed > 10% MAPE, or a fairness gap widened, *roll back*.
   Do not weaken the gate.

## Fairness governance

- The descriptive head uses all features including sensitive ones.
- The recommendation head uses the blinded feature view only.
- Promotion of a new model bundle requires the counterfactual fairness audit to be
  recorded in `reports/runs/<RUN_ID>/fairness.md` with the median |gap| and the
  per-segment table. Numbers must beat the thresholds in `models/fairness.py`.
- Never adjust the thresholds without explicit user approval, even if "it would help us
  ship".

## Data acquisition

- Confirmed source policy: **authoritative open KSA data + anchored synthetic
  observations**. Do not introduce a scraper for LinkedIn / Bayt / Indeed / Glassdoor.
  If the user later requests microdata, the integration point is `data/sources/`; add a
  new typed loader with explicit attribution metadata.
- Be honest about source quality. Each source has a trust prior in
  `data/sources/__init__.py::SOURCE_TRUST`. Lower priors flow through to per-record
  confidence scoring (§16 of the design doc).

## Code review checklist before declaring "done"

- [ ] `make check` passes (lint + typecheck + tests)
- [ ] `make iterate` runs end-to-end and writes a report
- [ ] No new dependency added without justification in the PR body
- [ ] No `# type: ignore` without a comment naming the specific issue
- [ ] No magic numbers in modeling code (constants live in `config.py`)
- [ ] No `print`; use `structlog`
- [ ] No emojis in source files or docs
- [ ] Sensitive features are not present in the recommendation head's feature view

## Risky operations — pause and ask

- Any change to fairness thresholds, governance gates, or sensitive-feature handling
- Adding a new dependency
- Adding a new data source
- Changing the canonical compensation representation (`data/normalize.py`)
- Changing the seed default or the train/val/test split policy
- Database schema changes (if/when we wire one)
- Anything that touches `/srv/`, `/etc/`, or system paths

## Common pitfalls in this codebase

- **Leakage via wage anchors.** The synthetic generator uses GASTAT anchors at the row's
  `observed_at`. Features must use anchors at `observed_at - lag`, never the row's own
  anchor.
- **Quantile crossing.** LightGBM trains quantiles independently — p90 < p50 happens.
  `models/quantile.py::enforce_monotonic` fixes it post-hoc; do not skip the step.
- **Small-N segments.** With < 200 rows, conformal intervals are noisy. The retrieval
  blend kicks in (see `models/ensemble.py::blend`). Do not disable it.
- **Arabic title normalization.** Some titles are Arabic. The embedding fallback uses
  multilingual e5; do not switch to an English-only encoder.

## Where the design doc lives

The full system design (19 sections, end-to-end) plus the v0 iteration journey is
persisted at `docs/design/v1.md`. When you need the rationale for a decision, read
that file first before asking — the chat context that originally produced the design
may not be available in your session.

## The model will be fine-tuned with real survey data later

The current bundle is a *prior*, not the final model. Future iterations will ingest
real employee and employer survey data and fine-tune on top. This shapes how we
build today:

- **The data layer must accept any new source via the `data/sources/<name>.py`
  + canonical-row contract.** Don't hard-code synthetic-only assumptions into
  training or features. The pattern used for GOSI / Mercer stubs is the template
  for employee_survey / employer_survey loaders.
- **Confidence is sample weight.** Synthetic rows carry `confidence=0.6`; real
  survey rows should land with `0.85-0.95` and naturally dominate training as
  volume grows. Do not throw away the confidence column.
- **Source-level provenance must survive end-to-end.** Every observation has a
  `source` column. The iteration runner and API both need to surface a
  `training_mix` summary so it's always visible what fraction of the model came
  from synthetic vs survey vs microdata.
- **Plan for a `fine-tune` target.** When real survey data arrives, the workflow
  should be: load the latest bundle, warm-start the LightGBM boosters
  (`init_model=` in `lgb.train`), continue training on the combined dataset,
  evaluate on a real-only held-out slice, gate promotion on lift over the prior
  bundle. Don't reach for transformer / NN architectures just because new data
  arrived; the GBM warm-start path is the right fit.
- **Survey-data bias is its own concern.** Self-reported employee salaries are
  noisy (inflation, selection), and employer-reported salaries can systematically
  understate to manage budget pressure. The data quality / fraud module (§16 of
  the design doc) must run on incoming surveys, not just synthetic.

## Data freshness policy (hard rule)

> **Never use data older than 2 years as an anchor / current-level input.**
> Data up to 20-30 years old is fine for trend modeling, lag features, and
> forecasting.

Codified in `src/salary_model/data/policy.py`:

- `MAX_AGE_YEARS_FOR_ANCHOR = 2.0` — anchors / "what's the level now"
- `MAX_AGE_YEARS_FOR_TRENDLINE = 30.0` — trend / lag / forecasting features

How to comply when adding a new fetcher:

1. Tag the result with `anchor_year` (the publication year of the values).
2. Before using it as a current-level anchor, call `policy.freshness(anchor_year)`
   and either:
   - use it as-is if `ok_as_anchor` is True, or
   - trend it forward by `verdict.trend_factor(cpi_yoy)` (compound CPI), or
   - refuse to use it for absolute anchoring and only feed it into trend
     features.
3. For trend / lag features, check `ok_as_trendline` and never extrapolate
   beyond 30 years.

The calibration pipeline (`data/calibrate.py`) already enforces this — the 2020
KAPSARC anchor gets trended forward by ~12% (6 years of 2% CPI) before pinning
the synthetic mean. Future anchor refreshes that bring the data within 2 years
will skip the trend step automatically.

## Always consider the time factor

Salary is a time-varying quantity. Any number, recommendation, or feature must carry
an explicit time anchor. Specifically:

- **Every salary figure cited to the user must be tagged with an `as_of` date and a
  currency note** (e.g. "12,000 SAR/month gross, as of 2026-05, nominal"). Never
  quote a number without these tags.
- **Distinguish nominal vs real.** When comparing across years, deflate with
  GASTAT CPI (now available via `data/sources/macro_series.py`). A 10k SAR salary
  in 2020 is roughly an 11k SAR salary in 2026 in real terms.
- **Use `as_of` end-to-end.** The API accepts `as_of` in the request; features must
  be looked up at that date (merge_asof on the monthly macro series). A prediction
  with `as_of=2027-03` must condition on 2027-03 macro snapshot, not the constants.
- **Time-based train/val/test splits, not random.** Already enforced in
  `features/build.split_indices`; never weaken to random.
- **Lag, don't leak.** Features anchored on `observed_at` must use information
  available at `observed_at - lag`, never the future.
- **Drift over time is a first-class concern.** `make drift` exists for this; the
  monitoring/drift.py PSI report is the canonical alert.
- **Vision 2030 phase is a coarse but useful time feature.** Currently encoded as
  `vision_phase` (0/1/2/3 by year). Refine when KSA program milestones publish.
- **Seasonality:** Ramadan, Hajj, fiscal-year-end (Dec/Jan budgets) all matter.
  We have `month_sin/cos` today; explicit calendar flags (Ramadan month, Hajj
  month, budget month) are a planned addition.
- **Salary inflation expectation:** ~3-5% per year nominal in KSA is typical;
  a quote that doesn't refresh annually starts to mislead.
- **Retraining cadence:** monthly retrain with a rolling 24-month window is the
  documented default in §13 of the design doc. Don't drift from this without a
  written reason.

## When in doubt

Stop and ask. The user explicitly prefers a question over a guess.
