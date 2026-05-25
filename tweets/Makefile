# tweets — feed service for the omono Twitter tab.
# Hosts a small HTTP/JSON endpoint that the Android app consumes.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

GO     ?= go
BINARY := bin/tweetsd
ADDR   ?= :8080

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: build
build: ## Compile the tweetsd binary into ./bin/
	mkdir -p bin
	$(GO) build -o $(BINARY) ./cmd/tweetsd

.PHONY: run
run: ## Run tweetsd on $ADDR (default :8080)
	$(GO) run ./cmd/tweetsd -addr $(ADDR)

.PHONY: test
test: ## Run unit tests
	$(GO) test ./...

.PHONY: lint
lint: ## go vet (full golangci-lint can be added when needed)
	$(GO) vet ./...

.PHONY: tidy
tidy: ## Update go.mod / go.sum
	$(GO) mod tidy

.PHONY: clean
clean: ## Remove build artefacts
	rm -rf bin
