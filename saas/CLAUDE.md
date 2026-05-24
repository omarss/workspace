# saas/ — Claude working notes

Project-specific guidance for working in this repo. Read `AGENTS.md` first; it owns the
product thesis, architecture, API contract, modules, security posture, and roadmap. This
file is a small *how to work in this repo* layer.

Inherits from:

- `~/.claude/CLAUDE.md` — global user rules (PR template, atomic commits, no co-author, etc.)
- `../CLAUDE.md` — `workspace_personal/` orientation (homelab, nginx, k3s, geofence, gotchas)

---

## What this repo is

A SaaS **control plane** + **data plane** platform. The control plane provisions and
operates many isolated SaaS deployments; each deployment is a separate k3s namespace,
Postgres database, and nginx vhost on this homelab. See `AGENTS.md` §3 and §6 for the
full picture.

Two distinct API surfaces:

```text
Control Plane API   operator-only   (control.saas.omarss.net)
Data Plane API      per-deployment  (<env>.<project>.<base>.omarss.net)
```

---

## Where to look in AGENTS.md

| If you need… | Read |
|---|---|
| Who calls what API | §0 Personas |
| Why control plane vs data plane | §3.1 |
| Approved libraries and licenses | §3.5, §4.1, §4.4, §25.8 |
| Repo structure | §3.4 |
| HTTP API rules (idempotency, ETag, cursors, rate limit) | §5 |
| Homelab provisioning sequence and gotchas | §6 |
| Resource model | §7 |
| Endpoint surface | §8 |
| Event envelope and outbox | §9 |
| OpenAPI generator pins | §11 |
| MVP scope (hard cut) | §15 |
| Build order (vertical slice first) | §16 |
| Test layers required | §17 |
| Security rules | §18 |
| **Vault and encryption (OpenBao)** | §18.7 |
| Coding agent rules | §25 |
| Definition of done | §26 |
| Breaking change policy | §27 |

If your change affects one of these areas, update `AGENTS.md` in the same PR. The document
is the contract.

---

## Mandatory workflow

Apply on every change:

1. **Spec first.** If the change touches a public endpoint, update
   `openapi/control-plane.yaml` or `openapi/data-plane.yaml` *before* code. Run
   `make openapi-check` (lint + generator round-trip). The OpenAPI specs are the source of
   truth — code follows them, not the other way around.
2. **Makefile for everything.** Build, lint, test, generate, migrate, run, deploy. Per global
   rule. Never invoke `go`, `kubectl`, `helm`, `migrate`, or `oapi-codegen` directly outside
   the Makefile.
3. **Lint and test before pushing.** `make lint` and `make test` must pass locally. CI
   re-runs them; both must be green.
4. **License-check every new dep.** Per `AGENTS.md` §3.5 and §25.8: OSI-approved only,
   AGPL acceptable only when used as a standalone network service, BSL/SSPL forbidden. Add
   an ADR under `docs/adr/` for any non-obvious choice.
5. **Migrations are forward-only and rollback-compatible.** Every schema change is a new
   migration file, applied to every Deployment on upgrade, and backward-compatible with the
   previous image for one release so `deployment.rollback` works without a DB revert.
6. **Authorization tests are mandatory** for any tenant-bound endpoint — see `AGENTS.md`
   §17.3 for the required table. Skip them and CI fails the security review.
7. **Audit events for security-sensitive actions** — see `AGENTS.md` §18.3 for the list.
8. **Never log secrets.** The redactor list lives in `internal/platform/log/redact.go`.
   Add to it when a new sensitive field is introduced.
9. **Public API breakage is forbidden** without an ADR + a `/v2` path. Per `AGENTS.md` §27.

---

## Vault (OpenBao) — what to remember

Per `AGENTS.md` §18.7. Quick reference:

```text
Sensitive fields use envelope encryption (DEK + OpenBao Transit wrap).
Each Deployment has its own transit key. Verify kid == deployment_id before decrypt.
API key secrets: argon2id hash AND envelope-encrypt the prefix-search index.
Never store DEK plaintext anywhere.
Never log Vault tokens, unseal shares, or wrapped DEKs.
Root token is revoked after setup; use AppRole or OIDC short-lived tokens for ops.
PII fields declared in OpenAPI with `x-pii: true` are encryption-required at handler
   boundaries — codegen enforces the call site.
```

