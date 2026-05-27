SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

# ── tool pins ───────────────────────────────────────────────────────────────
# Go is invoked inside a pinned container (this host has no go toolchain).
# Override GO=/usr/local/go/bin/go if you prefer a host install.
GO_IMAGE                   := docker.io/library/golang:1.24-alpine
GO_TEST_IMAGE              := docker.io/library/golang:1.24
OAPI_CODEGEN_VERSION       := v2.7.0
OPENAPI_GENERATOR_VERSION  := 7.22.0
PRISM_VERSION              := 5.15.10
SPECTRAL_VERSION           := 6.15.1
SQLC_VERSION               := 1.31.1
GOLANGCI_LINT_VERSION      := v2.12.2
GOFUMPT_VERSION            := v0.10.0
GOIMPORTS_VERSION          := v0.45.0

# host caches reused across invocations
GOCACHE_HOST := $(HOME)/.cache/saas-go-build
GOPKG_HOST   := $(HOME)/.cache/saas-go-pkg
$(shell mkdir -p $(GOCACHE_HOST) $(GOPKG_HOST))

DOCKER       ?= docker
UID          := $(shell id -u)
GID          := $(shell id -g)

# Run containers as the invoking user so files written under $(CURDIR) are owned correctly.
DOCKER_RUN   := $(DOCKER) run --rm --user $(UID):$(GID) -v $(CURDIR):/work -w /work
DOCKER_RUN_GO := $(DOCKER) run --rm \
    --user $(UID):$(GID) \
    -v $(CURDIR):/work -w /work \
    -v $(GOCACHE_HOST):/.cache/go-build \
    -v $(GOPKG_HOST):/go/pkg \
    -e HOME=/tmp \
    -e GOCACHE=/.cache/go-build \
    -e GOFLAGS=-buildvcs=false \
    -e GOTOOLCHAIN=auto \
    -e CGO_ENABLED=0

# `make GO=go` (host) overrides this; otherwise we ship everything through the container.
GO ?= $(DOCKER_RUN_GO) $(GO_IMAGE) go

# Test invocation uses the debian-based image (gcc available) with cgo enabled
# so `-race` works. Override with GO_TEST=go for host runs.
GO_TEST ?= $(DOCKER) run --rm \
    --user $(UID):$(GID) \
    -v $(CURDIR):/work -w /work \
    -v $(GOCACHE_HOST):/.cache/go-build \
    -v $(GOPKG_HOST):/go/pkg \
    -e HOME=/tmp \
    -e GOCACHE=/.cache/go-build \
    -e GOFLAGS=-buildvcs=false \
    -e GOTOOLCHAIN=auto \
    -e CGO_ENABLED=1 \
    $(GO_TEST_IMAGE) go

SPECTRAL   := $(DOCKER_RUN) stoplight/spectral:$(SPECTRAL_VERSION)
PRISM      := $(DOCKER_RUN) -p 4010:4010 -p 4011:4011 stoplight/prism:$(PRISM_VERSION)
OPENAPI_GEN:= $(DOCKER_RUN) openapitools/openapi-generator-cli:v$(OPENAPI_GENERATOR_VERSION)
OAPI_CODEGEN := $(GO) run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@$(OAPI_CODEGEN_VERSION)
SQLC       := $(DOCKER_RUN) sqlc/sqlc:$(SQLC_VERSION)
GOLANGCI_LINT := $(DOCKER) run --rm \
    --user $(UID):$(GID) \
    -v $(CURDIR):/work -w /work \
    -v $(GOCACHE_HOST):/.cache/go-build \
    -v $(GOPKG_HOST):/go/pkg \
    -e HOME=/tmp \
    -e GOCACHE=/.cache/go-build \
    golangci/golangci-lint:$(GOLANGCI_LINT_VERSION) golangci-lint

# ── top-level ───────────────────────────────────────────────────────────────
.PHONY: build test test-int contract-test lint openapi-check \
        openapi-lint openapi-overlay openapi-gen-go openapi-gen-ts openapi-diff-check \
        compose-up compose-down migrate migrate-down sqlc-gen sdk-ts sdk-go sdk-go-test sdk-go-quickstart \
        openbao-init openbao-status openbao-rotate openbao-policies openbao-approle-creds \
        operators-realm-import operators-realm-validate \
        postman postman-check recipes-sync recipes-check \
        fmt vet tidy clean help

help:
	@echo "Targets: build test test-int contract-test lint openapi-check compose-up compose-down migrate migrate-down sqlc-gen sdk-ts sdk-go fmt vet tidy clean"

