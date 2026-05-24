# Phase 14 — Go SDK (Generated Client + Handwritten Workflow Wrappers)

> **Goal**: Ship the Go SDK under `sdk/go/` with separate sub-modules for control plane and data plane. Generate the typed HTTP client via `oapi-codegen` in client mode against both specs. Author handwritten workflow wrappers that compose multiple calls into the §21 first-class workflows: `provision_deployment`, `create_tenant`, `invite_member`, `check_authorization`, `create_api_key`, `list_audit_events`, `send_notification`, `link_social_provider`, `attach_custom_domain`, `start_impersonation`. Publish as a separate Go module (`sdk/go/go.mod`).
>
> **Why now**: §16 puts the Go SDK after operator MFA + impersonation because the SDK exposes those flows. The TS SDK has been kept in sync per phase (mandated by §26 DoD); the Go SDK was deferred to one consolidated phase to avoid churn. After this phase, machine clients (the §0 "machine" persona) have a first-class Go SDK option.
>
> **What this phase does NOT do**: No Python / Java / Rust SDKs (out of scope; §28). No SDK auto-publish to a Go proxy (operators import directly via `go get github.com/omarss/saas/sdk/go/...`). No retry/backoff library auto-wired (consumers compose).
>
> **Maps to AGENTS.md**: §10 (SDK strategy), §21 (first-class workflows). `01-foundations.md` §2 (oapi-codegen client mode).
>
> **Estimated subagent sessions**: 2 (one for generated clients + module wiring; one for workflow wrappers + tests).

---

## Pre-flight

1. AGENTS.md §10, §21.
2. `01-foundations.md` §2 (oapi-codegen client config).
3. Phases 2-13 complete.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Module structure | Separate sub-module `sdk/go/` with its own `go.mod`; sub-packages `controlplane/`, `dataplane/`, `workflows/` | Mono-module (refused — pulls in all of saas) |
| Client codegen | oapi-codegen `generate: client: true, models: true` per plane | Manual (refused) |
| HTTP transport | `http.DefaultClient` overridable; SDK accepts `*http.Client` | Wrap with retry (refused — let the consumer choose) |
| Idempotency-Key | SDK auto-generates a ULID prefix `idem_` per POST/PATCH unless caller passes one | Always require caller to supply (refused — boilerplate); never auto (refused — bypassable) |
| ETag handling | SDK exposes `If-Match` as a typed param on PATCH/DELETE methods | Auto-pull from previous GET (refused — too magical) |
| Workflow wrappers | Handwritten; one file per §21 workflow | Generated (refused — workflows are multi-call orchestration) |
| Versioning | `v0.1.0` initial tag; `sdk/go/v1` path when v1 lands (Go module semver) | Single tag (refused — couples to platform release cadence) |
| Auth | Bearer token via `Configuration.AccessToken`; refresh handled by caller (or by the helper `oidc.RefreshingClient` in `workflows/`) | Built-in OIDC (refused — too opinionated) |

---

## Tasks

### 14.1 oapi-codegen client configs

`.oapi-codegen-controlplane-client.yaml`:

```yaml
package: controlplaneclient
output: sdk/go/controlplane/client.gen.go
generate:
  models: true
  client: true
output-options:
  skip-fmt: false
  skip-prune: false
  overlay:
    path: openapi/overlays/30-downgrade.yaml
```

Same shape for `dataplaneclient` writing to `sdk/go/dataplane/client.gen.go`.

Makefile additions:

```make
sdk-go: openapi-overlay
	$(OAPI_CODEGEN) -config .oapi-codegen-controlplane-client.yaml openapi/_generated/control-plane.yaml
	$(OAPI_CODEGEN) -config .oapi-codegen-dataplane-client.yaml    openapi/_generated/data-plane.yaml
	cd sdk/go && go mod tidy && go build ./...
```

Wire `sdk-go` into `openapi-check` so drift is caught.