When adding a new sensitive field:

1. Mark it `x-pii: true` and/or `x-sensitive: true` in the OpenAPI schema.
2. Regenerate handler types.
3. Add to the redactor list.
4. The codegen template will refuse to compile if the handler stores the field without
   calling the envelope encryptor.

---

## Things that are easy to get wrong here

1. **nginx `apply-nginx` clobbers certbot blocks** (workspace `CLAUDE.md`). The control plane
   therefore patches its own per-deployment vhost and runs `nginx -s reload` — it never calls
   `make apply-nginx` from the homelab repo. Mirror the homelab pattern (pre-certbot vhost
   files) but apply incrementally.
2. **Tenant context comes from the JWT/API key**, not headers (`AGENTS.md` §5.1). Do not
   add reads of `X-Tenant-Id` anywhere in handlers. The only sanctioned header is
   `X-Acting-Tenant-Id` and it requires the `tenants.impersonate` scope.
3. **Audit table is append-only at the DB level.** The Postgres app role has no UPDATE or
   DELETE grant on `audit_event`. If a test needs a clean state, rebuild the test DB.
4. **Cursor schema is versioned (`v` field).** Bumping it requires returning 410 Gone for
   old cursors, not silently re-interpreting them.
5. **Idempotency window is 24 h with body-hash conflict detection** — same key + different
   body returns 422, not 200 (Stripe-style). Don't optimize this into a 200.
6. **Deployment rollback does NOT roll back the DB.** Migrations must remain backward-
   compatible with the previous image for at least one release.
7. **OpenAPI generator versions are pinned** (`AGENTS.md` §11.1). Don't `go install ...@latest`
   for a generator; bump the pin in the Makefile and rerun the round-trip check.
8. **Each Deployment has its own DB on the host Postgres.** Do not write code that connects
   to "the platform DB" generically — handlers always get a per-Deployment connection pool.
9. **k3s namespace isolation is real.** No NetworkPolicy gaps: a data-plane pod must not be
   able to reach another deployment's services. Test before assuming.
10. **MVP scope is a hard cut** (`AGENTS.md` §15). Billing, entitlements, webhooks,
    notifications, files, feature flags, analytics, and the Next.js starter are explicitly
    deferred. Do not implement them without an ADR promoting them from v1 roadmap.

---

## Repo entry points (planned)

```text
AGENTS.md              full product + architecture spec (the contract)
CLAUDE.md              this file
openapi/               control-plane.yaml, data-plane.yaml — source of truth
cmd/                   controlplane/, dataplane/, migrate/, saasctl/
internal/              Go source, hexagonal per module (§3.4)
migrations/            controlplane/, dataplane/ — forward-only
deploy/                k3s/, nginx/ — templates rendered per Deployment
sdk/                   ts/, go/ — generated + handwritten workflow wrappers
docs/adr/              architecture decisions, including license rationale
Makefile               every build/lint/test/run/deploy target
```

---

## When unsure, ask

Global rule applies especially here. Stop and ask before:

- a breaking change to any public endpoint
- adding or removing a dependency (or bumping a generator pin)
- modifying the provisioning sequence in `AGENTS.md` §6.2
- anything touching Vault, RBAC, audit, or tenant isolation
- destructive operations on a Deployment, its DB, its k3s namespace, or its vhost
- importing/deleting a Keycloak realm or client (global rule)
- dropping tables / databases / schemas (global rule)

Improper workarounds and rabbit holes are forbidden by the global rule. If a clean fix is
not obvious, write the question down and ask.

---

## Style

- Comments explain *why*, not *what* (global rule).
- One atomic commit per completed feature stage; push after each (global rule).
- PRs follow `.github/` template, add `ready` label, monitor CI (global rule).
- No emojis in code, commits, or PR text (global rule).
- No Co-Authored-By Claude / Codex lines (global rule).
- Lowercase commit titles ≤ 50 chars (global rule).
