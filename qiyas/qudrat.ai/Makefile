# qudrat — assessment-content platform for Qudurat / Tahsili.
# All Go work runs inside the builder container; no Go required on the host.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# ---- toolchain pins -----------------------------------------------------------
GO_VERSION              := 1.26.2
BUILDER_BASE            := docker.io/library/golang:$(GO_VERSION)-alpine
BUILDER_IMAGE           := localhost/qudrat-builder:dev
BUILDER_CONTAINERFILE   := build/Containerfile.builder

# ---- workspace ----------------------------------------------------------------
ROOT                    := $(CURDIR)
GOCACHE_HOST            := $(HOME)/.cache/qudrat-go-build
GOPKG_HOST              := $(HOME)/.cache/qudrat-go-pkg
SERVICES                := api worker importer
WEB_IMAGE               := localhost/qudrat/web:dev
NAMESPACE               := qudrat
HOMELAB_DIR             := $(abspath $(ROOT)/../../homelab)
QUESTIONS_DIR           := $(abspath $(ROOT)/../questions)

$(shell mkdir -p $(GOCACHE_HOST) $(GOPKG_HOST))

# ---- container runners --------------------------------------------------------
PODMAN  := podman
RUN_OPTS := --rm \
            --userns=keep-id \
            -v $(ROOT):/work:Z \
            -v $(GOCACHE_HOST):/cache/go-build:Z \
            -v $(GOPKG_HOST):/go/pkg:Z \
            -w /work \
            -e HOME=/tmp \
            -e GOCACHE=/cache/go-build \
            -e GOFLAGS=-buildvcs=false

IN_BUILDER       := $(PODMAN) run $(RUN_OPTS) -e CGO_ENABLED=0 -t $(BUILDER_IMAGE)
IN_BUILDER_TEST  := $(PODMAN) run $(RUN_OPTS) -e CGO_ENABLED=1 -t $(BUILDER_IMAGE)
IN_BUILDER_IT    := $(PODMAN) run $(RUN_OPTS) -e CGO_ENABLED=0 -it $(BUILDER_IMAGE)

# ---- meta ---------------------------------------------------------------------
.PHONY: help
help:  ## list targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | sort

# ---- builder image ------------------------------------------------------------
.PHONY: builder
builder:  ## build the local builder image (golang + golangci-lint + gofumpt + sqlc + migrate)
	$(PODMAN) build -t $(BUILDER_IMAGE) -f $(BUILDER_CONTAINERFILE) build/

.PHONY: tools
tools: builder  ## ensure host + builder tools are present
	@command -v $(PODMAN) >/dev/null || { echo "podman missing"; exit 1; }
	@command -v kubectl  >/dev/null || { echo "kubectl missing"; exit 1; }
	@echo "host + builder tools OK"

.PHONY: sh
sh: builder  ## open an interactive shell in the builder
	$(IN_BUILDER_IT) sh

# ---- go workflow --------------------------------------------------------------
.PHONY: tidy
tidy: builder  ## go mod tidy
	$(IN_BUILDER) go mod tidy

.PHONY: fmt
fmt: builder  ## gofumpt + goimports via golangci-lint
	$(IN_BUILDER) golangci-lint fmt

.PHONY: lint
lint: builder  ## static analysis
	$(IN_BUILDER) golangci-lint run ./...

.PHONY: vet
vet: builder  ## go vet
	$(IN_BUILDER) go vet ./...

.PHONY: test
test: builder  ## unit tests with race detector
	$(IN_BUILDER_TEST) go test -race -shuffle=on -count=1 ./...

.PHONY: test-int
test-int: builder  ## integration tests against the dev DB (run `make db-up migrate-up` first)
	$(PODMAN) run $(RUN_OPTS) --network=host -e CGO_ENABLED=1 \
	    -e QUDRAT_TEST_DB_DSN="$(DEV_DB_DSN)" \
	    -t $(BUILDER_IMAGE) \
	    go test -tags=integration -race -count=1 ./...

.PHONY: cover
cover: builder  ## test coverage
	$(IN_BUILDER_TEST) sh -c "go test -coverprofile=coverage.out ./... && go tool cover -func=coverage.out | tail -1"

# ---- service binaries ---------------------------------------------------------
define BUILD_SERVICE
.PHONY: build-$(1)
build-$(1): builder  ## build $(1) binary into bin/
	$(IN_BUILDER) go build -trimpath -ldflags='-s -w' -o bin/$(1) ./cmd/$(1)
