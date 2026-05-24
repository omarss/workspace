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
        compose-up compose-down migrate migrate-down sqlc-gen sdk-ts sdk-go \
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

contract-test:
	@echo "[contract-test] starting stub server and prism proxy"
	# Wired in Phase 2 once /v1/tenants exists.
	@echo "not yet wired"

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
openapi-check: openapi-lint openapi-overlay openapi-gen-go openapi-gen-ts openapi-diff-check

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

openapi-diff-check:
	@git diff --exit-code -- internal/controlplane/httpapi internal/dataplane/httpapi sdk/ts \
	    || { echo "ERROR: generated code drifted from spec — commit regeneration"; exit 1; }

# ── SDKs ────────────────────────────────────────────────────────────────────
sdk-ts: openapi-gen-ts

sdk-go:
	# Wired in Phase 13 (Go SDK).
	@echo "not yet wired"

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

# ── housekeeping ────────────────────────────────────────────────────────────
clean:
	rm -rf bin openapi/_generated
