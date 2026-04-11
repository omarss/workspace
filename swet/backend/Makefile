.PHONY: setup dev test test-unit test-integration test-cov lint format migrate seed swet clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

# Setup virtual environment and install dependencies
setup:
	python3.12 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	$(VENV)/bin/pre-commit install

# Run development server
dev:
	$(PYTHON) -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Run all tests
test:
	$(PYTHON) -m pytest tests/ -v

# Run unit tests only
test-unit:
	$(PYTHON) -m pytest tests/ -v -m "not integration"

# Run integration tests only
test-integration:
	$(PYTHON) -m pytest tests/ -v -m "integration"

# Run tests with coverage
test-cov:
	$(PYTHON) -m pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

# Lint
lint:
	$(PYTHON) -m ruff check src/ tests/
	$(PYTHON) -m ruff format --check src/ tests/
	$(PYTHON) -m mypy src/

# Format code
format:
	$(PYTHON) -m ruff check --fix src/ tests/
	$(PYTHON) -m ruff format src/ tests/

# Run Alembic migrations
migrate:
	$(PYTHON) -m alembic upgrade head

# Create a new migration
migration:
	$(PYTHON) -m alembic revision --autogenerate -m "$(msg)"

# Run SWET CLI practice mode
swet:
	$(PYTHON) -m src.cli.main $(ARGS)

# Seed the database
seed:
	$(PYTHON) -m src.cli.seed

# Clean
clean:
	rm -rf $(VENV) __pycache__ .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
