# Phase 5 — Identity Façade via gocloak + Social Login (Google / GitHub / Apple)

> **Goal**: Ship the `/v1/users` data-plane resource end-to-end behind a Keycloak-backed identity façade. Swap Phase 2/3's `MockMiddleware` for a real JWT verifier (jwx v3 + JWKS cache). Land the `/v1/users/{id}/social-providers` endpoints + Keycloak IdP brokering config for Google, GitHub, Apple. Author ADRs 007 (per-Deployment KC client) and 014 (social login promotion).
>
> **Why now**: AGENTS.md §8.3 and §12.2 list Identity as a core MVP module. Phase 6 Notifications depends on Identity (to look up a user's email when sending invitations). Phase 7 Organizations depends on Identity (members reference users). Phase 8 RBAC depends on members existing. The build order in §16 puts Identity first among the "remaining MVP modules" group. Phase 5 cannot rely on Phase 6 Notifications for password-reset email — it delegates to Keycloak's built-in flow OR explicitly stubs the send for re-wiring in Phase 6.
>
> **What this phase does NOT do**: No password-reset email sending from the platform itself — Keycloak's built-in SMTP handler is used until Phase 6 ships Notifications. No MFA for users (operator MFA is Phase 13). No webhook deliveries on user events (out of MVP). No per-Deployment Keycloak realm provisioning (that's wired in Phase 12 alongside the real provisioner; Phase 5 uses a single shared `saas-data` realm for local dev).
>
> **Maps to AGENTS.md**: §0 (personas), §8.3 (Identity endpoints), §12.2 (Identity module), §17.3 (authorization tests — Users is tenant-bound), §18.3 (audit list: user disable/enable/password-reset), §18.5 (PII on email/phone/address), §18.7 (envelope encryption for email at rest), §21 (first-class workflow: link-social-provider). `01-foundations.md` §8 (gocloak v14 signatures, jwx v3 verifier, IdP broker).
>
> **Estimated subagent sessions**: 3 (one for OpenAPI + migration + sqlc; one for handler + service + gocloak adapter + JWT swap; one for social login flow + tests + SDK).

---

## Pre-flight

