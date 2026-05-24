# SaaS Platform — MVP Implementation Plan

> Source contract: `/home/omar/workspace_personal/saas/AGENTS.md`
> Working notes: `/home/omar/workspace_personal/saas/CLAUDE.md`
> Plan author: orchestrator (make-plan skill), 2026-05-24
> Execution target: `claude-mem:do` (one phase per subagent session)

This plan implements the §15 MVP — all 13 items. It follows the §16 vertical-slice-first build order. Each phase file is **self-contained** so a subagent can pick up the work in a fresh context with only `AGENTS.md`, `CLAUDE.md`, this master, the linked phase file, and `01-foundations.md` (Allowed APIs reference).

---

## Phase index

| # | File | Title | Output | Checkpoint after |
|---|---|---|---|---|
| 0 | `01-foundations.md` | Allowed APIs + verified pins | Reference doc | — |
| 1 | `02-walking-skeleton.md` | Repo bootstrap, both binaries, Compose stack, /healthz | Empty platform that runs | — |
| 2 | `03-tenants-slice.md` | Tenants vertical slice end-to-end (OpenAPI → handler → sqlc → contract test → audit → TS SDK) | First feature lands; pattern set | — |
| 3 | `04-platform-patterns.md` | Promote shared code into `internal/platform/` | CONVENTIONS.md written | **CHECKPOINT 1** |
| 4 | `05-openbao-integration.md` | Envelope encryption, kid binding, k8s auth/AppRole, KV v2 | `internal/platform/crypto/envelope/` ready for downstream modules | — |
| 5 | `06-identity-keycloak.md` | Identity façade via gocloak + **social login** (Keycloak IdP brokering for Google / GitHub / Apple) | `/v1/users` + `/v1/users/{id}/social-providers` | — |
| 6 | `07-notifications-novu.md` | Notifications module wrapping Novu (email + in-app); Novu added to compose | `/v1/notifications/send`, `/v1/notification-channels/*` | **CHECKPOINT 2** |
| 7 | `08-organizations.md` | Organizations + Members + Invitations (uses Notifications for invite email) | `/v1/organizations/*`, `/v1/invitations/*` | — |
| 8 | `09-rbac-casbin.md` | RBAC-with-domains on Casbin + pgx adapter | `/v1/authorization/check` | — |
| 9 | `10-api-keys.md` | argon2id hash + envelope-encrypted prefix index + rotation | `/v1/api-keys` | — |
| 10 | `11-audit-logs.md` | Append-only DB grants + hash chain + integrity verify | `/v1/audit-events` | **CHECKPOINT 3** |
| 11 | `12-control-plane-skeleton.md` | `/control/v1/deployments` against a local-mode provisioner (no host writes) | Operator can CRUD a fake deployment | **CHECKPOINT 4** (approve sudoers, certbot config, layout) |
| 12a | `13a-host-nginx.md` | nginx vhost adapter (file write + reload, NEVER bulk apply-nginx) | One real vhost installed | **CHECKPOINT 5** |
| 12b | `13b-k3s-clientgo.md` | client-go typed apply via kustomize-rendered manifests + NetworkPolicy | Real namespace + Deployment + Service applied with isolation | **CHECKPOINT 6** |
| 12c | `13c-postgres-provisioner.md` | Per-Deployment DB + role + RLS grants on host Postgres | One real DB created | **CHECKPOINT 7** |
| 12d | `13d-openbao-provisioner.md` | Per-Deployment transit key + k8s role + KV path + audit policy | One real key created | **CHECKPOINT 8** |
| 12e | `13e-provisioning-sequence.md` | Wire the §6.2 13-step sequence + destroy reconciler + upgrade/rollback/restore/purge | End-to-end real provision | **CHECKPOINT 9** |
| 13 | `14-impersonation-operator-mfa.md` | operators realm import, MFA, step-up, impersonation tokens | Operator → data-plane impersonation works | — |
| 14 | `15-go-sdk.md` | Go SDK generated + handwritten workflows | `sdk/go/` publishable | — |
| 15 | `16-dx-polish.md` | Static HTML walkthrough, Postman, prism in CI, recipes | DX ready | — |
| 16 | `17-final-verification.md` | §26 DoD across every endpoint + §17.3 matrix + §17.4 provisioning | MVP shippable | — |

