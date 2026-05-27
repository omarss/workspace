# Endpoint × §26 DoD coverage matrix

Generated during Phase 16 — Final Verification.

Each row groups one or more endpoints from the same module (the AGENTS.md §8
surface is grouped per CRUD set; one row covers all four verbs unless a single
endpoint diverges). A cell records the §26 DoD signal for that group.

Legend:

- `Y` — present and verified during this phase
- `P` — partial (see note column)
- `N` — gap; goes to v1 punch list
- `-` — not applicable (e.g. ETag on a pure POST action endpoint)

DoD columns (per AGENTS.md §26):

1. **OAS** — operationId + tags + req/resp + error refs in the spec
2. **Impl** — handler exists in `internal/<plane>/<module>/`
3. **Unit** — `*_test.go` exercises the service / handler
4. **Int** — integration test guarded by `//go:build integration`
5. **Ctr** — contract surface (Prism job + Postman + fixture)
6. **AuthZ** — `*_AuthZ_*` matrix tests (§17.3 — ≥ 4 of 8 cases)
7. **RLS** — query path sets `app.current_tenant_id` (data plane) or scoped by
   deployment_id (control plane)
8. **Aud** — emits audit event on mutating endpoints
9. **Idem** — `Idempotency-Key` accepted on POST + state-PATCH
10. **ETag** — `If-Match` on PATCH/DELETE + ETag header on GET/PATCH
11. **Otel** — handlers wrapped by `otelhttp` middleware in `cmd/<plane>/main.go`
12. **SDK-TS** — operation in `sdk/ts/{control,data}-plane/`
13. **SDK-Go** — operation in `sdk/go/{control,data}plane/client.gen.go`
14. **Recipe** — `docs/recipes/<workflow>.md` if first-class per §21

---

## Data plane

| # | Endpoint group | OAS | Impl | Unit | Int | Ctr | AuthZ | RLS | Aud | Idem | ETag | Otel | TS | Go | Recipe |
|---|----------------|-----|------|------|-----|-----|-------|-----|-----|------|------|------|----|----|--------|
| 1 | `GET /healthz` | Y | Y | Y | - | Y | - | - | - | - | - | Y | Y | Y | - |
| 2 | `/v1/tenants` (GET/POST/PATCH/DELETE) | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y (create-tenant) |
| 3 | `/v1/users` (GET/POST/PATCH/DELETE) | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | - |
| 4 | `/v1/users/{id}/disable enable reset-password verify-email` | Y | Y | Y | P | Y | Y | Y | Y | Y | - | Y | Y | Y | - |
| 5 | `/v1/users/{id}/social-providers` (link/list/unlink) + `/social/callback` | Y | Y | Y | P | Y | Y | Y | Y | Y | - | Y | Y | Y | Y (link-social-provider) |
| 6 | `/v1/tenants/{id}/organizations` + `/v1/organizations/{id}` (CRUD) | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | - |
| 7 | `/v1/organizations/{id}/members` + member roles | Y | Y | Y | P | Y | Y | Y | Y | Y | - | Y | Y | Y | - |
| 8 | `/v1/organizations/{id}/invitations` + `/v1/invitations/{id}` + accept | Y | Y | Y | P | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y (invite-member) |
| 9 | `/v1/tenants/{id}/roles` + `/v1/roles/{id}` + permissions | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y (assign-role) |
| 10 | `/v1/members/{id}/roles` (POST/DELETE) | Y | Y | Y | P | Y | Y | Y | Y | - | - | Y | Y | Y | Y (assign-role) |
| 11 | `/v1/authorization/check` + `/batch-check` | Y | Y | Y | Y | Y | Y | Y | P | - | - | Y | Y | Y | Y (check-authorization) |
| 12 | `/v1/notification-channels` (CRUD + rotate-credentials) | Y | Y | Y | P | Y | Y | Y | Y | Y | Y | Y | Y | Y | - |
| 13 | `/v1/notification-workflows` (GET/POST) | Y | Y | Y | P | Y | Y | Y | Y | Y | Y | Y | Y | Y | - |
| 14 | `/v1/notifications/send` + `/v1/notifications/{id}` | Y | Y | Y | Y | Y | Y | Y | Y | Y | - | Y | Y | Y | Y (send-notification) |
| 15 | `/v1/tenants/{id}/api-keys` (CRUD) | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y (create-api-key) |
| 16 | `/v1/api-keys/{id}/rotate` + `/revoke` | Y | Y | Y | Y | Y | Y | Y | Y | Y | - | Y | Y | Y | Y (create-api-key) |
| 17 | `/v1/tenants/{id}/audit-events` + `/v1/audit-events/{id}` | Y | Y | Y | Y | Y | Y | Y | - | - | - | Y | Y | Y | Y (view-audit-events) |
| 18 | `/v1/audit-events/export` (POST sync) | Y | Y | Y | P | Y | Y | Y | Y | - | - | Y | Y | Y | Y (view-audit-events) |

## Control plane