### 14.2 sdk/go/go.mod

```go
module github.com/omarss/saas/sdk/go

go 1.24

require (
    github.com/oapi-codegen/runtime v1.2.0
    github.com/oklog/ulid/v2 v2.1.1
    github.com/coreos/go-oidc/v3 v3.x.x   // for the OIDC helper in workflows/
)
```

The SDK module is independent of the platform's `go.mod`; users `go get github.com/omarss/saas/sdk/go/controlplane` directly.

### 14.3 Idempotency helper

`sdk/go/internal/idem/key.go`:

```go
package idem

import "github.com/oklog/ulid/v2"

func New() string { return "idem_" + ulid.Make().String() }
```

Consumed by every workflow wrapper that issues POST/PATCH.

### 14.4 Workflow wrappers

`sdk/go/workflows/`:

```text
sdk/go/workflows/
  provision_deployment.go
  create_tenant.go
  invite_member.go
  check_authorization.go
  create_api_key.go
  list_audit_events.go
  send_notification.go
  link_social_provider.go
  attach_custom_domain.go
  start_impersonation.go
  verify_audit_integrity.go
  oidc_client.go           # RefreshingClient helper
  workflows_test.go
```

Example — `provision_deployment.go`:

```go
package workflows

import (
    "context"

    cp "github.com/omarss/saas/sdk/go/controlplane"
    "github.com/omarss/saas/sdk/go/internal/idem"
)

// ProvisionDeployment encapsulates the create + ledger-wait + bootstrap-secret
// flow. Returns the deployment, bootstrap API key id + secret, and a CLI-style
// summary string. The caller MUST persist the secret immediately; this helper
// only returns it once.
func ProvisionDeployment(ctx context.Context, c *cp.Client, in ProvisionInput) (Provisioned, error) {
    body := cp.CreateDeploymentRequest{
        ProjectSlug:     in.ProjectSlug,
        EnvironmentSlug: in.EnvironmentSlug,
        ImageVersion:    in.ImageVersion,
        Modules:         in.Modules,
        Region:          ptr(in.Region),
        DataResidency:   ptr(in.DataResidency),
        Metadata:        in.Metadata,
    }
    res, err := c.CreateDeploymentWithResponse(ctx, &cp.CreateDeploymentParams{IdempotencyKey: idem.New()}, body)
    if err != nil { return Provisioned{}, err }
    if res.StatusCode() != 201 {
        return Provisioned{}, errFromBody(res.Body)
    }
    return Provisioned{
        Deployment:        res.JSON201.Data,
        BootstrapAPIKeyID: res.JSON201.BootstrapApiKey.Id,
        BootstrapSecret:   res.JSON201.BootstrapApiKey.Secret,
        BootstrapTenantID: res.JSON201.BootstrapApiKey.TenantId,
    }, nil
}

type ProvisionInput struct {
    ProjectSlug     string
    EnvironmentSlug string
    ImageVersion    string
    Modules         []string
    Region          string
    DataResidency   string
    Metadata        map[string]string
}

type Provisioned struct {
    Deployment        cp.Deployment
    BootstrapAPIKeyID string
    BootstrapSecret   string
    BootstrapTenantID string
}
```

Example — `attach_custom_domain.go`:

```go
// AttachCustomDomain bundles Attach + Verify + a small DNS-TXT-check loop.
func AttachCustomDomain(ctx context.Context, c *cp.Client, depID, domain string, opts AttachDomainOptions) (cp.DeploymentDomain, error) {
    res, err := c.AttachDeploymentDomainWithResponse(ctx, depID,
        &cp.AttachDeploymentDomainParams{IdempotencyKey: idem.New()},
        cp.AttachDomainRequest{Domain: domain})
    if err != nil || res.StatusCode() != 201 { return cp.DeploymentDomain{}, ... }
    dd := res.JSON201.Data
    // Optional: poll DNS until the TXT record appears (caller may choose to wait).
    if opts.WaitForDNS {
        if err := waitDNSTXT(ctx, dd.VerificationRecord.RecordName, dd.VerificationRecord.RecordValue, opts.PollInterval, opts.Timeout); err != nil {
            return dd, err
        }
        v, err := c.VerifyDeploymentDomainWithResponse(ctx, depID, dd.Id, &cp.VerifyDeploymentDomainParams{IdempotencyKey: idem.New()})
        if err != nil || v.StatusCode() != 200 { return dd, ... }
        return v.JSON200.Data, nil
    }
    return dd, nil
}
```

