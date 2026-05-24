# AGENTS.md — Operating manual for AI coding agents

This file is the source of truth for any AI agent (Claude Code, Cursor, OpenAI Codex,
Aider, etc.) working inside this repository. It describes how the project is laid out,
what conventions to follow, what to never do, and how to run the lifecycle.

Claude Code: also read `CLAUDE.md` for Claude-specific instructions.

## Project in one paragraph

A Saudi Arabia labor-market intelligence model that predicts monthly compensation as a
calibrated quantile distribution with explainability, a retrieval-based comparable
records head, and explicit separation of *descriptive* and *fair-recommendation* outputs.
Built on open KSA data anchors plus a synthetic observation generator, with a clear path
to swap in authoritative microdata (GOSI / Mercer / MUDAD) when licensed.

## Tech stack

- Python **3.12** (pin in `.python-version`; do not use 3.13+ — model wheels lag)
- Package manager: **uv** (lockfile committed)
- Models: **LightGBM** + **MAPIE** (conformal) + **NumPyro** (v2 Bayesian)
- Embeddings: **sentence-transformers** (multilingual e5)
- Indexing: **FAISS** (local) — Postgres `pgvector` swap-in is a later concern
- Tracking: **MLflow** (local `mlruns/`)
- API: **FastAPI** + **uvicorn**
- Strictness: **mypy --strict**, **ruff** (lint + format), **pytest** with `filterwarnings = error`

## Folder map

```
src/salary_model/
├── config.py            # pydantic-settings; env-driven config; structlog setup
├── cli.py               # typer entry point (`salary-model`)
├── data/
│   ├── anchors.py       # bundled GASTAT/SAMA/HRSD aggregates (is_estimate=True)
│   ├── build.py         # dataset builder; writes versioned Parquet + manifest
│   ├── normalize.py     # canonical compensation rules (period, currency, gross/net, allowances)
│   ├── synthetic.py     # anchored synthetic observation generator (deterministic, seeded)
│   ├── taxonomy.py      # title / level / skill normalization (rules + embedding fallback)
│   ├── types.py         # enums + pydantic types (Region, Sector, Level, CompensationComponents, …)
│   └── sources/
│       ├── _common.py            # FetchManifest, httpx helpers
│       ├── gastat.py             # GASTAT wage anchors (bundled)
│       ├── sama.py               # SAMA single-row indicators (bundled)
│       ├── worldbank.py          # World Bank WDI (live REST)
│       ├── macro_series.py       # monthly KSA macro series (bundled, joined per-row)
│       ├── gosi.py               # GOSI microdata loader (stub)
│       ├── mercer.py             # Mercer TRS XLSX loader (stub)
│       ├── mudad.py              # MUDAD wage-protection aggregates (stub)
│       ├── lightcast.py          # Lightcast postings (stub)
│       └── employee_survey.py    # self-reported employee submissions (stub)
├── features/
│   └── build.py         # leakage-safe feature pipeline; merge_asof macro join; category codes
├── models/
│   ├── baseline.py      # Ridge on log(target)
│   ├── quantile.py      # LightGBM quantile bundle + L1 single-point booster
│   ├── conformal.py     # split-conformal calibration (symmetric + asymmetric)
│   ├── retrieval.py     # comparables (sklearn kNN over standardized features)
│   ├── bayes.py         # empirical / NumPyro hierarchical shrinkage (diagnostic only)
│   ├── ensemble.py      # blend logic (parametric × retrieval)
│   ├── fairness.py      # sensitive-group reweighting + counterfactual audit
│   └── explain.py       # SHAP TreeExplainer wrapper, serialized into the bundle
├── monitoring/
│   └── drift.py         # PSI drift detector + Markdown/JSON report writer
├── training/
│   ├── evaluate.py      # metrics + slice scorecard
│   └── iterate.py       # the ladder (0..8) + MLflow tracking + bundle serialization
└── api/
    ├── schemas.py       # pydantic request/response models
    └── app.py           # FastAPI; loads bundle; serves /predict, /model, /health
```

`data/`, `artifacts/`, `mlruns/` are gitignored. `reports/runs/<RUN_ID>/` is **committed**
(summary.md, fairness.md, notes.md, slice_scorecard.csv, manifest.json, metrics.json —
not the large model_bundle.joblib).

## Lifecycle (the only way to run anything)

Everything goes through the Makefile.

```bash
make install            # uv-managed venv + pinned deps (Python 3.12)
make fetch-reports      # download published PDFs (HRDF/HRSD/GASTAT/MOF/Vision2030/etc.)
make fetch-open-data    # best-effort pull from open.data.gov.sa (WAF; may need manual)
make data-anchors       # refresh in-process anchor fetchers (KAPSARC live, World Bank, etc.)
make fetch-all          # = anchors + reports + open-data, one command
make data               # build the versioned dataset snapshot from fetched sources
make retrain            # = data + iterate (rebuild + train, skip fetch)
make refresh            # = fetch-all + data + iterate + evaluate (full pipeline)
make iterate            # run the full iteration ladder, writes reports/runs/<RUN_ID>/
make evaluate           # print summary.md of the latest run
make fairness-audit     # print fairness.md of the latest run
make drift CURRENT=...  # PSI drift report vs the training snapshot
make serve              # FastAPI :8080 with reload
make serve-prod         # FastAPI :8080 with workers, no reload
make docker-build       # build image (prefers podman over docker)
make docker-run         # run API container locally
make precommit-install  # install git pre-commit + pre-push hooks
make precommit-run      # run pre-commit against all files
make check              # lint + typecheck + test (the CI gate)
```

