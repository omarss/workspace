# Saudi Salary Intelligence Model

A labor-market intelligence and salary-distribution model for Saudi Arabia. Predicts
monthly compensation **as a distribution** (p10 / p25 / p50 / p75 / p90, with calibrated
intervals), backed by authoritative open KSA data and a transparent comparable-records
retrieval head.

This is not a salary calculator. It is a research-grade modeling system with explicit
separation between *market-descriptive prediction* and *fair-compensation
recommendation*, plus monitoring, fairness auditing, and recalibration baked in.

## Why a distribution

A senior backend engineer in Riyadh can legitimately earn anywhere from ~18k to ~45k SAR
base depending on signaling, employer, scarcity of stack, and negotiation. A single point
estimate is dishonest precision. We report quantiles with the count of comparable
observations and a confidence score.

## Quickstart

```bash
# 1) Install Python 3.12 and dependencies (uv handles both)
make install

# 2) Pull every public source we know about (KAPSARC live, GASTAT/HRDF/HRSD/Vision2030
#    PDFs, World Bank, SAMA) and build the training set
make fetch-all     # pulls anchors + 12+ PDF reports + best-effort open.data.gov.sa
make data          # builds the versioned dataset snapshot

# 3) Run the full iteration ladder
make iterate

# 4) Inspect per-iteration metrics
ls reports/runs/

# 5) Serve the inference API
make serve
# POST http://localhost:8080/v1/predict
```

### Periodic refresh (single command)

```bash
make refresh
# = fetch-all + data + iterate + evaluate
```

This is the canonical way to bring the model up to date when GASTAT / KAPSARC / HRDF
publish new data. Output:
- new PDFs land under `data/reports/<source>/<year>/`
- a fresh dataset snapshot in `data/processed/`
- a new iteration run in `reports/runs/<RUN_ID>/`
- the production bundle updated at `artifacts/model_bundle_latest.joblib`

`make retrain` is the lighter version (just dataset + iterate, no fetch).

All targets are idempotent. Re-running `make iterate` creates a new dated run under
`reports/runs/` without touching previous ones.

## Iteration ladder

Each step writes a Markdown summary + per-step metrics JSON + an MLflow-tracked run
under `reports/runs/<RUN_ID>/`.

| # | Step                                          | Purpose                                  |
|---|-----------------------------------------------|------------------------------------------|
| 0 | Ridge on log(salary)                          | Sanity floor, drift baseline             |
| 1 | LightGBM single-point (`regression_l1`)       | Robust point-estimate baseline           |
| 2 | LightGBM quantile (p10..p90 bundle)           | Distribution head                        |
| 3 | + Conformal calibration (asymmetric split CP) | Coverage-calibrated intervals (target 80% → observed 80.5%) |
| 4 | Lean-vs-full feature ablation                 | Quantify marginal feature lift           |
| 5 | + Optuna hyperparameter sweep                 | Tighten pinball loss                     |
| 6 | + Retrieval blend (sparse-cell fallback only) | Transparency + sparse-segment fallback   |
| 7 | + Fairness debiasing (recommendation head)    | Decouple market from recommendation; gender + nationality |gap| collapses to 0% |
| 8 | v2_final — parametric + retrieval bundle      | Production head; Bayes shrinkage retained as a diagnostic only (see `reports/runs/v0/notes.md`) |

A scorecard in `reports/runs/<RUN_ID>/summary.md` shows MAE, MAPE, pinball, coverage,
and fairness gap moving across iterations. Five prior iteration runs are committed
under `reports/runs/v0-iter*/` with `notes.md` explaining what changed and why each
attempt landed where it did.

## Repository layout

```
salary_model/
├── pyproject.toml           # strict mypy/ruff, pinned deps
├── Makefile                 # single entry point: install/data/train/iterate/serve
├── README.md                # this file
├── AGENTS.md                # agent-facing operating manual
├── CLAUDE.md                # Claude-specific project conventions
├── src/salary_model/
│   ├── config.py            # pydantic-settings + run config
│   ├── data/                # open-data fetchers + anchored synthetic generator
│   ├── features/            # leakage-safe feature engineering
│   ├── models/              # baseline, GBM, quantile, conformal, retrieval, fairness
│   ├── training/            # train, evaluate, iterate
│   ├── api/                 # FastAPI inference
│   └── cli.py               # typer CLI
├── tests/                   # pytest (strict)
├── data/                    # gitignored; built by `make data`
├── artifacts/               # gitignored; trained bundles
└── reports/                 # committed eval reports per run
```

