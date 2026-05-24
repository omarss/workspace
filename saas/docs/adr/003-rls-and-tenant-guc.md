# ADR 003 — Row-Level Security with `app.current_tenant_id` session GUC

## Status

Accepted (2026-05-24, Phase 2).

## Context

AGENTS.md section 18.1 names tenant isolation as the platform's primary
security invariant. The master MVP plan enumerates eight defense layers
(`docs/plans/mvp/00-master.md`); layer 3 — the database — is the one this ADR
locks in.

Three options were considered:

1. **Application-layer scoping only.** Every query carries an explicit
   `tenant_id = $1` predicate. Pro: simple. Con: one missed `WHERE` clause
   and the bug ships; the database is no defense.
2. **Per-tenant database role.** A new Postgres role per tenant; each request
   logs in as the tenant. Pro: physical separation. Con: thousands of roles,
   connection pooling becomes per-tenant, GRANTs blow up on scale.
3. **Row-Level Security with a session GUC.** One DB role per Deployment;
   every tenant-bound table has an RLS `USING` policy that compares its
   `tenant_id` column to `current_setting('app.current_tenant_id')`. The
   request middleware sets the GUC on every acquired connection.

## Decision

Adopt option 3.

- Every tenant-bound table is `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL
  SECURITY` (so the table owner cannot bypass it either).
- The policy reads `current_setting('app.current_tenant_id', true)`; the
  optional `true` returns NULL instead of erroring when the GUC is unset —
  the resulting filter is `tenant_id = NULL`, which is `UNKNOWN`, which is
  treated as `false`, which means **zero rows visible**. The safer failure
  mode.
- The pgxpool's `PrepareConn` hook executes
  `SELECT set_config('app.current_tenant_id', $tenant, false)` on every
  connection it hands out, sourced from `auth.TenantFromContext(ctx)`. If
  the caller has no tenant in context the GUC is set to empty, and RLS hides
  every row.
- The `tenant` table is special: `tenant_id` IS its `id`, so the policy is
  `USING (id = current_setting('app.current_tenant_id', true))`.

## Caveat — dev environment bypasses FORCE RLS

The dev Postgres in `compose.yaml` runs as the `saas` superuser role for
convenience (Phase 1 placeholder). Postgres superusers bypass Row-Level Security
**even when `FORCE ROW LEVEL SECURITY` is set on the table**. As a result, the
RLS policies declared in `migrations/dataplane/000002_tenants.up.sql` are
**dormant** in the dev environment.

Phase 2's tenant isolation is enforced entirely by the application layer:

- The mock `auth` middleware reads `X-Mock-Tenant-Id` (env-gated, prod-rejected).
- `auth.AssertTenant(ctx, requestedTenantID)` runs at every Service method
  entry point.

DB-layer RLS bites only when Phase 11c provisions a per-Deployment non-
superuser app role (`saas_<project>_<env>_app`) with the explicit grants
listed in §6.1. Until then, RLS is a "defense in depth" annotation only —
removing it before 11c would silently expose cross-tenant reads if the
service layer regresses.

Subagents working on Phases 3-10 must NOT assume RLS will catch a tenant
isolation bug in the dev DB. The §17.3 authorization-matrix tests are the
guard rail.

## Consequences

- Forgetting to wire the `PrepareConn` hook silently breaks every read. A
  Phase-2 anti-pattern guard documents this; Phase 3 promotes the pool
  helper into `internal/platform/pgx` with a regression test.
- `set_config(..., false)` makes the GUC session-scoped, not transaction-
  scoped. Pool connections reset the GUC on the next acquire. Phase 11c
  switches to `SET LOCAL` once per-request transactions land.
- Migrations must grant `app_role` (or PUBLIC in Phase 2) only the minimal
  set of privileges; `FORCE ROW LEVEL SECURITY` keeps the policy effective
  even for the owner.
- A misconfigured `tenant_id` column in a future table would punch a hole.
  Mitigation: lint rule in Phase 3 that fails CI when a new migration
  creates a tenant-bound table without `ENABLE ROW LEVEL SECURITY`.

## Revisit

Phase 11c (per-Deployment DB role) and Phase 13 (operator impersonation)
extend this model. ReBAC via OpenFGA would not change the DB layer — it
would add a separate authorization endpoint while RLS still backs the SELECTs.
