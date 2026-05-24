# ADR 001 — Stack pins and license rationale

## Status
Accepted (2026-05-24).

## Context

`AGENTS.md` §3.5 mandates OSI-only dependencies (AGPL only as standalone network
service; no BSL / SSPL / Elastic / source-available). §25.8 lists the approved
primitives. This ADR records the Q2 2026 pins from
`docs/plans/mvp/01-foundations.md` §1 together with the license of each
component, and the reasoning behind the choice.

## Decision

### Go module (`github.com/omarss/saas`, Go 1.24)

| Component | Version | License | Why |
|---|---|---|---|
| github.com/go-chi/chi/v5 | v5.3.0 | MIT | Idiomatic Go router; matches qudrat's convention. |
| github.com/jackc/pgx/v5 | v5.9.2 | MIT | Driver of record for Postgres; sqlc emits pgx/v5 code. |
| github.com/oapi-codegen/oapi-codegen/v2 | v2.7.0 | Apache-2.0 | OpenAPI -> chi-server strict-server stubs. Build-only. |
| github.com/oapi-codegen/nethttp-middleware | v1.1.2 | Apache-2.0 | OapiRequestValidatorWithOptions for AuthN hook. |
| github.com/oapi-codegen/runtime | v1.2.0 | Apache-2.0 | Generated code runtime support. |
| github.com/golang-migrate/migrate/v4 | v4.19.1 | MIT | Forward-only DDL runner with iofs source + pgx target. |
| github.com/oklog/ulid/v2 | v2.1.1 | Apache-2.0 | Sortable, monotonic ID generation (`tenant_`, `dep_`, …). |
| github.com/exaring/otelpgx | latest | MIT | OpenTelemetry tracing for pgx; verify Go-version compatibility. |
| go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp | v0.68.0 | Apache-2.0 | HTTP span wrapper. |
| github.com/go-playground/validator/v10 | latest | MIT | Struct/field validation. |
| golang.org/x/crypto | latest | BSD-3-Clause | argon2id + helpers; OWASP-2024 parameters. |
| github.com/openbao/openbao/api/v2 | v2.5.1 | MPL-2.0 | OpenBao client; OSS HashiCorp Vault fork after BSL change. |
| github.com/casbin/casbin/v2 | v2.135.0 | Apache-2.0 | RBAC-with-domains enforcement. |
| github.com/pckhoi/casbin-pgx-adapter/v3 | v3.2.0 | Apache-2.0 | Adapter; phase-7 compile-check required. |
| github.com/Nerzal/gocloak/v14 | v14.0.3 | Apache-2.0 | Keycloak admin client. |
| github.com/lestrrat-go/jwx/v3 | v3.1.1 | MIT | JWT/JWKS verification. |
| k8s.io/client-go | v0.30.x | Apache-2.0 | Typed apply against k3s; pinned to cluster minor. |
| sigs.k8s.io/kustomize/api | v0.21.1 | Apache-2.0 | Manifest rendering for per-Deployment overlays. |
| github.com/spf13/cobra | latest | Apache-2.0 | CLI scaffolding for `saasctl`. |
| sqlc | v1.31.1 | MIT | DB-typed query generation; build-only. |

### Node tooling (Dockerized via Makefile)

| Component | Version | License |
|---|---|---|
| @stoplight/spectral-cli | 6.16.0 | Apache-2.0 |
| @stoplight/prism-cli | 5.15.10 | Apache-2.0 |
| @openapitools/openapi-generator-cli | 7.22.0 | Apache-2.0 |

### Database / platform images

| Component | Version | License |
|---|---|---|
| PostgreSQL | 16+ | PostgreSQL License (BSD-style; OSI) |
| OpenBao | v2.5.4 | MPL-2.0 |
| Keycloak | 26.x | Apache-2.0 |

## Consequences

- Any new dependency requires its own ADR (per `AGENTS.md` §25.8).
- Pins are reviewed quarterly and per security advisory.
- `go install ...@latest` for code generators is forbidden; the Makefile pins
  them via `go run @<version>` or Docker image digests.
- AGPL is permitted only when the dependency is consumed as a standalone
  network service (none in Phase 1).
- BSL / SSPL / Elastic / source-available licenses are forbidden.
