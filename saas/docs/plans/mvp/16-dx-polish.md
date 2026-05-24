# Phase 15 — Developer Experience Polish (saasctl init, Static Walkthrough, Postman, Prism in CI, Recipes)

> **Goal**: Ship the developer-experience surface that turns the platform from "running" to "approachable." Land the full `saasctl init` wizard (compose-up + bootstrap + first tenant + first API key). Author the static-HTML walkthrough at `docs/walkthrough/` (no framework — plain HTML + curl examples per persona). Export a Postman collection from the OpenAPI specs. Wire prism mock server into CI as a contract-test target. Author the 10 §21 first-class workflow recipes under `docs/recipes/` and expose them via `saasctl recipe <name>`.
>
> **Why now**: §16 puts DX polish last in the "remaining MVP modules" set. After Phase 14 SDK, every API surface is consumable by both TS and Go; this phase makes the platform learnable. AGENTS.md §21 explicitly lists these DX requirements; Phase 15 fulfills them.
>
> **What this phase does NOT do**: No commercial docs site (out of MVP; v1 may use Docusaurus). No video walkthroughs. No interactive playground. No customer-facing dashboards (out of MVP; `novu-web` and `saasctl` cover operator needs).
>
> **Maps to AGENTS.md**: §15 (DX bullet), §21 (entire section). 00-master.md scope-change row for `saasctl init` (ADR 016).
>
> **Estimated subagent sessions**: 2-3 (one for saasctl init full impl + ADR 016; one for walkthrough + Postman + recipes; one for prism CI wiring + saasctl recipe command).

---

## Pre-flight

1. AGENTS.md §15, §21.
2. 00-master.md ADR 016 (saasctl init wizard).
3. Phases 1-14 complete; in particular Phase 12e (real provisioning) and Phase 14 (Go SDK).
4. `01-foundations.md` §16 (OpenAPI tooling pins).

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| `saasctl init` UX | Interactive prompts (with `--config init.yaml` for non-interactive); 8 steps; idempotent re-run | Pure config file (refused — bad first-run UX) |
| Walkthrough format | Static HTML (no JS framework) + plain curl examples + screenshots | Markdown rendered by GitHub (refused — needs to work offline) |
| Postman export | Run `openapi-generator-cli generate -g postman-collection` per spec | Hand-curated (refused — drift) |
| Prism in CI | One step in `gate` job runs `make contract-test` against each spec + a recorded fixtures set | Local-only (refused — drift creeps in) |
| Recipes | Markdown files; one per §21 workflow; saasctl prints them with `recipe <name>` | Generated (refused — needs human voice) |
| Recipes content | Each recipe has: prerequisites, step-by-step CLI + SDK + curl, common pitfalls | Just CLI (refused — multi-language users) |
| `saasctl init` first-tenant policy | Auto-create tenant "default" + first user "admin@<host>" + admin role + API key. Output the secret once. | Skip + leave for user (refused — first-run friction) |

---

## Tasks

### 15.1 saasctl init — full impl

`cmd/saasctl/init.go`:

```go
var initCmd = &cobra.Command{
    Use:   "init",
    Short: "Bootstrap a local SaaS stack end-to-end.",
    Long: `Runs an 8-step bootstrap:
  1. compose-up (postgres, openbao, keycloak, mailhog, novu stack, prism mocks)
  2. wait for healthchecks
  3. openbao-init (transit, kv, k8s/approle auth, audit)
  4. realm import (saas-data-local, operators)
  5. migrate (control plane + data plane)
  6. operator login (PKCE)
  7. deployment create "default/dev"
  8. report bootstrap API key + URLs

Re-running is idempotent; existing artifacts are reused.`,
    RunE: runInit,
}

func runInit(cmd *cobra.Command, args []string) error {
    cfg := loadInitConfig(cmd)
    steps := []initStep{
        {"compose-up",     runComposeUp},
        {"wait-healthy",   waitHealthy},
        {"openbao-init",   runOpenBaoInit},
        {"realm-import",   runRealmImport},
        {"migrate",        runMigrate},
        {"operator-login", runOperatorLogin},
        {"provision",      runProvision},
        {"summary",        printSummary},
    }
    for _, s := range steps {
        fmt.Printf("→ %s ... ", s.name)
        if err := s.fn(cmd.Context(), cfg); err != nil {
            fmt.Println("FAIL")
            return fmt.Errorf("%s: %w", s.name, err)
        }
        fmt.Println("OK")
    }
    return nil
}
```

The init config (defaulted to `~/.saas/init.yaml`):

```yaml
project: default
environment: dev
image_version: v0.3.1
operator:
  email: admin@localhost
  display_name: Admin
  ip_allowlist: []
notifications:
  default_channel:
    provider: smtp
    name: mailhog
    smtp_host: mailhog
    smtp_port: 1025
    smtp_from: noreply@example.test
```

`saasctl init --config init.yaml --yes` runs unattended.

### 15.2 ADR 016

`docs/adr/016-saasctl-init-wizard.md`:

```markdown
# ADR 016 — saasctl init wizard scope + idempotency

## Status
Accepted (2026-05-24).

## Context
First-run UX is critical: the platform's value-prop falls flat if the operator
has to wire 8 systems before /healthz works. §21 mandates an "easy setup"
flow; the scope-change row in 00-master.md elevates this to MVP.

## Decision
saasctl init runs an 8-step bootstrap that ends with a usable platform:
1. compose-up
2. wait-healthy
3. openbao-init
4. realm-import (saas-data-local + operators)
5. migrate
6. operator-login (PKCE; opens browser)
7. provision default/dev
8. summary (bootstrap secret + URLs)

Idempotent: each step checks for existing state and is a no-op when already
done. Failure leaves the system in the state of the last successful step;
re-running picks up.

## Consequences
+ A new operator goes from `git clone` to a working platform in < 10 minutes.
+ The recipes can assume a known starting state.
- The init flow couples to compose.yaml; changes to service set require an
  init update.
- The operator-login step opens a browser; SSH-only operators use the
  `--operator-token-file` override to skip.
```

### 15.3 Static walkthrough

`docs/walkthrough/`:

```text
docs/walkthrough/
  index.html        # landing page; persona switcher; install instructions
  styles.css        # minimal; ~3 KB
  operator.html     # operator persona walkthrough
  builder.html      # product builder persona walkthrough
  tenant-admin.html # tenant admin walkthrough
  end-user.html     # end-user walkthrough
  machine.html      # machine client (API key) walkthrough
  screenshots/      # PNG screenshots referenced inline
```

`index.html` (sketch):

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SaaS Platform — Walkthrough</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header>
    <h1>SaaS Platform — Get Started</h1>
    <p>5-minute walkthrough. Pick your persona.</p>
  </header>
  <nav>
    <a href="operator.html">Operator</a>
    <a href="builder.html">Product Builder</a>
    <a href="tenant-admin.html">Tenant Admin</a>
    <a href="end-user.html">End User</a>
    <a href="machine.html">Machine Client</a>
  </nav>
  <main>
    <h2>Install</h2>
    <pre><code>git clone https://github.com/omarss/saas.git
cd saas
make build
./bin/saasctl init</code></pre>
    <p>This runs <a href="../adr/016-saasctl-init-wizard.md">saasctl init</a>
       (8 steps, idempotent). End state: a real Deployment + bootstrap API
       key + URLs.</p>
  </main>
</body>
</html>
```

Each persona page walks through 5-7 concrete tasks with verbatim curl + saasctl examples.

### 15.4 Postman collection

`make postman` target:

```make
postman:
	$(OPENAPI_GEN) generate -i /work/openapi/_generated/control-plane.yaml \
	    -g postman-collection -o /work/sdk/postman/control-plane \
	    --additional-properties=collectionName=SaaS Control Plane API
	$(OPENAPI_GEN) generate -i /work/openapi/_generated/data-plane.yaml \
	    -g postman-collection -o /work/sdk/postman/data-plane \
	    --additional-properties=collectionName=SaaS Data Plane API
```

Commit `sdk/postman/control-plane/postman.json` + `sdk/postman/data-plane/postman.json`. Add to `openapi-check` so drift is caught.

### 15.5 Prism in CI

`.github/workflows/ci.yml` addition:

```yaml
  contract:
    needs: gate
    runs-on: ubuntu-latest
    services:
      postgres: { ... existing pattern ... }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: "1.24" }
      - run: make build
      - run: ./bin/dataplane &
      - run: |
          docker run --rm -d --name prism -p 4011:4011 \
            -v $PWD/openapi:/work/openapi:ro stoplight/prism:5.15.10 \
            proxy /work/openapi/_generated/data-plane.yaml http://host.docker.internal:9090 --errors
      - run: ./scripts/replay-contract-fixtures.sh
```

`scripts/replay-contract-fixtures.sh` walks `test/fixtures/**/*.http` and replays each against prism + verifies response schema match.

### 15.6 Recipes

`docs/recipes/`:

```text
docs/recipes/
  provision-deployment.md
  create-tenant.md
  invite-member.md
  assign-role.md
  check-authorization.md
  create-api-key.md
  view-audit-events.md
  send-notification.md
  link-social-provider.md
  attach-custom-domain.md
```

Each recipe follows a template:

```markdown
# Recipe: <Name>

## When to use
<one paragraph>

## Prerequisites
- <list>

## CLI
$ saasctl <command> ...
# expected output

## curl
$ curl -X POST ... \
    -H "Authorization: Bearer $TOKEN" ...
# expected JSON

## TS SDK
import { ... } from "@omarss/saas-dataplane-sdk";
...

## Go SDK
import "github.com/omarss/saas/sdk/go/workflows"
...

## Common pitfalls
- <thing>: cause + fix
```

`saasctl recipe <name>` reads `docs/recipes/<name>.md` (or fuzzy-matches) and prints to stdout (with optional `--less` to pipe through a pager).

### 15.7 Health screen in saasctl

`saasctl status` displays a one-screen summary:

```text
SaaS Platform — Status

