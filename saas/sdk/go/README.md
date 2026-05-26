# SaaS Go SDK

Generated typed clients for the SaaS control plane and data plane, plus a
small set of handwritten workflow wrappers that compose multiple calls
into the first-class flows documented in `AGENTS.md` §21.

This module is an **independent Go module** (`sdk/go/go.mod`) — it has its
own `go.mod`, its own dependencies, and intentionally does NOT import any
package from the platform's `internal/`. Consumers `go get` it directly.

---

## Install

```bash
go get github.com/omarss/saas/sdk/go/controlplane
go get github.com/omarss/saas/sdk/go/dataplane
go get github.com/omarss/saas/sdk/go/workflows
```

Requires Go 1.24 or later.

---

## Auth

Two clients, two token shapes:

| Client       | Token                                  | How to obtain                                     |
|--------------|----------------------------------------|---------------------------------------------------|
| controlplane | operator OIDC access token             | `saasctl operator login` (MFA + step-up enforced) |
| dataplane    | tenant-scoped API key OR user JWT      | bootstrap secret (one-time) or KC user flow       |

Inject the token via `WithRequestEditorFn`:

```go
import (
    cp "github.com/omarss/saas/sdk/go/controlplane"
    "github.com/omarss/saas/sdk/go/workflows"
)

client, _ := cp.NewClientWithResponses(
    "https://control.saas.omarss.net",
    cp.WithRequestEditorFn(workflows.BearerControlPlane(operatorToken)),
)
```

For OIDC token refresh, use `workflows.NewRefreshingHTTPClient(ctx, cfg)`
and pass the resulting `*http.Client` via `WithHTTPClient`. The SDK does
**not** cache tokens to disk; persistence is `saasctl`'s concern.

---

## Workflows

Each workflow is a **free function** that takes the relevant client as its
first argument (per Open Question 2: simpler + testable). Every workflow
that issues a POST or a state-transition PATCH auto-generates an
`Idempotency-Key` of the form `idem_<ulid>` unless the caller overrides
it via `workflows.WithIdempotencyKey(...)`.

Mapping to `AGENTS.md` §21:

| Workflow                  | Endpoint(s)                                                                       | Plane    |
|---------------------------|-----------------------------------------------------------------------------------|----------|
| `ProvisionDeployment`     | `POST /control/v1/deployments`                                                    | control  |
| `CreateTenant`            | `POST /v1/tenants`                                                                | data     |
| `InviteMember`            | `POST /v1/organizations/{org}/invitations` (email-based per Phase 7)              | data     |
| `CheckAuthorization`      | `POST /v1/authorization/check`                                                    | data     |
| `BatchCheckAuthorization` | `POST /v1/authorization/batch-check`                                              | data     |
| `CreateAPIKey`            | `POST /v1/tenants/{id}/api-keys` (plaintext secret returned ONCE)                 | data     |
| `RotateAPIKey`            | `POST /v1/api-keys/{id}/rotate` (with grace window per Phase 9)                   | data     |
| `ListAuditEvents`         | `GET /v1/tenants/{id}/audit-events` (cursor pagination)                           | data     |
| `SendNotification`        | `POST /v1/notifications/send` + optional poll of `GET /v1/notifications/{id}`     | data     |
| `LinkSocialProvider`      | `POST /v1/users/{id}/social-providers` (hashed link URL per ADR 014)              | data     |
| `AttachCustomDomain`      | `POST /control/v1/deployments/{id}/domains` + DNS poll + verify                   | control  |
| `StartImpersonation`      | `POST /control/v1/deployments/{id}/impersonation-sessions` (Phase 13)             | control  |
| `VerifyAuditIntegrity`    | `GET /control/v1/deployments/{id}/audit-integrity`                                | control  |

### Idempotency-Key behaviour

- Every workflow that calls `POST` or a state-transition `PATCH`
  auto-generates a `Idempotency-Key: idem_<ulid>` header.
- Pass `workflows.WithIdempotencyKey("idem_my_retry_key")` to override
  (use this when retrying a failed call with the SAME body — the platform
  returns the cached response).
- Multi-call workflows (e.g. `AttachCustomDomain` with `WaitForDNS`) issue
  each HTTP call with its OWN fresh key — Attach and Verify are distinct
  state transitions per AGENTS.md §5.2.

### ETag / If-Match

`If-Match` is exposed as a typed `string` parameter on the underlying
generated wrappers (e.g. `client.UpdateTenantWithResponse`). The SDK
does **not** auto-pull the ETag from a prior GET — that magic was flagged
during planning as too implicit. Read it from the previous response's
`ETag` header or `etag` field and pass it explicitly on PATCH/DELETE.

### Errors

Workflows return `*workflows.APIError` for any non-2xx response. The
error exposes the RFC 9457 problem-type discriminator (`Type` field) —
switch on `workflows.IsType(err, "<problem-type-uri>")` at the call site
rather than HTTP status, because the platform may map the same problem
to different statuses across versions.

Example:

```go
_, err := workflows.CreateTenant(ctx, c, in)
if err != nil {
    if workflows.IsType(err, "https://saas.omarss.net/problems/forbidden") {
        // distinguishable at the call site
    }
}
```

### Retry strategy

**The SDK does NOT auto-retry on 5xx.** Callers compose their own retry
strategy (`hashicorp/go-retryablehttp`, `cenkalti/backoff/v5`, etc.) by
wrapping the `*http.Client` they pass to `WithHTTPClient`. Recommended:

- exponential backoff with jitter
- cap at 3 attempts for `POST`s that mutate state
- always reuse the same `Idempotency-Key` across retry attempts
- skip retry on 4xx (those are client errors and won't change)

---

## Versioning

The SDK module follows Go module semver:

- `v0.x` while the platform is pre-MVP (current).
- `v1.0.0` lands with the first stable platform release (`AGENTS.md` §27
  defines the breaking-change policy: bump to `sdk/go/v2` only when the
  platform issues a `/v2` API).

---

## Anti-patterns we explicitly avoid

- No imports from the platform's `internal/`. Verify with
  `go list -m all` inside the SDK module: only the four declared deps
  appear.
- No 5xx auto-retry inside workflows.
- No PII / secret logging. The SDK never calls `log.Print` with any field
  the platform marks `pii:"true"` or `sensitive:"true"`.
- No spec generation from the 3.1 yaml directly — codegen reads from
  `openapi/_generated/*.yaml` after the platform's overlay-downgrade.

---

## Generating the clients

The two generated files (`controlplane/client.gen.go`,
`dataplane/client.gen.go`) are checked in and regenerated by the platform
Makefile:

```bash
make sdk-go         # regenerate + tidy + build
make sdk-go-test    # unit tests (no live stack required)
```

`make openapi-check` runs `sdk-go` as part of the diff-check, so spec
drift fails CI exactly like server-side server.gen.go drift.

---

## Quickstart example

`examples/quickstart/main.go` demonstrates four workflows end-to-end
against a live stack:

```bash
make compose-up && make migrate
saasctl operator login           # writes operator token
export SAAS_OPERATOR_TOKEN=$(cat ~/.saas/operator_token)
make sdk-go-quickstart
```

The program prints the deployment id, tenant id, API key id, and
notification id; secrets are deliberately omitted from output.

---

## Integration tests (not in this module)

The unit tests under `workflows/` use `net/http/httptest` and run with
`make sdk-go-test`. End-to-end integration tests against a real
`compose-up` stack live in `test/integration/sdk_go/` in the parent
module and are gated behind `-tags=integration`.
