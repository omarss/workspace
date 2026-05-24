# AGENTS.md

## Project: SaaS Control Plane & Backend Platform

This repository implements an opinionated, OpenAPI-first SaaS backend platform with a
**control plane** that provisions isolated, per-product SaaS deployments on demand.

Two distinct API surfaces:

```text
Control Plane API   →  operator-only; provisions/destroys/upgrades deployments
Data Plane API      →  one instance per deployment; what product builders integrate with
```

Product goal:

```text
Stop rebuilding SaaS plumbing. Build the business logic.
Each SaaS product gets its own isolated, versioned, API-provisioned stack.
```

The platform should feel like:

```text
Operator: POST /control/v1/deployments  →  isolated SaaS stack appears
Builder:  Choose modules, generate SDKs, build product against the new data plane URL
Customer: Signs up, gets a tenant, uses the product
```

---

## 0. Personas and Calling Patterns

Every API decision in this document must be readable through one of these personas.
If a proposed endpoint does not have an obvious persona, it is probably misplaced.

| Persona | Who | Surface | Auth | Notes |
|---|---|---|---|---|
| Platform Operator | The person running this machine (Omar) | Control Plane API | OIDC + step-up + IP allowlist | Highest blast radius. Every action audited. |
| Product Builder | Team building a SaaS product on top of a Deployment | Data Plane API (admin scope) | OIDC | Owns plans, entitlements, webhook endpoints, API keys, audit views |
| Tenant Admin | The Product Builder's *customer's* admin | Data Plane API | OIDC | Manages org, members, roles; views subscription/invoices |
| Tenant User | End user of the Product Builder's app | Data Plane API | OIDC | Profile, inbox, own data |
| Machine Client | Server-to-server caller | Data Plane API | Bearer API key | Usage events, billing, notifications, webhook delivery |

Rules:

```text
Control Plane and Data Plane are physically separated services with separate JWT audiences.
A Data Plane token must never grant Control Plane access.
A Control Plane operator may impersonate into a Data Plane only via an audited impersonation session.
```

---

## 1. Product Thesis

Most SaaS products repeatedly rebuild the same backend foundation:

```text
identity
tenancy
organizations
teams
roles
permissions
billing
subscriptions
usage metering
entitlements
notifications
files
audit logs
API keys
webhooks
admin tools
analytics
support
observability
```

The platform provides these as reusable, documented, secure, observable, auditable, API-driven modules.

Product builders should only need to build:

```text
domain model
domain workflows
unique UI
business logic
pricing details
special integrations
go-to-market
```

---

## 2. Positioning

Primary positioning:

```text
An opinionated, API-provisioned backend platform for launching isolated B2B SaaS products faster.
```

Preferred niche positioning:

```text
Compliance-aware SaaS backend for B2B startups in KSA/MENA, with per-product isolation by default.
```

Avoid positioning as:

```text
Open-source Firebase alternative.
Generic backend-as-a-service.
No-code app builder.
Plugin marketplace.
```

This platform is not trying to compete directly with Firebase, Supabase, Appwrite, or Nhost as a
generic backend platform. It is a SaaS *operating layer* with a control plane for serious B2B products.

---

## 3. Architecture Philosophy

### 3.1 Control plane + isolated data planes

The platform is a **control plane** that provisions and operates many isolated **data plane
deployments**. Each Deployment is a full, independent SaaS stack — its own Postgres database,
its own k3s namespace, its own nginx vhost, its own TLS cert, its own version pin.

```text
                Control Plane (single global instance)
                ├── deployments registry (Postgres)
                ├── provisioning workers
                ├── observability rollup
                └── operator admin
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        Deployment A   Deployment B   Deployment C
        (k3s ns A)     (k3s ns B)     (k3s ns C)
        (Postgres A)   (Postgres B)   (Postgres C)
        (vhost A)      (vhost B)      (vhost C)
```

Why isolate:

```text
hard tenant-boundary by default (defense in depth)
per-product backup/restore and PITR
per-product version pin and rollback
per-product scale and resource quota
per-product data residency
clean blast radius — one deployment falling over does not take others with it
```

Tradeoff: more Postgres databases, more nginx vhosts, more certs. Mitigated by automation
(see §6 Homelab Deployment Model).

### 3.2 Build an API-driven façade

Expose one clean public API per plane:

```text
Control Plane API   (operator)
Data Plane API      (everyone else)
```

External users and product teams must not integrate directly with internal tools such as:

```text
Keycloak
Lago
Novu
OpenFGA
MinIO
PostHog
Chatwoot
Grafana
Prometheus
Loki
SigNoz
Infisical
Directus
```

They integrate only with the platform APIs and generated SDKs.

### 3.3 Contract-first

The OpenAPI contract is the source of truth. Two specs: `openapi/control-plane.yaml` and
`openapi/data-plane.yaml`.

Backend implementation, generated SDKs, docs, mocks, and contract tests should be derived
from or validated against the OpenAPI specifications.

```text
Do not implement endpoints that are not represented in the OpenAPI contract.
Do not change public response shapes without updating the OpenAPI contract.
Do not invent breaking changes — see §27 Breaking Change Policy.
```

### 3.4 Modular monolith first (per plane)

Do not start with microservices. Each plane is a single Go binary with strict module boundaries.

Preferred structure (Go):

```text
saas/
  cmd/
    controlplane/        # control plane binary
    dataplane/           # data plane binary (one process per Deployment in k3s)
    migrate/             # migration runner
  internal/
    controlplane/
      deployments/       # provisioning, lifecycle
      operators/         # operator admin
      observability/     # rollup, billing, usage telemetry
    dataplane/
      identity/
      tenancy/
      organizations/
      authorization/
      apikeys/
      audit/
      billing/           # v1 — deferred behind module flag
      entitlements/      # v1 — deferred
      notifications/     # v1 — deferred
      files/             # v1 — deferred
      webhooks/          # v1 — deferred
    platform/            # shared: logger, problem-details, idempotency, pagination, ids
  openapi/
    control-plane.yaml
    data-plane.yaml
  migrations/
    controlplane/        # one schema, one DB
    dataplane/           # applied to every Deployment's DB on provision / upgrade
  deploy/
    k3s/                 # base manifests + per-deployment template
    nginx/               # vhost template (pre-certbot, mirrors homelab/nginx pattern)
  sdk/
    ts/                  # generated + hand-written workflows
    go/                  # generated + hand-written workflows
```

Each module owns its application services, domain model, ports, adapters, persistence mapping,
and tests.

Cross-module access must go through application services, ports, or domain events. Do not perform
direct cross-module table access unless explicitly designed and documented.

### 3.5 Reuse over reinvent; commercial-friendly licenses

Default to well-maintained, OSI-approved, commercial-friendly OSS for every cross-cutting
concern. Do not write a new library when a healthy one exists.

License rules:

```text
Prefer                MIT, Apache-2.0, BSD, MPL-2.0, PostgreSQL, ISC
Acceptable for SaaS   AGPL-3.0 ONLY when consumed as a separate network service
                      (e.g. Lago/Grafana/Loki/MinIO running in their own processes,
                      called over the network). Never link or vendor AGPL code into
                      platform binaries.
Avoid                 BSL, SSPL, Elastic License v2, "source-available", Commons Clause,
                      any non-OSI license. These create commercial risk and surprise
                      relicenses (Directus is the canonical example — drop it).
```

When choosing a dependency, check in this order:

```text
1. Is there an obvious incumbent with > 1k stars, recent commits, and an OSI license? Use it.
2. Is it Apache/MIT/BSD/MPL? Default to yes.
3. Is it AGPL? Yes only if we run it as a standalone service we call over the network.
4. Is it BSL/SSPL/Elastic/Commons? No, find an alternative or build only what we must.
5. Only when nothing of the above exists, write our own — and keep it minimal.
```

Document each non-obvious dependency choice in `docs/adr/` with the alternatives considered
and the license rationale.

### 3.6 Internal architecture per module

Use this pattern:

```text
HTTP handler
  -> Application Service
    -> Domain Service
      -> Port (Go interface)
        -> Adapter
          -> External system or database
```