Example — `send_notification.go`:

```go
// SendNotification triggers a workflow and (optionally) polls until the
// notification reaches a terminal status.
func SendNotification(ctx context.Context, c *dp.Client, in SendNotificationInput) (dp.Notification, error) {
    res, err := c.SendNotificationWithResponse(ctx,
        &dp.SendNotificationParams{IdempotencyKey: idem.New()},
        dp.SendNotificationRequest{
            WorkflowName: in.WorkflowName,
            To:           dp.SendNotificationRequestTo{UserId: in.ToUserID},
            Payload:      in.Payload,
        })
    if err != nil || res.StatusCode() != 202 { return dp.Notification{}, ... }
    notif := res.JSON202.Data
    if !in.WaitForTerminal { return notif, nil }
    // Poll /v1/notifications/{id} until sent/delivered/failed.
    return pollNotificationStatus(ctx, c, notif.Id, in.PollInterval, in.Timeout)
}
```

Example — `oidc_client.go`:

```go
// NewRefreshingHTTPClient returns an *http.Client that automatically refreshes
// the access token using a stored refresh token. Used by saasctl-style apps.
func NewRefreshingHTTPClient(ctx context.Context, cfg OIDCConfig) (*http.Client, error) { ... }
```

### 14.5 Tests — `workflows_test.go`

For each workflow: unit-test against a mock HTTP server (`net/http/httptest`). Cases:

- Happy path → returns expected envelope.
- API returns 422 → wrapped error with problem-type.
- Idempotent retry: second call with same body returns cached response.
- Cross-tenant error → distinguishable problem-type at the call site.

Integration test (tagged): against a live `compose up` + provisioned dep. Tests:

- `ProvisionDeployment` E2E
- `CreateTenant` → `InviteMember` → `AcceptInvitation` (simulated) → `AssignMemberRole`
- `CreateAPIKey` → use it → `RotateAPIKey` → use new + old
- `SendNotification` → mailhog received
- `LinkSocialProvider` → URL returned
- `AttachCustomDomain` (dry-run mode without real DNS)
- `VerifyAuditIntegrity` → green

### 14.6 SDK example program

`sdk/go/examples/quickstart/main.go`:

```go
// Demonstrates the §21 first-class workflows in one program.
// Run after `make compose-up && make migrate && saasctl operator login`.
func main() {
    ctx := context.Background()
    cp, _ := controlplane.NewClientWithResponses("https://control.saas.omarss.net", controlplane.WithRequestEditorFn(bearerEditor(opToken)))
    prov, _ := workflows.ProvisionDeployment(ctx, cp, workflows.ProvisionInput{ProjectSlug: "demo", EnvironmentSlug: "dev", ImageVersion: "v0.3.1"})
    fmt.Println("provisioned:", prov.Deployment.Id)

    dp, _ := dataplane.NewClientWithResponses(fmt.Sprintf("https://%s", prov.Deployment.PrimaryVhost), dataplane.WithRequestEditorFn(bearerEditor(prov.BootstrapSecret)))
    tenant, _ := workflows.CreateTenant(ctx, dp, workflows.CreateTenantInput{Slug: "acme", Name: "Acme Inc"})
    fmt.Println("tenant:", tenant.Id)
    // ... invite, role assign, API key, send notification, audit list
}
```

