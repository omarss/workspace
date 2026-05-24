# Phase 1 — Walking Skeleton

> **Goal**: A repository that builds, lints, tests, and runs both binaries with `/healthz`, plus a local Compose stack of Postgres + Keycloak (dev) + OpenBao (dev) + SigNoz (optional, deferred). One end-to-end happy path: `POST /control/v1/deployments` against a **local-mode provisioner** that creates a Postgres database (and nothing else). No host writes; no k3s; no real nginx.
>
> **Outputs**: Empty platform that runs. Zero domain modules. Patterns are set but unused.
>
> **Maps to AGENTS.md**: §16 Phase 1 (bullets 1–6). §3.4 folder layout. §25.9 Makefile targets.
>
> **Estimated subagent sessions**: 2 (one for repo bootstrap + Makefile + compose, one for both binaries + migrate runner + first local-mode provisioner).

---

## Pre-flight (subagent reads first)

1. Read `AGENTS.md` (the contract).
2. Read `CLAUDE.md` (global + project).
3. Read `docs/plans/mvp/00-master.md` (this plan's invariants + rules).
4. Read `docs/plans/mvp/01-foundations.md` (Allowed APIs reference — every library version + signature you'll use comes from here).
5. Read `../qiyas/qudrat.ai/Makefile`, `../qiyas/qudrat.ai/sqlc.yaml`, `../qiyas/qudrat.ai/.golangci.yml`, `../qiyas/qudrat.ai/.github/PULL_REQUEST_TEMPLATE.md`, `../qiyas/qudrat.ai/go.mod`, and `../qiyas/qudrat.ai/internal/api/server/server.go` — these are the canonical templates to copy.

---

## Tasks (in order)

### 1.1 Repository bootstrap

Create the directory tree from `00-master.md` Appendix at `/home/omar/workspace_personal/saas/`. Use `mkdir -p` for new directories; do not touch `AGENTS.md` or `CLAUDE.md`.

`go.mod`:

```text
module github.com/omarss/saas

go 1.24

// All pins land here. Copy from 01-foundations.md §1.
```

After `go mod init`, add the pinned dependencies one-by-one with explicit versions:

```bash
go get github.com/go-chi/chi/v5@v5.3.0
go get github.com/jackc/pgx/v5@v5.9.2
go get github.com/golang-migrate/migrate/v4@v4.19.1
go get github.com/oklog/ulid/v2@v2.1.1
go get golang.org/x/crypto@latest
go get github.com/openbao/openbao/api/v2@v2.5.1
go get go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp@v0.68.0
go get github.com/exaring/otelpgx@latest
go get github.com/go-playground/validator/v10@latest
go get github.com/spf13/cobra@latest
go get github.com/oapi-codegen/runtime@v1.2.0
go get github.com/oapi-codegen/nethttp-middleware@v1.1.2
# (others added in later phases as needed)
```

`go mod tidy` after.

### 1.2 Copy local convention files

| Destination | Source | Adjustment |
|---|---|---|
| `.golangci.yml` | `../qiyas/qudrat.ai/.golangci.yml` | Change `local-prefixes: github.com/omarss/qudrat` → `github.com/omarss/saas`. |
| `.github/PULL_REQUEST_TEMPLATE.md` | `../qiyas/qudrat.ai/.github/PULL_REQUEST_TEMPLATE.md` | Replace Scope checkboxes with SaaS modules (see template below). |

PR template Scope section (replace verbatim):

```markdown
## Scope
- [ ] Control plane API (cmd/controlplane, internal/controlplane)
- [ ] Data plane API (cmd/dataplane, internal/dataplane)
- [ ] Platform shared (internal/platform: idempotency, etag, pagination, problem, log, crypto, auth)
- [ ] OpenAPI specs (openapi/)
- [ ] Migrations (migrations/controlplane, migrations/dataplane)
- [ ] Provisioning (deploy/k3s, deploy/nginx, deploy/openbao)
- [ ] SDK (sdk/ts, sdk/go)
- [ ] CLI (cmd/saasctl)
- [ ] Compose / local dev (compose.yaml, Dockerfile.*)
- [ ] CI / lint config
- [ ] Docs / ADRs
```

Keep the Testing and Checklist sections from qudrat verbatim. Add one line under Checklist: `- [ ] Tenant isolation invariant honored (see docs/plans/mvp/00-master.md)`.

### 1.3 Makefile (all §25.9 targets)

Create `/home/omar/workspace_personal/saas/Makefile`. Stub targets are OK where the underlying feature isn't built yet, but every target must exit 0 (or with a `not yet wired` message that is grep-safe).

```make
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

# ── tool pins ───────────────────────────────────────────────────────────────
GO ?= go
OAPI_CODEGEN_VERSION       := v2.7.0
OPENAPI_GENERATOR_VERSION  := 7.22.0
PRISM_VERSION              := 5.15.10
SPECTRAL_VERSION           := 6.16.0
SQLC_VERSION               := v1.31.1

DOCKER_RUN := docker run --rm -v $(PWD):/work -w /work
SPECTRAL   := $(DOCKER_RUN) stoplight/spectral:$(SPECTRAL_VERSION)
PRISM      := $(DOCKER_RUN) -p 4010:4010 -p 4011:4011 stoplight/prism:$(PRISM_VERSION)
OPENAPI_GEN:= $(DOCKER_RUN) openapitools/openapi-generator-cli:v$(OPENAPI_GENERATOR_VERSION)
OAPI_CODEGEN := $(GO) run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@$(OAPI_CODEGEN_VERSION)
SQLC       := $(DOCKER_RUN) sqlc/sqlc:$(SQLC_VERSION)

# ── top-level ───────────────────────────────────────────────────────────────
.PHONY: build test contract-test lint openapi-check \
        compose-up compose-down migrate sdk-ts sdk-go \
        fmt vet tidy clean help

help:
	@echo "Targets: build test contract-test lint openapi-check compose-up compose-down migrate sdk-ts sdk-go"

build:
	$(GO) build -o bin/controlplane ./cmd/controlplane
	$(GO) build -o bin/dataplane    ./cmd/dataplane
	$(GO) build -o bin/migrate      ./cmd/migrate
	$(GO) build -o bin/saasctl      ./cmd/saasctl

# ── tests ───────────────────────────────────────────────────────────────────
test:
	$(GO) test -race -count=1 ./...

test-int:
	$(GO) test -race -count=1 -tags=integration ./...

contract-test:
	@echo "[contract-test] starting stub server and prism proxy"
	# Wired in Phase 2 once /v1/tenants exists.
	@echo "not yet wired"

# ── lint / format ───────────────────────────────────────────────────────────
lint:
	golangci-lint run ./...
	$(MAKE) openapi-check

fmt:
	gofumpt -w .
	goimports -w -local github.com/omarss/saas .

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
	    --additional-properties=npmName=@omarss/saas-controlplane-sdk,supportsES6=true,withInterfaces=true,withSeparateModelsAndApi=true
	$(OPENAPI_GEN) generate -i /work/openapi/_generated/data-plane.yaml \
	    -g typescript-axios -o /work/sdk/ts/data-plane \
	    --additional-properties=npmName=@omarss/saas-dataplane-sdk,supportsES6=true,withInterfaces=true,withSeparateModelsAndApi=true

openapi-diff-check:
	git diff --exit-code -- internal/controlplane/httpapi internal/dataplane/httpapi sdk/ts || \
	    { echo "ERROR: generated code drifted from spec — commit regeneration"; exit 1; }

# ── SDKs ────────────────────────────────────────────────────────────────────
sdk-ts: openapi-gen-ts
sdk-go:
	# Wired in Phase 13 (Go SDK).
	@echo "not yet wired"

# ── DB ──────────────────────────────────────────────────────────────────────
migrate: build
	./bin/migrate -plane controlplane up
	./bin/migrate -plane dataplane    up

migrate-down:
	./bin/migrate -plane dataplane    down 1
	./bin/migrate -plane controlplane down 1

sqlc-gen:
	$(SQLC) generate

# ── compose ────────────────────────────────────────────────────────────────
compose-up:
	docker compose -f compose.yaml up -d --wait

compose-down:
	docker compose -f compose.yaml down -v

# ── housekeeping ────────────────────────────────────────────────────────────
clean:
	rm -rf bin openapi/_generated
```

Note: `golangci-lint`, `gofumpt`, `goimports` come from the developer's environment (not Dockerized). If the user prefers Dockerized lint, swap in `golangci/golangci-lint:latest`. Document the choice.

### 1.4 Spectral config

`/home/omar/workspace_personal/saas/.spectral.yaml`:

```yaml
extends: ["spectral:oas"]
rules:
  operation-operationId: error
  operation-operationId-unique: error
  operation-tags: error
  operation-tag-defined: error
  operation-success-response: error
  oas3-valid-media-example: error
  oas3-schema: error
  path-params: error
  no-$ref-siblings: error
  # SaaS-specific
  operation-description: warn
  operation-summary: warn
```

### 1.5 oapi-codegen configs

`/home/omar/workspace_personal/saas/.oapi-codegen-controlplane.yaml`:

```yaml
package: controlplaneapi
output: internal/controlplane/httpapi/server.gen.go
generate:
  models: true
  chi-server: true
  strict-server: true
  embedded-spec: true
output-options:
  skip-fmt: false
  skip-prune: false
  overlay:
    path: openapi/overlays/30-downgrade.yaml
```

`.oapi-codegen-dataplane.yaml` is the same, with `package: dataplaneapi` and `output: internal/dataplane/httpapi/server.gen.go`.

### 1.6 OpenAPI 3.1 → 3.0 overlay

`/home/omar/workspace_personal/saas/openapi/overlays/30-downgrade.yaml`:

```yaml
overlay: 1.0.0
info:
  title: Downgrade 3.1 → 3.0 for oapi-codegen
  version: 0.0.0
actions:
  - target: "$.openapi"
    update: "3.0.3"
  # Map type:[X, "null"] to nullable: true + type: X
  - target: '$.components.schemas..properties[?(@.type && length(@.type) == 2)]'
    update:
      type: string
      nullable: true
```

### 1.7 Skeleton OpenAPI specs

`/home/omar/workspace_personal/saas/openapi/control-plane.yaml`:

```yaml
openapi: 3.1.0
info:
  title: SaaS Control Plane API
  version: 0.0.1
  description: Operator-only API for provisioning and operating isolated SaaS deployments.
servers:
  - url: https://control.saas.omarss.net
tags:
  - name: meta
    description: Health and metadata.
paths:
  /healthz:
    get:
      operationId: getHealthz
      tags: [meta]
      summary: Liveness probe.
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Health"
components:
  schemas:
    Health:
      type: object
      required: [status]
      properties:
        status:
          type: string
          enum: [ok]
        version:
          type: string
        commit:
          type: string
```

`/home/omar/workspace_personal/saas/openapi/data-plane.yaml`: same shape, title "SaaS Data Plane API", server `https://{env}.{project}.saas.omarss.net`.

### 1.8 cmd/controlplane

`/home/omar/workspace_personal/saas/cmd/controlplane/main.go`:

```go
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)

var (
	version = "dev"
	commit  = "unknown"
)

func main() {
	if err := run(); err != nil {
		slog.Error("controlplane exited", "err", err)
		os.Exit(1)
	}
}

func run() error {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	slog.SetDefault(logger)

	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(60 * time.Second))

	r.Get("/healthz", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"status":"ok","version":%q,"commit":%q}`, version, commit)
	})

	srv := &http.Server{
		Addr:              ":8080",
		Handler:           otelhttp.NewHandler(r, "saas-controlplane"),
		ReadHeaderTimeout: 5 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		slog.Info("controlplane listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("listen failed", "err", err)
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return srv.Shutdown(shutdownCtx)
}
```

`cmd/dataplane/main.go` is the same with `:9090` and span name `"saas-dataplane"`.

### 1.9 cmd/migrate

`/home/omar/workspace_personal/saas/cmd/migrate/main.go`:

```go
package main

import (
	"embed"
	"flag"
	"fmt"
	"log/slog"
	"os"

	"github.com/golang-migrate/migrate/v4"
	_ "github.com/golang-migrate/migrate/v4/database/postgres"
	"github.com/golang-migrate/migrate/v4/source/iofs"
)

//go:embed migrations/controlplane/*.up.sql
var controlplaneFS embed.FS

//go:embed migrations/dataplane/*.up.sql
var dataplaneFS embed.FS

func main() {
	plane := flag.String("plane", "", "controlplane | dataplane")
	flag.Parse()

	if flag.NArg() < 1 {
		fmt.Fprintln(os.Stderr, "usage: migrate -plane <controlplane|dataplane> up|down [n]")
		os.Exit(2)
	}
	cmd := flag.Arg(0)

	var (
		dsn   string
		fsys  embed.FS
		root  string
		table string
	)
	switch *plane {
	case "controlplane":
		dsn = os.Getenv("CONTROLPLANE_DATABASE_URL")
		fsys = controlplaneFS
		root = "migrations/controlplane"
		table = "schema_migrations_controlplane"
	case "dataplane":
		dsn = os.Getenv("DATAPLANE_DATABASE_URL")
		fsys = dataplaneFS
		root = "migrations/dataplane"
		table = "schema_migrations_dataplane"
	default:
		fmt.Fprintln(os.Stderr, "unknown -plane")
		os.Exit(2)
	}
	if dsn == "" {
		fmt.Fprintln(os.Stderr, "DATABASE_URL not set")
		os.Exit(2)
	}
	dsn = fmt.Sprintf("%s&x-migrations-table=%s", dsn, table)

	src, err := iofs.New(fsys, root)
	if err != nil {
		slog.Error("iofs", "err", err); os.Exit(1)
	}
	m, err := migrate.NewWithSourceInstance("iofs", src, dsn)
	if err != nil {
		slog.Error("migrate.New", "err", err); os.Exit(1)
	}
	defer m.Close()

	switch cmd {
	case "up":
		err = m.Up()
	case "down":
		err = m.Steps(-1)
	default:
		fmt.Fprintln(os.Stderr, "unknown cmd")
		os.Exit(2)
	}
	if err != nil && err != migrate.ErrNoChange {
		slog.Error("migrate", "err", err); os.Exit(1)
	}
	slog.Info("migrate ok", "plane", *plane, "cmd", cmd)
}
```

Initial migration files (empty placeholders so the embed succeeds):

`/home/omar/workspace_personal/saas/migrations/controlplane/000001_init.up.sql`:

```sql
-- placeholder; real schema lands in Phase 10.
CREATE TABLE IF NOT EXISTS schema_bootstrap_controlplane (
    bootstrapped_at timestamptz NOT NULL DEFAULT now()
);
```

`/home/omar/workspace_personal/saas/migrations/dataplane/000001_init.up.sql`:

```sql
-- placeholder; real schema lands in Phase 2.
CREATE TABLE IF NOT EXISTS schema_bootstrap_dataplane (
    bootstrapped_at timestamptz NOT NULL DEFAULT now()
);
```

### 1.10 cmd/saasctl (stub)

`/home/omar/workspace_personal/saas/cmd/saasctl/main.go`:

```go
package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func main() {
	root := &cobra.Command{
		Use:   "saasctl",
		Short: "Operator CLI for the SaaS control plane.",
	}
	root.AddCommand(&cobra.Command{
		Use:   "version",
		Short: "Print version.",
		Run:   func(*cobra.Command, []string) { fmt.Println("saasctl dev") },
	})
	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
}
```

(Phase 2 adds `saasctl deployment list`; Phase 13 fills out the full command surface.)

### 1.11 Local Compose stack

`/home/omar/workspace_personal/saas/compose.yaml`:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: saas
      POSTGRES_PASSWORD: saas
      POSTGRES_DB: saas
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "saas"]
      interval: 2s
      timeout: 3s
      retries: 30

  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    command: start-dev --import-realm
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
      KC_DB: dev-file
    ports: ["8081:8080"]
    volumes:
      - ./deploy/keycloak/realms:/opt/keycloak/data/import:ro

  openbao:
    image: openbao/openbao:2.5.4
    cap_add: ["IPC_LOCK"]
    environment:
      BAO_DEV_ROOT_TOKEN_ID: dev-root
      BAO_DEV_LISTEN_ADDRESS: "0.0.0.0:8200"
    command: ["server", "-dev"]
    ports: ["8200:8200"]

  prism-mock-cp:
    image: stoplight/prism:5.15.10
    command: ["mock", "-h", "0.0.0.0", "-p", "4010", "/work/openapi/_generated/control-plane.yaml"]
    volumes: [".:/work:ro"]
    ports: ["4010:4010"]

  prism-mock-dp:
    image: stoplight/prism:5.15.10
    command: ["mock", "-h", "0.0.0.0", "-p", "4011", "/work/openapi/_generated/data-plane.yaml"]
    volumes: [".:/work:ro"]
    ports: ["4011:4011"]

volumes:
  pgdata: {}
```

**Why OpenBao runs in `-dev` mode for Phase 1**: the real `static`/Shamir unseal lands in Phase 6 (`07-openbao-integration.md`). Dev mode is "in-memory backend, root token = `dev-root`, auto-unsealed" — fine for skeleton, never for prod. The Compose file is rewritten in Phase 6.

**SigNoz is deferred** to Phase 14 (DX polish). OpenTelemetry instrumentation is wired in Phase 1 (`otelhttp.NewHandler`); without an exporter, traces drop, which is correct.

`/home/omar/workspace_personal/saas/deploy/keycloak/realms/` is empty in Phase 1. Real realm JSON lands in Phase 4 (Identity) and Phase 12 (operators MFA).

### 1.12 sqlc.yaml

`/home/omar/workspace_personal/saas/sqlc.yaml`:

```yaml
version: "2"
sql:
  - engine: "postgresql"
    queries: "internal/controlplane/db/queries"
    schema:  "migrations/controlplane"
    gen:
      go:
        package: "db"
        out: "internal/controlplane/db/sqlc"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_interface: true
        emit_pointers_for_null_types: true
        emit_enum_valid_method: true
  - engine: "postgresql"
    queries: "internal/dataplane/db/queries"
    schema:  "migrations/dataplane"
    gen:
      go:
        package: "db"
        out: "internal/dataplane/db/sqlc"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_interface: true
        emit_pointers_for_null_types: true
        emit_enum_valid_method: true
```

Two stanzas — control plane and data plane generate into different packages.

### 1.13 Dockerfiles

`/home/omar/workspace_personal/saas/Dockerfile.controlplane`:

```dockerfile
FROM golang:1.24-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG VERSION=dev
ARG COMMIT=unknown
RUN CGO_ENABLED=0 go build \
    -ldflags="-s -w -X main.version=${VERSION} -X main.commit=${COMMIT}" \
    -o /out/controlplane ./cmd/controlplane

FROM gcr.io/distroless/static:nonroot
COPY --from=build /out/controlplane /controlplane
USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/controlplane"]
```

Same for `Dockerfile.dataplane` (binary `dataplane`, port 8080 inside container).

### 1.14 CI workflow

`/home/omar/workspace_personal/saas/.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push: { branches: [main] }
  pull_request: { types: [opened, reopened, synchronize, labeled] }

jobs:
  gate:
    if: github.event_name == 'push' || contains(github.event.pull_request.labels.*.name, 'ready')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: "1.24", cache: true }
      - run: make tidy
      - run: git diff --exit-code go.mod go.sum
      - run: make vet
      - uses: golangci/golangci-lint-action@v6
        with: { version: latest }
      - run: make openapi-check
      - run: make build
      - run: make test

  integration:
    needs: gate
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: saas
          POSTGRES_PASSWORD: saas
          POSTGRES_DB: saas
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U saas" --health-interval 2s --health-timeout 3s --health-retries 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: "1.24", cache: true }
      - run: make build
      - env:
          CONTROLPLANE_DATABASE_URL: "postgres://saas:saas@localhost:5432/saas?sslmode=disable"
          DATAPLANE_DATABASE_URL:    "postgres://saas:saas@localhost:5432/saas?sslmode=disable"
        run: |
          ./bin/migrate -plane controlplane up
          ./bin/migrate -plane dataplane    up
      - run: make test-int
```

CI runs only on PRs that carry the `ready` label (per project CLAUDE.md).

### 1.15 ADRs 001 + 002

`/home/omar/workspace_personal/saas/docs/adr/001-stack-and-licenses.md`:

```markdown
# ADR 001 — Stack pins and license rationale

## Status
Accepted (2026-05-24).

## Context
AGENTS.md §3.5 mandates OSI-only dependencies (AGPL only as standalone network service;
no BSL / SSPL / Elastic / source-available). §25.8 lists the approved primitives.
This ADR records the Q2 2026 pins and the license of each.

## Decision
[Table copied from docs/plans/mvp/01-foundations.md §1, with license columns and reasoning.]

## Consequences
- Any new dependency requires an ADR (§25.8).
- Pins are reviewed on a fixed cadence (quarterly) and per security advisory.
```

`/home/omar/workspace_personal/saas/docs/adr/002-openapi-3.1-with-overlay-downgrade.md`:

```markdown
# ADR 002 — OpenAPI 3.1 authoring with overlay-downgrade for oapi-codegen

## Status
Accepted (2026-05-24).

## Context
- We author the contract in OpenAPI 3.1 (full JSON Schema 2020-12, webhooks section).
- oapi-codegen v2.7 does not natively support 3.1 (issue #373, blocked on Go 1.26).
- openapi-generator-cli 7.22.0 (typescript-axios) handles 3.1 with caveats.

## Decision
Apply an Overlay 1.0 transformation that down-converts the 3.1 spec to 3.0.3 before
oapi-codegen runs. Generated files live under openapi/_generated/. Spectral lints the
3.1 source. TS SDK is generated from the 3.0 down-converted copy as well, until the
ts generator's 3.1 path is verified.

## Consequences
- Authors write 3.1, tooling sees 3.0 — keep an eye on 3.1-only constructs that the
  overlay can't smoothly down-convert (prefixItems, unevaluatedProperties, $dynamicRef).
  These are banned in our spec until issue #373 closes.
- Revisit when oapi-codegen merges feat/kin-openapi-3.1.
```

### 1.16 Initial commit + push

Per global CLAUDE.md (atomic commits, lowercase ≤ 50 chars, no Co-Authored-By):

```bash
git add .
git status         # confirm contents
git commit -m "bootstrap saas repo"
# Sync with main; push later when CI has been smoke-tested.
```

If the user wants to sanity-check Phase 1 before pushing, stop after `git status` and surface what's staged.

---

## Verification checklist (subagent runs these)

```bash
# 1. Repo builds:
$ make build
# Expected: bin/controlplane, bin/dataplane, bin/migrate, bin/saasctl

# 2. Linters clean:
$ make lint
# Expected: 0 findings

# 3. OpenAPI specs valid:
$ make openapi-check
# Expected: spectral 0 errors; oapi-codegen generates internal/{controlplane,dataplane}/httpapi/server.gen.go

# 4. Compose stack starts:
$ make compose-up
$ docker compose -f compose.yaml ps
# Expected: postgres, keycloak, openbao, prism-mock-cp, prism-mock-dp all healthy

# 5. Migrations run:
$ CONTROLPLANE_DATABASE_URL="postgres://saas:saas@localhost:5432/saas?sslmode=disable" \
  DATAPLANE_DATABASE_URL="postgres://saas:saas@localhost:5432/saas?sslmode=disable" \
  make migrate
# Expected: both planes report "migrate ok"

# 6. Binaries serve /healthz:
$ ./bin/controlplane &
$ curl -s http://localhost:8080/healthz | jq .
# Expected: {"status":"ok","version":"dev","commit":"unknown"}
$ kill %1
$ ./bin/dataplane &
$ curl -s http://localhost:9090/healthz | jq .
# Expected: {"status":"ok","version":"dev","commit":"unknown"}
$ kill %1

# 7. Prism mocks serve the spec:
$ curl -s http://localhost:4010/healthz | jq .
$ curl -s http://localhost:4011/healthz | jq .
# Expected: 200 OK with Health schema

# 8. saasctl runs:
$ ./bin/saasctl version
# Expected: "saasctl dev"

# 9. CI workflow lints clean (act or push to a branch):
$ act -j gate           # optional local
# Expected: green

# 10. Generated code is committed and stable:
$ make openapi-check
$ git status --porcelain
# Expected: empty (no drift)
```

If any of these fail, the phase is not done.

---

## Anti-pattern guards (do not do these)

- **Do not** add domain logic (tenants, users, organizations) in Phase 1. That belongs to Phase 2+.
- **Do not** wire OpenBao secret storage yet — the dev-mode container is for Phase 1 smoke only. Real envelope encryption lands in Phase 6.
- **Do not** add Keycloak realm JSON yet. Phase 4 owns Identity; Phase 12 owns operators realm. The Keycloak container in Phase 1 boots empty.
- **Do not** call `make -C ../homelab apply-nginx`. The platform never re-runs homelab's bulk apply (clobbers certbot). Phase 11a writes per-vhost.
- **Do not** put `tenant_id` in any URL path, query string, or request body in this phase. There are no tenants yet, and when they arrive in Phase 2, `tenant_id` will come from the JWT only.
- **Do not** invent endpoints that aren't in the OpenAPI spec. The only endpoint in Phase 1 is `/healthz`.
- **Do not** commit secrets to compose.yaml. The `dev-root` token + `admin` password are dev-only sentinel strings; document this in compose.yaml comments.
- **Do not** use `r.PathValue` from chi handlers. Use `chi.URLParam(r, "name")` — oapi-codegen's chi target depends on it.
- **Do not** `go install ...@latest` for any generator. Use the pinned versions.
- **Do not** skip pre-commit hooks (`--no-verify`). Per global CLAUDE.md.

---

## Open questions for the user (surface before completing Phase 1)

1. **Module path.** This plan uses `github.com/omarss/saas` to mirror qudrat. If you want a different vanity URL or a private repo path (e.g. `github.com/yourorg/saas`), say so before `go mod init`.
2. **PR-by-PR vs single Phase-1 PR.** This phase has ~15 files; default is one PR titled `bootstrap saas repo`. If you prefer to land sub-pieces incrementally (Makefile, then compose, then binaries, then migrate, then CI), say so.
3. **Compose components in Phase 1.** Plan includes Postgres + Keycloak + OpenBao (dev) + Prism mocks. SigNoz is deferred to Phase 14. If you want SigNoz now for observability dogfooding, add a `signoz` service.

---

## Phase 1 — Definition of done

- [ ] All files in §1.1–§1.15 exist on disk
- [ ] `make build` succeeds
- [ ] `make lint` succeeds (golangci-lint + spectral)
- [ ] `make openapi-check` succeeds
- [ ] `make compose-up` brings up all services and they pass healthchecks
- [ ] `make migrate` applies the placeholder migrations
- [ ] `curl /healthz` on both binaries returns 200 + version + commit
- [ ] Prism mocks serve `/healthz` from the specs
- [ ] `git status --porcelain` is empty after a fresh `make openapi-check` (no codegen drift)
- [ ] ADR 001 + ADR 002 committed
- [ ] PR template + .golangci.yml present
- [ ] CI workflow exists and parses
- [ ] User has reviewed the open questions (§Open questions) and confirmed answers
- [ ] Commit titled `bootstrap saas repo` lands on a feature branch

After Phase 1 — no checkpoint; proceed directly to Phase 2 (Tenants vertical slice).

---

End of Phase 1. Next: `03-tenants-slice.md`.