Example (Go, data plane):

```text
POST /v1/users
  -> users.Handler.Create
    -> users.Service.Create
      -> identity.Port.CreateUser
        -> keycloak.IdentityAdapter.CreateUser
```

The public API never mentions Keycloak.

---

## 4. Recommended Technology Stack

### 4.1 Backend (both planes)

All picks are well-maintained, OSI-licensed, and chosen to avoid reinventing primitives.
Licenses noted; nothing AGPL/BSL is linked into the binary (per §3.5).

```text
Go 1.23+
chi                              # MIT          — HTTP router, stdlib-compatible
sqlc                             # MIT          — type-safe queries (matches qudrat/qiyas)
pgx                              # MIT          — Postgres driver
golang-migrate                   # MIT          — forward-only migrations
oapi-codegen                     # Apache 2.0   — OpenAPI server stubs + types
testcontainers-go                # MIT          — real Postgres in tests
slog (stdlib)                    # stdlib       — structured logs (fallback: zerolog, MIT)
otelhttp + otelpgx               # Apache 2.0   — OpenTelemetry instrumentation
casbin                           # Apache 2.0   — RBAC engine (do not roll our own)
cobra                            # Apache 2.0   — saasctl operator CLI
client-go                        # Apache 2.0   — Kubernetes API client
kustomize                        # Apache 2.0   — k8s manifest templating (not string templates)
oklog/ulid                       # Apache 2.0   — ULIDs for public IDs
golang.org/x/crypto/argon2       # BSD          — API key hashing
go-playground/validator          # MIT          — request validation
openbao/api                      # MPL 2.0      — Vault/OpenBao client (see §18.7)
asynq                            # Apache 2.0   — background jobs (deferred until outbox alone is insufficient)
watermill                        # MIT          — alternative event router (only if asynq is wrong fit)
```

Forbidden in MVP without ADR: any new infra dependency under AGPL, BSL, SSPL, Elastic
License v2, or "source available" terms.

Backend style:

```text
REST JSON over HTTPS
OpenAPI 3.1 first (pin generator versions — see §11)
Modular monolith per plane
Hexagonal architecture per module
Postgres-first persistence
Event-driven integration via outbox table
```

### 4.2 Frontend starter

Default (post-MVP):

```text
Next.js (App Router)
TypeScript
shadcn/ui
@platform/sdk-ts (generated + handwritten wrappers)
```

In MVP, ship a static HTML + curl walkthrough instead of a full Next.js app. A walkthrough
proves the API faster and reaches Go/Python/Ruby consumers too.

### 4.3 Infrastructure (this machine)

The platform runs on the existing homelab (see §6):

```text
host nginx                    # vhost per deployment, TLS via certbot
host Postgres (single instance)   # database-per-deployment
k3s (single cluster)          # namespace-per-deployment
host MinIO or S3-compatible   # shared object storage; bucket-per-deployment
Infisical                     # secrets
SigNoz or Prom/Grafana/Loki   # observability
```

Deployment path:

```text
Self-hosted on this homelab first.
Hosted multi-tenant offering later.
Customer-self-hosted enterprise package later.
```

### 4.4 Open source components matrix

All defaults are well-maintained projects with commercial-friendly licenses. AGPL components
are only used **as standalone network services** (no AGPL code is linked or vendored into the
platform binaries). Source-available / BSL / SSPL projects are not used at all — see §3.5.

| Capability | Default | License | Status / notes |
|---|---|---|---|
| Identity | Keycloak | Apache 2.0 | Required MVP |
| Authorization | Casbin (RBAC); OpenFGA later if ReBAC needed | Apache 2.0 / Apache 2.0 | MVP = Casbin |
| Secrets + crypto vault | OpenBao | MPL 2.0 | Required MVP — replaces Infisical (see §18.7) |
| Database | Postgres | PostgreSQL License | Required MVP |
| Observability | OpenTelemetry + SigNoz | Apache 2.0 / MIT | Required MVP |
| Metrics | VictoriaMetrics (preferred) or Prometheus | Apache 2.0 / Apache 2.0 | Required MVP |
| Logs | VictoriaLogs (preferred) or Loki (AGPL service) | Apache 2.0 / AGPL 3.0 | Required MVP — prefer VictoriaLogs |
| Dashboards | Grafana (network service) or Perses | AGPL 3.0 / Apache 2.0 | Required MVP — Grafana OK as service; consider Perses to stay AGPL-free |
| Queue / events | Postgres outbox first; asynq later | — / Apache 2.0 | MVP = outbox |
| Object storage | SeaweedFS or any S3-compatible managed (R2, B2, S3) | Apache 2.0 / commercial | Deferred — avoid MinIO (AGPL relicense) |
| Billing | Lago (consumed as network service) | AGPL 3.0 | Deferred — OK as service, never vendored |
| Notifications | Novu (consumed as network service) | Apache 2.0 | Required MVP — email + in-app (SMS / WhatsApp v1) — see ADR 013 |
| Analytics | PostHog | MIT | Deferred |
| Support | Chatwoot | MIT | Deferred |
| Admin / data tooling | — (own Admin API; Refine for ad-hoc UI) | MIT | Deferred — Directus dropped (BSL relicense) |

Important rules:

```text
1. Do not expose these tools directly through the public product API. Wrap them behind
   stable platform abstractions.
2. Never link AGPL code into the platform binaries. AGPL is acceptable only when the tool
   runs as a separate process and the platform communicates with it over the network.
3. Reject any future dependency under BSL, SSPL, Elastic License v2, Commons Clause, or
   other "source available / non-OSI" terms.
```

---

## 5. Public API Principles

These apply to **both** Control Plane and Data Plane APIs.

| Area | Decision |
|---|---|
| API style | REST JSON over HTTPS |
| Contract | OpenAPI 3.1.x (pinned generator versions) |
| Auth (humans) | OAuth2 / OIDC Bearer JWT |
| Auth (machines) | Bearer API keys |
| Versioning | `/v1` path versioning; see §27 Breaking Change Policy |
| Errors | RFC 9457 Problem Details |
| Pagination | Cursor-based, opaque cursors |
| Concurrency | ETag + `If-Match` on PATCH/PUT/DELETE |
| Writes | `Idempotency-Key` header with 24 h replay window |
| Tenant isolation | Tenant context **resolved from token**, not header (see §5.1) |
| Rate limiting | `RateLimit-*` headers (IETF draft), 429 on exceed |
| SDKs | Generated from OpenAPI + thin handwritten workflow wrappers |
| Webhooks | First-class event system with signed payloads and `event_version` |
| Internal tools | Hidden behind ports/adapters |

### 5.1 Common headers

User-authenticated calls (Data Plane):

```http
Authorization: Bearer <jwt>
X-Request-Id: req_...
Idempotency-Key: idem_...
If-Match: "<etag>"
```

Machine-authenticated calls:

```http
Authorization: Bearer <api_key_secret>
X-Request-Id: req_...
Idempotency-Key: idem_...
```

**Tenant context is resolved from the token, not from a header.** The JWT carries `tenant_id`,
`environment_id`, and `actor_id` claims; API keys are bound to one tenant at creation.

Optional `X-Acting-Tenant-Id` is only allowed when the token carries the
`tenants.impersonate` scope (operator impersonation). When present, every audit row carries
both `actor_tenant_id` and `impersonated_tenant_id`. Conflicts between path tenant and
token tenant always 403.

### 5.2 Idempotency

All unsafe writes support idempotency via the `Idempotency-Key` header.

```http
Idempotency-Key: idem_<ulid>
```

Required on:

```text
POST
PATCH on state-transition endpoints
billing mutations
usage event ingestion
notification sends
webhook retry triggers
file completion
API key rotation
```