Override the run id: `make iterate RUN_ID=2026-05-24-a`. Override the seed: `SEED=42`.

## Conventions agents MUST follow

### Typing
- Every function takes typed args and returns a typed value. No `Any` unless wrapped in
  a `# type: ignore[<rule>]` with an inline justification.
- Public data structures are `pydantic.BaseModel` subclasses or `@dataclass(frozen=True)`.
- DataFrame columns are validated through pydantic models or `pandera` schemas at
  ingestion boundaries.

### Style
- Lines ≤ 100 chars. `ruff format` is the only formatter.
- No `print`. Use `structlog`. The root logger is configured once in `salary_model.config`.
- No relative imports across packages. Absolute imports only.
- No comments restating what the code does. Comments are reserved for non-obvious WHY.

### Reproducibility
- Every randomized operation accepts a `seed: int` parameter. Default lives in `config`.
- Training reads a frozen data snapshot pinned by hash; the hash is logged in MLflow.
- `make iterate RUN_ID=X` is deterministic given the same data and seed.

### Data
- **Never scrape** ToS-protected sites (LinkedIn, Bayt, Indeed, Glassdoor). The project
  is committed to authoritative open data plus anchored synthetic.
- Synthetic data is always tagged `source = "synthetic_anchored"`. Predictions trained
  on synthetic-only data are clearly labeled as such in the API metadata block.

### Provenance (data, not assumptions)
The user-stated rule: **the model should be built on data, not assumptions**. Every
fetched dataset returns a `FetchManifest` carrying `ok`, `fallback`, and (planned)
`is_estimate`. Bundled values that don't come from a live fetch must be tagged
`is_estimate=True`. The API's `data_provenance` block in the response should surface:
- the share of training rows that are `synthetic_anchored` vs real microdata vs survey,
- which fetched sources were live vs bundled at training time,
- a `trained_on_real_data: bool` flag.
When adding a new source: implement a real fetcher if any open path exists (data.gov.sa
CKAN, KAPSARC OpenDataSoft, ILOSTAT SDMX). Stub it via the GOSI/Mercer pattern only if
no open access exists. Never hard-code "best-effort recall" numbers and call them
authoritative.

### Sensitive fields
- `gender`, `is_saudi`, `age_bucket` are gated. They live in the descriptive feature
  view only. The recommendation head trains on the blinded view (`features/build.py::
  blinded_features`).
- Counterfactual fairness audit runs on every model promotion. Promotion is blocked if
  the audit median absolute gap exceeds the thresholds in `models/fairness.py`.

### Testing
- Tests live in `tests/`. Use `pytest` markers: `slow`, `network`.
- `filterwarnings = error` — fix warnings, don't suppress them.
- Property-based tests (`hypothesis`) for normalizers (compensation, title, skill).

### Git
- Commit titles ≤ 50 chars, imperative, lowercase. Match the repo's existing style:
  `add data fetchers and synthetic generator`.
- One logical change per commit. No "fix typo" follow-ups; amend instead.
- Never `git push --force` without explicit user request.
- Never bypass hooks (`--no-verify`).
- Never add `Co-Authored-By` lines.

### Never do
- Never commit data files (`data/raw/**`, `data/processed/**`, `*.parquet`).
- Never commit model artifacts (`artifacts/**`, `mlruns/**`).
- Never write to `/etc`, `/usr`, or anywhere outside this repo.
- Never disable strict mypy or ruff rules wholesale to make a build pass. Either fix or
  ask the human before adding a per-file ignore with a comment.
- Never silence a failing test by skipping it. Fix the root cause or escalate.
- Never weaken fairness thresholds without explicit human approval.
- Never introduce a new prediction surface without an explainability path.

## Iteration discipline

When asked to "improve the model":
1. Read `reports/runs/` for the current state. Don't repeat work.
2. Form a hypothesis (a sentence: "I expect MAE to drop because X").
3. Implement the smallest change consistent with the hypothesis.
4. Run `make iterate`. Don't tune by hand.
5. Compare the new `summary.md` vs the previous one. Commit only if metrics improve
   without regressing any protected slice or breaching fairness thresholds.
6. Append a Markdown note in `reports/runs/<RUN_ID>/notes.md` explaining what you tried
   and what you observed.

## Performance budgets

- `make data` end-to-end: ≤ 60 seconds on a laptop.
- `make iterate` full ladder on the default synthetic dataset: ≤ 5 minutes on CPU.
- `make check`: ≤ 30 seconds.
- API p95 latency for `/predict`: ≤ 80 ms (no GPU).

If a change blows a budget by > 2x, flag it in the iteration note.

## Asking for help

If anything is ambiguous — data licensing, fairness thresholds, model promotion gates,
or whether to introduce a dependency — stop and ask the user. Do not invent a policy.
