SHELL := /bin/bash
PY    := .venv/bin/python
PIP   := .venv/bin/pip
ALEMBIC := .venv/bin/alembic
MCQS  := .venv/bin/mcqs

DB_ROLE := mcqs
DB_PASS := mcqs
DB_NAME := mcqs

.PHONY: help install db-create db-drop migrate revision \
        ingest plan-round generate status serve lint clean \
        image-build image-load k8s-apply k8s-status release deploy deploy-nginx psql

help:
	@echo "Setup"
	@echo "  install           create .venv and install project + dev deps"
	@echo "  db-create         create local Postgres role+db (needs sudo)"
	@echo "  db-drop           drop local Postgres db (destructive; asks sudo)"
	@echo "  migrate           run Alembic migrations"
	@echo "  revision m=...    create new Alembic revision"
	@echo "Pipeline"
	@echo "  ingest            scan DOCS_BUNDLE_ROOT → subjects/source_docs/doc_chunks"
	@echo "  plan-round [n=N]  open a new round and queue pending generation jobs"
	@echo "  generate          run the generator worker (resumable)"
	@echo "  status            show round/subject/type progress"
	@echo "API"
	@echo "  serve             run the FastAPI /v1/mcq service locally"
	@echo "  image-build       build Docker image mcqs/api:latest"
	@echo "  image-load        import the image into the host k3s containerd"
	@echo "  k8s-apply         kubectl apply the homelab manifests"
	@echo "  k8s-status        show deploy/pod/svc for api-mcqs"
	@echo "  release           bump + commit + tag + image + rollout + push"
	@echo "  deploy            (sudo) import image + rollout pod — code-only path"
	@echo "  deploy-nginx      (sudo) sync nginx vhost + remind to re-run certbot"
	@echo "Dev"
	@echo "  psql              open psql shell against the project db"
	@echo "  lint              ruff check"
	@echo "  clean             remove .venv and caches"

install: .venv/bin/python
	$(PIP) install -U pip
	$(PIP) install -e '.[dev]'

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
	@read -p "Drop database $(DB_NAME)? This destroys all MCQs. [y/N] " ok && [ "$$ok" = "y" ]
	@sudo -u postgres dropdb --if-exists $(DB_NAME)

migrate:
	$(ALEMBIC) upgrade head

revision:
	@test -n "$(m)" || (echo "usage: make revision m='message'"; exit 1)
	$(ALEMBIC) revision -m "$(m)"

ingest:
	$(MCQS) ingest

plan-round:
	$(MCQS) plan-round $(if $(n),--target $(n),)

generate:
	$(MCQS) generate $(ARGS)

status:
	$(MCQS) status

serve:
	$(MCQS) serve

IMAGE ?= mcqs/api:latest
image-build:
	docker build -t $(IMAGE) .

image-load:
	docker save $(IMAGE) | sudo k3s ctr images import -

k8s-apply:
	kubectl apply -k ../homelab/apps/api-mcqs/ 2>/dev/null \
	  || kubectl apply -f ../homelab/apps/api-mcqs/

k8s-status:
	sudo k3s kubectl -n api-mcqs get deploy,pod,svc -o wide

psql:
	psql "$$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)"

lint:
	.venv/bin/ruff check src

clean:
	rm -rf .venv .ruff_cache .pytest_cache **/__pycache__

# One-shot release — mirrors gplaces_parser's flow. Aborts on dirty tree.
#
# The dirty-tree check lives on a dependency target rather than inline
# so bump-version.sh (which is wrapped in $(eval $(shell …)) and thus
# expands at recipe-expansion time) runs only after the check has
# passed. Inlining the check left the file dirty on every failed run,
# which caused the next invocation to also fail — see commit history.
.PHONY: _release-preflight
_release-preflight:
	@test -z "$$(git -C .. status --porcelain mcqs/)" \
	  || (echo "working tree has uncommitted changes under mcqs/"; exit 1)

release: _release-preflight
	@echo ">> bumping version"
	$(eval NEW_VERSION := $(shell ./scripts/bump-version.sh))
	@test -n "$(NEW_VERSION)" || (echo "bump-version.sh did not return a version"; exit 2)
	@echo ">> new version = $(NEW_VERSION)"
	@./scripts/changelog.sh | sed 's/^/  /'
	git -C .. add mcqs/pyproject.toml
	git -C .. commit -m "release mcqs v$(NEW_VERSION)"
	git -C .. tag "mcqs/v$(NEW_VERSION)"
	@echo ">> building image mcqs/api:v$(NEW_VERSION) + :latest"
	docker build -t $(IMAGE) -t mcqs/api:v$(NEW_VERSION) .
	rm -f /tmp/mcqs-api.tar
	docker save mcqs/api:v$(NEW_VERSION) -o /tmp/mcqs-api.tar
	@$(MAKE) deploy TAG=v$(NEW_VERSION)
	git -C .. push origin main
	git -C .. push origin "mcqs/v$(NEW_VERSION)"
	@echo ">> released + deployed mcqs v$(NEW_VERSION)"

TAG ?= latest
NGINX_SRC ?= ../homelab/nginx/api.omarss.net.conf
NGINX_DST ?= /etc/nginx/sites-available/api.omarss.net.conf
deploy:
	@echo ">> importing /tmp/mcqs-api.tar into k3s containerd"
	@sudo k3s ctr images import /tmp/mcqs-api.tar
	@echo ">> rolling out api-mcqs pod"
	sudo k3s kubectl -n api-mcqs set image deployment/api-mcqs api=localhost/mcqs/api:$(TAG)
	sudo k3s kubectl -n api-mcqs rollout restart deployment/api-mcqs
	sudo k3s kubectl -n api-mcqs rollout status deployment/api-mcqs --timeout=120s
	@echo ">> deployed."

# api.omarss.net.conf is shared with gplaces — deploying nginx here reloads
# the whole vhost. Certbot's 443 listener gets clobbered → re-run:
#   sudo certbot --nginx -d api.omarss.net
deploy-nginx:
	@echo ">> syncing $(NGINX_SRC) → $(NGINX_DST) (sudo)"
	@sudo bash -c '\
	  set -euo pipefail; \
	  install -o root -g root -m 644 $(NGINX_SRC) $(NGINX_DST); \
	  nginx -t; \
	  systemctl reload nginx; \
	'
	@echo
	@echo ">> nginx vhost was reset to the pre-certbot template. Re-run:"
	@echo "   sudo certbot --nginx -d api.omarss.net"