Semantics (matches Stripe's de-facto standard):

```text
TTL                                    24 hours from first request
Same key + same body hash              return the original response unchanged
Same key + different body hash         return 422 Problem Details with type "idempotency-key-conflict"
Same key + concurrent in-flight        second request blocks up to 30 s on the first; on timeout returns 409
Different key                          treated as a new request
```

The idempotency record stores:

```text
idempotency_key
tenant_id, environment_id
route, method
request_body_hash (sha256)
response_status
response_body
created_at, expires_at
in_flight (bool)
```

### 5.3 Pagination

Use opaque cursor pagination for list endpoints. Cursors are
`base64url(json{"v":1, "k":"<sort key tuple>", "id":"<resource id>"})` — clients must treat
as opaque.

Request:

```http
GET /v1/tenants/{tenant_id}/audit-events?limit=25&cursor=...
```

Response:

```json
{
  "data": [],
  "pagination": {
    "next_cursor": "eyJ2IjoxLCJrIjoiMjAyNi0wNS0wMVQwOTowMDowMFoiLCJpZCI6ImF1ZGl0XzEyMyJ9",
    "has_more": true
  }
}
```

Rules:

```text
limit                         default 25, max 200
cursor stability              cursors include a schema version (v); reject mismatched versions with 410 Gone
sort change                   if the sort param differs from the cursor's encoded sort, reject 422
deletes mid-pagination        rows may disappear between pages; clients must tolerate gaps
total counts                  not returned (expensive; use cursor presence instead)
```

### 5.4 Sorting

Use signed sort tokens:

```http
sort=created_at
sort=-created_at
```

Default sort is `-created_at`. Only fields explicitly declared in the OpenAPI per-endpoint
`x-sortable-fields` extension are allowed.

### 5.5 Errors

Use `application/problem+json` (RFC 9457).

```json
{
  "type": "https://api.example.com/problems/validation-error",
  "title": "Validation failed",
  "status": 422,
  "detail": "One or more fields are invalid.",
  "instance": "/v1/tenants",
  "request_id": "req_123",
  "errors": [
    {
      "field": "name",
      "message": "must not be blank",
      "code": "not_blank"
    }
  ]
}
```

Common `type` URIs are catalogued in `openapi/problems/`. Do not invent ad-hoc error formats.

### 5.6 Response envelope

Single resource:

```json
{
  "data": {
    "id": "tenant_123",
    "object": "tenant",
    "name": "Acme",
    "status": "active"
  }
}
```

List:

```json
{
  "data": [
    { "id": "tenant_123", "object": "tenant", "name": "Acme" }
  ],
  "pagination": { "next_cursor": "...", "has_more": true }
}
```

### 5.7 Optimistic concurrency

Mutable resources return an `ETag` on read. PATCH/PUT/DELETE require `If-Match`. Missing or
stale `If-Match` returns 412 Precondition Failed.

```http
GET /v1/tenants/tenant_123        → ETag: "W/\"v17\""
PATCH /v1/tenants/tenant_123      → If-Match: "W/\"v17\""
```

### 5.8 Rate limiting

Apply rate limits per `(api_key_id or jwt_subject, deployment_id)`. Send IETF draft headers:

```http
RateLimit-Limit: 1000
RateLimit-Remaining: 994
RateLimit-Reset: 27
Retry-After: 27
```

429 responses are Problem Details with `type` = `rate-limit-exceeded`.

---

## 6. Homelab Deployment Model

This section is specific to this machine. Generic deployment recipes live in `deploy/`.

### 6.1 Physical layout

Every Deployment provisioned by the control plane materializes as:

```text
Postgres database     :  saas_<project_slug>_<env_slug>      (host Postgres)
DB role               :  saas_<project_slug>_<env_slug>_app  (least-priv, owns its schema)
k3s namespace         :  saas-<project_slug>-<env_slug>
k3s deployment        :  data-plane (Go binary), N replicas
k3s service           :  data-plane.<ns>.svc.cluster.local:8080
nginx vhost           :  <env_slug>.<project_slug>.<base_domain>   (e.g. prod.acme.saas.omarss.net)
TLS cert              :  certbot --nginx -d <vhost>   (issued once at provision)
Object storage prefix :  s3://platform/<deployment_id>/             (deferred until Files module)
Secrets               :  Infisical project "<deployment_id>"
```

Each Deployment is independently versioned, backed up, restored, scaled, and destroyed.

### 6.2 Provisioning

`POST /control/v1/deployments` triggers a deterministic sequence (all idempotent):

```text
1. validate project + environment slug (DNS-safe, ≤ 32 chars, lowercase + hyphen)
2. allocate deployment_id (dep_<ulid>)
3. record desired state row in control-plane Postgres (status = provisioning)
4. create Postgres database + app role (no superuser)
5. apply data-plane migrations to the new DB (golang-migrate)
6. seed initial admin tenant + bootstrap API key
7. render k3s manifests from deploy/k3s/template/ (image pinned to current platform version)
8. kubectl apply -n <ns> -f -
9. render nginx vhost from deploy/nginx/template (pre-certbot, mirrors homelab/nginx pattern)
10. sudo apply-nginx + sudo certbot --nginx -d <vhost>   (see homelab gotcha §6.7)
11. wait for /healthz to return 200
12. flip status = active; emit deployment.provisioned event
13. return bootstrap API key once
```

If any step fails, the deployment is marked `failed` and a `destroy` reconciler cleans up
on retry. **Never partially leave nginx/cert state.**

### 6.3 Upgrading / rolling back

```text
PATCH /control/v1/deployments/{id}   { "image_version": "v1.4.2" }
POST  /control/v1/deployments/{id}/rollback
```

Upgrade is: render template with new image tag → `kubectl apply` → wait for rollout →
run pending migrations (forward-only) → mark new `image_version`.

Rollback restores the previous image but **does not roll back the database**. Any migration
applied in the failed upgrade must remain backward-compatible with the previous image — this
is enforced by §27.

### 6.4 Destroying

```text
DELETE /control/v1/deployments/{id}    [?retain_days=30]
```

Default is soft-delete: status = `destroyed`, traffic stopped, namespace and nginx kept for
`retain_days` (default 30) so the operator can revive. After retention, a sweeper removes
the namespace, drops the DB, removes the nginx vhost, and runs `certbot delete`.

PII deletion for GDPR/PDPL right-to-erasure is **physical** and ignores the retain window
when triggered via `POST /control/v1/deployments/{id}/purge`. See §19.6.

### 6.5 nginx, TLS, geofence

Follows the existing `homelab/nginx/` pattern (workspace_personal/CLAUDE.md §homelab):

```text
deploy/nginx/template renders a pre-certbot vhost file.
Provisioning copies it to /etc/nginx/sites-{available,enabled}, reloads nginx, then
   runs certbot --nginx -d <vhost> exactly once.
Re-running apply-nginx clobbers certbot blocks — control plane therefore never re-runs
   bulk apply-nginx; it patches only the vhost it owns, with reload nginx -s reload.
SA geofence (homelab/geofence/) applies to all deployments automatically.
```

### 6.6 Backups

```text
WAL archiving               : enabled on host Postgres (cluster-wide)
Per-deployment logical dump : nightly, retained 14 days, scoped pg_dump -d <db>
PITR                        : whole-cluster; restore is per-deployment via pg_restore into a fresh DB
```

`POST /control/v1/deployments/{id}/restore { "to_timestamp": "..." }` provisions a new
deployment from a point-in-time copy and returns the new deployment id.

### 6.7 Gotchas (homelab-specific)

```text
1. apply-nginx clobbers certbot blocks — control plane patches per-vhost, never bulk applies
2. rsync -a propagates source dir mode to dest; use -t --no-perms --no-owner --no-group
3. sudo umask may inherit 077; use install -d -m 755 -o omar -g omar
4. nginx add_header has no inheritance; use shared snippet includes per location
5. nginx `if` drops parent add_header directives; use regex location blocks instead
6. SA geofence blocks GitHub webhooks unless the source IP is allowlisted explicitly
7. apps.omarss.net is unrelated to this platform; do not collide with /srv/apps
```

---

## 7. Resource Model

```text
Control Plane
  Operator
  Deployment              ← physical isolation unit
    deployment_revision   ← image version history
    deployment_backup     ← snapshot pointer

Data Plane (one tree per Deployment)
  Tenant
    Organization
      User
      Member
      Role
      Permission
      Subscription        (v1)
      UsageEvent          (v1)
      Entitlement         (v1)
      Notification        (v1)
      File                (v1)
      ApiKey
      WebhookEndpoint     (v1)
      AuditEvent
```

Definitions:

| Resource | Plane | Meaning |
|---|---|---|
| Operator | Control | Human with control-plane access |
| Deployment | Control | One isolated SaaS stack (DB + ns + vhost) |
| Tenant | Data | Isolated customer/account within a Deployment |
| Organization | Data | Team inside a tenant (omit if not needed — see note below) |
| User | Data | Human identity |
| Member | Data | User membership in org/tenant |
| Role | Data | Named permission bundle |
| Permission | Data | Atomic action authorization |
| Entitlement | Data | Feature/limit granted by plan |
| UsageEvent | Data | Billable or quota-related event |
| AuditEvent | Data | Immutable security/business trail |

**Tenant vs Organization.** Most B2B SaaS only needs one layer; `Tenant` is the default unit
of isolation and billing. `Organization` is an optional intra-tenant team layer for products
that genuinely have multiple teams per customer (e.g. Linear-style). MVP supports a single
auto-created Organization per Tenant; the multi-org flag turns on the second layer.

Do not merge `User` and `Tenant`. That mistake is hard to undo.

---

## 8. Public API Surface

### 8.0 Control Plane API

Operator-only. Lives at a separate host (e.g. `control.saas.omarss.net`) with its own JWT
audience.

```http
GET    /control/v1/deployments
POST   /control/v1/deployments
GET    /control/v1/deployments/{deployment_id}
PATCH  /control/v1/deployments/{deployment_id}
DELETE /control/v1/deployments/{deployment_id}

POST   /control/v1/deployments/{deployment_id}/upgrade
POST   /control/v1/deployments/{deployment_id}/rollback
POST   /control/v1/deployments/{deployment_id}/restart
POST   /control/v1/deployments/{deployment_id}/restore
POST   /control/v1/deployments/{deployment_id}/purge

GET    /control/v1/deployments/{deployment_id}/revisions
GET    /control/v1/deployments/{deployment_id}/health
GET    /control/v1/deployments/{deployment_id}/logs     (tail, with filter)

POST   /control/v1/deployments/{deployment_id}/impersonation-sessions
GET    /control/v1/audit-events                          (global; control-plane actions only)
GET    /control/v1/operators

# BYOD — custom domain attach + DNS verify + per-domain cert (ADR 015)
GET    /control/v1/deployments/{deployment_id}/domains
POST   /control/v1/deployments/{deployment_id}/domains
GET    /control/v1/deployments/{deployment_id}/domains/{domain_id}
DELETE /control/v1/deployments/{deployment_id}/domains/{domain_id}
POST   /control/v1/deployments/{deployment_id}/domains/{domain_id}/verify
```

Deployment create request:

```json
{
  "project_slug": "acme",
  "environment_slug": "prod",
  "region": "ksa-riyadh",
  "modules": ["identity", "tenancy", "organizations", "authorization", "apikeys", "audit"],
  "image_version": "v0.3.1",
  "data_residency": "ksa",
  "metadata": { "owner": "acme-team" }
}
```

### 8.1 Data Plane — Core

```http
GET    /v1/me

GET    /v1/tenants
POST   /v1/tenants
GET    /v1/tenants/{tenant_id}
PATCH  /v1/tenants/{tenant_id}
DELETE /v1/tenants/{tenant_id}

GET    /v1/tenants/{tenant_id}/settings
PATCH  /v1/tenants/{tenant_id}/settings
```

### 8.2 Data Plane — Organizations and teams

```http
GET    /v1/tenants/{tenant_id}/organizations
POST   /v1/tenants/{tenant_id}/organizations
GET    /v1/organizations/{organization_id}
PATCH  /v1/organizations/{organization_id}
DELETE /v1/organizations/{organization_id}

GET    /v1/organizations/{organization_id}/members
POST   /v1/organizations/{organization_id}/invitations
GET    /v1/organizations/{organization_id}/invitations
DELETE /v1/invitations/{invitation_id}
POST   /v1/invitations/{invitation_id}/accept
```

### 8.3 Data Plane — Identity façade

```http
GET    /v1/users
POST   /v1/users
GET    /v1/users/{user_id}
PATCH  /v1/users/{user_id}
DELETE /v1/users/{user_id}

POST   /v1/users/{user_id}/disable
POST   /v1/users/{user_id}/enable
POST   /v1/users/{user_id}/reset-password
POST   /v1/users/{user_id}/verify-email

# Social login — Keycloak IdP brokering for Google / GitHub / Apple (ADR 014)
GET    /v1/users/{user_id}/social-providers
POST   /v1/users/{user_id}/social-providers           # initiate link flow
DELETE /v1/users/{user_id}/social-providers/{provider}
GET    /v1/social-providers                            # list providers enabled for this Deployment
```

Expose identity as your own API. Internally it may call Keycloak or another IAM system, but
consumers never see Keycloak concepts.

### 8.4 Data Plane — Authorization (RBAC)

MVP is **pure RBAC**. The check payload is intentionally role-shaped, not Zanzibar-shaped,
so it can evolve cleanly later if ReBAC becomes necessary.

```http
GET    /v1/tenants/{tenant_id}/roles
POST   /v1/tenants/{tenant_id}/roles
GET    /v1/roles/{role_id}
PATCH  /v1/roles/{role_id}
DELETE /v1/roles/{role_id}

GET    /v1/permissions
POST   /v1/members/{member_id}/roles
DELETE /v1/members/{member_id}/roles/{role_id}

POST   /v1/authorization/check
POST   /v1/authorization/batch-check
```

Check request (RBAC-shaped):

```json
{
  "member_id": "member_123",
  "permission": "invoice.read",
  "tenant_id": "tenant_abc"
}
```

Check response:

```json
{
  "data": {
    "allowed": true,
    "via_role": "role_tenant_admin"
  }
}
```

If/when OpenFGA is added, a separate `/v1/authorization/check-relation` endpoint is
introduced. The RBAC endpoint stays.

### 8.5 Data Plane — API keys

```http
GET    /v1/tenants/{tenant_id}/api-keys
POST   /v1/tenants/{tenant_id}/api-keys
GET    /v1/api-keys/{api_key_id}
PATCH  /v1/api-keys/{api_key_id}
DELETE /v1/api-keys/{api_key_id}

POST   /v1/api-keys/{api_key_id}/rotate    { "grace_period_seconds": 86400 }
POST   /v1/api-keys/{api_key_id}/revoke
```

API key fields:

```text
id (apik_...)
prefix (visible, 8 chars, e.g. "live_ax9_")
hashed_secret (argon2id)
scopes []
expires_at, last_used_at, created_by, revoked_at
rate_limit_per_minute
ip_allowlist []
tenant_id, environment_id
```

Rotation returns the new secret once and keeps the old one valid for `grace_period_seconds`
(default 24 h, max 7 d) so clients can roll over without downtime.

Only return the secret once at creation or rotation time. Never store API key secrets in
plaintext.

### 8.6 Data Plane — Audit logs

```http
GET    /v1/tenants/{tenant_id}/audit-events
GET    /v1/audit-events/{audit_event_id}
POST   /v1/audit-events/export
```

Audit logs are append-only at the API and database level (no DELETE, no UPDATE, enforced
by a Postgres trigger that revokes those grants from the app role). Integrity is hash-chained:
each row stores `prev_hash` and `row_hash = sha256(prev_hash || canonical_json(row))`.
Operators can verify the chain via `GET /control/v1/deployments/{id}/audit-integrity`.

Minimum fields:

```text
id, tenant_id, actor_type, actor_id
action, resource_type, resource_id
occurred_at, ip_address, user_agent, request_id
metadata
prev_hash, row_hash
```

### 8.7 Deferred modules (v1 roadmap, not MVP)

These follow the original §7 sketch but are not built in MVP. Notifications was promoted to MVP per ADR 013 (§15 item 14); the remainder stay deferred:

```text
8.7.1  Plans, Subscriptions, Billing      (wraps Lago)
8.7.2  Entitlements and Limits
8.7.3  Notifications: SMS + WhatsApp channels (Novu + KSA SMS provider)
8.7.4  Newsletters                         (subscriber lists, opt-in, GDPR/PDPL unsubscribe)
8.7.5  Files                               (presign upload/download via SeaweedFS / S3)
8.7.6  Webhooks                            (own outbox + delivery worker)
8.7.7  Feature Flags
8.7.8  Analytics
8.7.9  Support                             (wraps Chatwoot)
```

Spec sketches live in `openapi/data-plane.v1-roadmap.yaml`. Do not implement until promoted
to the active spec by an ADR.

---

## 9. Public Events

All important state changes emit events. Every event payload includes `event_version`
(starts at `1`) so payload schemas can evolve safely.

MVP events:

```text
deployment.provisioned        (control plane)
deployment.upgraded
deployment.rollback
deployment.destroyed
deployment.purged
deployment.domain_attached    (BYOD — ADR 015)
deployment.domain_verified
deployment.domain_detached

tenant.created
tenant.updated
tenant.suspended
tenant.deleted

user.created
user.disabled
user.enabled
user.email_verified
user.social_linked            (ADR 014)
user.social_unlinked

member.invited
member.joined
member.removed
member.role_changed

api_key.created
api_key.rotated
api_key.revoked

notification.queued           (ADR 013)
notification.sent
notification.delivery_failed
notification_channel.created
notification_channel.rotated  (BYOK creds rotation — ADR 017)
notification_channel.deleted
```

Deferred events (with their modules):

```text
subscription.*, usage.*, limit.exceeded, entitlement.*
invoice.*
newsletter.*                          (v1 — subscriber lists, broadcasts)
webhook.delivery_failed, file.uploaded
```

Events are used for:

```text
webhook delivery (when webhooks module ships)
audit logging
internal async processing
analytics forwarding
billing synchronization
notification triggering
```

Use an **outbox pattern** for reliable publication: writers insert into `outbox` in the same
transaction as their state change; a dispatcher polls and publishes. No external broker is
required for MVP; NATS may be added later.

Event envelope:

```json
{
  "id": "evt_01HXYZ...",
  "type": "tenant.created",
  "event_version": 1,
  "occurred_at": "2026-05-24T10:15:00Z",
  "deployment_id": "dep_...",
  "tenant_id": "tenant_...",
  "data": { }
}
```

---

## 10. SDK Strategy

MVP SDKs:

```text
TypeScript      generated from data-plane.yaml + handwritten workflow wrappers
Go              generated from data-plane.yaml + handwritten workflow wrappers
Postman         exported alongside each spec version
Mock server     prism --mock (CI + local dev)
```

Deferred: Python SDK (when first Python consumer appears). **No Java SDK** — the audience is
not there, and maintenance is non-trivial.

Generated SDKs are mechanically correct but rarely ergonomic. Always ship a thin
handwritten wrapper layer for these workflows:

```text
provision deployment            (control-plane SDK only)
create tenant
invite member
check authorization
create API key
list audit events
```

The SDKs are versioned independently and pinned to a spec version. Breaking changes follow
§27.

---

## 11. OpenAPI Requirements

### 11.1 Version and tooling

Use OpenAPI 3.1.x. **Pin generator versions** in the Makefile — generator bugs are the
single biggest risk to a contract-first promise.

Confirmed-working generators (as of 2026-05):

```text
openapi-generator-cli 7.10+    typescript-axios, go (server stubs not used)
oapi-codegen 2.4+              Go server stubs and types (preferred for backend)
prism 5+                       mock server, contract validation
spectral 6+                    lint
```

`make openapi-check` runs spectral lint + a round-trip generation test in CI. PRs that touch
`openapi/` and don't pass these fail.

### 11.2 Required qualities

Every spec includes:

```text
operationId for every operation
tags for every operation
request and response schemas
error response references to shared problem types
security schemes (bearerAuth, apiKeyAuth)
pagination parameters
idempotency-key parameter
If-Match / ETag parameter on mutating endpoints
examples for important APIs
webhooks section
schema validation constraints (min/max/format)
x-sortable-fields extension where applicable
```

### 11.3 operationId naming

```text
createDeployment
listDeployments
getDeployment
upgradeDeployment
createTenant
listTenants
checkAuthorization
createApiKey
rotateApiKey
listAuditEvents
```

### 11.4 Schema naming

```text
Tenant
TenantResponse
TenantListResponse
CreateTenantRequest
UpdateTenantRequest
Problem
FieldError
Pagination
```

### 11.5 Resource IDs

Prefixed, opaque, ULID-derived public IDs:

```text
op_...          operator
dep_...         deployment
tenant_...
org_...
user_...
member_...
role_...
perm_...
plan_...        (v1)
sub_...         (v1)
usage_...       (v1)
file_...        (v1)
apik_...        API key (NOTE: rename from api_key_; shorter, less confusable)
whep_...        webhook endpoint  (whsec_ reserved for the signing SECRET, never an ID)
whdel_...       webhook delivery
audit_...
evt_...         event
```

Never expose auto-increment DB IDs in the public API.

---

## 12. Module Responsibilities

Only MVP modules are described here. Deferred module sketches live in
`docs/modules/v1-roadmap.md`.

### 12.1 Deployments module (control plane)

```text
deployment lifecycle (provision / upgrade / rollback / destroy / restore / purge)
revision history
backup pointers
image registry interaction
template rendering for k3s + nginx (multi-server_name for BYOD)
secret bootstrapping (via OpenBao KV v2 — see §18.7)
DB provisioning (database + role + grants)
health and readiness rollup
BYOD custom domain attach / DNS verify / per-domain cert issuance (ADR 015)
freeze-keys for incident response (§18.7)
```

Hides: kubectl, helm, certbot, pg_create, nginx config layout.

### 12.2 Identity module (data plane)

```text
user CRUD
disable / enable
email verification
password reset trigger
identity provider mapping (KeycloakUserId → user_id)
profile sync
social provider brokering: Google / GitHub / Apple via Keycloak IdP brokers (ADR 014)
social provider linking and unlinking
```

Hides Keycloak realm/client/protocol details entirely.

### 12.3 Tenancy module (data plane)

```text
tenant CRUD
tenant settings
tenant status (active | suspended | deleted)
tenant isolation enforcement (every query scoped)
soft-delete with retention policy
```

### 12.4 Organizations module (data plane)

```text
organization CRUD
member management
invitations
roles per member
team-level settings
```

### 12.5 Authorization module (data plane)

Backed by **Casbin** (Apache 2.0). Do not write a bespoke RBAC engine. The platform owns the
RBAC model file, persistence adapter (sqlc + Postgres), and the public API; the matching/eval
engine is Casbin.

```text
RBAC roles + permissions catalog (Casbin RBAC model)
role assignment
authorization check (sync)
batch authorization check
audit hook for every denial
```

If ReBAC becomes necessary later, OpenFGA is the chosen engine — it does **not** replace
Casbin; it adds a separate relation-shaped endpoint (see §8.4).

### 12.6 API keys module (data plane)

```text
key creation with one-time-secret return
key rotation with grace period
key revocation (immediate)
scopes enforcement
rate limit metadata
IP allowlist
hashed secret storage (argon2id)
last_used tracking (batched write)
```

### 12.7 Audit module (data plane)

```text
append-only audit log
hash chain integrity
actor and resource tracking
admin action tracking
impersonation logging
export (CSV / JSON)
retention policy (per tenant)
```

---

## 13. Compliance-Aware Defaults

The platform is compliance-aware by default, especially for B2B, fintech-adjacent, and
KSA/MENA contexts.

Included from MVP:

```text
audit logs (hash-chained)
admin activity tracking
impersonation logs
tenant isolation (token-derived)
PII masking hooks in logger
data retention policies (per-deployment configurable)
export and delete workflows
security event trail
request IDs
least-privilege API keys
explicit roles and permissions
per-deployment data residency hint
```

Do not claim regulatory compliance unless a formal compliance program, controls, evidence,
and external assessment exist. Use:

```text
compliance-aware
audit-ready
security-oriented
control-friendly
```

Never claim:

```text
PCI compliant by default
SAMA compliant by default
PDPL compliant by default
```

---

## 14. KSA/MENA-Ready Differentiators

Treated as product differentiators, not core infrastructure:

```text
Arabic/English bilingual
SAR billing                       (v1 — when billing module ships)
VAT-ready invoice metadata        (v1)
local SMS providers               (v1 — when notifications ship)
WhatsApp-ready notification channel  (v1)
local payment integrations        (v1)
KSA data residency option         (MVP — surfaced as `data_residency` on Deployment)
PDPL-oriented data handling
SAMA-style audit posture
Arabic admin templates
```

---

## 15. MVP Scope (hard cut)

Build only:

```text
1.  Control Plane API: Deployments (create / upgrade / rollback / destroy / restore / purge)
2.  Data Plane API: Tenants
3.  Data Plane API: Organizations + Members + Invitations
4.  Data Plane API: Identity façade (over Keycloak) + Social login (Google / GitHub / Apple via IdP brokering — ADR 014)
5.  Data Plane API: RBAC (roles, permissions, check, batch-check)
6.  Data Plane API: API keys (create, rotate w/ grace, revoke, scopes)
7.  Data Plane API: Audit logs (append-only, hash-chained, list/export)
8.  OpenAPI specs (control + data) with pinned generators and lint in CI
9.  TypeScript SDK
10. Go SDK
11. Docker Compose local stack (Postgres, Keycloak, OpenBao, Novu stack, SigNoz)
12. Static HTML + curl walkthrough (no full Next.js starter yet)
13. CLI: `saasctl` thin wrapper over the Control Plane API for operators
14. Data Plane API: Notifications (email + in-app via Novu — ADR 013)
15. Control Plane API: Bring-Your-Own-Domain (custom domain attach + DNS verify + per-domain cert — ADR 015)
16. CLI: `saasctl init` easy-setup wizard (compose-up + migrate + first-tenant + first-API-key bootstrap — ADR 016)
17. Bring-Your-Own-Key vendor credentials for Notification channels (SMTP / SendGrid / SES creds per Deployment, envelope-encrypted via OpenBao — ADR 017)
```

That is the platform's MVP. Nothing else.

### 15.1 v1 roadmap (post-MVP, in this order)

```text
18. Plans / Subscriptions / Billing      (wraps Lago)
19. Usage metering + Entitlements + Limits
20. Webhooks
21. Notifications: SMS + WhatsApp channels (Novu + KSA SMS provider)
22. Newsletters                           (subscriber lists, opt-in, GDPR/PDPL unsubscribe; built on Notifications + Novu broadcast)
23. Files                                 (presign upload/download)
24. Feature flags
25. Analytics ingest
26. Next.js starter app
27. Python SDK
```

### 15.2 Never (without explicit ADR)

```text
serverless functions
visual workflow builder
database designer
no-code app builder
multi-cloud orchestration
generic marketplace
plugin marketplace
custom scripting engine
microservices-first split
Java SDK
```

---

## 16. Build Order

Vertical-slice-first. Do not design the full contract in the abstract — build one slice
end-to-end, harvest patterns, then formalize.

### Phase 1: Walking skeleton

```text
- repo bootstrap (Go, Makefile, lint, test)
- control-plane binary serving GET /healthz
- data-plane binary serving GET /healthz
- Docker Compose local stack
- single migration runner
- one happy-path: POST /control/v1/deployments creates a Postgres DB + namespace + vhost
```

### Phase 2: One full vertical slice (Tenants)

```text
- OpenAPI spec for /v1/tenants
- handler + service + port + adapter + sqlc queries + migration
- contract test (prism replay against running server)
- tenant isolation test
- audit emission
- TypeScript SDK generation pipeline
- end-to-end test from saasctl
```

### Phase 3: Promote patterns

```text
- factor shared platform code (problem-details, idempotency, pagination, etag) out of tenants
- write CONVENTIONS.md from what worked
- only now write the rest of the OpenAPI surfaces
```

### Phase 4: Remaining MVP modules

```text
- Identity façade → Organizations → RBAC → API keys → Audit
- each module follows the Phase-2 template
```

### Phase 5: Developer experience polish

```text
- both SDKs publishable
- mock server (prism) wired into CI
- static walkthrough page
- saasctl complete
```

### Phase 6: v1 roadmap items, one per phase

---

## 17. Testing Strategy

### 17.1 Required test layers

```text
unit tests                          per package, fast
module integration tests            real Postgres via testcontainers-go
API contract tests                  spec ↔ server via prism + golden replays
adapter tests                       real Keycloak via testcontainers (one-shot)
end-to-end smoke tests              via saasctl against a Compose stack
security tests for access control   table-driven, every endpoint
```

### 17.2 Contract tests

Every public endpoint:

```text
request schema
response schema
error schema
authentication requirements
authorization requirements
idempotency behavior where applicable
pagination behavior where applicable
ETag / If-Match where applicable
rate-limit headers present on 429
```

### 17.3 Authorization tests (mandatory per endpoint)

```text
same tenant access allowed
cross tenant access denied (403)
missing tenant context denied
disabled user denied
revoked API key denied (401)
expired API key denied (401)
missing scope denied (403)
IP allowlist enforcement
```

### 17.4 Provisioning tests (control plane)

```text
happy path: provision → /healthz returns 200
partial failure: cleanup leaves no dangling DB, ns, or vhost
upgrade: image flips, migrations run, traffic resumes
rollback: previous image restored; DB unchanged
restore: PITR copy lands as a new deployment id
purge: physical DB drop verified
```

### 17.5 Billing / entitlement / webhook tests

Deferred with their modules.

---

## 18. Security Rules

### 18.1 Tenant isolation

Tenant isolation is mandatory. Every tenant-bound query is scoped by `tenant_id` derived
from the token. The Postgres app role per deployment additionally has a Row-Level Security
policy on every tenant-scoped table as defense in depth.

```text
Do not rely on frontend filtering.
Do not rely on object IDs alone.
Do not trust tenant headers without policy enforcement.
```

### 18.2 API key storage

Never store raw API key secrets. Store:

```text
id, prefix, argon2id hash, scopes
tenant_id, environment_id
expires_at, revoked_at, last_used_at, created_by
rate_limit_per_minute, ip_allowlist
```

Show the raw secret once at creation and once at rotation, then never again.

### 18.3 Audit sensitive actions

Always audit:

```text
deployment provisioning, upgrade, rollback, destroy, purge
operator login + impersonation
tenant suspension / unsuspension
role and permission changes
API key creation / rotation / revocation
subscription changes and billing overrides (v1)
file deletion (v1)
webhook secret rotation (v1)
user disable / enable / password reset
```

### 18.4 Operator (admin) auth model

The Control Plane API uses a **separate IdP realm and JWT audience** from the Data Plane:

```text
realm        : operators
audience     : aud=saas-control
MFA          : required (TOTP or WebAuthn)
step-up      : destructive actions require a fresh re-auth within 5 minutes
IP allowlist : configurable per operator
```

A Data Plane token never satisfies a Control Plane endpoint. Operator-into-Data-Plane access
goes through `POST /control/v1/deployments/{id}/impersonation-sessions` which mints a
short-lived (≤ 15 min) Data Plane token marked `actor_type=operator_impersonation`. Every
request under it is tagged in audit.

### 18.5 PII and logs

Never log:

```text
passwords, tokens, API key secrets
Authorization headers (filtered at logger)
payment details
PII payloads (a structured-log redactor masks declared PII fields)
file contents
webhook secrets
```

The redactor list is in `internal/platform/log/redact.go` and unit-tested.

### 18.6 Right-to-erasure (GDPR / PDPL)

Soft delete is the default for tenants and users. `POST /control/v1/deployments/{id}/purge`
or `POST /v1/tenants/{tenant_id}/purge` triggers **physical** deletion. Purge bypasses the
soft-delete retention window, drops referenced rows, and emits a `tenant.purged` audit event
*before* the rows disappear so the chain remains verifiable.

### 18.7 Secrets and crypto vault (OpenBao)

Strong encryption is non-negotiable. The platform runs **OpenBao** (MPL 2.0, Linux
Foundation fork of Vault Community) as its secrets store and cryptographic vault. Required
from MVP. OpenBao runs in the homelab k3s cluster, auto-unsealed via a sealed file on the
host for MVP; production migration path to a cloud KMS or HSM is documented but out of MVP
scope.

OpenBao has three responsibilities for this platform:

#### 1. Secrets storage (KV v2)

Stores:

```text
control-plane bootstrap credentials
per-deployment Postgres app passwords
per-deployment Keycloak admin credentials
per-deployment Lago / Novu / S3 / PostHog provider keys (when those modules ship)
customer-managed secrets surfaced through the Data Plane
```

All secret reads are authenticated via Kubernetes auth (each Deployment's k3s service
account maps to an OpenBao policy scoped to its paths). Audit device logs every read with
caller identity to file + Loki/VictoriaLogs.

#### 2. Transit encryption (envelope)

Each Deployment has its own AES-256-GCM transit key:

```text
transit/keys/<deployment_id>     type=aes256-gcm96, rotation period=90 days
```

All sensitive payloads use **envelope encryption** at the application layer:

```text
1. App generates a 32-byte data key (DEK).
2. Encrypts the payload with the DEK using AES-256-GCM (stdlib crypto/aes + crypto/cipher).
3. Calls OpenBao Transit Encrypt to wrap the DEK with the deployment's transit key.
4. Stores in Postgres: { ciphertext, wrapped_dek, key_version, nonce, algo, kid }.
5. Never stores the DEK plaintext anywhere.
```

Decrypting verifies `kid == deployment_id` before calling OpenBao — a row from Deployment A
must never be decryptable with Deployment B's key, even if a query bug crosses tenants.

#### 3. Dynamic database credentials (opt-in)

OpenBao's database secrets engine can issue short-lived Postgres roles per data-plane
process. Static roles remain the default; the dynamic-creds path is opt-in per Deployment
and recommended for compliance-sensitive customers.

#### Required encryption posture

```text
At rest (sensitive fields)   AES-256-GCM via envelope (DEK + OpenBao Transit wrap)
At rest (filesystem)         LUKS on the homelab host (verify before going live)
At rest (Postgres TDE)       Not used — application-level envelope is preferred
In transit                   TLS 1.3 everywhere
                             Postgres: sslmode=verify-full
                             control plane ↔ data plane: mTLS via cert-manager
                             OpenBao: TLS-only listener; client cert auth for k3s pods
Key rotation                 Transit keys auto-rotate every 90 days; old versions retained
                             for decrypt-only; application re-wraps DEKs lazily on next write
Backup encryption            Backups encrypted with a separate transit key
                             `transit/keys/backups-master` so a leaked snapshot does not
                             compromise live deployment keys
Audit                        OpenBao audit device → file + Loki/VictoriaLogs
                             Every key access logged with caller identity, path, response code
Unseal                       Shamir 5-of-3 in MVP; shares held offline by the operator
                             Cloud KMS auto-unseal documented as the production target
Root token                   Revoked immediately after initial setup
                             Ops uses short-lived OIDC or AppRole tokens (max 1 h)
```

#### What MUST be envelope-encrypted at the application layer

Declared in OpenAPI per field with the `x-pii: true` and/or `x-sensitive: true` extensions.
Code generation enforces the encryption call site at handler boundaries.

```text
PII fields (names, emails, phone numbers, national IDs, addresses, IPs at rest)
OAuth refresh tokens and access tokens stored for replay
Webhook signing secrets (whsec_*) at rest
API key plaintext at any point except the one-time post-creation return
External provider IDs treated as sensitive (e.g. payment customer IDs)
File presign URLs cached on disk
Audit metadata fields containing user-controlled strings
```

API key secrets are additionally **hashed** with argon2id (golang.org/x/crypto/argon2)
before storage. Hashing and envelope encryption are complementary: the hash protects
against offline secret comparison; the envelope protects the hash itself plus any
prefix-search auxiliary index.

#### Operator rules

```text
Never store secrets in environment variables beyond process lifetime.
Never log OpenBao tokens, unseal shares, or wrapped DEKs.
Never commit OpenBao root tokens — root is revoked after initial setup.
Every Deployment maps to its own OpenBao policy, bound to its k3s service account.
Disabling a Deployment's transit key (POST /control/v1/deployments/{id}/freeze-keys)
   immediately blinds that deployment's reads — used during incident response.
Key revocation is auditable and reversible only by re-providing the wrapped DEKs;
   destroying a transit key version is final and requires step-up auth.
```

---

## 19. Data Model Guidelines

Public IDs use stable prefixes (§11.5).

Timestamps used consistently:

```text
created_at
updated_at
deleted_at         (soft delete)
occurred_at        (events / audit)
expires_at
revoked_at
last_used_at
```

Soft delete pattern:

```text
deleted_at IS NOT NULL    AND status = 'deleted'
```

Flexible metadata is allowed but capped:

```json
{ "metadata": { "key": "value" } }
```

```text
max 16 keys
max 4 KB total JSON
core queryable fields must be first-class columns, not metadata
```

ETag is computed from `updated_at` epoch ms + a monotonic per-row sequence; format is
`W/"v<sequence>"`.

---

## 20. Observability Requirements

Every request includes or generates:

```text
request_id
trace_id, span_id
deployment_id
tenant_id when available
actor_id when available
```

Minimum telemetry from MVP:

```text
HTTP request latency (histogram, by route, status)
HTTP status counter (by route, status)
database query latency (by query name)
external adapter latency (by adapter)
outbox publish failures
auth failures
authorization denials
deployment provisioning latency
deployment provisioning failure counter
```

Use OpenTelemetry instrumentation. The control plane rolls up per-deployment metrics
behind `GET /control/v1/deployments/{id}/health`.

Do not build vendor lock-in into observability. Exporters are configured at process start.

---

## 21. Developer Experience Requirements

The platform provides:

```text
OpenAPI documentation (control + data)
generated SDKs (TypeScript, Go)
Postman collection per spec
mock server (prism)
local Docker Compose
saasctl operator CLI
copy-paste recipes (curl + SDK)
```

First-class workflows shipped as recipes in MVP:

```text
provision a deployment            (operator)
attach a custom domain            (operator — BYOD, ADR 015)
saasctl init wizard               (operator — easy setup, ADR 016)
create a tenant
invite a member                   (uses Notifications module — ADR 013)
assign a role
check authorization
create an API key
view audit events
send a notification               (ADR 013)
configure a notification channel  (BYOK vendor creds, ADR 017)
link a social provider            (ADR 014)
```

v1 recipes (with their modules):

```text
subscribe a tenant
record usage
check entitlement
broadcast a newsletter
upload a file
register a webhook endpoint
```

---

## 22. Pricing Model (when productized)

```text
Free
  1 deployment
  limited tenants
  limited usage
  community support

Startup
  hosted deployments
  core SaaS modules
  email support

Growth
  advanced billing
  usage metering
  webhooks
  audit retention
  multiple environments

Enterprise
  self-hosted control plane
  customer-owned data plane
  SAML/OIDC enterprise SSO
  custom retention
  compliance evidence
  premium support
```

Hosted first. Self-hosted later. Customer-self-hosted enterprise last.

---

## 23. First Customer Profile

Best first customer:

```text
A small technical team building a B2B SaaS that needs:
  auth, teams, billing, usage limits, notifications, audit logs, API keys, webhooks, admin tooling.
```

Bad first customer:

```text
consumer social app
highly custom marketplace
game backend
generic no-code builder
enterprise with many custom security demands
```

---

## 24. Main Risks and Mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Too generic | Competes with Supabase/Firebase/Appwrite | Focus on B2B SaaS + KSA |
| Too complex | Platform becomes harder than the startups it serves | Hard MVP cut (§15), vertical-slice build order (§16) |
| Too many integrations | Maintenance burden explodes | Hide tools behind stable ports |
| Weak differentiation | Users see it as boilerplate | Per-deployment isolation, compliance, regional angle |
| Poor DX | Developers abandon quickly | OpenAPI, SDKs, examples, local stack |
| Open-source ops burden | Self-hosting becomes painful | Offer hosted first; ship saasctl |
| Per-deployment fleet sprawl | 50 deployments → 50 DBs, vhosts, certs to manage | Automation in §6 is the product; treat ops as a feature |
| OpenAPI generator drift | Contract-first promise breaks | Pin generators, lint + round-trip test in CI (§11.1) |

---

## 25. Coding Agent Instructions

When modifying this repository, follow these rules.

### 25.1 Public API changes

Before implementing or changing any public endpoint:

```text
1. Update the OpenAPI spec (control or data, as appropriate).
2. Ensure operationId is stable and meaningful.
3. Add request and response schemas.
4. Add error response references.
5. Add examples for important workflows.
6. Add or update contract tests.
7. Implement backend behavior.
8. Regenerate SDKs.
9. Update walkthrough / recipes.
```

Do not create undocumented endpoints.

### 25.2 Module boundaries

Do not directly access another module's tables unless explicitly allowed by an ADR.

Prefer:

```text
application service
domain event
port (Go interface)
adapter
```

Avoid:

```text
cross-module repository imports
shared mutable domain entities
global utility business logic
```

### 25.3 Security-sensitive code

For security-sensitive changes, include tests for:

```text
authentication failure
authorization failure
cross-tenant access
disabled user
revoked API key
expired API key
missing scope
invalid tenant context
IP allowlist enforcement
```

### 25.4 Database migrations

Every schema change includes a migration (`migrations/dataplane/` or
`migrations/controlplane/`).

Migrations are:

```text
forward-only
safe for existing data
explicit about defaults
backward-compatible with the previous image for one release (so rollback works without DB revert)
applied to every Deployment on upgrade
```

Avoid destructive migrations without a documented rollout plan.

### 25.5 Error handling

Return Problem Details for errors.

Do not leak:

```text
stack traces
SQL errors
internal provider details
secrets, tokens
raw external service errors
```

### 25.6 External adapters

Adapters translate external provider concepts into platform domain concepts. Provider IDs
are stored as `*ProviderMapping` rows, never exposed in the public API.

```text
Keycloak user ID  → IdentityProviderMapping
Lago customer ID  → BillingProviderMapping
Novu subscriber   → NotificationProviderMapping
```

### 25.7 Tests required before marking work complete

For any meaningful feature:

```text
unit tests
module integration tests (with real Postgres via testcontainers)
API contract tests
authorization tests if tenant-bound
migration test if schema changed
adapter test if external integration changed
provisioning test if it touches the control plane
```

### 25.8 Don't reinvent; verify license first

Before adding any infrastructure code, search for and evaluate an established OSS option.
Document non-obvious choices in an ADR under `docs/adr/`.

Approved primitives (do not write your own):

```text
RBAC                     →  casbin                                  (Apache 2.0)
HTTP routing             →  chi                                      (MIT)
SQL access               →  sqlc + pgx                               (MIT / MIT)
Migrations               →  golang-migrate                           (MIT)
OpenAPI server stubs     →  oapi-codegen                             (Apache 2.0)
Background jobs          →  asynq (or Postgres outbox)               (Apache 2.0)
CLI                      →  cobra                                    (Apache 2.0)
Kubernetes API           →  client-go                                (Apache 2.0)
Manifest templating      →  kustomize                                (Apache 2.0)
ULIDs                    →  oklog/ulid                               (Apache 2.0)
Argon2id hashing         →  golang.org/x/crypto/argon2               (BSD)
Request validation       →  go-playground/validator                  (MIT)
Secrets + crypto vault   →  OpenBao (openbao/api client)             (MPL 2.0)
Logging                  →  log/slog (stdlib) or zerolog             (MIT)
OpenTelemetry            →  otelhttp + otelpgx                       (Apache 2.0)
Postgres integration     →  testcontainers-go                        (MIT)
Mock server / spec lint  →  prism + spectral                         (Apache 2.0 / Apache 2.0)
```

License rules before adding any new dependency:

```text
1. Confirm OSI-approved license. Prefer MIT, Apache-2.0, BSD, MPL-2.0, PostgreSQL, ISC.
2. AGPL is allowed ONLY when consumed as a standalone network service (never linked
   into platform binaries). Document this in the ADR.
3. Reject BSL, SSPL, Elastic License v2, Commons Clause, or any "source available" terms.
4. Confirm the project is maintained (recent commits, responsive issues, > 1k stars or
   a recognized maintainer).
5. Add the dependency only if the answer to all four is yes; otherwise propose the next
   option in the ADR or build the minimum we need.
```

If a needed capability has no healthy OSS option, write the minimum, keep it isolated, and
note in the ADR what would make us replace it later.

### 25.9 Makefile

Every build, lint, test, and run goes through the Makefile (per user CLAUDE.md). Common
targets:

```text
make build              both binaries
make test               unit + module integration
make contract-test      prism replay
make lint               go vet, golangci-lint, spectral on openapi/
make openapi-check      spectral + generator round-trip
make compose-up         local stack
make compose-down
make migrate            apply migrations to local data plane DB
make sdk-ts             regenerate TypeScript SDK
make sdk-go             regenerate Go SDK
```

---

## 26. Definition of Done

A feature is done only when:

```text
OpenAPI contract updated (and lint + round-trip green)
implementation complete
tests pass (unit + integration + contract)
security cases tested
tenant isolation tested
audit events added where needed
idempotency implemented where needed
ETag / If-Match implemented on mutating endpoints
observability added (metrics + traces)
docs / recipes updated
SDK impact checked (regenerated if shape changed)
migration included if schema changed (and backward-compatible for one release)
```

For public API features, also require:

```text
contract test added
example request/response added
error responses documented
pagination documented if list endpoint
```

---

## 27. Breaking Change Policy

Breaking changes are expensive. The default is **never break**; introduce additive changes.

### 27.1 What counts as breaking

```text
removing or renaming a field, endpoint, operationId, or enum value
narrowing a type (string → uuid pattern, optional → required)
changing default values
changing error type URIs
changing event payload schemas without bumping event_version
changing ID prefixes
changing pagination semantics
changing auth requirements
```

### 27.2 What is additive (allowed)

```text
adding a new field (optional, with default)
adding a new endpoint
adding a new enum value where the consumer is documented to accept unknowns
adding a new optional query parameter
widening a type
adding a new event_version bumped by 1
```

### 27.3 Process for unavoidable breakage

```text
1. Open an ADR in docs/adr/ explaining why and the migration path.
2. Get explicit operator approval (this is non-negotiable per user CLAUDE.md).
3. Introduce /v2 of the affected resource alongside /v1.
4. Keep /v1 running for at least 6 months after /v2 GA.
5. Emit deprecation warning headers (Deprecation, Sunset, Link) on /v1.
6. Announce in release notes; SDKs ship both versions during overlap.
```

A version-bumped path (`/v2/...`) is the only acceptable way to break the contract.
Never break `/v1` in place.

---

## 28. Non-Goals

Do not build these unless explicitly approved by an ADR:

```text
generic no-code builder
generic database-as-a-service
custom scripting engine
visual automation builder
plugin marketplace
multi-cloud orchestrator
serverless function platform
Kubernetes operator-first product
full analytics product
full customer support product
surveys / NPS module (Product Builder feature, not platform plumbing)
Java SDK
microservices-first split
```

The platform integrates or wraps specialized tools; it does not become all of them.

---

## 29. Strong Product Recommendation

Build this as:

```text
OpenAPI-first SaaS control plane + data plane
modular monolith implementation in Go
per-product isolated deployments by default
open-source components behind adapters
B2B SaaS-focused workflows
compliance-aware defaults
KSA/MENA-ready differentiators
excellent developer experience
operator CLI as a first-class artifact
```

Do not build it as:

```text
microservices-first architecture
generic BaaS clone
plugin marketplace
no-code platform
collection of exposed open-source tools
single-tenant logical multi-tenancy
```

The durable product is the **stable SaaS contract + the provisioning automation**, not the
internal tools.
