# ADR 005 — RBAC-with-domains on Casbin; dom = tenant_id; no wildcard; no multi-replica watcher

## Status

Accepted (Phase 8, 2026-05-25).

## Context

`AGENTS.md` §8.4 mandates pure RBAC for MVP — no ReBAC, no Zanzibar, no
OpenFGA. `AGENTS.md` §18.1 layer 6 specifies Casbin's RBAC-with-domains
model as the chosen mechanism for per-tenant policy isolation. The
Authorization module needs:

- per-tenant policy isolation (layer 6 of §18.1)
- constant-time check on every request (target: ~10µs)
- an audit trail for grants and denials (§18.3)
- a path to multi-replica without breaking the model

Casbin v2's RBAC-with-domains model is the canonical fit:

```ini
[request_definition]
r = sub, dom, obj, act

[policy_definition]
p = sub, dom, obj, act

[role_definition]
g = _, _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub, r.dom) && r.dom == p.dom && r.obj == p.obj && r.act == p.act
```

Strict equality on `dom` encodes per-tenant isolation: a role in tenant
A cannot accidentally grant access in tenant B because the matcher
refuses to match across domains.

The pckhoi/casbin-pgx-adapter v3.2.0 is the only pgx-native Postgres
adapter for Casbin v2. The upstream casbin/casbin-pg-adapter uses lib/pq
which is incompatible with the platform's pgx stack. Last release of the
pgx adapter was Aug 2024; verified to build against casbin v2.135.0 by
the Phase 8 compile-check (commit `<phase-8-compile-check>` in the
worktree's history).

## Decision

1. **Casbin version**: v2.135.0 with the embedded `rbac.conf` shown
   above. The model file is shipped in-binary (`//go:embed`) so
   operators cannot tamper with it at runtime.

2. **Subject / domain / object / action**:
   - `sub` is `m:<member_id>` for grouping rows. The `m:` prefix keeps
     subjects in the `g` relation distinct from role names — without
     it, a role named `member_abc` could collide with a member id
     `member_abc` and short-circuit the matcher. All call sites go
     through `authorization.FormatSubject`.
   - `dom` is `tenant_id`. No wildcards.
   - `obj` is the resource type (`tenant`, `member`, `role`, `apikey`,
     `audit`, `notification`, ...).
   - `act` is the action (`read`, `write`, `delete`, `assign`,
     `disable`, `send`, ...).

3. **Permission string split**: `obj, act := strings.Cut(permission, ".")`
   at the service boundary (`splitPermission` in `service.go`). Permission
   names like `"invoice.read"` are split exactly once. Re-implementations
   elsewhere are an anti-pattern.

4. **Wildcard domain forbidden**: defence in depth at three layers:
   - DB CHECK constraint on `casbin_rule` (`v1 <> '*'` for `p` rows;
     `v2 <> '*'` for `g` rows).
   - Service-layer validation (`guardDomain` in `enforcer.go` rejects
     `tenant_id == "*"` and the role-name validator forbids `name == "*"`).
   - Role-name pattern `^[a-zA-Z][a-zA-Z0-9_.-]*$` excludes `*` syntactically.

5. **Adapter**: pckhoi/casbin-pgx-adapter v3.2.0 with
   `WithSkipTableCreate` so our migration owns the schema (CHECK
   constraint + custom indexes the adapter cannot reproduce).
   Contingency: if the adapter breaks under future Casbin upgrades, a
   thin sqlc-driven adapter implementing `persist.Adapter` (~80 LoC) is
   the fallback path documented in the Phase 8 plan §8.2.

6. **Single-replica MVP**: `LoadPolicy` runs once on startup;
   `EnableAutoSave(true)` keeps in-memory state and the DB aligned on
   every `AddPolicy` / `RemovePolicy` / `AddGroupingPolicy` /
   `RemoveGroupingPolicy`. There is NO multi-replica policy sync today
   — a second data-plane pod would diverge until the next restart. The
   chosen mechanism when scaling out is `github.com/casbin/redis-watcher/v2`
   (the only Go LISTEN/NOTIFY-style watcher that exists for Casbin v2 —
   a pure-Go pg LISTEN/NOTIFY watcher does NOT exist as of 2026).
   Multi-replica is deferred to the scale event.

7. **Audit on denial**: every `Check` that returns `allowed=false`
   publishes an `authorization.denied` event to the outbox. Phase 10
   audit consumes these for the hash-chained audit log. Denied checks
   are first-class security signals; the audit row carries `member_id`,
   `tenant_id`, `permission`, `reason`, and the principal actor.

8. **Member-tenant cross-check**: before consulting Casbin, the service
   verifies the member belongs to the claimed tenant. A member in
   tenant A cannot be evaluated against tenant B's domain even if the
   caller is in tenant B. Returns `ErrCrossTenantMember`.

9. **System roles are immutable**: roles with `is_system=true` (seeded
   on tenant creation by the Phase 8 §8.5 hook — `tenant_admin`,
   `tenant_member`, `tenant_billing_admin`) refuse `DeleteRole` with
   `ErrSystemRoleImmutable`. Removing `tenant_admin` would lock the
   operator out of their own tenant.

10. **No deny rules**: the policy effect is `some(where (p.eft == allow))`
    — pure allow. There is no `eft=deny` path. If a future requirement
    needs forcible deny, the path is to remove permissions, not add a
    deny rule. Confirmed not needed for MVP.

## Consequences

### Positive

- Per-tenant isolation enforced at the policy layer; cross-tenant
  policy rows physically can't exist because of the DB CHECK constraint.
- The permission catalogue lives in the DB and is exposed via
  `/v1/permissions` so operators can discover what permissions exist
  before composing roles.
- Denials are first-class audit events; security teams have a built-in
  signal for unusual access patterns.
- The model is small (~80 lines of model file + ~600 lines of Go code
  outside generated). Easy to audit, easy to extend.

### Negative

- Cross-tenant queries are impossible by construction. Features that
  legitimately need them (operator audit rollup, billing aggregation)
  must go through control-plane endpoints with a separate role and
  cannot reuse the data-plane Casbin enforcer.
- Single replica until the scale event. A newly-assigned role becomes
  visible immediately in the writing pod, but a second pod would not
  see it until restart. Tests must not rely on instant cross-pod
  visibility.
- The pckhoi adapter is community-maintained (last release Aug 2024).
  We pin v3.2.0 and own a contingency adapter path; future upgrades
  require a re-run of the Phase 8.1 compile-check.

### Neutral

- Permission strings are split exactly once at the boundary. Adding a
  permission like `"audit.event.read"` (two dots) would be rejected by
  `splitPermission`. Future permissions must stay `resource_type.action`
  shaped.

## Alternatives considered

- **OpenFGA / Zanzibar**: rejected — too heavy for MVP. ReBAC adds
  network hops + a separate service to operate. Revisit if a customer
  asks for fine-grained sharing semantics (e.g. "share document X with
  user Y").
- **CEL / Cedar policy language**: rejected — increases the operator's
  cognitive load. Casbin's RBAC-with-domains is sufficient for the
  endpoint surface in MVP.
- **Header-driven RBAC (X-Role)**: rejected — privileges sourced from
  headers are CVE-shaped. The principal source is always the JWT/API
  key (§18.1 layer 1).
- **In-memory policy without DB**: rejected — operators need to manage
  roles via API, and the audit log needs a durable record of grants.

## References

- `docs/plans/mvp/01-foundations.md` §6 — verified Casbin APIs and the
  rbac.conf model file.
- `docs/plans/mvp/09-rbac-casbin.md` — Phase 8 implementation plan.
- `AGENTS.md` §8.4 (RBAC endpoints), §17.3 (matrix), §18.1 layer 6,
  §18.3 (audit on denials).
- `CONVENTIONS.md` §2 (service signatures), §5 (security matrix).
- Casbin v2 docs: https://casbin.org/docs/rbac-with-domains
- pckhoi/casbin-pgx-adapter v3.2.0:
  https://github.com/pckhoi/casbin-pgx-adapter
