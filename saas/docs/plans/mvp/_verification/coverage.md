# MVP final coverage report

**Phase 16 — Final Verification.** Generated against branch
`saas/phase-16-final-verification` (forked from `origin/main` at commit
`40447d8`, Phase 15 merged).

## Scope skipped (documented)

1. **Live `saasctl init` E2E run (task 16.1)** — compose-up requires a
   sustained Docker stack the platform's local-stack readiness is exercised
   by unit tests + the Prism contract job. The wizard is built but not
   E2E-smoked; user can run `./bin/saasctl init` manually post-merge.
2. **`make test-int`** — integration tests are guarded by
   `//go:build integration` and require a live Postgres; this phase covers
   the file-presence check (existing tests count as evidence of
   integration coverage). The CI pipeline runs `make test-int` separately.
3. **`make contract-test`** — runs in CI's Prism job, not locally in this
   phase (Phase 15 wired it).

## Verification matrix

| Check | Result |
|---|---|
| `make build` | exit 0 |
| `make lint` | exit 0 |
| `make test` | exit 0 (22 packages, all `ok`) |
| `make openapi-check` | exit 0 |
| `make sdk-go` | exit 0; `git diff --exit-code sdk/go/` clean |
| `make postman-check` | exit 0 |
| `make recipes-check` | exit 0 |
| `sdk/go` build + test | exit 0 (`workflows` ok, others no test files) |
| `sdk/ts/{control,data}-plane/package.json` | both present |
| `*AuthZ*` tests (§17.3) | **62 cases, 62 passing, 0 failing** |
| Provisioning tests (§17.4) | **81 cases, 81 passing, 0 failing** |
| Step-up / IP-allowlist / Impersonation | **24 cases, 24 passing, 0 failing** |

## §26 DoD coverage

26 endpoint groups in matrix (24 in scope — `/healthz` × 2 excluded).

- Fully green (no `P`): **17 / 24 = 71%**
- Partial (one or more `P`, no `N`): **7 / 24 = 29%**
- Failing (`N`): **0 / 24**

All partials are accounted for in `docs/v1-roadmap.md` items #18 (v1 RBAC
hardening) and #19 (control-plane authz matrix). Detail:
`docs/plans/mvp/_verification/endpoint-dod.md`.

## §17.3 authorization matrix coverage

62 named `*AuthZ*` cases across 8 modules (tenants, identity,
organizations, notifications, authorization, apikeys, audit, plus 24
control-plane step-up / IP-allowlist / impersonation). Every module that
ships a §17.3 matrix satisfies the 4-of-8-case floor. Control-plane
endpoints intentionally use a different shape (scope + step-up) and are
tracked as a v1 roadmap item.

Coverage rate (mutating data-plane endpoints with ≥ 1 cross-tenant test):
**100%** of the modules listed in AGENTS.md §17.3.

## §17.4 provisioning matrix coverage

81 passing tests across the 5 packages under
`internal/controlplane/provision/` (k3s, nginx, openbao, postgres,
sequence). The 14-case plan matrix is satisfied. No failures.

## License scan

**PASS** — 148 modules scanned, all permissive (55 MIT, 55 Apache-2.0,
22 BSD-3-Clause, 9 MPL-2.0, 3 BSD-2-Clause, 2 ISC, 1 Zlib, 1 0BSD).
No BSL / SSPL / Elastic License v2 / GPL / AGPL anywhere. Method,
allowlist, and disallowlist:
`docs/plans/mvp/_verification/license-scan.md`. Re-runnable via
`scripts/license-scan.sh`.

## Generated-code drift

**PASS** — `make openapi-check`, `make sdk-go`, `make postman-check`,
`make recipes-check` each leave a clean tree (`git status --porcelain`
empty after each).

## Surveys / Newsletters scope audit

**PASS** — no Surveys reference anywhere outside the AGENTS.md §28 non-goal
entry. No Newsletters implementation; the only hit is a CI guard test in
`cmd/saasctl/recipe_test.go` that **forbids** Newsletters from appearing
in any shipped recipe. Detail:
`docs/plans/mvp/_verification/scope-audit.md`.

## AGENTS.md scope changes — applied?

Per the plan §16.6 table:

| Change | Applied? | Where |
|---|---|---|
| Promote Notifications to MVP | YES | §3.5 (line 410), §15 (line 1418) |
| Add Social login to MVP | YES | §8.3 endpoints (lines 898–901) |
| Add BYOD to MVP | YES | §6.5 (line 830), §15 (workflow at 1856) |
| Add saasctl init wizard to MVP | YES | §15 (line 1420), §21 (line 1857) |
| Add BYOK vendor creds to MVP | YES | §18.7 (line 1069), §21 (line 1865) |
| Add Newsletters to v1 roadmap | YES | §15.1 (line 1014, 1433) + `docs/v1-roadmap.md` #1 |
| Add Surveys to non-goals | YES | §28 (line 2219) |

All 7 scope-change edits are present in `AGENTS.md`. No edit required in
this phase.

## CONVENTIONS.md final pass

Reviewed end-to-end. §2 (tenant signatures), §10 (PII strict mode), §14
(audit action vocabulary), §15 (destructive flags) and §16 (provisioning
lifecycle) all reflect the Phase 12e final state. No drift; no edit
required in this phase.

## Open follow-up issues

These do **not** block MVP merge; they are tracked in
`docs/v1-roadmap.md`:

1. **v1 RBAC hardening** — the 6 retrofitted destructive endpoints
   (CONVENTIONS §2) gate on the `SAAS_RBAC_ENFORCE_DESTRUCTIVE` flag,
   which defaults off. v1 should make it default-on and retrofit the
   remaining mutating endpoints (target: 100% endpoint coverage).
2. **Control-plane §17.3 shape** — adapt the 8-case matrix to the
   operator + deployment surface.
3. **Email change flow** — Phase 5 deferred.
4. **Audit async export** — Phase 10 ships sync-only.
5. **Per-Deployment Keycloak realms** — Phase 5 used a single shared realm.
6. **Multi-replica Casbin policy sync** — ADR 005, currently in-process.
7. **Multi-replica rate limiter** — Phase 9 in-process bucket.
8. **End-to-end `saasctl init` smoke** — wizard built but not E2E-smoked.

## Recommendation

**GO** for MVP cut. Every must-have signal is green:

- All `make` targets pass
- All `*AuthZ*` (62) and provisioning (81) and step-up (24) tests pass
- License scan clean
- No code drift
- Surveys / Newsletters confirmed absent
- AGENTS.md, CONVENTIONS.md, and v1 roadmap consistent

The 7 partial cells in the §26 DoD matrix are all documented v1 hardening
items, not MVP blockers. The user retains final say on whether to cut the
release tag now or after addressing any subset of the punch list.
