# ivr — multi-tenant conversational IVR platform.
# All Go work runs inside the builder container; no Go required on the host.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# ---- toolchain pins -----------------------------------------------------------
GO_VERSION              := 1.26.2
BUILDER_BASE            := docker.io/library/golang:$(GO_VERSION)-alpine
BUILDER_IMAGE           := localhost/ivr-builder:dev
BUILDER_CONTAINERFILE   := build/Containerfile.builder

# ---- workspace ----------------------------------------------------------------
ROOT                    := $(CURDIR)
GOCACHE_HOST            := $(HOME)/.cache/ivr-go-build
GOPKG_HOST              := $(HOME)/.cache/ivr-go-pkg
SERVICES                := api admin orchestrator webhook-ingress webhook-delivery
NAMESPACE               := ivr-dev

$(shell mkdir -p $(GOCACHE_HOST) $(GOPKG_HOST))

# ---- container runners --------------------------------------------------------
# `make sh` opens an interactive shell. CI runs commands via $(IN_BUILDER).
PODMAN  := podman
# CGO is off by default for static binary builds; tests override to 1 so the
# race detector works.
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
	@command -v helm     >/dev/null || { echo "helm missing"; exit 1; }
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
test-int: builder  ## integration tests (testcontainers, requires podman socket)
	$(IN_BUILDER_TEST) go test -tags=integration -race -count=1 ./...

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

# ---- container images for k3s -------------------------------------------------
# Each service has a tiny multi-stage Dockerfile under build/Containerfile.<svc>
# (added in a later phase). For now `image-<svc>` is wired up for when they exist.
define IMAGE_SERVICE
.PHONY: image-$(1)
image-$(1):  ## build $(1) container image
	$(PODMAN) build -t localhost/ivr-$(1):dev -f build/Containerfile.$(1) .

.PHONY: image-load-$(1)
image-load-$(1): image-$(1)  ## import $(1) image into k3s containerd
	$(PODMAN) save localhost/ivr-$(1):dev | sudo k3s ctr images import -
endef
$(foreach svc,$(SERVICES),$(eval $(call IMAGE_SERVICE,$(svc))))

# ---- k3s deployment -----------------------------------------------------------
.PHONY: ns
ns:  ## create the dev namespace
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

.PHONY: deploy-deps
deploy-deps: ns  ## deploy PG (Percona), NATS, Valkey, SeaweedFS, Svix into $(NAMESPACE)
	@echo "TODO Phase 0 task #10 — wired in next commit"

.PHONY: deploy-api
deploy-api:  ## kustomize apply the api service to $(NAMESPACE)
	kubectl -n $(NAMESPACE) apply -k deploy/k8s/overlays/dev

.PHONY: smoke
smoke:  ## health check the api service from inside the cluster
	kubectl -n $(NAMESPACE) run smoke --rm -it --image=curlimages/curl:latest --restart=Never -- \
	    curl -fsS http://api.$(NAMESPACE).svc.cluster.local/healthz

# ---- housekeeping -------------------------------------------------------------
.PHONY: clean
clean:  ## remove built artefacts (keeps caches)
	rm -rf bin dist coverage.out coverage.html

.PHONY: distclean
distclean: clean  ## also blow away go module + build caches
	rm -rf $(GOCACHE_HOST) $(GOPKG_HOST)