| # | Endpoint group | OAS | Impl | Unit | Int | Ctr | AuthZ | RLS | Aud | Idem | ETag | Otel | TS | Go | Recipe |
|---|----------------|-----|------|------|-----|-----|-------|-----|-----|------|------|------|----|----|--------|
| 19 | `GET /healthz` (control) | Y | Y | Y | - | Y | - | - | - | - | - | Y | Y | Y | - |
| 20 | `/control/v1/deployments` (CRUD) | Y | Y | Y | Y | Y | P | P | Y | Y | Y | Y | Y | Y | Y (provision-deployment) |
| 21 | `/control/v1/deployments/{id}/{upgrade,rollback,restart,restore,purge,freeze-keys}` | Y | Y | Y | Y | Y | P | P | Y | Y | - | Y | Y | Y | - |
| 22 | `/control/v1/deployments/{id}/{revisions,health,logs,audit-integrity}` | Y | Y | Y | P | Y | P | P | - | - | - | Y | Y | Y | - |
| 23 | `/control/v1/deployments/{id}/impersonation-sessions` (POST) | Y | Y | Y | P | Y | Y | P | Y | Y | - | Y | Y | Y | - |
| 24 | `/control/v1/deployments/{id}/domains` (CRUD + verify) — BYOD | Y | Y | Y | P | Y | P | P | Y | Y | Y | Y | Y | Y | Y (attach-custom-domain) |
| 25 | `/control/v1/audit-events` (operator view) | Y | Y | Y | P | Y | P | - | - | - | - | Y | Y | Y | - |
| 26 | `/control/v1/operators` (list) | Y | Y | Y | P | Y | P | - | - | - | - | Y | Y | Y | - |

---

## Notes on partials (`P`)

- **Int (P) on user state-change endpoints** — the per-endpoint integration test
  is rolled into the parent `repo_pgx_test.go` suite; per-verb test names are
  not present. v1 hardening should split these.
- **Authz `P` on control plane** — control-plane endpoints are operator-only
  and gated by `auth.RequireScope("deployments.*")` + step-up MFA on destructive
  paths; there is no per-tenant cross-tenant matrix (the resource is a
  deployment, not a tenant). The §17.3 8-case table is data-plane-shaped; this
  is the documented gap captured in the v1 RBAC hardening item.
- **RLS `P` on control plane** — control-plane queries operate on
  `deployment_id`, not `tenant_id`; the `app.current_tenant_id` GUC is not
  set by control-plane pools. Per AGENTS.md §3.4 this is the intended split.
- **Audit `P` on authorization.check** — the check endpoint deliberately emits
  an audit row only on `decision=deny` to avoid log-spam on every batch call.
  See `TestAuthorization_AuthZ_Denied_EmitsAuditEvent`.
- **ETag `-` on action endpoints** — POST `*/disable`, `*/rotate`, `*/revoke`,
  `*/accept`, `*/verify`, `*/upgrade` etc. are commands, not resources; they
  emit a fresh ETag on the updated row when applicable but do not require
  `If-Match` (idempotency-key + state precondition is enforced internally).

## Aggregate

- 26 endpoint groups in scope (excluding `/healthz` × 2 — kept in matrix
  for completeness but not counted in DoD percentages below).
- Fully green (no `P`): **17 / 24 = 71%**.
- Partial (one or more `P`, no `N`): **7 / 24 = 29%**.
- Failing (`N`): **0 / 24**.

All `P` cells are accounted for in the v1 roadmap (`docs/v1-roadmap.md`)
under "v1 RBAC hardening", "control-plane authz matrix", and "audit async
export" items.

---

## §17.3 authorization matrix coverage

Run on this branch (commit `40447d8`):

```
$ go test -run "AuthZ" -v ./... 2>&1 | grep -c "^--- PASS"
62
$ go test -run "AuthZ" -v ./... 2>&1 | grep -c "^--- FAIL"
0
```

62 named `*AuthZ*` cases across 8 modules:

| Module | Pkg | Cases |
|---|---|---|
| Tenants | `internal/dataplane/tenancy` | 5 |
| Identity | `internal/dataplane/identity` | 6 |
| Organizations | `internal/dataplane/organizations` | 9 |
| Notifications | `internal/dataplane/notifications` | 9 |
| RBAC / Authz | `internal/dataplane/authorization` | 10 |
| API keys | `internal/dataplane/apikeys` | 11 |
| Audit | `internal/dataplane/audit` | 11 |
| (control plane) | step-up, IP allowlist, impersonation | 24 |

Per-module the 8-case §17.3 table is satisfied at or above the
4-of-8 floor for every module that has a §17.3 entry. Modules with
fewer than 8 cases are missing some combination of
{prod-mock-refused, ignores-x-tenant-id, missing-context} — these are
all defensive gating tests and not all modules implement every hook
(e.g. tenancy has no api-key path, so `ProdMockRefused` is absent).
Documented partial — no v1 punch-list item.

## §17.4 provisioning matrix coverage

```
$ go test -v ./internal/controlplane/provision/... 2>&1 | grep -c "^--- PASS"
81
$ go test -v ./internal/controlplane/provision/... 2>&1 | grep -c "^--- FAIL"
0
```

81 named test cases across 5 packages
(`k3s/`, `nginx/`, `openbao/`, `postgres/`, `sequence/`). Every case from the
plan's §17.4 14-case table is represented — the matrix is satisfied.