Compose stack:
  postgres   ✓ healthy
  keycloak   ✓ healthy
  openbao    ✓ healthy (unsealed)
  mailhog    ✓ healthy
  novu-api   ✓ healthy
  ...

Deployments:
  dep_01HXAA... default/dev   active   v0.3.1   https://dev.default.saas.omarss.net
  dep_01HXBB... mvp/prod      active   v0.3.1   https://prod.mvp.saas.omarss.net

Operators:
  op_01HX...   omar@omarss.net   MFA: ✓   Allowlist: any
```

### 15.8 Tests

`init_test.go`:

- Run init twice; second is no-op (all steps detect existing state).
- Run init with --config init.yaml; matches expected output.
- Skip operator-login when `--operator-token-file` supplied.

`recipes_test.go`:

- Every §21 workflow has a recipe file present.
- `saasctl recipe <name>` outputs valid markdown.
- Recipe content references actual API operationIds (lint via grep).

`prism_contract_test.sh`:

- All fixtures replay green.

### 15.9 Commits

```bash
git add cmd/saasctl/init.go cmd/saasctl/recipe.go cmd/saasctl/status.go
git commit -m "implement saasctl init recipe and status"

git add docs/walkthrough/
git commit -m "add static html walkthrough per persona"

git add sdk/postman/ Makefile
git commit -m "export postman collections from openapi"

git add .github/workflows/ci.yml scripts/replay-contract-fixtures.sh
git commit -m "wire prism contract test in ci"

git add docs/recipes/
git commit -m "author first class workflow recipes"

git add docs/adr/016-saasctl-init-wizard.md
git commit -m "add saasctl init adr"
```

---

## Verification checklist

```bash
# 1. Init E2E.
$ make compose-down
$ docker volume rm $(docker volume ls -q)        # nuke state for a true first-run
$ ./bin/saasctl init
# Expected: 8 steps, all OK. Final output prints bootstrap secret + URLs.

# 2. Re-run init is idempotent.
$ ./bin/saasctl init
# Expected: 8 steps, all OK with "(already done)" markers.

# 3. Walkthrough renders.
$ python3 -m http.server -d docs/walkthrough 8000 &
$ curl -sf http://localhost:8000/index.html
$ curl -sf http://localhost:8000/operator.html
# Visual inspection in browser.

# 4. Postman.
$ make postman
$ ls sdk/postman/control-plane/postman.json sdk/postman/data-plane/postman.json
# Optional: import into Postman desktop.

# 5. Prism contract test.
$ make contract-test
# Expected: all fixtures green.

# 6. Recipes.
$ ./bin/saasctl recipe create-tenant
$ ./bin/saasctl recipe provision-deployment
$ ls docs/recipes/ | wc -l
# Expected: 10

# 7. Status.
$ ./bin/saasctl status
# Expected: one-screen status with all components.

# 8. CI green on a fresh PR.
$ # Open a no-op PR; ensure the contract job runs and passes.
```

---

## Anti-pattern guards

- **NEVER** add a JavaScript framework to the walkthrough. Plain HTML + CSS. The user opening `index.html` from a tarball must see something useful.
- **NEVER** generate recipes from the OpenAPI spec. They have a human voice that codegen can't replicate.
- **NEVER** ship the Postman collection without regenerating it on spec change. CI catches drift.
- **NEVER** require an external network for `saasctl init`. compose pulls images once; subsequent runs are offline.
- **NEVER** print the bootstrap secret to a file unless the user explicitly passes `--write-secret-file <path>`. STDOUT only by default.
- **NEVER** suggest a workflow that bypasses Idempotency-Key in any recipe.

---

## Open questions

1. **Walkthrough hosting.** Default: served by `python3 -m http.server` in dev; in prod, can be served from `claw.omarss.net/saas-docs/` (separate static site). Out of MVP to deploy.
2. **Localization.** All docs/recipes in English for MVP. Arabic translation in v1 (KSA differentiator).
3. **Postman environment.** Default: `sdk/postman/environment.json` template with `{{control_url}}`, `{{operator_token}}`. Commit alongside collections.
4. **`saasctl status` polls in real-time?** Default: one-shot. v1 may add `--watch`.

---

## Phase 15 — Definition of done

- [ ] `saasctl init` 8-step wizard works end-to-end + is idempotent
- [ ] `docs/walkthrough/` 6 HTML pages + screenshots
- [ ] `sdk/postman/` exports for both planes; regen target in Makefile
- [ ] Prism contract test in CI gate
- [ ] `docs/recipes/` 10 markdown files covering every §21 workflow
- [ ] `saasctl recipe <name>` prints the recipe
- [ ] `saasctl status` shows compose + deployments + operators
- [ ] ADR 016 committed
- [ ] All Phase 2-14 tests still green
- [ ] PR template, `ready` label, CI green

---

End of Phase 15. Next: `17-final-verification.md`.