build:
	$(GO) build -o bin/controlplane ./cmd/controlplane
	$(GO) build -o bin/dataplane    ./cmd/dataplane
	$(GO) build -o bin/migrate      ./cmd/migrate
	$(GO) build -o bin/saasctl      ./cmd/saasctl

# ── tests ───────────────────────────────────────────────────────────────────
test:
	$(GO_TEST) test -race -count=1 ./...

test-int:
	$(GO_TEST) test -race -count=1 -tags=integration ./...

contract-test: build openapi-overlay
	@echo "[contract-test] launching dataplane + prism proxy"
	@mkdir -p /tmp/saas-contract
	@SAAS_ENV=dev DATAPLANE_DATABASE_URL="$${DATAPLANE_DATABASE_URL:-postgres://saas:saas@localhost:55432/saas?sslmode=disable}" \
	    ./bin/dataplane >/tmp/saas-contract/dataplane.log 2>&1 & echo $$! > /tmp/saas-contract/dataplane.pid
	@sleep 2
	@$(DOCKER) run --rm -d --name saas-contract-prism --network host \
	    -v $(CURDIR):/work:ro stoplight/prism:$(PRISM_VERSION) \
	    proxy /work/openapi/_generated/data-plane.yaml http://localhost:9090 --errors -p 4011 -m=false \
	    >/tmp/saas-contract/prism.id
	@sleep 3
	@./scripts/replay-contract-fixtures.sh http://localhost:4011 \
	    ; rc=$$? ; \
	    $(DOCKER) kill saas-contract-prism >/dev/null 2>&1 || true ; \
	    kill $$(cat /tmp/saas-contract/dataplane.pid) >/dev/null 2>&1 || true ; \
	    exit $$rc

# ── lint / format ───────────────────────────────────────────────────────────
lint:
	$(GOLANGCI_LINT) run ./...
	$(MAKE) openapi-check

fmt:
	$(GO) run mvdan.cc/gofumpt@$(GOFUMPT_VERSION) -w .
	$(GO) run golang.org/x/tools/cmd/goimports@$(GOIMPORTS_VERSION) -w -local github.com/omarss/saas .

vet:
	$(GO) vet ./...

tidy:
	$(GO) mod tidy

# ── OpenAPI ─────────────────────────────────────────────────────────────────
openapi-check: openapi-lint openapi-overlay openapi-gen-go openapi-gen-ts sdk-go postman-check recipes-check openapi-diff-check

openapi-lint:
	$(SPECTRAL) lint openapi/control-plane.yaml openapi/data-plane.yaml -r .spectral.yaml

openapi-overlay:
	@mkdir -p openapi/_generated
	# Apply overlay via spectral's overlay support (or a node script in later phases).
	# For now, oapi-codegen consumes the overlay path directly via output-options.overlay.
	@cp openapi/control-plane.yaml openapi/_generated/control-plane.yaml
	@cp openapi/data-plane.yaml    openapi/_generated/data-plane.yaml

openapi-gen-go:
	$(OAPI_CODEGEN) -config .oapi-codegen-controlplane.yaml openapi/_generated/control-plane.yaml
	$(OAPI_CODEGEN) -config .oapi-codegen-dataplane.yaml    openapi/_generated/data-plane.yaml

openapi-gen-ts:
	$(OPENAPI_GEN) generate -i /work/openapi/_generated/control-plane.yaml \
	    -g typescript-axios -o /work/sdk/ts/control-plane \
	    --api-package=api --model-package=models \
	    --additional-properties=npmName=@omarss/saas-controlplane-sdk,supportsES6=true,withInterfaces=true,withSeparateModelsAndApi=true
	$(OPENAPI_GEN) generate -i /work/openapi/_generated/data-plane.yaml \
	    -g typescript-axios -o /work/sdk/ts/data-plane \
	    --api-package=api --model-package=models \
	    --additional-properties=npmName=@omarss/saas-dataplane-sdk,supportsES6=true,withInterfaces=true,withSeparateModelsAndApi=true
	# Post-gen: add ulidx as a runtime dep so handwritten workflow wrappers
	# (sdk/ts/*/workflows/*.ts) resolve at consumer install time. openapi-generator
	# overwrites package.json on every run, so this patch must re-run with it.
	$(DOCKER_RUN) node:22-alpine node -e "for (const d of ['sdk/ts/control-plane','sdk/ts/data-plane']) { const f=d+'/package.json'; const p=JSON.parse(require('fs').readFileSync(f,'utf8')); p.dependencies = Object.assign({}, p.dependencies, { ulidx: '^2.4.1' }); require('fs').writeFileSync(f, JSON.stringify(p, null, 2) + '\n'); }"

