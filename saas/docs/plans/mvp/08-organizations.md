# Phase 7 — Organizations + Members + Invitations

> **Goal**: Ship the Organizations resource and its supporting Members and Invitations sub-resources end-to-end. Land the optional `multi_org` per-Deployment flag (defaulted OFF in MVP — auto-create one Organization per Tenant). Use Phase 6 Notifications to send invitation emails. Mark all PII (member name, invite email) with the persistence walker. Land §17.3 authorization tests across all endpoints.
>
> **Why now**: AGENTS.md §16 puts Organizations after Identity and Notifications because invitations need to send email, and members reference users. Phase 8 RBAC depends on the `member` resource existing (Casbin's `sub` = `member_id`). Phase 9 API keys are scoped to a tenant + can be created by a member. Phase 10 audit emits `member.added`, `member.removed`, `member.role_changed` events. Organizations must land before any of those.
>
> **What this phase does NOT do**: No SCIM provisioning (v1 roadmap). No org-level billing (v1). No org-level entitlements (v1). No team/group nesting inside an org (out of MVP per §7 note). The multi-org flag is wired but defaulted off; Phase 7 makes it work for tenants that opt in but does not promote multi-org to default behaviour.
>
> **Maps to AGENTS.md**: §7 (resource model: Organization, Member, Invitation), §8.2 (endpoints), §12.4 (Organizations module), §17.3 (authz matrix mandatory), §18.3 (audit list: member.added/removed/role_changed; invitation events not on the §18.3 list but added for consistency), §18.5 (PII: member name, invite email), §18.7 (invitation token envelope-encrypted), §21 (workflow: invite-member). `01-foundations.md` §13 (ID prefixes `org_`, `member_`, `inv_`).
>
> **Estimated subagent sessions**: 2-3 (one for OpenAPI + migration; one for module impl; one for invite flow + email + tests).

---

## Pre-flight

1. AGENTS.md §7 (Tenant vs Organization note), §8.2, §12.4, §17.3, §18.3.
2. Phase 6 (`07-notifications-novu.md`) — confirm `notifications.Send` ready; `member.invited` workflow seeded.
3. CONVENTIONS.md §10 (PII), §3 (service signatures).
4. `01-foundations.md` §13 (ID prefixes), §11 (idempotency + ETag).
5. Phase 5 — confirm Users API ready (members reference users).

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Multi-org behaviour | Default OFF — a Tenant has exactly one auto-created Organization with slug `default` (created in Phase 2's `Tenants.Create` post-hook; this phase adds the table + back-fills) | Multi-org always-on (refused — overcomplicates the 90% case) |
| Member role at invite time | One role allowed at invitation; assigned at acceptance time | Multiple roles (refused — Phase 8 RBAC handles multi-role) |
| Invitation token format | `inv_<ulid>` opaque, single-use, 7-day TTL, stored envelope-encrypted | JWT (refused — unrevocable until expiry); HMAC (refused — same revocation problem) |
| Invitation email transport | Phase 6 Notifications with workflow `member.invited` | Direct SMTP (refused — duplicates the abstraction) |
| Member soft-delete | Soft (status='removed') for audit trail; physical delete via tenant purge only | Hard delete (refused — breaks audit chain) |
| Accept flow auth | Invitee must be authenticated; their JWT user_id must match the invitation's `invitee_user_id` (set at invite time when the invitee already has a user row), OR the invitee creates a new user via the accept flow (when `invitee_user_id` is null at invite time) | Token-only accept (refused — anonymous joins are a phishing vector) |
| Invitation list visibility | Org admins see all invitations for the org; tenant admins see all invitations across all orgs in the tenant; non-admins see only invitations they sent | Show all to all members (refused — leaks who else is being invited) |

If the user disagrees with any default, stop.

---

## Tasks

### 7.1 OpenAPI spec — `/v1/tenants/{tenant_id}/organizations` + `/v1/organizations/...` + `/v1/invitations/...`

`openapi/data-plane.yaml` additions:

```yaml
tags:
  - name: organizations
    description: Teams inside a tenant. Optional second isolation layer.
  - name: members
    description: User membership in an organization.
  - name: invitations
    description: Pending member invitations.

paths:
  /v1/tenants/{tenant_id}/organizations:
    parameters:
      - { in: path, name: tenant_id, required: true, schema: { type: string, pattern: "^tenant_[0-9A-HJKMNP-TV-Z]{26}$" } }
    get:  { operationId: listOrganizations, tags: [organizations], parameters: [ { $ref: "#/components/parameters/Limit" }, { $ref: "#/components/parameters/Cursor" }, { $ref: "#/components/parameters/Sort" } ], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/OrganizationListResponse" } } } } } }
    post: { operationId: createOrganization, tags: [organizations], parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/CreateOrganizationRequest" } } } }, responses: { "201": { headers: { ETag: { schema: { type: string } } }, content: { application/json: { schema: { $ref: "#/components/schemas/OrganizationResponse" } } } } } }

  /v1/organizations/{organization_id}:
    parameters: [ { in: path, name: organization_id, required: true, schema: { type: string, pattern: "^org_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    get:    { operationId: getOrganization, tags: [organizations], responses: { "200": { headers: { ETag: { schema: { type: string } } }, content: { application/json: { schema: { $ref: "#/components/schemas/OrganizationResponse" } } } } } }
    patch:  { operationId: updateOrganization, tags: [organizations], parameters: [ { $ref: "#/components/parameters/IfMatch" }, { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/UpdateOrganizationRequest" } } } }, responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/OrganizationResponse" } } } } } }
    delete: { operationId: deleteOrganization, tags: [organizations], parameters: [ { $ref: "#/components/parameters/IfMatch" } ], responses: { "204": { description: Soft-deleted. } } }

  /v1/organizations/{organization_id}/members:
    parameters: [ { in: path, name: organization_id, required: true, schema: { type: string } } ]
    get:  { operationId: listMembers, tags: [members], parameters: [ { $ref: "#/components/parameters/Limit" }, { $ref: "#/components/parameters/Cursor" } ], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/MemberListResponse" } } } } } }

  /v1/organizations/{organization_id}/members/{member_id}:
    parameters: [ { in: path, name: organization_id, required: true, schema: { type: string } }, { in: path, name: member_id, required: true, schema: { type: string, pattern: "^member_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    get:    { operationId: getMember, tags: [members], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/MemberResponse" } } } } } }
    delete: { operationId: removeMember, tags: [members], parameters: [ { $ref: "#/components/parameters/IfMatch" } ], responses: { "204": { description: "Soft-removed; status=removed." } } }

  /v1/organizations/{organization_id}/invitations:
    parameters: [ { in: path, name: organization_id, required: true, schema: { type: string } } ]
    get:  { operationId: listInvitations, tags: [invitations], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/InvitationListResponse" } } } } } }
    post: { operationId: createInvitation, tags: [invitations], parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/CreateInvitationRequest" } } } }, responses: { "201": { content: { application/json: { schema: { $ref: "#/components/schemas/InvitationResponse" } } } } } }

  /v1/invitations/{invitation_id}:
    parameters: [ { in: path, name: invitation_id, required: true, schema: { type: string, pattern: "^inv_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    delete: { operationId: cancelInvitation, tags: [invitations], parameters: [ { $ref: "#/components/parameters/IfMatch" } ], responses: { "204": { description: Cancelled. } } }

  /v1/invitations/{invitation_id}/accept:
    parameters: [ { in: path, name: invitation_id, required: true, schema: { type: string } } ]
    post:
      operationId: acceptInvitation
      tags: [invitations]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/AcceptInvitationRequest" }
      responses:
        "200":
          description: Member created (status=active).
          content: { application/json: { schema: { $ref: "#/components/schemas/MemberResponse" } } }
        "410":
          description: Invitation expired or already used.
          content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }

components:
  schemas:
    Organization:
      type: object
      required: [id, object, tenant_id, slug, name, status, created_at, updated_at, etag]
      properties:
        id:        { type: string }
        object:    { type: string, enum: [organization] }
        tenant_id: { type: string }
        slug:      { type: string, pattern: "^[a-z][a-z0-9-]*[a-z0-9]$", minLength: 2, maxLength: 32 }
        name:      { type: string, minLength: 1, maxLength: 120 }
        status:    { type: string, enum: [active, deleted] }
        metadata:  { $ref: "#/components/schemas/Metadata" }
        created_at: { type: string, format: date-time }
        updated_at: { type: string, format: date-time }
        etag:       { type: string }

    Member:
      type: object
      required: [id, object, organization_id, tenant_id, user_id, status, created_at, etag]
      properties:
        id:               { type: string }
        object:           { type: string, enum: [member] }
        organization_id:  { type: string }
        tenant_id:        { type: string }
        user_id:          { type: string }
        display_name:     { type: string, x-oapi-codegen-extra-tags: { pii: "true" } }
        status:           { type: string, enum: [active, removed] }
        created_at:       { type: string, format: date-time }
        removed_at:       { type: [string, "null"], format: date-time }
        etag:             { type: string }

    Invitation:
      type: object
      required: [id, object, organization_id, email, status, created_at, expires_at]
      properties:
        id:               { type: string }
        object:           { type: string, enum: [invitation] }
        organization_id:  { type: string }
        tenant_id:        { type: string }
        email:            { type: string, format: email, x-oapi-codegen-extra-tags: { pii: "true" } }
        invitee_user_id:  { type: [string, "null"] }
        invited_by:       { type: string }
        suggested_role_id: { type: [string, "null"] }
        status:           { type: string, enum: [pending, accepted, cancelled, expired] }
        created_at:       { type: string, format: date-time }
        accepted_at:      { type: [string, "null"], format: date-time }
        expires_at:       { type: string, format: date-time }

    CreateOrganizationRequest:
      type: object
      required: [slug, name]
      properties:
        slug: { type: string }
        name: { type: string }
        metadata: { $ref: "#/components/schemas/Metadata" }

    UpdateOrganizationRequest:
      type: object
      properties:
        name:     { type: string }
        metadata: { $ref: "#/components/schemas/Metadata" }

    CreateInvitationRequest:
      type: object
      required: [email]
      properties:
        email:            { type: string, format: email, x-oapi-codegen-extra-tags: { pii: "true" } }
        suggested_role_id: { type: string }
        message:          { type: string, maxLength: 500 }

    AcceptInvitationRequest:
      type: object
      required: [token]
      properties:
        token: { type: string, description: "Token from invitation email link." }

    OrganizationResponse:      { type: object, properties: { data: { $ref: "#/components/schemas/Organization" } } }
    OrganizationListResponse:  { type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/Organization" } }, pagination: { $ref: "#/components/schemas/Pagination" } } }
    MemberResponse:            { type: object, properties: { data: { $ref: "#/components/schemas/Member" } } }
    MemberListResponse:        { type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/Member" } }, pagination: { $ref: "#/components/schemas/Pagination" } } }
    InvitationResponse:        { type: object, properties: { data: { $ref: "#/components/schemas/Invitation" } } }
    InvitationListResponse:    { type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/Invitation" } } } }
```

### 7.2 Migration — `migrations/dataplane/000005_organizations.up.sql`

```sql
CREATE TABLE organization (
    id          text PRIMARY KEY CHECK (id LIKE 'org_%'),
    tenant_id   text NOT NULL REFERENCES tenant (id),
    slug        text NOT NULL,
    name        text NOT NULL,
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active','deleted')),
    metadata    jsonb NOT NULL DEFAULT '{}'::jsonb,
    row_seq     bigint NOT NULL DEFAULT 1,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz,
    UNIQUE (tenant_id, slug) WHERE deleted_at IS NULL
);
CREATE TRIGGER organization_bump_row_seq BEFORE UPDATE ON organization FOR EACH ROW EXECUTE FUNCTION bump_row_seq();
ALTER TABLE organization ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization FORCE  ROW LEVEL SECURITY;
CREATE POLICY organization_tenant_only ON organization USING (tenant_id = current_setting('app.current_tenant_id', true));

CREATE TABLE member (
    id               text PRIMARY KEY CHECK (id LIKE 'member_%'),
    organization_id  text NOT NULL REFERENCES organization (id),
    tenant_id        text NOT NULL REFERENCES tenant (id),
    user_id          text NOT NULL REFERENCES platform_user (id),
    -- Display name is PII; encrypted via persist walker.
    display_name_ciphertext  bytea,
    display_name_wrapped_dek text,
    display_name_nonce       bytea,
    display_name_kid         text,
    display_name_key_version integer,
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active','removed')),
    row_seq          bigint NOT NULL DEFAULT 1,
    created_at       timestamptz NOT NULL DEFAULT now(),
    removed_at       timestamptz,
    UNIQUE (organization_id, user_id) WHERE status = 'active'
);
CREATE TRIGGER member_bump_row_seq BEFORE UPDATE ON member FOR EACH ROW EXECUTE FUNCTION bump_row_seq();
ALTER TABLE member ENABLE ROW LEVEL SECURITY;
ALTER TABLE member FORCE  ROW LEVEL SECURITY;
CREATE POLICY member_tenant_only ON member USING (tenant_id = current_setting('app.current_tenant_id', true));

CREATE TABLE invitation (
    id                text PRIMARY KEY CHECK (id LIKE 'inv_%'),
    organization_id   text NOT NULL REFERENCES organization (id),
    tenant_id         text NOT NULL REFERENCES tenant (id),
    -- Invite email is PII; encrypted via walker.
    email_lookup_hash bytea NOT NULL,
    email_ciphertext  bytea NOT NULL,
    email_wrapped_dek text  NOT NULL,
    email_nonce       bytea NOT NULL,
    email_kid         text  NOT NULL,
    email_key_version integer NOT NULL,
    -- Token is envelope-encrypted so even DB-leak doesn't surface accept-tokens.
    token_ciphertext  bytea NOT NULL,
    token_wrapped_dek text  NOT NULL,
    token_nonce       bytea NOT NULL,
    token_kid         text  NOT NULL,
    token_key_version integer NOT NULL,
    -- HMAC of token for constant-time lookup at accept time.
    token_lookup_hash bytea NOT NULL UNIQUE,
    invitee_user_id   text REFERENCES platform_user (id),
    invited_by        text NOT NULL,                   -- member_id of inviter
    suggested_role_id text,
    status            text NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending','accepted','cancelled','expired')),
    message           text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    accepted_at       timestamptz,
    expires_at        timestamptz NOT NULL
);
CREATE INDEX invitation_status_idx ON invitation (organization_id, status);
CREATE INDEX invitation_expiry_idx ON invitation (expires_at) WHERE status = 'pending';
ALTER TABLE invitation ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitation FORCE  ROW LEVEL SECURITY;
CREATE POLICY invitation_tenant_only ON invitation USING (tenant_id = current_setting('app.current_tenant_id', true));

-- Per-Tenant multi_org flag.
ALTER TABLE tenant ADD COLUMN multi_org boolean NOT NULL DEFAULT false;

-- Back-fill: every existing tenant gets a default organization.
INSERT INTO organization (id, tenant_id, slug, name, status)
SELECT 'org_' || substr(md5(random()::text), 1, 26),
       t.id, 'default', 'Default Organization', 'active'
FROM tenant t
WHERE NOT EXISTS (SELECT 1 FROM organization o WHERE o.tenant_id = t.id);

-- After back-fill, set tenant.default_organization_id.
UPDATE tenant t
SET default_organization_id = o.id
FROM organization o
WHERE o.tenant_id = t.id AND o.slug = 'default'
  AND t.default_organization_id IS NULL;
```

The back-fill is wrapped in a transaction; if it fails (e.g. a tenant has a slug collision somehow), the migration rolls back and the operator investigates.

### 7.3 Module layout — `internal/dataplane/organizations/`

```text
internal/dataplane/organizations/
  domain.go         # Organization, Member, Invitation types
  ports.go          # OrganizationRepo, MemberRepo, InvitationRepo, EventPublisher
  service.go        # service orchestration; takes Notifications dep
  repo_pgx.go
  invite.go         # invite flow with token gen + envelope + notifications call
  handler.go
  errors.go
  service_test.go
  repo_pgx_test.go
  invite_test.go
  security_test.go
```

`ports.go`:

```go
package organizations

import "context"

type OrganizationRepo interface {
    Create(ctx context.Context, o Organization) (Organization, error)
    Get(ctx context.Context, tenantID, orgID string) (Organization, error)
    List(ctx context.Context, tenantID string, limit int, cursor *ListCursor) ([]Organization, bool, error)
    Update(ctx context.Context, tenantID, orgID string, seq int64, patch OrgPatch) (Organization, error)
    Delete(ctx context.Context, tenantID, orgID string, seq int64) error
}

type MemberRepo interface {
    Create(ctx context.Context, m Member) (Member, error)
    Get(ctx context.Context, tenantID, memberID string) (Member, error)
    List(ctx context.Context, tenantID, orgID string, limit int, cursor *ListCursor) ([]Member, bool, error)
    Remove(ctx context.Context, tenantID, memberID string, seq int64) error
}

type InvitationRepo interface {
    Create(ctx context.Context, inv Invitation) (Invitation, error)
    Cancel(ctx context.Context, tenantID, invID string, seq int64) error
    LookupByTokenHash(ctx context.Context, tokenHash []byte) (Invitation, error)
    MarkAccepted(ctx context.Context, invID string) error
    List(ctx context.Context, tenantID, orgID string) ([]Invitation, error)
    ExpireOlderThan(ctx context.Context, before time.Time) (int64, error)
}

// EmailNotifier is a narrow interface around Phase 6 Notifications.
type EmailNotifier interface {
    SendInvitation(ctx context.Context, tenantID, toEmail, inviteURL, fromName, orgName string) error
}
```

### 7.4 Invite flow

`invite.go`:

```go
package organizations

import (
    "context"
    "crypto/hmac"
    "crypto/rand"
    "crypto/sha256"
    "encoding/base64"
    "encoding/hex"
    "fmt"
    "time"

    "github.com/omarss/saas/internal/platform/auth"
    "github.com/omarss/saas/internal/platform/crypto/envelope"
    "github.com/omarss/saas/internal/platform/id"
)

const invitationTTL = 7 * 24 * time.Hour

// rawTokenBytes returns 32 random bytes; the URL-safe encoding is what the
// invitee receives by email.
func newRawToken() ([]byte, string) {
    raw := make([]byte, 32)
    _, _ = rand.Read(raw)
    return raw, base64.RawURLEncoding.EncodeToString(raw)
}

func tokenHash(hmacKey, raw []byte) []byte {
    h := hmac.New(sha256.New, hmacKey)
    h.Write(raw)
    return h.Sum(nil)
}

func (s *Service) CreateInvitation(ctx context.Context, tenantID, orgID, email string, suggestedRoleID, message string) (Invitation, error) {
    if err := auth.AssertTenant(ctx, tenantID); err != nil { return Invitation{}, err }
    inviter, ok := auth.PrincipalFromContext(ctx)
    if !ok { return Invitation{}, auth.ErrUnauthorized }

    rawToken, encodedToken := newRawToken()
    hmacKey, err := s.hmacFor(ctx, tenantID, "invitation_token")
    if err != nil { return Invitation{}, err }
    tokenLookupHash := tokenHash(hmacKey, rawToken)

    // Envelope-encrypt the raw token so DB exfil doesn't surface it.
    tokenEnv, err := s.enc.Encrypt(ctx, s.deploymentID, rawToken, []byte(orgID+"|invitation"))
    if err != nil { return Invitation{}, err }

    inv := Invitation{
        ID:              id.New(id.PrefixInvitation),
        OrganizationID:  orgID,
        TenantID:        tenantID,
        EmailPlaintext:  email,                  // walker encrypts on persist
        TokenEnvelope:   tokenEnv,
        TokenLookupHash: tokenLookupHash,
        InvitedBy:       inviter.ActorID,
        SuggestedRoleID: suggestedRoleID,
        Status:          "pending",
        Message:         message,
        CreatedAt:       time.Now(),
        ExpiresAt:       time.Now().Add(invitationTTL),
    }
    inv, err = s.invRepo.Create(ctx, inv)
    if err != nil { return Invitation{}, err }

    inviteURL := fmt.Sprintf("%s/invitations/accept?token=%s", s.publicBaseURL, encodedToken)
    if err := s.notifier.SendInvitation(ctx, tenantID, email, inviteURL, inviter.ActorID, orgID); err != nil {
        // Email failure does NOT roll back the invitation — operator can re-send.
        // Audit catches the failure.
    }

    _ = s.events.Publish(ctx, "member.invited", tenantID, map[string]any{
        "invitation_id": inv.ID, "organization_id": orgID, "invited_by": inviter.ActorID,
    })
    return inv, nil
}

func (s *Service) AcceptInvitation(ctx context.Context, encodedToken string) (Member, error) {
    raw, err := base64.RawURLEncoding.DecodeString(encodedToken)
    if err != nil { return Member{}, ErrInvalidToken }
    // The accept path is unauthenticated-by-tenant initially; the caller IS
    // the invitee, so we look up by token hash, validate, then require the
    // authenticated user to match invitee_user_id (or be a new user).
    inviter, ok := auth.PrincipalFromContext(ctx)
    if !ok { return Member{}, auth.ErrUnauthorized }

    // Resolve which tenant the invitation belongs to so we can hash.
    // Trick: the token hash includes a per-tenant HMAC key, but we don't know
    // which tenant yet. Solution: store the token hash with the per-DEPLOYMENT
    // HMAC key (one key per Deployment, not per-tenant). This is acceptable
    // because the data plane IS a single Deployment.
    hmacKey, err := s.hmacFor(ctx, "", "invitation_token_deployment_wide")
    if err != nil { return Member{}, err }
    inv, err := s.invRepo.LookupByTokenHash(ctx, tokenHash(hmacKey, raw))
    if err != nil { return Member{}, ErrInvalidToken }
    if inv.Status != "pending" { return Member{}, ErrInvitationConsumed }
    if time.Now().After(inv.ExpiresAt) {
        _ = s.invRepo.ExpireOlderThan(ctx, time.Now())
        return Member{}, ErrInvitationExpired
    }
    if inv.InviteeUserID != nil && *inv.InviteeUserID != inviter.ActorID {
        return Member{}, auth.ErrForbidden
    }

    m := Member{
        ID:             id.New(id.PrefixMember),
        OrganizationID: inv.OrganizationID,
        TenantID:       inv.TenantID,
        UserID:         inviter.ActorID,
        Status:         "active",
        CreatedAt:      time.Now(),
    }
    m, err = s.memberRepo.Create(ctx, m)
    if err != nil { return Member{}, err }
    _ = s.invRepo.MarkAccepted(ctx, inv.ID)

    _ = s.events.Publish(ctx, "member.joined", inv.TenantID, map[string]any{
        "member_id": m.ID, "organization_id": inv.OrganizationID, "user_id": inviter.ActorID,
    })
    return m, nil
}
```

**Subtlety**: the token hash uses a deployment-wide HMAC key (NOT per-tenant) because the accept flow doesn't know the tenant until after lookup. Token hashes are still unique across the deployment (32 random bytes → ~zero collision risk). The accept handler does NOT set the tenant context from the URL; it derives it from the looked-up invitation, then sets `app.current_tenant_id` for any subsequent queries. This is the ONE deviation from "tenant_id always from JWT" and is documented in CONVENTIONS.md as a specific exception.

### 7.5 Notifications integration — `member.invited` workflow

Phase 6's `make notifications-seed-default-workflows` target seeds an invitation workflow with default email template:

```text
Subject: You're invited to join {org_name}
Body:    {inviter_name} invited you to {org_name}. Accept by clicking {invite_url}.
         This invite expires on {expires_at}.
         If you weren't expecting this, ignore this email.
```

`notifications.Send` is called with workflow_name="member.invited" + payload {invite_url, org_name, inviter_name, expires_at}. Phase 6's outbox subscriber triggers Novu, which sends via the active email channel.

### 7.6 Tenants service auto-creates default organization

Update Phase 2's `Tenants.Create`:

```go
t, err := s.repo.Create(ctx, ...)
if err != nil { return Tenant{}, err }
// Auto-create default org per §7 note.
org, err := s.orgs.AutoCreateDefault(ctx, t.ID)
if err != nil { return Tenant{}, err }
_ = s.repo.SetDefaultOrganization(ctx, t.ID, org.ID)
```

This adds a dependency from `tenancy.Service` → `organizations.Service`. The wiring in `cmd/dataplane/main.go` becomes: build organizations module first, inject into tenancy.

### 7.7 §17.3 authorization matrix tests

For every endpoint:

| Test | Assert |
|---|---|
| Same-tenant access on /v1/tenants/{tid}/organizations | 200 |
| Cross-tenant access on /v1/tenants/{tid_other}/organizations | 403 (tenant_id is in URL → explicit deny) |
| Cross-tenant access on /v1/organizations/{org_id_of_other_tenant} | 404 (no path-tenant → existence hidden) |
| Cross-org member list within same tenant | 200 — same tenant, different org; whether to allow depends on RBAC (Phase 8); for now, allow if same tenant |
| Accept invitation when caller is not invitee_user_id | 403 |
| Accept expired invitation | 410 Gone |
| Accept already-accepted invitation | 410 Gone |
| Accept invalid token | 410 |
| Create invitation as non-member | 403 |
| Create invitation as member without scope | 403 (Phase 8 introduces granular scopes; Phase 7 defaults to "any member can invite" with a TODO note) |
| List invitations as non-admin | 200 with only own-invitations (Phase 8 tightens) |

### 7.8 Audit events

Emitted to outbox (consumed by Phase 10):

- `member.invited` — when invitation created
- `member.joined` — when invitation accepted
- `member.removed` — when removeMember called
- `invitation.cancelled` — when cancelInvitation called
- `invitation.expired` — by the cleanup ticker
- `organization.created` / `.updated` / `.deleted`

### 7.9 Cleanup ticker

`internal/dataplane/organizations/expire.go` — a 5-min ticker that calls `ExpireOlderThan(now())`, flips matching pending invitations to status='expired', and emits `invitation.expired` audit events. Wired in `cmd/dataplane/main.go`.

### 7.10 TS SDK regeneration + workflow wrappers

```bash
make sdk-ts
```

`sdk/ts/data-plane/workflows/organizations.ts` exposes `create`, `list`, `get`, `update`, `listMembers`, `removeMember`, `invite`, `cancelInvitation`, `acceptInvitation`.

### 7.11 saasctl

```text
saasctl org create --tenant <id> --slug <s> --name <n>
saasctl org list --tenant <id>
saasctl member list --org <id>
saasctl member remove <member_id>
saasctl invitation create --org <id> --email <e> [--suggested-role <role_id>]
saasctl invitation list --org <id>
saasctl invitation cancel <inv_id>
```

### 7.12 ADRs

This phase does not introduce a brand-new ADR from the master table (00-master.md's ADR list does not include a phase-7-specific ADR). Document the multi-org default-OFF and the accept-flow exception (URL-derived tenant) inline in CONVENTIONS.md §3 (service signatures) as a documented exception.

If the user wants a dedicated ADR for the multi-org policy, create `docs/adr/018-multi-org-default-off.md` covering: rationale, migration path to multi-org=on, impact on RBAC scoping. Confirm with user before adding to the ADR ledger.

### 7.13 Commits

```bash
git add openapi/data-plane.yaml openapi/problems/
git commit -m "add organizations members invitations endpoints"

git add migrations/dataplane/000005_organizations.up.sql internal/dataplane/db/queries/organizations.sql
git commit -m "add organization member invitation tables"

git add internal/dataplane/organizations/
git commit -m "implement organizations module"

git add internal/dataplane/tenancy/  # auto-create default org
git commit -m "auto create default org on tenant create"

git add sdk/ts/data-plane/workflows/organizations.ts cmd/saasctl/
git commit -m "ts sdk and saasctl org coverage"

git add CONVENTIONS.md
git commit -m "document accept flow tenant exception"
```

---

## Verification checklist

```bash
# 1. Migrations apply; back-fill creates default orgs for any existing tenants.
$ make migrate
$ psql -c "SELECT t.id, o.id, o.slug FROM tenant t JOIN organization o ON o.tenant_id = t.id;"
# Expected: every tenant has exactly one org with slug='default'

# 2. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 3. §17.3 matrix.
$ go test -run TestOrganizations_AuthZ -v ./internal/dataplane/organizations/...

# 4. Create tenant → default org auto-created.
$ curl -X POST http://localhost:9090/v1/tenants ... -d '{"slug":"acme","name":"Acme"}'
$ curl http://localhost:9090/v1/tenants/<id>/organizations ... | jq '.data | length'
# Expected: 1, with slug=default

# 5. Invite + accept E2E.
$ curl -X POST http://localhost:9090/v1/organizations/<org>/invitations ... -d '{"email":"bob@example.com"}'
# Email arrives in mailhog.
$ curl http://localhost:8025/api/v2/messages | jq '.items[0].Content.Body' | grep "invitations/accept"
# Click the URL → extract token.
$ TOKEN=...
# Bob's JWT (mock or real); accept.
$ curl -X POST http://localhost:9090/v1/invitations/<inv>/accept \
    -H "Authorization: Bearer $BOB_TOK" -H "Idempotency-Key: idem_..." \
    -d "{\"token\":\"$TOKEN\"}"
# Expected: 200 with member object.

# 6. Re-accept same invitation → 410.
$ curl -X POST http://localhost:9090/v1/invitations/<inv>/accept ... -d "{\"token\":\"$TOKEN\"}"
# Expected: 410 problem invitation-consumed.

# 7. Invitation expiry ticker.
$ # Manipulate expires_at in DB to past; wait 5 min or call cleanup manually.
$ psql -c "UPDATE invitation SET expires_at = now() - interval '1 minute' WHERE id = '<inv>';"
$ sleep 310
$ psql -c "SELECT status FROM invitation WHERE id = '<inv>';"
# Expected: status='expired'

# 8. Remove member.
$ curl -X DELETE http://localhost:9090/v1/organizations/<org>/members/<member> -H "Authorization: Bearer $TOK" -H "If-Match: W/\"v1\""
$ psql -c "SELECT status, removed_at FROM member WHERE id = '<member>';"
# Expected: status='removed', removed_at set

# 9. PII redaction: invitation email never appears in logs.
$ grep "bob@example.com" /tmp/dataplane.log | wc -l
# Expected: 0

# 10. Cross-tenant access deny.
$ curl http://localhost:9090/v1/tenants/<other_tenant>/organizations -H "Authorization: Bearer $TOK"
# Expected: 403 with cross-tenant-access-denied problem.
```

---

## Anti-pattern guards

- **NEVER** look up an invitation by `token` (plaintext). Always by `token_lookup_hash`. The plaintext token never touches the DB.
- **NEVER** persist the accept token in plaintext. It's envelope-encrypted in `token_ciphertext` for forensic recovery (operator can decrypt if needed), but the canonical lookup is via HMAC hash.
- **NEVER** allow accepting an invitation with the wrong invitee (`invitee_user_id != caller.ActorID`).
- **NEVER** return the raw token in any API response after the initial create. The token only travels via the invite email.
- **NEVER** allow an authenticated user to enumerate invitations across tenants. The invitation tables have RLS; query joins with tenant binding only.
- **NEVER** auto-promote a member to org admin. Role assignment is Phase 8's responsibility; Phase 7 members are role-less until then.
- **NEVER** delete an organization without checking for active members. Soft-delete with status='deleted' marks it; physical purge belongs to Phase 12e (`/control/v1/deployments/{id}/purge`).
- **NEVER** allow multi-org=on without an ADR. Default is off; flipping it requires confirmed business need.

---

## Open questions

1. **Multi-org promotion**. Should a tenant be able to flip multi_org=true at any time? Default: yes, via PATCH /v1/tenants/{id} (Phase 2 endpoint, extended). Flipping back to false requires no active orgs beyond `default`. Confirm.
2. **Suggested role at invite time**. Default: invitation carries a `suggested_role_id` field but role assignment happens AFTER member creation via Phase 8 endpoints. The invite UI passes the suggestion through. Confirm that's acceptable, or whether role should be assigned atomically with member creation in the accept handler.
3. **Self-service invitation cancellation**. Should the invitee be able to cancel their own pending invitation? Default: only the original inviter or org admin. Confirm.
4. **Invitation reminder emails**. Out of MVP. Add to v1 roadmap.

---

## Phase 7 — Definition of done

- [ ] OpenAPI updated; `make openapi-check` green
- [ ] Migrations 000005 applied; `organization`, `member`, `invitation` tables exist with RLS + persist-walker fields
- [ ] `internal/dataplane/organizations/` complete: domain, ports, service, repos, invite, handler, errors, tests
- [ ] `Tenants.Create` auto-creates default org; back-fill applied to existing tenants
- [ ] Invitation email flows through Phase 6 Notifications → mailhog receives
- [ ] Accept flow validates token via HMAC hash; expired/used invitations return 410
- [ ] Invitation expiry ticker runs every 5 min; flips pending → expired
- [ ] §17.3 authorization matrix covers every endpoint (12 cases minimum)
- [ ] PII (member name, invite email) marked + walker encrypts on persist
- [ ] Audit events emitted: member.invited, .joined, .removed, .role_changed (Phase 8 will add the last one), invitation.cancelled, .expired, organization.created/.updated/.deleted
- [ ] TS SDK regenerated + workflow wrapper added
- [ ] saasctl org / member / invitation subtrees wired
- [ ] CONVENTIONS.md updated to document the accept-flow tenant-context exception
- [ ] All Phase 2-6 tests still green
- [ ] PR template, `ready` label, CI green

---

End of Phase 7. Next: `09-rbac-casbin.md`.
