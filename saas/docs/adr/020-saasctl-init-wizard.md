# ADR 020 — saasctl init wizard: scope, idempotency, and PKCE deferral

## Status

Accepted (2026-05-27).

Note on numbering: Phase 15's plan (`docs/plans/mvp/16-dx-polish.md`)
nominally calls this ADR "016". That number was already taken by ADR
016 — *OpenBao shared audit device with per-policy tagging* (accepted
during Phase 12d). The wizard ADR therefore takes the next available
slot: ADR 020.

## Context

First-run UX is the cheapest place to lose an operator. AGENTS.md §15
elevates DX polish to MVP-scope, and AGENTS.md §21 lists "easy setup"
as a first-class workflow recipe. The platform has eight independent
moving parts that all must come up before the first `/healthz` returns
200:

```text
docker compose                 (postgres, openbao, keycloak, mailhog, novu, prism)
docker compose --wait healthcheck pass
openbao engines + auth methods (transit, kv-v2, approle, kubernetes auth)
keycloak operators realm       (imported via --import-realm)
control-plane + data-plane migrations
operator bearer token          (PKCE against operators realm)
control-plane.CreateDeployment (first Deployment, project + environment)
bootstrap API key              (single-use secret, hashed with argon2id)
```

Wiring those by hand is a ~30-minute exercise and gates every other
workflow recipe (§21). Without an `init` command the platform's
value-prop collapses on encounter.

## Decision

`saasctl init` runs an 8-step bootstrap that ends with a usable
platform:

1. **compose-up**     — delegate to `make compose-up` (runs docker
   compose with `--wait`)
2. **wait-healthy**   — re-check `docker compose ps` health (belt and
   braces against flaky environments)
3. **openbao-init**   — delegate to `make openbao-init` (idempotent
   `bao secrets enable …` calls)
4. **realm-import**   — delegate to `make operators-realm-import`
   (one-shot Keycloak container with the operators-realm.json)
5. **migrate**        — delegate to `make migrate` (both planes)
6. **operator-login** — accept a pre-obtained bearer token via
   `--operator-token-file` (cf. *Deferred* below). Without that flag,
   emit `skipped (PKCE deferred — see ADR 020)` and continue.
7. **provision**      — POST to `/control/v1/deployments` to create
   the first Deployment (project + environment + image_version).
   Re-runs that find a matching Deployment short-circuit to
   "already done".
8. **summary**        — print Deployment URLs, service endpoints, and
   the bootstrap API key inside a fenced "COPY THIS NOW" banner.

Each step is its own file (`cmd/saasctl/init_<step>.go`) so each can
be exercised independently in tests. The orchestrator simply iterates
through the slice; failure aborts, success advances.

### Idempotency

Each step is a no-op when the prior state is already correct:

| Step             | "Already done" detection                                  |
|------------------|-----------------------------------------------------------|
| compose-up       | `docker compose ps --format json` returns all healthy     |
| wait-healthy     | polls the same check until healthy or 90 s deadline       |
| openbao-init     | each `bao … enable` ends in `\|\| true` (target Makefile) |
| realm-import     | one-shot Keycloak container is a no-op when realm exists  |
| migrate          | `golang-migrate` tracks schema version                    |
| operator-login   | a `~/.saas/credentials.json` short-circuits the step      |
| provision        | GET `/control/v1/deployments` filtered on project+env     |
| summary          | always runs (read-only)                                   |

The wizard NEVER prompts on re-run when the prior state already
satisfies the target; this matches the global rule about
"never re-do work the user already paid for".

### PKCE deferral

The real browser-based PKCE flow against the operators realm requires
the gocloak admin client (Phase 13 ships the realm import + step-up
MFA policies; the runtime PKCE client lands later when we wire the
operator session-management endpoints).

In the interim:

- `--operator-token-file <path>` accepts a pre-obtained bearer token
  (issued, for example, by the existing `kcadm.sh get-token` runbook
  step) and writes it to `~/.saas/credentials.json` for subsequent
  saasctl commands to pick up.
- Without the flag, the wizard logs `skipped (PKCE deferred — see ADR
  020)` and proceeds. The provision step falls back to the
  `X-Mock-Operator-*` headers that the local-dev control plane
  already accepts (Phase 11 dev pattern).
- Production rollout will replace the fallback with a hard 401 once
  the real PKCE flow ships; the data-plane / control-plane contracts
  do not change.

This deferral is explicitly logged in the step output so an operator
can never silently mistake "no real auth" for "auth happened".

### Bootstrap-secret handling

The bootstrap API key secret is, by design, only retrievable on the
original POST `/control/v1/deployments`. The wizard:

- prints the secret to STDOUT inside a fenced "COPY THIS NOW" banner;
- writes nothing to disk unless `--write-secret-file <path>` is set;
- when that flag is set, appends to the file with `0600` permissions
  so historical re-runs accumulate as an operator-private audit log;
- never reflects the secret in any log line, metric, or audit event
  emitted by saasctl itself (the server-side `api_key.created`
  audit event records only the prefix per ADR 008).

This honours global rule "Never log secrets" and the Phase 15
anti-pattern guard "STDOUT only by default".

### Configuration source

The wizard reads `~/.saas/init.yaml` (override: `--config <path>`)
for defaults. The YAML schema is intentionally tiny:

```yaml
project: default
environment: dev
image_version: v0.3.1
operator:
  email: admin@localhost
  display_name: Admin
```

CLI flags override file values; defaults fill in anything still
blank. We use `gopkg.in/yaml.v3` (already an indirect dep, now
promoted) rather than viper to keep the wizard's dependency surface
small. Viper adds ~600 LOC of config-discovery machinery the wizard
does not need.

## Consequences

Positive:

- A new operator goes from `git clone` to a working platform in
  < 10 minutes. The recipes (`docs/recipes/*`) can assume a known
  starting state.
- The 8 steps map 1:1 to verifiable Make targets, so the wizard is
  thin orchestration over already-tested machinery.
- Re-running is safe — useful for "compose just went down, re-bootstrap".

Negative / risks:

- The flow couples to `compose.yaml`; changes to the service set
  require an init update.
- The operator-login step is a stub until the PKCE client lands.
  Operators must use `--operator-token-file` for now; this is
  documented in `--help` and printed in the step status.
- The wizard reads `docker compose ps --format json`; the output
  schema is fairly stable but a docker / compose version pin would
  protect against future drift. Tracked as a follow-up.

## Alternatives considered

- **Pure config-file (no prompts).** Refused — bad first-run UX. Plan
  decision-row reaffirmed.
- **Re-implement the OpenBao / Keycloak / Postgres bootstrap in Go.**
  Refused — would double the wizard's surface area, drift from the
  Make-based runbooks, and re-introduce hand-rolled
  bao / keycloak / migrate clients. Cross-cutting constraint #3
  (orchestrator brief) explicitly rejected this.
- **Use `viper`.** Refused — out of proportion for a five-field YAML
  schema. Adopting yaml.v3 (already in `go.sum` as an indirect dep)
  is enough.
- **Persist the bootstrap secret to disk by default.** Refused — the
  secret is one-shot by design (ADR 008); persisting it broadens the
  blast radius of a compromised dev machine.

## References

- AGENTS.md §15 (DX as MVP), §21 (recipes inventory)
- ADR 008 (API keys / argon2id / envelope prefix index)
- ADR 016 (OpenBao shared audit device — distinct from this ADR)
- ADR 019 (Operators realm MFA step-up)
- Plan: `docs/plans/mvp/16-dx-polish.md`