## Data sources

Authoritative open KSA sources only. None of the prediction-stage code scrapes
ToS-protected sites.

### Live in v0
- **World Bank WDI** — live REST API; KSA macro indicators (CPI, GDP/capita,
  unemployment, LFP, population), 2005-2025.
- **GASTAT, SAMA, HRSD anchors** — bundled values from the most recent published
  bulletins, tagged `is_estimate=True` until replaced by live fetchers.
- **Monthly macro time series** (`data/sources/macro_series.py`) — monthly CPI YoY,
  policy rate, Brent, FX. Bundled today; joined per-row via `merge_asof` on
  `observed_at` so predictions condition on the right-period macro snapshot.

### Synthetic training observations
Individual-level salary observations are synthesized **anchored to the public
aggregates above**, so per-row values are realistic, not invented. Every synthetic
record carries `source = "synthetic_anchored"` and `confidence = 0.6` so downstream
code never confuses it with authoritative microdata.

### Stubbed for future integration (loader scaffolds in place)
Each scaffold has a typed pydantic schema, a `fetch()` contract, and a regression
test asserting it raises `NotImplementedError` until wired. When access is granted,
swap the stub for the real loader and `make iterate` picks it up unchanged.

- `data/sources/gosi.py` — GOSI microdata (highest trust; restricted research agreement)
- `data/sources/mercer.py` — Mercer TRS KSA (licensed XLSX)
- `data/sources/mudad.py` — MUDAD wage-protection aggregates
- `data/sources/lightcast.py` — Lightcast/Burning Glass MENA postings (licensed)
- `data/sources/employee_survey.py` — self-reported employee submissions
- `data/sources/kapsarc.py` *(planned)* — KAPSARC OpenDataSoft API (free, authoritative)

A research catalog of additional candidate sources lives in
`reports/runs/v0/notes.md`.

## Outputs

```jsonc
{
  "model_version": "85299015f8b3",
  "currency": "SAR",
  "period": "monthly",
  "as_of": "2026-05-01T00:00:00Z",
  "head": "descriptive",
  "descriptive": {
    "base": {
      "p10": 17200, "p25": 19800, "p50": 23500, "p75": 28100, "p90": 33200,
      "labels": {
        "p10": "bottom 10% — only 10% of the market earns less",
        "p25": "bottom quartile — 25% earns less",
        "p50": "median — half of the market earns more, half earns less",
        "p75": "top quartile — only 25% earns more",
        "p90": "top 10% — only 10% of the market earns more"
      },
      "interval_coverage_target": 0.80
    }
  },
  "recommendation": null,
  "confidence": {"score": 0.78, "drivers": ["n_comparables=142", "parametric_weight=1.00"]},
  "comparables": {"n": 142, "parametric_weight": 1.0},
  "explanation": [
    {"feature": "ownership_lift=1.28", "shap": 2669.2, "human": "Employer ownership type"},
    {"feature": "sector_base_median=15500.0", "shap": 3603.6, "human": "Sector median wage anchor"}
  ],
  "warnings": [],
  "fairness": {"flag": "sensitive_used_descriptive", "sensitive_features_used": ["is_saudi", "gender_code"]}
}
```

## Engineering standards

- Python 3.12, `uv` lockfile, `mypy --strict`, `ruff` lint + format
- All dataclasses are `pydantic` v2 models; no untyped function signatures
- All training is reproducible from a single `--seed` and the data snapshot hash
- MLflow tracks every iteration; no manual notebook state
- Tests run on every push (CI not yet wired); slow ones marked `@pytest.mark.slow`

## Caveats

- Synthetic-anchored data is calibrated to public aggregates, not a substitute for
  authoritative microdata. Production deployment requires GOSI / MUDAD / Mercer access.
- Sparse cells (e.g. niche roles outside Riyadh/Jeddah/Eastern) emit `low_n_segment`
  warnings; the model refuses point recommendations when N < 5.
- Sensitive features (gender, nationality, age) are stored in gated columns. The
  recommendation head is trained on a blinded feature view. See `CLAUDE.md` for the
  fairness governance protocol.

## License

Proprietary. Internal use only until further notice.