Total: **21 implementation files** across **16 logical phases**, with **9 user checkpoints** gating any irreversible action.

### Scope changes from baseline AGENTS.md (user-approved 2026-05-24)

| Change | What | Where | ADR |
|---|---|---|---|
| Promote Notifications to MVP | Novu wrapper module (email + in-app first); SMS/WhatsApp stay v1 | AGENTS.md §4.4, §15, §15.1, §8.7, §9, §18.3, §21 | 013 |
| Add Social login to MVP | Keycloak IdP brokering for Google, GitHub, Apple at minimum; new identity endpoints `/v1/users/{id}/social-providers` | AGENTS.md §8.3, §12.2, §17.3, §18.3, §21 | 014 |
| Add Bring-Your-Own-Domain (BYOD) to MVP | Each Deployment can attach 1..N custom domains; certbot issues per-domain cert; DNS verify via TXT or ACME http-01; new control-plane endpoints `/control/v1/deployments/{id}/domains/*` | AGENTS.md §6.5, §8.0, §12.1, §15 | 015 |
| Add easy-setup tooling to MVP | `saasctl init` wizard (compose-up + migrate + auto-bootstrap first tenant + auto-issue first API key); 5-min walkthrough | AGENTS.md §15, §21 | 016 |
| Add Bring-Your-Own-Key (BYOK) vendor creds to MVP | Notification channel config (Phase 6) accepts Deployment-provided SMTP/SendGrid/SES creds; OpenBao-envelope-encrypted; rotation API; audit on read | AGENTS.md §15, §18.7, §21 | 017 |
| Add Newsletters to v1 roadmap | Built on Notifications + Novu broadcast; subscriber lists, opt-in, GDPR/PDPL unsubscribe | AGENTS.md §15.1 (insert new item) | — |
| Add Surveys to non-goals | Surveys are a Product Builder feature, not platform plumbing | AGENTS.md §28 (insert new bullet) | — |

MVP item count: **18** (was 13). Phase count: **16 logical phases** (with Phase 12 split into 5 sub-phases). Checkpoint count: **9**.

---

## Tenant isolation — cross-phase invariant

Per user directive and AGENTS.md §18.1, tenant isolation is enforced at every layer. Every phase honors all eight layers; if a phase introduces code that touches tenant-bound data, its verification checklist must prove all applicable layers hold.

| Layer | Mechanism | Where enforced | Phase that lands it |
|---|---|---|---|
| 1. Auth | `tenant_id` only from JWT claim or API key binding. `X-Tenant-Id` header rejected (401). `X-Acting-Tenant-Id` only with `tenants.impersonate` scope. | `internal/platform/auth/` middleware | Phase 3 (skeleton in Phase 2) |
| 2. Service | Every service method that touches tenant-bound rows takes `tenantID` as first non-context param. No "global" helpers on tenant-bound tables. | Hexagonal port signatures + linter rule | Phase 3 |
| 3. DB | Row-Level Security on every tenant-bound table. `app_role` has `FORCE ROW LEVEL SECURITY`. Policy `USING (tenant_id = current_setting('app.current_tenant_id')::text)`. pgx `AfterAcquire` hook sets `SET LOCAL app.current_tenant_id` from request context. | Migrations + pgxpool config | Phase 2 (first table), enforced in Phase 3 platform |
| 4. Physical | One Postgres DB per Deployment; one k3s namespace per Deployment with default-deny `NetworkPolicy`; one nginx vhost per Deployment. | Provisioner | Phase 11c (DB), 11b (k3s + NetworkPolicy), 11a (nginx) |
| 5. Crypto | Per-Deployment OpenBao transit key. Row stores `kid`; decrypt path verifies `kid == deployment_id` before calling `transit/decrypt/<kid>`. Cross-Deployment decrypt physically refused. | `internal/platform/crypto/envelope/` | Phase 6 |
| 6. RBAC | Casbin RBAC-with-domains: `(sub, dom, obj, act)`. `dom = tenant_id`. Matcher `r.dom == p.dom`. `CHECK (v1 <> '*')` on `casbin_rule` to forbid wildcard domain. | `internal/dataplane/authorization/` + migration | Phase 7 |
| 7. Test | §17.3 matrix mandatory per endpoint. Cross-tenant access test must land in the same PR as the endpoint. CI fails authorization-tests stage if any tenant-bound endpoint lacks the matrix. | `internal/dataplane/<module>/security_test.go` | Phase 2 (first), every phase after |
| 8. Audit | Every authorization denial emits an audit row with `actor_tenant_id` + `target_tenant_id`. Hash chain detects post-hoc tampering. Append-only Postgres grants make UPDATE/DELETE physically impossible from the app role. | `internal/dataplane/audit/` + Postgres trigger | Phase 9 |

