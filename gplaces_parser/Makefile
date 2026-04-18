SHELL := /bin/bash
PY    := .venv/bin/python
PIP   := .venv/bin/pip
ALEMBIC := .venv/bin/alembic
GPLACES := .venv/bin/gplaces

DB_ROLE := gplaces
DB_PASS := gplaces
DB_NAME := gplaces

.PHONY: help install install-browser db-create db-drop migrate revision scrape-places scrape-reviews status psql lint clean

help:
	@echo "Setup"
	@echo "  install           create .venv and install project + dev deps"
	@echo "  install-browser   download Chromium for Playwright (~200 MB)"
	@echo "  db-create         create local Postgres role+db (needs sudo)"
	@echo "  db-drop           drop local Postgres db (destructive; asks sudo)"
	@echo "  migrate           run Alembic migrations"
	@echo "  revision m=...    create new Alembic revision"
	@echo "Scraper"
	@echo "  scrape-places     enumerate Riyadh tiles x categories, fetch places"
	@echo "  scrape-reviews    fetch reviews for places without reviews"
	@echo "  status            show scrape progress"
	@echo "API"
	@echo "  serve             run the FastAPI /v1/nearby service locally"
	@echo "  image-build       build Docker image gplaces/api:latest"
	@echo "  image-load        import the image into the host k3s containerd"
	@echo "  k8s-apply         kubectl apply the homelab manifests"
	@echo "  k8s-status        show deploy/pod/svc for api-places"
	@echo "Dev"
	@echo "  psql              open psql shell against the project db"
	@echo "  lint              ruff check"
	@echo "  clean             remove .venv and caches"

install: .venv/bin/python
	$(PIP) install -U pip
	$(PIP) install -e '.[dev]'

install-browser:
	$(PY) -m playwright install chromium --with-deps

serve:
	$(GPLACES) serve

# Build the API image and load it into the local k3s containerd so the
# Deployment can pull it without an external registry.
IMAGE ?= gplaces/api:latest
image-build:
	docker build -t $(IMAGE) .

image-load:
	docker save $(IMAGE) | sudo k3s ctr images import -

k8s-apply:
	kubectl apply -k ../homelab/apps/api-places/ 2>/dev/null \
	  || kubectl apply -f ../homelab/apps/api-places/

k8s-status:
	kubectl -n api-places get deploy,pod,svc -o wide

.venv/bin/python:
	python3 -m venv .venv

# Uses peer auth via sudo -u postgres; idempotent.
db-create:
	@echo "Creating role $(DB_ROLE) and database $(DB_NAME) (idempotent)..."
	@sudo -u postgres psql -v ON_ERROR_STOP=1 -c "DO \$$\$$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='$(DB_ROLE)') THEN CREATE ROLE $(DB_ROLE) LOGIN PASSWORD '$(DB_PASS)'; END IF; END \$$\$$;"
	@sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$(DB_NAME)';" | grep -q 1 \
	  || sudo -u postgres createdb -O $(DB_ROLE) $(DB_NAME)
	@echo "Done. DATABASE_URL=postgresql://$(DB_ROLE):$(DB_PASS)@localhost:5432/$(DB_NAME)"

db-drop:
	@read -p "Drop database $(DB_NAME)? This destroys all scraped data. [y/N] " ok && [ "$$ok" = "y" ]
	@sudo -u postgres dropdb --if-exists $(DB_NAME)

migrate:
	$(ALEMBIC) upgrade head

revision:
	@test -n "$(m)" || (echo "usage: make revision m='message'"; exit 1)
	$(ALEMBIC) revision --autogenerate -m "$(m)"

scrape-places:
	$(GPLACES) scrape-places

scrape-reviews:
	$(GPLACES) scrape-reviews

status:
	$(GPLACES) status

psql:
	psql "$$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)"

lint:
	.venv/bin/ruff check src

clean:
	rm -rf .venv .ruff_cache .pytest_cache **/__pycache__