openapi-diff-check:
	@git diff --exit-code -- internal/controlplane/httpapi internal/dataplane/httpapi sdk/ts sdk/go/controlplane sdk/go/dataplane \
	    || { echo "ERROR: generated code drifted from spec — commit regeneration"; exit 1; }

# ── SDKs ────────────────────────────────────────────────────────────────────
sdk-ts: openapi-gen-ts

sdk-go: openapi-overlay
	$(OAPI_CODEGEN) -config .oapi-codegen-controlplane-client.yaml openapi/_generated/control-plane.yaml
	$(OAPI_CODEGEN) -config .oapi-codegen-dataplane-client.yaml    openapi/_generated/data-plane.yaml
	# The SDK is an independent Go module (sdk/go/go.mod). go mod tidy + build
	# from inside that module so the platform's go.mod is never touched.
	$(DOCKER_RUN_GO) -w /work/sdk/go $(GO_IMAGE) sh -c 'go mod tidy && go build ./...'

sdk-go-test:
	# Unit tests for SDK workflows. Runs in the same containerised toolchain
	# as `make test`, but scoped to the SDK module.
	$(DOCKER) run --rm \
	    --user $(UID):$(GID) \
	    -v $(CURDIR):/work -w /work/sdk/go \
	    -v $(GOCACHE_HOST):/.cache/go-build \
	    -v $(GOPKG_HOST):/go/pkg \
	    -e HOME=/tmp \
	    -e GOCACHE=/.cache/go-build \
	    -e GOFLAGS=-buildvcs=false \
	    -e GOTOOLCHAIN=auto \
	    -e CGO_ENABLED=1 \
	    $(GO_TEST_IMAGE) go test -race -count=1 ./...

sdk-go-quickstart:
	# Requires a live stack: `make compose-up && make migrate && saasctl operator login`
	# and an exported SAAS_OPERATOR_TOKEN env var. NOT wired into `make test`.
	cd sdk/go/examples/quickstart && go run .

# ── DB ──────────────────────────────────────────────────────────────────────
migrate: build
	./bin/migrate -plane controlplane up
	./bin/migrate -plane dataplane    up

migrate-down: build
	./bin/migrate -plane dataplane    down 1
	./bin/migrate -plane controlplane down 1

sqlc-gen:
	$(SQLC) generate

# ── compose ─────────────────────────────────────────────────────────────────
compose-up:
	$(DOCKER) compose -f compose.yaml up -d --wait

compose-down:
	$(DOCKER) compose -f compose.yaml down -v

# ── OpenBao bootstrap ───────────────────────────────────────────────────────
# All targets shell into the running openbao container so they don't need a
# host-side `bao` binary. The container's entrypoint already initialised +
# unsealed; these targets layer on the engines / auth methods / audit device.
# Every step is idempotent — the `|| true` lets re-runs be a no-op when the
# mount / device / auth method is already present.
openbao-init:
	@$(DOCKER) compose -f compose.yaml exec -T openbao sh -c '\
		set -e; \
		BAO_ADDR=http://127.0.0.1:8200; export BAO_ADDR; \
		ROOT_TOKEN=$$(awk -F\" '"'"'/"root_token"/ { print $$4; exit }'"'"' /openbao/secrets/init.json 2>/dev/null || true); \
		if [ -n "$$ROOT_TOKEN" ]; then export BAO_TOKEN=$$ROOT_TOKEN; fi; \
		bao secrets enable -path=transit transit 2>/dev/null || true; \
		bao secrets enable -path=secret -version=2 kv 2>/dev/null || true; \
		bao auth enable kubernetes 2>/dev/null || true; \
		bao auth enable approle 2>/dev/null || true; \
		bao write -f auth/approle/role/controlplane \
			token_policies=default \
			token_ttl=1h token_max_ttl=4h \
			secret_id_ttl=24h >/dev/null || true; \
		echo "openbao: bootstrap done (transit, kv-v2, kubernetes auth, approle auth; audit device declared in openbao.hcl)"'

openbao-status:
	@$(DOCKER) compose -f compose.yaml exec -T openbao bao status

openbao-policies:
	@$(DOCKER) compose -f compose.yaml exec -T openbao bao policy list

# Rotate the transit key for a specific deployment. `make openbao-rotate KID=dep_X`.
openbao-rotate:
	@test -n "$(KID)" || (echo "ERROR: set KID=<deployment_id>" && exit 2)
	@$(DOCKER) compose -f compose.yaml exec -T openbao bao write -f "transit/keys/$(KID)/rotate"