**Hard rules every phase must follow:**

- Never write a query that joins across `tenant_id`. If a feature needs cross-tenant data (e.g. operator audit rollup), it lives in the **control plane**, never the data plane, and uses a separate role.
- Never expose `tenant_id` as a function parameter that is sourced from URL/path/body — it always comes from `auth.TenantFromContext(ctx)`. If a handler reads `tenant_id` from anywhere else, the security review fails.
- Never share a `*pgxpool.Pool` across Deployments. The data-plane binary has exactly one pool, bound to its own Deployment's DB.
- Never store secrets unwrapped. Even in-memory caches of decrypted PII must zero-on-eviction (`crypto/subtle.ConstantTimeCopy` then explicit slice zero).
- Never log a `tenant_id` collision (two tenant_ids in the same log record) without flagging it — that pattern is a leak signal, not normal.

A failure in any of the eight layers is a security incident, not a bug. Each phase's "Anti-pattern guards" section enumerates the specific traps to avoid.

---

## Plan execution rules (for `claude-mem:do`)

These rules govern how a subagent should execute any phase file:

1. **Read these three files first**, in this order, every phase: `AGENTS.md`, `CLAUDE.md` (both global and project), this master, then the phase file, then `01-foundations.md`. Do not skip — the foundations file is the only place where exact library versions and signatures are recorded.

2. **OpenAPI is the contract.** If a phase touches a public endpoint, the spec change lands BEFORE any handler code. `make openapi-check` must pass (spectral lint + overlay-downgrade + oapi-codegen round-trip + openapi-generator round-trip). Authoring is in OpenAPI 3.1; an Overlay file in `openapi/overlays/30-downgrade.yaml` produces a 3.0-compatible copy for oapi-codegen (see Phase 0 §3).

3. **Every Makefile target listed in §25.9 must continue to work** after the phase. If a phase adds a new target, document it in `CONVENTIONS.md`.

4. **Per global CLAUDE.md** — atomic commits per stage, lowercase commit titles ≤ 50 chars, sync with `main` before push, PR follows `.github/PULL_REQUEST_TEMPLATE.md`, add `ready` label after PR open, monitor CI. **NO** `Co-Authored-By` lines. **NO** `--no-verify`.

5. **License gate.** Any new dependency requires:
   - OSI-approved license (MIT/Apache-2.0/BSD/MPL-2.0/PostgreSQL/ISC preferred; AGPL only as standalone network service)
   - Recent commits + > 1k stars OR recognized maintainer
   - An ADR in `docs/adr/` if it's a non-obvious choice
   See AGENTS.md §3.5 and §25.8.

6. **Migrations are forward-only AND backward-compatible with the previous image for one release** (§25.4). A subagent must write the migration so the prior data-plane image still boots against the new schema. If that's impossible, the change requires an ADR.