1. AGENTS.md §8.3, §12.2, §18.3, §18.5, §18.7.
2. CONVENTIONS.md (Phase 3 + Phase 4 updates).
3. `01-foundations.md` §8 (gocloak, jwx, JWKS cache).
4. `03-tenants-slice.md` — every shape in Phase 5 mirrors Phase 2's.
5. `05-openbao-integration.md` (Phase 4) — User.Email goes through the persist walker.
6. Confirm with user: Phase 5 uses a single `saas-data` realm for local dev; Phase 12 introduces per-Deployment realms. Phase 5 imports a realm JSON via Keycloak's `--import-realm` flag.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Keycloak client model | Per-Deployment client (`saas-data-<dep_id>`) with own audience; for Phase 5 local dev: single client `saas-data-local`, audience `saas-data-local` (Phase 12 swaps) | Single global client with audience-resolve mapper (refused per ADR 007 — scalability + revocation worse) |
| User identity model | One Keycloak user per platform User (`platform_user_id` stored as KC user attribute) | Federated identity (out of MVP) |
| Email verification | Keycloak's built-in `verify-email` action via `ExecuteActionsEmail` | Custom token flow (refused — Keycloak does it correctly) |
| Password reset email transport (Phase 5 only) | Keycloak's built-in SMTP, configured against the local compose `mailhog` service | Skip until Phase 6 (refused — must work end-to-end) |
| Social providers in MVP | Google, GitHub, Apple (per scope change in 00-master.md) | Add Microsoft/Facebook (out of MVP) |
| Social login state token storage | `state` opaque, 5 min TTL, in Postgres `social_login_state` table | Cookies (refused — cross-domain pain); Redis (overkill for MVP) |
| User disable propagation | Keycloak `Enabled=false` + platform User row `status='disabled'` + emit `user.disabled` event; tokens still valid until expiry (≤ 1h) | Force revoke all tokens immediately (Keycloak doesn't do this cleanly without Redis-backed session) |
| identity_provider_mapping schema | `(platform_user_id, provider, external_subject, linked_at)` with unique on `(provider, external_subject)` | None (refused — required for unlink + audit) |

If the user disagrees with any default, stop.

---

## Tasks

### 5.1 OpenAPI spec — `/v1/users`

`openapi/data-plane.yaml` (additions, mirroring the Tenants pattern):

```yaml
tags:
  - name: users
    description: Identity façade. Wraps Keycloak; consumers never see Keycloak.
  - name: social-providers
    description: Social login IdP linking via Keycloak brokering.

paths:
  /v1/users:
    get:
      operationId: listUsers
      tags: [users]
      parameters:
        - $ref: "#/components/parameters/Limit"
        - $ref: "#/components/parameters/Cursor"
        - $ref: "#/components/parameters/Sort"
        - { in: query, name: email, schema: { type: string, format: email } }
      responses:
        "200":
          content: { application/json: { schema: { $ref: "#/components/schemas/UserListResponse" } } }
        "401": { $ref: "#/components/responses/Unauthorized" }
        "410": { $ref: "#/components/responses/CursorGone" }
    post:
      operationId: createUser
      tags: [users]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/CreateUserRequest" } } } }
      responses:
        "201":
          headers: { ETag: { schema: { type: string } }, Location: { schema: { type: string } } }
          content: { application/json: { schema: { $ref: "#/components/schemas/UserResponse" } } }
        "401": { $ref: "#/components/responses/Unauthorized" }
        "422": { $ref: "#/components/responses/IdempotencyConflictOrValidation" }

  /v1/users/{user_id}:
    parameters:
      - { in: path, name: user_id, required: true, schema: { type: string, pattern: "^user_[0-9A-HJKMNP-TV-Z]{26}$" } }
    get:
      operationId: getUser
      tags: [users]
      responses:
        "200":
          headers: { ETag: { schema: { type: string } } }
          content: { application/json: { schema: { $ref: "#/components/schemas/UserResponse" } } }
        "401": { $ref: "#/components/responses/Unauthorized" }
        "403": { $ref: "#/components/responses/Forbidden" }
        "404": { $ref: "#/components/responses/NotFound" }
    patch:
      operationId: updateUser
      tags: [users]
      parameters: [ { $ref: "#/components/parameters/IfMatch" }, { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/UpdateUserRequest" } } } }
      responses:
        "200":
          headers: { ETag: { schema: { type: string } } }
          content: { application/json: { schema: { $ref: "#/components/schemas/UserResponse" } } }
        "412": { $ref: "#/components/responses/PreconditionFailed" }
    delete:
      operationId: deleteUser
      tags: [users]
      parameters: [ { $ref: "#/components/parameters/IfMatch" } ]
      responses:
        "204": { description: Soft-deleted (Keycloak Enabled=false + platform status='deleted'). }

  /v1/users/{user_id}/disable:
    post:
      operationId: disableUser
      tags: [users]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/UserResponse" } } } } }

  /v1/users/{user_id}/enable:
    post:
      operationId: enableUser
      tags: [users]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/UserResponse" } } } } }

  /v1/users/{user_id}/reset-password:
    post:
      operationId: triggerPasswordReset
      tags: [users]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses: { "202": { description: "Reset email queued by Keycloak (Phase 5) or Notifications (Phase 6 swap)." } }

  /v1/users/{user_id}/verify-email:
    post:
      operationId: triggerEmailVerify
      tags: [users]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses: { "202": { description: "Verify-email action queued in Keycloak." } }

  /v1/users/{user_id}/social-providers:
    parameters:
      - { in: path, name: user_id, required: true, schema: { type: string } }
    get:
      operationId: listSocialProviders
      tags: [social-providers]
      responses:
        "200":
          content: { application/json: { schema: { $ref: "#/components/schemas/SocialProviderListResponse" } } }
    post:
      operationId: linkSocialProvider
      tags: [social-providers]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/LinkSocialProviderRequest" }
      responses:
        "200":
          description: "Returns a Keycloak-brokered authorization URL. Caller redirects."
          content:
            application/json:
              schema: { $ref: "#/components/schemas/LinkSocialProviderResponse" }

  /v1/users/{user_id}/social-providers/{provider}:
    parameters:
      - { in: path, name: user_id, required: true, schema: { type: string } }
      - { in: path, name: provider, required: true, schema: { type: string, enum: [google, github, apple] } }
    delete:
      operationId: unlinkSocialProvider
      tags: [social-providers]
      responses: { "204": { description: Unlinked. Emits user.social_unlinked. } }

  /v1/social/callback:
    get:
      operationId: socialCallback
      tags: [social-providers]
      parameters:
        - { in: query, name: state, required: true, schema: { type: string } }
        - { in: query, name: code,  required: true, schema: { type: string } }
      responses:
        "303": { description: "Redirect to caller-supplied return_to URL with success/failure flag." }

components:
  schemas:
    User:
      type: object
      required: [id, object, status, created_at, updated_at, etag]
      properties:
        id:           { type: string, pattern: "^user_[0-9A-HJKMNP-TV-Z]{26}$" }
        object:       { type: string, enum: [user] }
        email:        { type: string, format: email, x-oapi-codegen-extra-tags: { pii: "true", sensitive: "true" } }
        email_verified: { type: boolean }
        phone:        { type: [string, "null"], x-oapi-codegen-extra-tags: { pii: "true", sensitive: "true" } }
        name:         { type: [string, "null"], x-oapi-codegen-extra-tags: { pii: "true" } }
        status:       { type: string, enum: [active, disabled, deleted] }
        metadata:     { $ref: "#/components/schemas/Metadata" }
        created_at:   { type: string, format: date-time }
        updated_at:   { type: string, format: date-time }
        etag:         { type: string }

    SocialProvider:
      type: object
      required: [provider, external_subject, linked_at]
      properties:
        provider:          { type: string, enum: [google, github, apple] }
        external_subject:  { type: string, x-oapi-codegen-extra-tags: { sensitive: "true" } }
        linked_at:         { type: string, format: date-time }

    CreateUserRequest:
      type: object
      required: [email]
      properties:
        email:    { type: string, format: email,  x-oapi-codegen-extra-tags: { pii: "true" } }
        name:     { type: string,                  x-oapi-codegen-extra-tags: { pii: "true" } }
        send_verification_email: { type: boolean, default: true }

    UpdateUserRequest:
      type: object
      properties:
        name:    { type: string, x-oapi-codegen-extra-tags: { pii: "true" } }
        phone:   { type: string, x-oapi-codegen-extra-tags: { pii: "true" } }
        metadata: { $ref: "#/components/schemas/Metadata" }

    LinkSocialProviderRequest:
      type: object
      required: [provider, return_to]
      properties:
        provider:  { type: string, enum: [google, github, apple] }
        return_to: { type: string, format: uri, maxLength: 2048 }

    LinkSocialProviderResponse:
      type: object
      required: [authorization_url, state, expires_at]
      properties:
        authorization_url: { type: string, format: uri }
        state:             { type: string }
        expires_at:        { type: string, format: date-time }

    UserResponse:
      type: object
      required: [data]
      properties: { data: { $ref: "#/components/schemas/User" } }

    UserListResponse:
      type: object
      required: [data, pagination]
      properties:
        data: { type: array, items: { $ref: "#/components/schemas/User" } }
        pagination: { $ref: "#/components/schemas/Pagination" }

    SocialProviderListResponse:
      type: object
      required: [data]
      properties:
        data: { type: array, items: { $ref: "#/components/schemas/SocialProvider" } }
```

### 5.2 Migration — `migrations/dataplane/000003_users.up.sql`

```sql
CREATE TABLE platform_user (
    id                      text PRIMARY KEY CHECK (id LIKE 'user_%'),
    tenant_id               text NOT NULL REFERENCES tenant (id),
    -- Email is PII. Plain "email_lookup_hash" is HMAC-SHA256 with the
    -- per-Deployment HMAC key (stored in OpenBao KV). Allows unique-by-email
    -- without storing plaintext.
    email_lookup_hash       bytea NOT NULL,
    email_ciphertext        bytea NOT NULL,
    email_wrapped_dek       text  NOT NULL,
    email_nonce             bytea NOT NULL,
    email_kid               text  NOT NULL,
    email_key_version       integer NOT NULL,
    email_verified          boolean NOT NULL DEFAULT false,

    -- Other PII fields use the same envelope pattern.
    name_ciphertext         bytea,
    name_wrapped_dek        text,
    name_nonce              bytea,
    name_kid                text,
    name_key_version        integer,

    phone_ciphertext        bytea,
    phone_wrapped_dek       text,
    phone_nonce             bytea,
    phone_kid               text,
    phone_key_version       integer,

    keycloak_user_id        text NOT NULL UNIQUE,
    status                  text NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'disabled', 'deleted')),
    metadata                jsonb NOT NULL DEFAULT '{}'::jsonb,
    row_seq                 bigint NOT NULL DEFAULT 1,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz
);

CREATE UNIQUE INDEX platform_user_email_unique
    ON platform_user (tenant_id, email_lookup_hash)
    WHERE deleted_at IS NULL;
CREATE INDEX platform_user_status_idx ON platform_user (tenant_id, status) WHERE deleted_at IS NULL;
CREATE INDEX platform_user_created_at_idx ON platform_user (tenant_id, created_at DESC);

CREATE TRIGGER platform_user_bump_row_seq
    BEFORE UPDATE ON platform_user
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

ALTER TABLE platform_user ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform_user FORCE  ROW LEVEL SECURITY;
CREATE POLICY platform_user_tenant_only ON platform_user
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Identity provider mapping (social login linkages).
CREATE TABLE identity_provider_mapping (
    platform_user_id   text NOT NULL REFERENCES platform_user (id) ON DELETE CASCADE,
    tenant_id          text NOT NULL,
    provider           text NOT NULL CHECK (provider IN ('google', 'github', 'apple')),
    external_subject   text NOT NULL,            -- IdP's "sub" claim
    linked_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (platform_user_id, provider),
    UNIQUE (provider, external_subject)
);
ALTER TABLE identity_provider_mapping ENABLE ROW LEVEL SECURITY;
ALTER TABLE identity_provider_mapping FORCE  ROW LEVEL SECURITY;
CREATE POLICY ipm_tenant_only ON identity_provider_mapping
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Social login state (5 min TTL, CSRF + return_to binding).
CREATE TABLE social_login_state (
    state              text PRIMARY KEY,
    tenant_id          text NOT NULL,
    platform_user_id   text NOT NULL,
    provider           text NOT NULL,
    return_to          text NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    expires_at         timestamptz NOT NULL
);
CREATE INDEX social_login_state_expiry_idx ON social_login_state (expires_at);
ALTER TABLE social_login_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_login_state FORCE  ROW LEVEL SECURITY;
CREATE POLICY sls_tenant_only ON social_login_state
    USING (tenant_id = current_setting('app.current_tenant_id', true));
```

The `email_lookup_hash` is an HMAC of normalised email (lowercased, trimmed) with a per-Deployment HMAC key stored in OpenBao KV at `secret/data/<deployment_id>/identity/email_hmac_key`. This lets `WHERE email_lookup_hash = $1` perform email lookups without ever exposing plaintext.

### 5.3 sqlc queries — `internal/dataplane/db/queries/users.sql`

(Standard CRUD + lookups by `email_lookup_hash` and `keycloak_user_id`.)

### 5.4 Domain types — `internal/dataplane/identity/`

```text
internal/dataplane/identity/
  domain.go         # User, SocialProvider, Status
  ports.go          # Repository, IdentityProvider (Keycloak façade), EmailHasher, EventPublisher
  service.go        # orchestration
  repo_pgx.go       # pgx + sqlc + crypto.EncryptPIIFields walker
  provider_kc.go    # gocloak adapter
  social.go         # social link/unlink + state token
  handler.go        # strict-server impl
  errors.go
  service_test.go
  repo_pgx_test.go
  provider_kc_test.go     # adapter test (testcontainers Keycloak)
  social_test.go
  security_test.go        # §17.3 matrix (mandatory)
```

`ports.go`:

```go
package identity

import "context"

type Repository interface {
    Create(ctx context.Context, u User) (User, error)
    Get(ctx context.Context, tenantID, userID string) (User, error)
    GetByEmailHash(ctx context.Context, tenantID string, emailHash []byte) (User, error)
    List(ctx context.Context, tenantID string, limit int, cursor *ListCursor, emailFilter []byte) ([]User, bool, error)
    Update(ctx context.Context, tenantID, userID string, expectedSeq int64, patch UpdatePatch) (User, error)
    Disable(ctx context.Context, tenantID, userID string) (User, error)
    Enable(ctx context.Context, tenantID, userID string) (User, error)
    SoftDelete(ctx context.Context, tenantID, userID string, expectedSeq int64) error

    LinkSocialProvider(ctx context.Context, tenantID, userID, provider, externalSubject string) error
    UnlinkSocialProvider(ctx context.Context, tenantID, userID, provider string) error
    ListSocialProviders(ctx context.Context, tenantID, userID string) ([]SocialProvider, error)
}

// IdentityProvider abstracts Keycloak. The gocloak v14 adapter implements it.
type IdentityProvider interface {
    CreateUser(ctx context.Context, realm string, u User) (kcUserID string, err error)
    UpdateUser(ctx context.Context, realm string, kcUserID string, patch UpdatePatch) error
    SetEnabled(ctx context.Context, realm, kcUserID string, enabled bool) error
    TriggerPasswordReset(ctx context.Context, realm, kcUserID string) error
    TriggerEmailVerify(ctx context.Context, realm, kcUserID string) error
    DeleteUser(ctx context.Context, realm, kcUserID string) error

    StartSocialLogin(ctx context.Context, realm, kcUserID, provider, state, returnTo string) (authorizationURL string, err error)
    CompleteSocialLogin(ctx context.Context, realm, state, code string) (externalSubject string, err error)
    ListIdentityProviderLinks(ctx context.Context, realm, kcUserID string) ([]string, error)
    UnlinkIdentityProvider(ctx context.Context, realm, kcUserID, provider string) error
}

type EmailHasher interface {
    Normalise(email string) string
    Hash(ctx context.Context, deploymentID, email string) ([]byte, error)
}
```

### 5.5 gocloak v14 adapter — `provider_kc.go`

```go
package identity

import (
    "context"
    "github.com/Nerzal/gocloak/v14"
)

type KeycloakProvider struct {
    kc     *gocloak.GoCloak
    tokenF func(ctx context.Context) (string, error) // client_credentials accessor
}

func NewKeycloakProvider(authBaseURL string, tokenFetcher func(ctx context.Context) (string, error)) *KeycloakProvider {
    return &KeycloakProvider{kc: gocloak.NewClient(authBaseURL), tokenF: tokenFetcher}
}

func (k *KeycloakProvider) CreateUser(ctx context.Context, realm string, u User) (string, error) {
    tok, err := k.tokenF(ctx); if err != nil { return "", err }
    return k.kc.CreateUser(ctx, tok, realm, gocloak.User{
        Username:      gocloak.StringP(u.ID),                   // platform-side id; Keycloak username is unique within realm
        Email:         gocloak.StringP(u.PlaintextEmail),       // post-decrypt only; never persisted by KC at rest plaintext (KC encrypts at rest separately)
        Enabled:       gocloak.BoolP(true),
        EmailVerified: gocloak.BoolP(false),
        Attributes: &map[string][]string{
            "platform_user_id": {u.ID},
            "tenant_id":        {u.TenantID},
        },
    })
}

func (k *KeycloakProvider) SetEnabled(ctx context.Context, realm, kcUserID string, enabled bool) error {
    tok, err := k.tokenF(ctx); if err != nil { return err }
    return k.kc.UpdateUser(ctx, tok, realm, gocloak.User{
        ID: gocloak.StringP(kcUserID), Enabled: gocloak.BoolP(enabled),
    })
}

func (k *KeycloakProvider) TriggerPasswordReset(ctx context.Context, realm, kcUserID string) error {
    tok, err := k.tokenF(ctx); if err != nil { return err }
    return k.kc.ExecuteActionsEmail(ctx, tok, realm, gocloak.ExecuteActionsEmail{
        UserID: gocloak.StringP(kcUserID), Actions: &[]string{"UPDATE_PASSWORD"},
    })
}

func (k *KeycloakProvider) TriggerEmailVerify(ctx context.Context, realm, kcUserID string) error {
    tok, err := k.tokenF(ctx); if err != nil { return err }
    return k.kc.ExecuteActionsEmail(ctx, tok, realm, gocloak.ExecuteActionsEmail{
        UserID: gocloak.StringP(kcUserID), Actions: &[]string{"VERIFY_EMAIL"},
    })
}

// StartSocialLogin builds the Keycloak "client-initiated account linking" URL.
// This is the SECURE primitive for user-facing manual-link, NOT
// CreateUserFederatedIdentity (which has no proof-of-possession and enables
// account takeover by anyone with manage-users). See the Keycloak server-
// development guide on Identity Brokering APIs.
//
// URL shape: /realms/<realm>/broker/<provider>/link?client_id=...&redirect_uri=...
//            &nonce=<nonce>&hash=base64url(sha256(nonce + session_state + issued_for + provider))
//
// The caller supplies the nonce; session_state and issued_for come from the
// access token. After redirect, Keycloak runs the OAuth dance with the
// external IdP and writes the federated_identity row itself on success.
// The user must hold the `account.manage-account-links` role.
func (k *KeycloakProvider) StartSocialLogin(ctx context.Context, realm, clientID, provider, nonce, sessionState, issuedFor, returnTo string) (string, error) {
    raw := nonce + sessionState + issuedFor + provider
    sum := sha256.Sum256([]byte(raw))
    hash := base64.RawURLEncoding.EncodeToString(sum[:])
    u := fmt.Sprintf("%s/realms/%s/broker/%s/link?client_id=%s&redirect_uri=%s&nonce=%s&hash=%s",
        k.kc.BasePath(), realm, provider, url.QueryEscape(clientID),
        url.QueryEscape(returnTo), url.QueryEscape(nonce), url.QueryEscape(hash))
    return u, nil
}

// CompleteSocialLogin reads the linked identity providers and extracts the
// external_subject of the just-linked provider. Called from /v1/social/callback.
func (k *KeycloakProvider) CompleteSocialLogin(ctx context.Context, realm, state, code string) (string, error) {
    // Keycloak completes the broker flow at its own callback URL; our handler
    // is only invoked after KC has linked the identity. We query KC for the
    // list of linked providers for the user (identified via the state row in DB)
    // and return the external_subject.
    // ...
}
```

**Resolved (pre-Phase-5 research)**: gocloak v14.0.3 DOES expose typed helpers:

```go
func (g *GoCloak) GetUserFederatedIdentities(ctx context.Context, token, realm, userID string) ([]*FederatedIdentityRepresentation, error)
func (g *GoCloak) CreateUserFederatedIdentity(ctx context.Context, token, realm, userID, providerID string, rep FederatedIdentityRepresentation) error    // by VALUE, not pointer
func (g *GoCloak) DeleteUserFederatedIdentity(ctx context.Context, token, realm, userID, providerID string) error
```

`providerID` is the IdP `alias` (`"google"`, `"github"`, `"apple"`). The struct `FederatedIdentityRepresentation` has pointer fields `IdentityProvider`, `UserID`, `UserName` — wrap with `gocloak.StringP`.

**Critical security choice — use the hashed-link URL flow, NOT `CreateUserFederatedIdentity`, for the user-facing manual-link endpoint.** Direct `CreateUserFederatedIdentity` requires the caller to already possess the external IdP's `userId` (the OAuth `sub` at Google/GitHub/Apple) — without doing the OAuth dance server-side you cannot honestly fill that field, and inserting a guessed/forged value enables takeover by anyone with `manage-users`. Reserve `CreateUserFederatedIdentity` for **operator/migration flows** (Control Plane bulk import where verified provider subjects are available) — never expose it on a user-facing endpoint.

Endpoint design:
- `POST /v1/users/{id}/social-providers` → returns `202 Accepted` with the constructed Keycloak link URL (above). Client redirects browser there; Keycloak handles OAuth and writes the federated_identity row itself.
- `GET  /v1/users/{id}/social-providers` → calls `GetUserFederatedIdentities` directly.
- `DELETE /v1/users/{id}/social-providers/{provider}` → calls `DeleteUserFederatedIdentity` directly (safe — no proof-of-possession needed to detach).

Two gaps confirmed but worth a spike before shipping:
1. Exact role mapping required on the service-account JWT for the link URL to accept tokens it didn't issue (likely `account.manage-account-links`).
2. Apple's IdP requires extra `clientSecret` config on the broker side (form-post response mode) — surfaced in the SocialProvider config flow (§5.7).

Document the hashed-link-vs-direct decision in ADR 014.

### 5.6 Service — `service.go`

Same shape as Tenants service. Every method takes `(ctx, tenantID, ...)` as first two params (CONVENTIONS.md §2). Cross-tenant `auth.AssertTenant` check happens before any DB or KC call.

Key flows:

- **Create**: HMAC the email; insert platform_user row with envelope-encrypted fields; create KC user; store `keycloak_user_id`; emit `user.created`; if `send_verification_email`, call `TriggerEmailVerify`.
- **Disable**: KC `Enabled=false` + DB status flip + emit `user.disabled`; no token revoke (acceptable trade-off; see Decisions).
- **Reset password**: KC `ExecuteActionsEmail` with `UPDATE_PASSWORD`; emit `user.password_reset_requested` audit event (Phase 10 consumes).
- **Link social provider**: persist `social_login_state` row with 5-min expiry; return Keycloak's broker URL + state. On callback, validate state, validate state hasn't expired, call `CompleteSocialLogin`, insert `identity_provider_mapping`, emit `user.social_linked`, delete the state row, redirect to `return_to`.

### 5.7 Swap MockMiddleware for jwx v3 JWT verifier

`internal/platform/auth/jwt.go` (new in Phase 5):

```go
package auth

import (
    "context"
    "errors"
    "net/http"
    "strings"
    "time"

    "github.com/lestrrat-go/jwx/v3/jwk"
    "github.com/lestrrat-go/jwx/v3/jwt"
)

type JWTVerifier struct {
    cache       *jwk.Cache
    issuer      string
    audience    string
}

func NewJWTVerifier(ctx context.Context, jwksURL, issuer, audience string) (*JWTVerifier, error) {
    cache, err := jwk.NewCache(ctx, jwk.WithRefreshInterval(15*time.Minute))
    if err != nil { return nil, err }
    if err := cache.Register(jwksURL); err != nil { return nil, err }
    if _, err := cache.Get(ctx, jwksURL); err != nil { return nil, err }
    return &JWTVerifier{cache: cache, issuer: issuer, audience: audience}, nil
}

func (v *JWTVerifier) Verify(ctx context.Context, raw string) (Principal, error) {
    ks, err := v.cache.Get(ctx, v.issuer + "/protocol/openid-connect/certs")
    if err != nil { return Principal{}, err }
    tok, err := jwt.Parse([]byte(raw),
        jwt.WithKeySet(ks),
        jwt.WithValidate(true),
        jwt.WithIssuer(v.issuer),
        jwt.WithAudience(v.audience),     // critical: aud check before tenant_id read
    )
    if err != nil { return Principal{}, err }
    var tid string
    _ = tok.Get("tenant_id", &tid)
    var scope string
    _ = tok.Get("scope", &scope)
    sub, _ := tok.Subject()
    return Principal{
        ActorType: ActorUser,
        ActorID:   sub,
        TenantID:  tid,
        Scopes:    ParseScopes(scope),
    }, nil
}

func (v *JWTVerifier) Middleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        h := r.Header.Get("Authorization")
        if !strings.HasPrefix(h, "Bearer ") {
            http.Error(w, "missing bearer", http.StatusUnauthorized); return
        }
        p, err := v.Verify(r.Context(), strings.TrimPrefix(h, "Bearer "))
        if err != nil {
            http.Error(w, "invalid token", http.StatusUnauthorized); return
        }
        next.ServeHTTP(w, r.WithContext(WithPrincipal(r.Context(), p)))
    })
}
```

`cmd/dataplane/main.go` wires:

```go
verifier, err := auth.NewJWTVerifier(ctx, os.Getenv("OIDC_JWKS_URL"),
    os.Getenv("OIDC_ISSUER"), os.Getenv("OIDC_AUDIENCE"))
if err != nil { return err }
r.Use(verifier.Middleware)
// MockMiddleware is still present in !prod builds and runs AFTER the JWT
// verifier as a fallback for X-Mock-Tenant-Id-only tests.
```

The Phase 2/3 mock middleware stays available in `!prod` builds for the existing test fixtures. The chain becomes: JWT verifier first; if no bearer, mock middleware reads `X-Mock-Tenant-Id`; in prod, only the JWT path runs.

### 5.8 Keycloak realm import — `deploy/keycloak/realms/saas-data-template.json`

A template realm JSON with:

- realm name: `saas-data-local` (Phase 12 templates render per Deployment)
- client `saas-data-local` with `aud=saas-data-local` mapper
- audience protocol mapper (oidc-audience-mapper)
- IdP brokers for Google, GitHub, Apple — config fields left as `${VAR}` placeholders so they don't leak into git
- SMTP settings pointing at a local `mailhog` container (added to compose.yaml in this phase)

`compose.yaml` additions:

```yaml
  mailhog:
    image: mailhog/mailhog:v1.0.1
    ports: ["1025:1025", "8025:8025"]
```

Keycloak's realm import command is `kc.sh start --import-realm`. Once imported, do NOT modify by re-importing — use gocloak (per `01-foundations.md` §8 anti-pattern: "Re-importing realm JSON to apply config drift").

### 5.9 Tests

`service_test.go`: mock Repository + IdentityProvider + EmailHasher. Cases:

- Create stores envelope-encrypted email; HMAC matches lookup query
- Create handles Keycloak failure by rolling back the DB insert (transactional outbox)
- Disable flips status + KC enabled and emits event
- Reset password calls `ExecuteActionsEmail("UPDATE_PASSWORD")`
- Link social provider creates state row + returns URL
- Callback validates state, expires used state, refuses replay

`provider_kc_test.go` (testcontainers Keycloak 26):

- Realm import succeeds
- CreateUser → Keycloak returns user with `platform_user_id` attribute
- TriggerPasswordReset succeeds; mailhog receives email (HTTP GET on mailhog API)
- IdP brokers configured for Google/GitHub/Apple (verify via admin API)

`security_test.go` (the §17.3 matrix — MANDATORY):

| Test | Setup | Assert |
|---|---|---|
| Same-tenant allow | mock JWT tenant=X; URL=/v1/users (no path id, list scope) | 200 |
| Cross-tenant deny on read | tenant=X JWT; URL=/v1/users/user_Y (user_Y belongs to tenant=Z) | 404 (NOT 403; we MUST NOT leak existence; same shape as Tenants) |
| Cross-tenant deny on update | as above | 404 |
| Cross-tenant deny on link-social | tenant=X JWT; URL=/v1/users/user_Y/social-providers | 404 |
| Missing tenant context | no Authorization header | 401 |
| Disabled user attempts mutation | tenant=X JWT, but principal user is disabled | 403 + problem `user-disabled` |
| Mock middleware refused in prod | SAAS_ENV=prod + mock header | 401 |
| `X-Tenant-Id` ignored | header set; no Authorization | 401 |
| Replay social state | same state used twice | 400 + `state-already-used` |
| Expired social state | state.expires_at < now() | 400 + `state-expired` |

Why 404 for cross-tenant on a known-existing id? Per AGENTS.md §18.1 + Phase 2's pattern: leaking existence is also an isolation breach. RLS returns zero rows; the handler maps that to 404. (Cross-tenant on resources where the URL contains a tenant_id explicitly returns 403 — but `/v1/users/{user_id}` does not.)

### 5.10 TS SDK regeneration + workflow wrapper

```bash
make sdk-ts
```

`sdk/ts/data-plane/workflows/users.ts`:

```typescript
export class UsersWorkflow {
  constructor(private config: Configuration) {}

  async create(email: string, name?: string, sendVerificationEmail = true) { ... }
  async linkSocialProvider(userId: string, provider: "google"|"github"|"apple", returnTo: string) {
    const idempotencyKey = "idem_" + ulid();
    const res = await new SocialProvidersApi(this.config).linkSocialProvider(userId,
      { provider, return_to: returnTo },
      { headers: { "Idempotency-Key": idempotencyKey } });
    // Caller window.location.href = res.data.authorization_url
    return res.data;
  }
}
```

### 5.11 saasctl

```go
root.AddCommand(&cobra.Command{Use: "user", Short: "User operations"})
// user list, user create, user disable, user reset-password, user link-social, user list-social
```

### 5.12 ADRs

`docs/adr/007-per-deployment-keycloak-client.md`:

```markdown
# ADR 007 — Per-Deployment Keycloak client vs single client with audience-resolve

## Status
Accepted (2026-05-24).

## Context
Each Deployment is an isolation boundary (§18.1). A platform User in Deployment
A must never present a token that satisfies Deployment B's audience check
(§18.4). Two ways to model this in Keycloak:

(1) Single global client `saas-data` with audience-resolve mapper that emits
    `aud=saas-data-<dep_id>` based on the user's `deployment_id` attribute.
(2) Per-Deployment client `saas-data-<dep_id>`.

## Decision
Per-Deployment client (option 2).

## Consequences
+ Audience check is mechanical: `aud=saas-data-<dep_id>` ⊕ token issued by
  realm `saas-data-<dep_id>` (Phase 12 introduces per-Deployment realms).
+ Per-Deployment client secret rotation is local; no global blast radius.
+ Deletion of a Deployment cleanly deletes its client.
- Client count grows with Deployment count. Keycloak handles thousands fine.
- For Phase 5 local dev, the single client `saas-data-local` is used; Phase 12
  switches to per-Deployment clients via gocloak APIs at provision time.
```

`docs/adr/014-social-login-promotion.md`:

```markdown
# ADR 014 — Promote social login (Keycloak IdP brokering) to MVP

## Status
Accepted (2026-05-24).

## Context
Original AGENTS.md §8.3 listed only password + email flows for MVP. User
feedback (2026-05-24) called out that B2B SaaS without Google/GitHub login
fails first impression. Apple is required by App Store guidelines for any
iOS app that also offers other social logins.

## Decision
Promote social login to MVP. Providers in MVP: Google, GitHub, Apple. Other
providers (Microsoft, Facebook, LinkedIn) deferred to v1.

Implementation:
- Keycloak's IdP brokering handles the OAuth dance.
- Platform endpoints: GET/POST/DELETE /v1/users/{id}/social-providers; GET
  /v1/social/callback for the post-broker redirect.
- `identity_provider_mapping` table stores `(platform_user_id, provider, external_subject)`.
- 5-min state TTL; CSRF + return_to binding.

## Consequences
+ Standard Keycloak feature; no custom OAuth code.
+ Adding a provider later = realm JSON update + nothing else.
- The IdP credentials (Google client_id/secret, etc.) are per-Deployment;
  Phase 6 stores them in OpenBao KV.
- gocloak v14 has no first-class "link IdP" method; we construct the broker
  URL manually. Verified against KC 26.x docs. If the URL pattern shifts in
  KC 27, the adapter test catches it.
```

### 5.13 Commits

```bash
git add openapi/data-plane.yaml openapi/problems/
git commit -m "add users and social provider endpoints"

git add migrations/dataplane/000003_users.up.sql internal/dataplane/db/queries/users.sql
git commit -m "add platform user and idp mapping tables"

git add internal/dataplane/identity/
git commit -m "implement identity module behind gocloak"

git add internal/platform/auth/jwt.go cmd/dataplane/main.go cmd/controlplane/main.go
git commit -m "swap mock middleware for jwx jwt verifier"

git add deploy/keycloak/realms/ compose.yaml
git commit -m "import saas data local realm with social brokers"

git add sdk/ts/data-plane/workflows/users.ts
git commit -m "ts sdk users workflow wrapper"

git add cmd/saasctl/ docs/adr/007-*.md docs/adr/014-*.md
git commit -m "saasctl user commands and identity adrs"
```

---

## Verification checklist

```bash
# 1. Spec lints + generates clean.
$ make openapi-check

# 2. Migrations apply.
$ make migrate
$ psql -c "\d platform_user" -c "\d identity_provider_mapping" -c "\d social_login_state"

# 3. Build + lint.
$ make build && make lint

# 4. Unit + integration tests.
$ make test && make test-int

# 5. Authorization matrix (the §17.3 mandate).
$ go test -run TestUsers_AuthZ -v ./internal/dataplane/identity/...

# 6. JWT verifier accepts a real KC token.
$ TOK=$(curl -s -X POST http://localhost:8081/realms/saas-data-local/protocol/openid-connect/token \
        -d grant_type=client_credentials -u saas-data-local:dev-secret | jq -r .access_token)
$ curl -s http://localhost:9090/v1/users \
    -H "Authorization: Bearer $TOK" | jq .
# Expected: 200 with empty list

# 7. Create user → KC user exists.
$ curl -s -X POST http://localhost:9090/v1/users \
    -H "Authorization: Bearer $TOK" \
    -H "Idempotency-Key: idem_$(uuidgen | tr -d '-' | tr 'a-z' 'A-Z' | head -c 26)" \
    -H "Content-Type: application/json" \
    -d '{"email":"alice@example.com","name":"Alice"}' | jq .
$ docker compose exec keycloak /opt/keycloak/bin/kcadm.sh get users \
    -r saas-data-local --fields username,email | jq .

# 8. Trigger password reset → mailhog receives.
$ curl -s -X POST http://localhost:9090/v1/users/<id>/reset-password \
    -H "Authorization: Bearer $TOK" -H "Idempotency-Key: idem_..."
$ curl -s http://localhost:8025/api/v2/messages | jq '.items[0].Content.Headers.Subject'
# Expected: "Update your password"

# 9. Social login start.
$ curl -s -X POST http://localhost:9090/v1/users/<id>/social-providers \
    -H "Authorization: Bearer $TOK" -H "Idempotency-Key: idem_..." \
    -H "Content-Type: application/json" \
    -d '{"provider":"google","return_to":"http://localhost:9090/callback-test"}' | jq .
# Expected: authorization_url, state, expires_at

# 10. Lookup by email round-trips (HMAC works).
$ go test -run TestIdentity_EmailLookupHMAC -v ./internal/dataplane/identity/...
```

---

## Anti-pattern guards

- **NEVER** read `tenant_id` from a Keycloak attribute as authoritative. The JWT's `tenant_id` claim is verified by the JWKS-signed token; the attribute is only used during KC user creation.
- **NEVER** verify `tenant_id` before `aud`. `jwt.WithAudience` must run before any `Get("tenant_id", ...)` access.
- **NEVER** persist a plaintext email column. Use the `email_lookup_hash` (HMAC with per-Deployment key) for uniqueness; envelope-encrypt the plaintext.
- **NEVER** re-import a realm JSON to apply config drift. `01-foundations.md` §8 anti-pattern. Use gocloak.
- **NEVER** `LoginAdmin` (username/password). Use `LoginClient` with the platform's service-account client.
- **NEVER** call `ExecuteActionsEmail` from a code path that should send via the platform's Notifications module. Phase 6 swaps the password-reset email to use Notifications + Novu; for Phase 5, Keycloak's built-in SMTP is the explicit deferred trade-off.
- **NEVER** trust the `code` from the social callback without checking that the matching `state` row exists, is fresh, and belongs to the claimed user.
- **NEVER** allow a state to be reused. Delete after one consumption; if the request fails, the client must restart the flow.
- **NEVER** log a JWT in full. The slog redactor catches `authorization` headers; raw token strings in app code go through `[REDACTED]`.
- **NEVER** add a new IdP provider without an ADR (Microsoft, Facebook, LinkedIn are out of MVP).

---

## Open questions

1. **Realm name for Phase 5 local dev.** Default: `saas-data-local`. Phase 12 introduces per-Deployment realms. Confirm.
2. **Apple Sign-In.** Apple's "Sign in with Apple" requires the platform to be an Apple Developer Program member with a Services ID configured. For local dev we leave the Apple stanza in the realm template but disabled. Production turn-on requires the operator to fill in `apple.team_id`, `apple.client_id`, `apple.private_key`, `apple.key_id` in OpenBao KV.
3. **Email lookup HMAC vs deterministic envelope.** Default: HMAC-SHA256 with per-Deployment HMAC key in OpenBao KV. Alternative: deterministic envelope (`transit/encrypt/<kid>` with `derived=true` and a context). HMAC is simpler and faster; deterministic envelope means email lookup goes through OpenBao on every read. Confirm HMAC.
4. **Soft-delete behaviour.** Per default: deleted user keeps row + KC disabled + status='deleted'. Hard-delete is the `/control/v1/deployments/{id}/purge` path (Phase 12e). Confirm acceptable.
5. **Email change flow.** Not implemented in Phase 5 (no endpoint). If a user changes email, the operator currently re-creates the user. Add to v1 roadmap.

---

## Phase 5 — Definition of done

- [ ] OpenAPI specs updated; `make openapi-check` green
- [ ] Migrations 000003 applied; `platform_user`, `identity_provider_mapping`, `social_login_state` exist with RLS
- [ ] `internal/dataplane/identity/` complete (domain, ports, service, repo, provider, social, handler, errors + tests)
- [ ] Keycloak realm `saas-data-local` imported via compose; mailhog wired
- [ ] gocloak v14 adapter verified against testcontainers KC 26
- [ ] jwx v3 JWT verifier wired in `cmd/dataplane/main.go`; mock middleware confined to `!prod` builds
- [ ] `email_lookup_hash` HMAC implemented; per-Deployment HMAC key stored in OpenBao KV
- [ ] §17.3 authorization matrix tests pass for every Users endpoint
- [ ] Social link/unlink flow E2E with at least one provider (Google preferred since easiest to register a test app)
- [ ] TS SDK regenerated + workflow wrapper added
- [ ] saasctl `user *` commands added
- [ ] ADRs 007 + 014 committed
- [ ] All Phase 2/3/4 tests still green
- [ ] PR template, `ready` label, CI green

---

End of Phase 5. Next: `07-notifications-novu.md`.