### 14.7 Documentation

`sdk/go/README.md`:

- Install instructions
- Auth flow for operator + data-plane clients
- Workflows table (matching §21)
- Versioning policy (`/v2` path for breaking changes per §27)
- Example output

### 14.8 Commits

```bash
git add .oapi-codegen-*-client.yaml Makefile
git commit -m "add oapi codegen client configs"

git add sdk/go/go.mod sdk/go/controlplane/ sdk/go/dataplane/ sdk/go/internal/idem/
git commit -m "generate go sdk clients"

git add sdk/go/workflows/
git commit -m "add handwritten go workflow wrappers"

git add sdk/go/examples/ sdk/go/README.md
git commit -m "add sdk quickstart example and readme"
```

---

## Verification checklist

```bash
# 1. SDK builds.
$ make sdk-go
$ cd sdk/go && go build ./...

# 2. Generated code has no drift after spec change.
$ make openapi-check          # includes sdk-go round-trip
$ git diff --exit-code sdk/go/

# 3. Workflows tested.
$ cd sdk/go && go test -race ./workflows/...

# 4. Quickstart example runs.
$ make compose-up && make migrate && ./bin/saasctl operator login
$ cd sdk/go/examples/quickstart && go run .
# Expected: prints provisioned id, tenant id, etc.

# 5. SDK module is independent.
$ mkdir /tmp/sdkconsumer && cd /tmp/sdkconsumer
$ go mod init test
$ go get github.com/omarss/saas/sdk/go/controlplane
$ go get github.com/omarss/saas/sdk/go/workflows
# Expected: tidy import; no platform internals pulled in.
```

---

## Anti-pattern guards

- **NEVER** add a workflow that does multi-write across plane boundaries without an Idempotency-Key chain. Cross-plane multi-write is rare and must be a single tx at the API layer where possible.
- **NEVER** vendor the platform's `internal/` packages into the SDK. The SDK is consumer-facing; vendoring leaks internal APIs.
- **NEVER** auto-retry on 5xx in the workflows. Let the consumer choose; document the recommended retry strategy in README.
- **NEVER** log the bootstrap secret or any API key secret in workflow code. The example program uses `fmt.Println` for the dep id only.
- **NEVER** generate Go SDK code from the 3.1 spec directly. The overlay-downgrade is mandatory (same path TS SDK uses).
- **NEVER** create a workflow that depends on a deferred (v1) feature. Newsletters, files, webhooks are not in MVP.

---

## Open questions

1. **Go version pin for SDK.** Default: 1.24 (same as platform). When platform moves to 1.25, SDK follows in the next minor.
2. **Should workflow methods be on a struct or free funcs?** Default: free funcs with a `client` first arg (simpler; testable). Alternative: `Workflows` struct that bundles a control + data client.
3. **Should `RefreshingClient` cache the token in `~/.saas/credentials.json`?** Default: no — the SDK is a library; caching is saasctl's concern. Confirm.
4. **Streaming endpoints (logs).** Default: SDK exposes the raw response body for `tailDeploymentLogs`; consumer streams. v1 may add an `iter.Seq` adapter.

---

## Phase 14 — Definition of done

- [ ] `.oapi-codegen-*-client.yaml` configs committed
- [ ] `make sdk-go` regenerates clean; `git diff --exit-code` passes
- [ ] `sdk/go/go.mod` is independent
- [ ] `sdk/go/controlplane/` + `sdk/go/dataplane/` generated
- [ ] 10+ workflow wrappers landed under `sdk/go/workflows/`
- [ ] `sdk/go/examples/quickstart/main.go` runs end-to-end
- [ ] Workflow tests (unit + integration)
- [ ] `sdk/go/README.md` documents auth + workflows
- [ ] All Phase 2-13 tests still green
- [ ] PR template, `ready` label, CI green

---

End of Phase 14. Next: `16-dx-polish.md`.