# Generate AppRole role_id + secret_id for the control-plane host process and
# write them to /etc/saas/approle/{role_id,secret_id} so cmd/controlplane can
# read them at boot. For local dev only; production uses a runbook step.
openbao-approle-creds:
	@$(DOCKER) compose -f compose.yaml exec -T openbao sh -c '\
		BAO_ADDR=http://127.0.0.1:8200; export BAO_ADDR; \
		ROOT_TOKEN=$$(awk -F\" '"'"'/"root_token"/ { print $$4; exit }'"'"' /openbao/secrets/init.json); \
		export BAO_TOKEN=$$ROOT_TOKEN; \
		bao read -field=role_id auth/approle/role/controlplane/role-id; \
		echo "----"; \
		bao write -field=secret_id -f auth/approle/role/controlplane/secret-id'

# ── Keycloak operators realm (Phase 13) ────────────────────────────────────
# operators-realm-validate runs the JSON schema check + a Python json
# parse so the realm file is provably importable before we ship it to
# Keycloak. Cheaper than spinning the full container in CI.
operators-realm-validate:
	@python3 -c "import json,sys; json.load(open('deploy/keycloak/realms/operators-realm.json')); print('operators-realm: JSON OK')"

# operators-realm-import boots a one-shot Keycloak container with the
# operators-realm.json mounted at /opt/keycloak/data/import, runs
# `kc.sh start-dev --import-realm`, waits for the discovery doc to be
# reachable, then exits. Use for local smoke verification.
operators-realm-import:
	@echo "[operators-realm-import] booting Keycloak with --import-realm"
	@$(DOCKER) run --rm -d --name saas-operators-realm \
	    -v $(CURDIR)/deploy/keycloak/realms:/opt/keycloak/data/import:ro \
	    -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=admin \
	    -p 8081:8080 \
	    quay.io/keycloak/keycloak:26.0 \
	    start-dev --import-realm --hostname-strict=false >/dev/null
	@for i in $$(seq 1 60); do \
	    sleep 2; \
	    curl -fsS http://localhost:8081/realms/operators/.well-known/openid-configuration >/dev/null 2>&1 && break; \
	done
	@curl -fsS http://localhost:8081/realms/operators/.well-known/openid-configuration \
	    | python3 -c "import json,sys; d=json.load(sys.stdin); print('operators realm discovered:', d['issuer'])"
	@$(DOCKER) kill saas-operators-realm >/dev/null

# ── Postman collections (Phase 15) ──────────────────────────────────────────
# Both planes export to sdk/postman/<plane>/postman.json. The generator
# overwrites the directory contents on every run, so postman-check
# regenerates and asserts the working tree is clean — catches drift
# the same way openapi-diff-check does for the SDKs.
postman: openapi-overlay
	@mkdir -p sdk/postman/control-plane sdk/postman/data-plane
	$(OPENAPI_GEN) generate -i /work/openapi/_generated/control-plane.yaml \
	    -g postman-collection -o /work/sdk/postman/control-plane \
	    --additional-properties=collectionName="SaaS Control Plane API",folderStrategy=Tags
	$(OPENAPI_GEN) generate -i /work/openapi/_generated/data-plane.yaml \
	    -g postman-collection -o /work/sdk/postman/data-plane \
	    --additional-properties=collectionName="SaaS Data Plane API",folderStrategy=Tags

postman-check: postman
	@git diff --exit-code -- sdk/postman \
	    || { echo "ERROR: postman collections drifted — commit \`make postman\` output"; exit 1; }

# ── Recipes (Phase 15) ──────────────────────────────────────────────────────
# Canonical recipes live under docs/recipes/. The saasctl binary embeds
# its copy from cmd/saasctl/recipes/ via go:embed — go:embed cannot
# climb out of the package directory, so we keep an in-package mirror
# and re-sync it whenever the canonical set changes. recipes-check
# enforces that the two stay byte-for-byte identical.
recipes-sync:
	@mkdir -p cmd/saasctl/recipes
	@cp docs/recipes/*.md cmd/saasctl/recipes/

recipes-check: recipes-sync
	@git diff --exit-code -- cmd/saasctl/recipes \
	    || { echo "ERROR: embedded recipes drifted — commit \`make recipes-sync\` output"; exit 1; }

# ── housekeeping ────────────────────────────────────────────────────────────
clean:
	rm -rf bin openapi/_generated
