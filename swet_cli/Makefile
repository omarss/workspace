VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: setup setup-api setup-bot setup-slack setup-whatsapp setup-web run run-api run-bot run-slack run-whatsapp dev-web build-web deploy-web test test-api test-bot test-slack test-whatsapp smoke lint format clean

setup:
	python3.12 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

setup-api:
	python3.12 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,api]"

setup-bot:
	python3.12 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,telegram]"

run:
	$(PYTHON) -m swet_cli.main run

run-api:
	$(PYTHON) -m uvicorn swet_api.app:app --reload --port 8000

run-bot:
	$(PYTHON) -m swet_telegram.bot

setup-slack:
	python3.12 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,slack]"

setup-whatsapp:
	python3.12 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,whatsapp]"

run-slack:
	$(PYTHON) -m swet_slack.bot

run-whatsapp:
	$(PYTHON) -m swet_whatsapp.bot

test:
	$(PYTHON) -m pytest tests/ -v

test-api:
	$(PYTHON) -m pytest tests/test_api/ -v

test-bot:
	$(PYTHON) -m pytest tests/test_telegram/ -v

test-slack:
	$(PYTHON) -m pytest tests/test_slack/ -v

test-whatsapp:
	$(PYTHON) -m pytest tests/test_whatsapp/ -v

lint:
	$(PYTHON) -m ruff check src/ tests/
	$(PYTHON) -m ruff format --check src/ tests/

format:
	$(PYTHON) -m ruff check --fix src/ tests/
	$(PYTHON) -m ruff format src/ tests/

setup-web:
	cd web && pnpm install

dev-web:
	cd web && pnpm dev

build-web:
	cd web && pnpm build

deploy-web: build-web
	sudo systemctl reload nginx

smoke:
	cd web && npx playwright test --project=smoke

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
