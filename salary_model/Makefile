# Saudi salary intelligence model — Makefile
#
# Single entry point for the full lifecycle: env -> data -> features -> train -> eval -> serve.
# Every target is idempotent. Re-running is safe; outputs live under data/ and artifacts/.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON_VERSION := 3.12
VENV := .venv
UV ?= uv
PY := $(UV) run --
RUFF := $(PY) ruff
MYPY := $(PY) mypy
PYTEST := $(PY) pytest

# Run identifier for an end-to-end iteration. Override: `make iterate RUN_ID=2026-05-24-a`.
RUN_ID ?= $(shell date -u +%Y%m%dT%H%M%SZ)
SEED ?= 17

# ── Help ─────────────────────────────────────────────────────────────────────

.PHONY: help
help:  ## Print available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} \
	    /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Environment ──────────────────────────────────────────────────────────────

.PHONY: install
install:  ## Create venv, install pinned deps (idempotent)
	$(UV) python install $(PYTHON_VERSION)
	$(UV) sync --extra dev

.PHONY: lock
lock:  ## Refresh uv lockfile against pyproject
	$(UV) lock

.PHONY: clean
clean:  ## Remove caches and the venv (keeps data/ and artifacts/)
	rm -rf $(VENV) .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov dist build *.egg-info

.PHONY: clean-all
clean-all: clean  ## Also remove generated data and artifacts
	rm -rf data/raw data/interim data/processed artifacts mlruns

# ── Quality gates ────────────────────────────────────────────────────────────

.PHONY: format
format:  ## Auto-format with ruff
	$(RUFF) format src tests
	$(RUFF) check --fix src tests

.PHONY: lint
lint:  ## Lint (ruff)
	$(RUFF) check src tests
	$(RUFF) format --check src tests

.PHONY: typecheck
typecheck:  ## Strict type-check (mypy --strict)
	$(MYPY)

.PHONY: test
test:  ## Run unit tests
	$(PYTEST) -m "not slow and not network"

.PHONY: test-all
test-all:  ## Run every test including slow ones
	$(PYTEST)

.PHONY: check
check: lint typecheck test  ## All quality gates

# ── Data ─────────────────────────────────────────────────────────────────────

.PHONY: data
data:  ## Fetch open data and build the training dataset (runs cleanup automatically)
	$(PY) salary-model data build --seed $(SEED) --run-id $(RUN_ID)

.PHONY: clean-data
clean-data:  ## Run the cleanup pipeline on a raw Parquet (set INPUT=path/to/obs.parquet)
	@if [ -z "$(INPUT)" ]; then echo "set INPUT=path/to/observations.parquet" && exit 1; fi
	$(PY) salary-model data clean $(INPUT) $(if $(OUTPUT),--output-path $(OUTPUT))

.PHONY: data-anchors
data-anchors:  ## Refresh public anchor tables only (GASTAT/SAMA/World Bank/KAPSARC)
	$(PY) salary-model data fetch-anchors

.PHONY: fetch-reports
fetch-reports:  ## Download published PDF reports (HRDF/HRSD/GASTAT/MOF/Vision2030/KornFerry/SABIC)
	bash scripts/fetch_pdf_reports.sh

.PHONY: fetch-reports-force
fetch-reports-force:  ## Re-download all PDFs even if already on disk
	bash scripts/fetch_pdf_reports.sh --force

.PHONY: fetch-open-data
fetch-open-data:  ## Best-effort pull from open.data.gov.sa (WAF-protected; may need manual)
	bash scripts/fetch_data_gov_sa.sh

.PHONY: fetch-boards
fetch-boards:  ## Pull active postings from Greenhouse + Lever + Ashby + Workable
	$(PY) salary-model data fetch-boards

.PHONY: fetch-all
fetch-all: data-anchors fetch-reports fetch-open-data fetch-boards  ## All external sources

# ── Retrain / refresh end-to-end ─────────────────────────────────────────────

.PHONY: retrain
retrain: data iterate  ## Rebuild dataset and re-run the iteration ladder

.PHONY: refresh
refresh: fetch-all retrain evaluate  ## Full refresh: pull every source, rebuild, retrain, evaluate

# ── Modeling ─────────────────────────────────────────────────────────────────

.PHONY: train
train: data  ## Train production model bundle (v2 = full ladder)
	$(PY) salary-model train --run-id $(RUN_ID) --seed $(SEED)

.PHONY: evaluate
evaluate:  ## Evaluate latest trained model and write reports/
	$(PY) salary-model evaluate --run-id $(RUN_ID)

OPTUNA_TRIALS ?= 4

.PHONY: iterate
iterate:  ## Run full iteration ladder (baseline -> v2) with a report per step
	$(PY) salary-model iterate --run-id $(RUN_ID) --seed $(SEED) --optuna-trials $(OPTUNA_TRIALS)

.PHONY: fairness-audit
fairness-audit:  ## Run counterfactual fairness audit on the current model bundle
	$(PY) salary-model fairness audit --run-id $(RUN_ID)

.PHONY: drift
drift:  ## Compare a current Parquet snapshot against the training snapshot (PSI)
	@if [ -z "$(CURRENT)" ]; then echo "set CURRENT=path/to/observations.parquet" && exit 1; fi
	$(PY) salary-model drift check $(CURRENT) --run-id $(RUN_ID)

# ── Serving ──────────────────────────────────────────────────────────────────

.PHONY: serve
serve:  ## Run FastAPI locally with reload
	$(PY) uvicorn salary_model.api.app:app --host 0.0.0.0 --port 8080 --reload

.PHONY: serve-prod
serve-prod:  ## Run FastAPI without reload (workers from $WORKERS, default 2)
	$(PY) uvicorn salary_model.api.app:app --host 0.0.0.0 --port 8080 --workers $${WORKERS:-2}

# ── Container ────────────────────────────────────────────────────────────────

# Prefer podman if present (works the same as docker); fall back to docker.
CONTAINER_CLI ?= $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
IMAGE ?= salary-model:local

.PHONY: docker-build
docker-build:  ## Build container image (uses podman if available, else docker)
	@if [ -z "$(CONTAINER_CLI)" ]; then echo "no container CLI found" && exit 1; fi
	$(CONTAINER_CLI) build -t $(IMAGE) .

.PHONY: docker-run
docker-run: docker-build  ## Run the API container locally on :8080
	$(CONTAINER_CLI) run --rm -p 8080:8080 \
	    -v $(PWD)/data:/data:ro \
	    -v $(PWD)/artifacts:/artifacts:ro \
	    -v $(PWD)/reports:/reports:ro \
	    --name salary-model-api $(IMAGE)

# ── Pre-commit ───────────────────────────────────────────────────────────────

.PHONY: precommit-install
precommit-install:  ## Install git pre-commit hooks
	$(UV) run pre-commit install
	$(UV) run pre-commit install --hook-type pre-push

.PHONY: precommit-run
precommit-run:  ## Run pre-commit against all files
	$(UV) run pre-commit run --all-files

# ── End-to-end ───────────────────────────────────────────────────────────────

.PHONY: all
all: install check iterate evaluate  ## Full pipeline: env, gates, iterate, evaluate