7. **The user is the final authority on checkpoint approval.** A subagent must STOP at every "CHECKPOINT N" marker and post a structured handoff: what changed, what to verify, what to approve. The subagent must NOT proceed past a checkpoint without the user typing approval.

8. **No partial host state.** If a phase performs any host write (`/etc/nginx/`, k3s API, host Postgres, OpenBao), it must implement rollback first. Provisioning failure must leave zero artifacts — see AGENTS.md §6.2.

9. **No new ports/sockets without coordination.** The homelab has running services; the SA geofence is on. New listeners must avoid colliding with: `qudrat.omarss.net`, `apps.omarss.net`, `claw.omarss.net`, `swet.omarss.net`, `sync.omarss.net`. New deployment vhosts live under `*.saas.omarss.net`.

10. **`/srv/apps` collision watch.** The existing apps host runs from `/srv/apps`. The SaaS control plane must never write there (AGENTS.md §6.7 footnote). Per-Deployment object storage uses a different prefix (deferred — Files module is post-MVP).

---

## Checkpoint policy

A checkpoint is a hard stop. At each checkpoint the subagent must produce:

```text
## Checkpoint N — <name>

### What was done
- file: path:lineno — change summary
- file: path:lineno — change summary
- ... (concrete, file-grained)

### What to verify (user runs these)
$ make <target>          # expected: <result>
$ curl <url>             # expected: <body>
$ kubectl get <res>      # expected: <state>
$ ls -la <path>          # expected: <listing>

### What approval means
By proceeding, the user accepts: <concrete list of irreversible
or shared-state changes the next phase will make>.

### Rollback if rejected
$ <commands to undo what just happened>
```

The 9 checkpoints are gated on:

| Checkpoint | Gate | Why |
|---|---|---|
| 1 (after Phase 3) | Foundations review | Patterns set the template for 16 more phases |
| 2 (after Phase 6) | OpenBao integration approved | Crypto is unrecoverable if misdesigned |
| 3 (after Phase 9) | Data plane complete | Last clean stop before control-plane work |
| 4 (after Phase 10) | sudoers, certbot, nginx layout approved | Phase 11a starts writing to /etc/nginx |
| 5 (after Phase 11a) | First real nginx vhost on disk | Verify no clobber, certbot integration sane |
| 6 (after Phase 11b) | First real k3s namespace | Verify NetworkPolicy isolation works |
| 7 (after Phase 11c) | First real Postgres DB on host | Verify RLS + grants tight |
| 8 (after Phase 11d) | First real OpenBao transit key | Verify kid binding + policy scope |
| 9 (after Phase 11e) | First end-to-end real Deployment | Inspect every artifact before declaring §15 item #1 done |

---

## ADRs to create across the plan

Each ADR lives in `docs/adr/NNN-<slug>.md`. The plan creates these in the listed phase:

| ADR | Title | Created in |
|---|---|---|
| 001 | Stack pins and license rationale | Phase 1 |
| 002 | OpenAPI 3.1 authoring with overlay-downgrade to 3.0 for oapi-codegen | Phase 1 |
| 003 | RLS + `app.current_tenant_id` session GUC for defense-in-depth | Phase 2 |
| 004 | `x-pii` enforcement via `x-oapi-codegen-extra-tags` + reflection middleware | Phase 3 |
| 005 | Casbin RBAC-with-domains, `dom = tenant_id`, no wildcard, no Go LISTEN/NOTIFY watcher (Redis watcher when scaling) | Phase 8 |
| 006 | OpenBao Shamir 5-of-3 unseal for MVP, prod path to cloud KMS auto-unseal | Phase 4 |
| 007 | Per-Deployment Keycloak client vs single client with audience-resolve | Phase 5 |
| 008 | Wildcard `*.saas.omarss.net` cert via DNS-01 vs per-vhost HTTP-01; coexistence with BYOD per-domain certs | Phase 12a |
| 009 | Outbox dispatcher: in-process goroutine for MVP, NATS/asynq deferred | Phase 2 |
| 010 | Idempotency record storage TTL and cleanup job (24h window) | Phase 3 |
| 011 | Cursor schema versioning policy (`v` bump → 410 Gone) | Phase 3 |
| 012 | Audit hash-chain canonicalization (RFC 8785 JCS or simpler ordered-key JSON) | Phase 10 |
| 013 | Promote Notifications module (Novu wrapper) to MVP | Phase 6 |
| 014 | Promote Social login (Keycloak IdP brokering for Google/GitHub/Apple) to MVP | Phase 5 |
| 015 | BYOD custom domain — DNS verification (TXT vs ACME http-01) + per-domain HTTP-01 cert + nginx multi-server_name vhost | Phase 11 (skeleton) + Phase 12a (real) |
| 016 | `saasctl init` wizard scope; idempotency of bootstrap; first-tenant + first-API-key auto-creation | Phase 1 (stub), Phase 15 (full) |
| 017 | BYOK vendor credentials — channel config schema, envelope encryption, rotation API, audit | Phase 6 |

---

## Definition of done — applied per phase

A phase is not done until **every** item in AGENTS.md §26 holds for the code it ships:

- [ ] OpenAPI contract updated (lint + overlay-downgrade + oapi-codegen round-trip + openapi-generator round-trip all green)
- [ ] Implementation complete (handler + service + port + adapter + sqlc queries + migration)
- [ ] Tests pass: unit + module integration (testcontainers-go) + contract (prism proxy)
- [ ] §17.3 authorization matrix for every tenant-bound endpoint
- [ ] §18.1 tenant isolation: RLS migration, service-layer signature, pgx AfterAcquire hook test, cross-tenant denial test
- [ ] Audit events emitted for actions on the §18.3 list (where applicable)
- [ ] Idempotency-Key implemented on POST + state-transition PATCH + listed endpoints
- [ ] ETag / If-Match on PATCH/PUT/DELETE
- [ ] OpenTelemetry traces + metrics added per §20
- [ ] Docs / recipes updated (especially for §21 first-class workflows)
- [ ] SDK impact checked: TS SDK regenerated and committed; Go SDK regenerated (from Phase 13 onward)
- [ ] Migration is backward-compatible with previous image for one release
- [ ] PR follows `.github/PULL_REQUEST_TEMPLATE.md`, `ready` label added, CI green

---

## Appendix: file map at MVP completion

```text
saas/
  AGENTS.md
  CLAUDE.md
  CONVENTIONS.md                        # produced in Phase 3
  Makefile
  .golangci.yml
  .spectral.yaml
  .oapi-codegen-controlplane.yaml
  .oapi-codegen-dataplane.yaml
  .github/
    PULL_REQUEST_TEMPLATE.md
    workflows/
      ci.yml
  cmd/
    controlplane/main.go
    dataplane/main.go
    migrate/main.go
    saasctl/main.go
  internal/
    platform/
      auth/          tenancy/      pgx/          log/          problem/
      idempotency/   pagination/   etag/         id/           validator/
      crypto/        outbox/       otel/
    controlplane/
      deployments/   operators/    observability/
    dataplane/
      identity/      tenancy/      organizations/  authorization/
      apikeys/       audit/
  openapi/
    control-plane.yaml
    data-plane.yaml
    overlays/30-downgrade.yaml
    problems/        # shared error component fragments
  migrations/
    controlplane/    dataplane/
  deploy/
    k3s/
      base/          overlays/template/
    nginx/
      template.conf.tmpl
    openbao/
      bootstrap.sh   policies/
  sdk/
    ts/              go/
  docs/
    adr/             plans/mvp/    walkthrough/  recipes/
  compose.yaml       # local stack
  Dockerfile.controlplane
  Dockerfile.dataplane
```

---

End of master. Next: `01-foundations.md`.