endef
$(foreach svc,$(SERVICES),$(eval $(call BUILD_SERVICE,$(svc))))

.PHONY: build
build: $(addprefix build-,$(SERVICES))  ## build all service binaries

# ---- run locally --------------------------------------------------------------
.PHONY: run-api
run-api: build-api  ## run the api binary locally on :8080
	./bin/api

.PHONY: run-importer
run-importer: build-importer  ## run the importer locally against the dev DB
	QUDRAT_DATABASE_DSN="$(DEV_DB_DSN)" QUDRAT_QUESTIONS_DIR="$(QUESTIONS_DIR)" ./bin/importer

# ---- database & sqlc ----------------------------------------------------------
# Default DSN points at the dev container started by `make db-up`. Production
# overrides come from the Kubernetes secret.
DEV_DB_NAME    := qudrat
DEV_DB_USER    := qudrat
DEV_DB_PASS    := qudrat-dev
DEV_DB_PORT    := 55433
DEV_DB_DSN     := postgres://$(DEV_DB_USER):$(DEV_DB_PASS)@127.0.0.1:$(DEV_DB_PORT)/$(DEV_DB_NAME)?sslmode=disable
DEV_DB_CONTAINER := qudrat-dev-pg

.PHONY: db-up
db-up:  ## start a dev Postgres 18 container on $(DEV_DB_PORT)
	@$(PODMAN) inspect $(DEV_DB_CONTAINER) >/dev/null 2>&1 && \
	    $(PODMAN) start $(DEV_DB_CONTAINER) || \
	    $(PODMAN) run -d --name $(DEV_DB_CONTAINER) \
	        -e POSTGRES_DB=$(DEV_DB_NAME) \
	        -e POSTGRES_USER=$(DEV_DB_USER) \
	        -e POSTGRES_PASSWORD=$(DEV_DB_PASS) \
	        -p $(DEV_DB_PORT):5432 \
	        docker.io/library/postgres:18-alpine
	@echo "waiting for $(DEV_DB_CONTAINER)…"
	@for i in $$(seq 1 30); do \
	    $(PODMAN) exec $(DEV_DB_CONTAINER) pg_isready -U $(DEV_DB_USER) -d $(DEV_DB_NAME) >/dev/null 2>&1 && break; \
	    sleep 1; \
	done

.PHONY: db-down
db-down:  ## stop the dev Postgres container (data preserved)
	-$(PODMAN) stop $(DEV_DB_CONTAINER)

.PHONY: db-reset
db-reset:  ## destroy and recreate the dev Postgres container
	-$(PODMAN) rm -f $(DEV_DB_CONTAINER)
	$(MAKE) db-up

.PHONY: migrate-up
migrate-up: builder  ## apply all pending migrations to the dev database
	$(PODMAN) run $(RUN_OPTS) --network=host -e CGO_ENABLED=0 -t $(BUILDER_IMAGE) \
	    migrate -path db/migrations -database "$(DEV_DB_DSN)" up

.PHONY: migrate-down
migrate-down: builder  ## roll back one migration on the dev database
	$(PODMAN) run $(RUN_OPTS) --network=host -e CGO_ENABLED=0 -t $(BUILDER_IMAGE) \
	    migrate -path db/migrations -database "$(DEV_DB_DSN)" down 1

.PHONY: sqlc-gen
sqlc-gen: builder  ## regenerate internal/store from db/migrations + db/queries
	$(IN_BUILDER) sqlc generate

# ---- production migrations & import (host postgres) ---------------------------
# These read PROD_DB_DSN from the environment so the password never lands on
# disk in this Makefile. Source it from ~/.config/qudrat/db-password:
#   export PROD_DB_DSN="postgres://qudrat:$$(cat ~/.config/qudrat/db-password)@127.0.0.1:5432/qudrat?sslmode=disable"
.PHONY: migrate-up-prod
migrate-up-prod: builder  ## apply migrations to the host Postgres at $$PROD_DB_DSN
	@test -n "$$PROD_DB_DSN" || { echo "PROD_DB_DSN not set"; exit 1; }
	$(PODMAN) run $(RUN_OPTS) --network=host -e CGO_ENABLED=0 -t $(BUILDER_IMAGE) \
	    migrate -path db/migrations -database "$$PROD_DB_DSN" up

