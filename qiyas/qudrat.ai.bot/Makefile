# qudrat-bot — Telegram + WhatsApp bot for the qudrat practice platform.
# All Go work runs inside the builder container; no Go required on the host.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

GO_VERSION              := 1.26.2
BUILDER_IMAGE           := localhost/qudrat-bot-builder:dev
BUILDER_CONTAINERFILE   := build/Containerfile.builder

ROOT                    := $(CURDIR)
GOCACHE_HOST            := $(HOME)/.cache/qudrat-bot-go-build
GOPKG_HOST              := $(HOME)/.cache/qudrat-bot-go-pkg
NAMESPACE               := qudrat
HOMELAB_DIR             := $(abspath $(ROOT)/../../homelab)

$(shell mkdir -p $(GOCACHE_HOST) $(GOPKG_HOST))

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

.PHONY: help
help:
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST) | sort

.PHONY: builder
builder:  ## build the builder image (golang + golangci-lint + gofumpt)
	$(PODMAN) build -t $(BUILDER_IMAGE) -f $(BUILDER_CONTAINERFILE) build/

.PHONY: tidy
tidy: builder  ## go mod tidy
	$(IN_BUILDER) go mod tidy

.PHONY: fmt
fmt: builder  ## gofumpt + goimports via golangci-lint
	$(IN_BUILDER) golangci-lint fmt

.PHONY: lint
lint: builder  ## static analysis
	$(IN_BUILDER) golangci-lint run ./...

.PHONY: test
test: builder  ## unit tests with race detector
	$(IN_BUILDER_TEST) go test -race -shuffle=on -count=1 ./...

.PHONY: build
build: builder  ## build the bot binary into bin/
	$(IN_BUILDER) go build -trimpath -ldflags='-s -w' -o bin/bot ./cmd/bot

.PHONY: run
run: build  ## run the bot locally (needs env vars set)
	./bin/bot

.PHONY: image-bot
image-bot: builder  ## build the bot container image
	$(PODMAN) build -t localhost/qudrat-bot:dev -f build/Containerfile.bot .

.PHONY: image-load-bot
image-load-bot: image-bot  ## import bot image into k3s containerd
	$(PODMAN) save localhost/qudrat-bot:dev | sudo k3s ctr images import -

.PHONY: save-tar
save-tar: image-bot  ## save bot image to /tmp/qudrat-bot.tar
	rm -f /tmp/qudrat-bot.tar
	$(PODMAN) save localhost/qudrat-bot:dev -o /tmp/qudrat-bot.tar

.PHONY: redeploy
redeploy: save-tar  ## rebuild + redeploy bot
	sudo k3s ctr images rm localhost/qudrat-bot:dev >/dev/null 2>&1 || true
	sudo k3s ctr images import /tmp/qudrat-bot.tar
	kubectl --context k3s-local -n $(NAMESPACE) delete pod -l app.kubernetes.io/component=bot --wait=false
	kubectl --context k3s-local -n $(NAMESPACE) rollout status deploy/qudrat-bot --timeout=180s

.PHONY: k8s-apply
k8s-apply:  ## kubectl apply the bot manifests from the homelab repo
	kubectl --context k3s-local apply -f $(HOMELAB_DIR)/apps/qudrat/bot-deployment.yaml -f $(HOMELAB_DIR)/apps/qudrat/bot-service.yaml

.PHONY: clean
clean:
	rm -rf bin dist coverage.out