.PHONY: import-prod
import-prod: build-importer  ## seed items from $(QUESTIONS_DIR) into host Postgres
	@test -n "$$PROD_DB_DSN" || { echo "PROD_DB_DSN not set"; exit 1; }
	QUDRAT_DATABASE_DSN="$$PROD_DB_DSN" QUDRAT_QUESTIONS_DIR="$(QUESTIONS_DIR)" ./bin/importer

# ---- container images for k3s -------------------------------------------------
define IMAGE_SERVICE
.PHONY: image-$(1)
image-$(1): builder  ## build $(1) container image
	$(PODMAN) build -t localhost/qudrat/$(1):dev -f build/Containerfile.$(1) .

.PHONY: image-load-$(1)
image-load-$(1): image-$(1)  ## import $(1) image into k3s containerd
	$(PODMAN) save localhost/qudrat/$(1):dev | sudo k3s ctr images import -
endef
$(foreach svc,$(SERVICES),$(eval $(call IMAGE_SERVICE,$(svc))))

.PHONY: images
images: image-api image-worker image-importer image-web  ## build all service images

# ---- web (Next.js) ------------------------------------------------------------
.PHONY: image-web
image-web:  ## build qudrat web image (Next.js standalone)
	$(PODMAN) build -t $(WEB_IMAGE) -f build/Containerfile.web .

.PHONY: image-load-web
image-load-web: image-web  ## import web image into k3s containerd
	$(PODMAN) save $(WEB_IMAGE) | sudo k3s ctr images import -

.PHONY: web-dev
web-dev:  ## run Next.js dev server on :3000 (proxies /api → 127.0.0.1:8080)
	cd web && pnpm dev

.PHONY: web-build
web-build:  ## production build of the Next.js client
	cd web && pnpm install --frozen-lockfile=false && pnpm build

.PHONY: web-typecheck
web-typecheck:  ## tsc --noEmit in web/
	cd web && pnpm typecheck

# ---- one-shot redeploy --------------------------------------------------------
# `make redeploy`: rebuild → save → sudo-import → reapply nginx → reissue TLS
# → force pod replace. Use after any code change. Sudo prompts once.
.PHONY: save-tars
save-tars: image-api image-web image-worker image-importer  ## save all images to /tmp/qudrat-*.tar
	@for svc in api web worker importer; do \
	    rm -f /tmp/qudrat-$$svc.tar; \
	    $(PODMAN) save localhost/qudrat/$$svc:dev -o /tmp/qudrat-$$svc.tar; \
	    echo "    /tmp/qudrat-$$svc.tar"; \
	done

.PHONY: redeploy
redeploy: save-tars redeploy-quick  ## rebuild + redeploy (nginx + tls + force pod replace)

.PHONY: redeploy-quick
redeploy-quick:  ## redeploy from existing /tmp/qudrat-*.tar (skip rebuild)
	sudo bash scripts/redeploy.sh
	@echo "==> forcing pod replacement"
	@for component in api web bot; do \
	    if kubectl --context k3s-local -n qudrat get deploy "qudrat-$$component" >/dev/null 2>&1; then \
	        kubectl --context k3s-local -n qudrat delete pod -l "app.kubernetes.io/component=$$component" --wait=false; \
	        kubectl --context k3s-local -n qudrat rollout status "deploy/qudrat-$$component" --timeout=180s; \
	    fi; \
	done
	@echo "done."

# ---- k3s deployment -----------------------------------------------------------
.PHONY: ns
ns:  ## create the qudrat namespace
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

.PHONY: k8s-apply
k8s-apply:  ## kubectl apply the qudrat manifests from the homelab repo
	kubectl apply -f $(HOMELAB_DIR)/apps/qudrat/

.PHONY: k8s-restart
k8s-restart:  ## roll the api deployment to pick up a new image tag
	kubectl -n $(NAMESPACE) rollout restart deploy/qudrat-api

# ---- housekeeping -------------------------------------------------------------
.PHONY: clean
clean:  ## remove built artefacts (keeps caches)
	rm -rf bin dist coverage.out coverage.html

.PHONY: distclean
distclean: clean  ## also blow away go module + build caches
	rm -rf $(GOCACHE_HOST) $(GOPKG_HOST)
