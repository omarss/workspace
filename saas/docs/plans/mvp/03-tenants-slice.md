# Phase 2 — Tenants Vertical Slice (End-to-End)

> **Goal**: One module — Tenants — built fully end-to-end so it becomes the template every subsequent module copies. OpenAPI spec → handler → service → port → adapter → sqlc queries → migration → contract test → authorization tests → audit emission → TS SDK regeneration → saasctl `tenant list` e2e.
>
> **Why this slice first**: AGENTS.md §16 Phase 2 explicitly mandates Tenants as the first vertical slice. Tenants are the unit of isolation; getting tenant_id-from-JWT and RLS right here establishes the pattern.
>
> **What this phase does NOT do**: No real provisioning yet (Phase 11+). No identity yet (Phase 5). No RBAC yet (Phase 8). Tenants are created via a mock JWT in tests; the real auth wiring comes in Phase 3 (platform patterns) and Phase 5 (Identity).
>
> **Maps to AGENTS.md**: §16 Phase 2; §3.6 internal architecture (hexagonal); §5 (idempotency, etag, pagination, RFC 9457); §7 (Tenant resource); §8.1 (endpoints); §9 (events); §17.3 (authorization tests); §18.1 (tenant isolation, RLS).
>
> **Estimated subagent sessions**: 2-3 (one for OpenAPI spec + migration, one for handler/service/adapter, one for tests + SDK).

---

## Pre-flight

1. `AGENTS.md`, `CLAUDE.md`, `00-master.md`, `01-foundations.md` — read.
2. Phase 1 complete (`make build`, `make compose-up`, `make migrate`, `/healthz` green).
3. Confirm with the user: this phase introduces `auth.TenantFromContext` with a **mock implementation** that reads a `X-Mock-Tenant-Id` header (dev-only, never in prod builds). Real JWT verification lands in Phase 5. This is necessary because Identity comes later in the phase order.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Mock auth header | `X-Mock-Tenant-Id` accepted only when `SAAS_ENV != "prod"` (build tag `dev`); production builds reject it with 401 | Stub a JWT issuer in Phase 2; significantly more setup work |
| Tenant slug uniqueness | Globally unique within a Deployment (the Deployment is already an isolation boundary) | Per-Region uniqueness; unused for MVP |
| `auto_create_default_organization` | True on tenant create (matches §7) | Off, requiring explicit org creation |
| Soft-delete retention | 30 days, configurable per Deployment | Hard delete only |
| Outbox dispatcher | Single in-process goroutine in the data-plane binary; polls every 250 ms; commits offset in same DB | External worker (Phase 11+); NATS deferred |

If the user disagrees with any default, stop and revise before writing migrations.

---

## Tasks

### 2.1 OpenAPI spec — `/v1/tenants`

`openapi/data-plane.yaml` (add to existing file from Phase 1):

```yaml
tags:
  - name: tenants
    description: Tenant CRUD. Tenant is the unit of isolation and billing.

paths:
  /v1/tenants:
    get:
      operationId: listTenants
      tags: [tenants]
      summary: List tenants for the caller's Deployment.
      parameters:
        - $ref: "#/components/parameters/Limit"
        - $ref: "#/components/parameters/Cursor"
        - $ref: "#/components/parameters/Sort"
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/TenantListResponse"
        "401": { $ref: "#/components/responses/Unauthorized" }
        "410": { $ref: "#/components/responses/CursorGone" }
        "429": { $ref: "#/components/responses/RateLimited" }
    post:
      operationId: createTenant
      tags: [tenants]
      summary: Create a tenant. Auto-creates a default Organization.
      parameters:
        - $ref: "#/components/parameters/IdempotencyKey"
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/CreateTenantRequest"
      responses:
        "201":
          description: Created
          headers:
            ETag: { schema: { type: string } }
            Location: { schema: { type: string, format: uri-reference } }
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/TenantResponse"
        "401": { $ref: "#/components/responses/Unauthorized" }
        "409": { $ref: "#/components/responses/IdempotencyInFlight" }
        "422": { $ref: "#/components/responses/IdempotencyConflictOrValidation" }

  /v1/tenants/{tenant_id}:
    parameters:
      - { in: path, name: tenant_id, required: true, schema: { type: string, pattern: "^tenant_[0-9A-HJKMNP-TV-Z]{26}$" } }
    get:
      operationId: getTenant
      tags: [tenants]
      responses:
        "200":
          description: OK
          headers:
            ETag: { schema: { type: string } }
          content:
            application/json:
              schema: { $ref: "#/components/schemas/TenantResponse" }
        "401": { $ref: "#/components/responses/Unauthorized" }
        "403": { $ref: "#/components/responses/Forbidden" }
        "404": { $ref: "#/components/responses/NotFound" }
    patch:
      operationId: updateTenant
      tags: [tenants]
      parameters:
        - $ref: "#/components/parameters/IfMatch"
        - $ref: "#/components/parameters/IdempotencyKey"
      requestBody:
        required: true
        content:
          application/json:
            schema: { $ref: "#/components/schemas/UpdateTenantRequest" }
      responses:
        "200":
          description: OK
          headers:
            ETag: { schema: { type: string } }
          content:
            application/json:
              schema: { $ref: "#/components/schemas/TenantResponse" }
        "401": { $ref: "#/components/responses/Unauthorized" }
        "403": { $ref: "#/components/responses/Forbidden" }
        "404": { $ref: "#/components/responses/NotFound" }
        "412": { $ref: "#/components/responses/PreconditionFailed" }
        "422": { $ref: "#/components/responses/IdempotencyConflictOrValidation" }
    delete:
      operationId: deleteTenant
      tags: [tenants]
      parameters:
        - $ref: "#/components/parameters/IfMatch"
      responses:
        "204": { description: Soft-deleted; retention applies. }
        "401": { $ref: "#/components/responses/Unauthorized" }
        "403": { $ref: "#/components/responses/Forbidden" }
        "404": { $ref: "#/components/responses/NotFound" }
        "412": { $ref: "#/components/responses/PreconditionFailed" }

components:
  schemas:
    Tenant:
      type: object
      required: [id, object, slug, name, status, created_at, updated_at, etag]
      properties:
        id:        { type: string, pattern: "^tenant_[0-9A-HJKMNP-TV-Z]{26}$" }
        object:    { type: string, enum: [tenant] }
        slug:      { type: string, minLength: 2, maxLength: 32, pattern: "^[a-z][a-z0-9-]*[a-z0-9]$" }
        name:      { type: string, minLength: 1, maxLength: 120 }
        status:    { type: string, enum: [active, suspended, deleted] }
        default_organization_id:
          type: [string, "null"]
          pattern: "^org_[0-9A-HJKMNP-TV-Z]{26}$"
        metadata:  { $ref: "#/components/schemas/Metadata" }
        created_at: { type: string, format: date-time }
        updated_at: { type: string, format: date-time }
        deleted_at: { type: [string, "null"], format: date-time }
        etag:       { type: string, description: 'Weak ETag; format W/"v<seq>".' }

    TenantResponse:
      type: object
      required: [data]
      properties:
        data: { $ref: "#/components/schemas/Tenant" }

    TenantListResponse:
      type: object
      required: [data, pagination]
      properties:
        data:
          type: array
          items: { $ref: "#/components/schemas/Tenant" }
        pagination: { $ref: "#/components/schemas/Pagination" }

    CreateTenantRequest:
      type: object
      required: [slug, name]
      properties:
        slug:     { type: string, minLength: 2, maxLength: 32, pattern: "^[a-z][a-z0-9-]*[a-z0-9]$" }
        name:     { type: string, minLength: 1, maxLength: 120 }
        metadata: { $ref: "#/components/schemas/Metadata" }

    UpdateTenantRequest:
      type: object
      properties:
        name:     { type: string, minLength: 1, maxLength: 120 }
        status:   { type: string, enum: [active, suspended] }
        metadata: { $ref: "#/components/schemas/Metadata" }

    Metadata:
      type: object
      maxProperties: 16
      additionalProperties: { type: string, maxLength: 256 }

    Pagination:
      type: object
      required: [has_more]
      properties:
        next_cursor: { type: [string, "null"] }
        has_more:    { type: boolean }

  parameters:
    Limit:
      in: query
      name: limit
      required: false
      schema: { type: integer, minimum: 1, maximum: 200, default: 25 }
    Cursor:
      in: query
      name: cursor
      required: false
      schema: { type: string }
    Sort:
      in: query
      name: sort
      required: false
      schema: { type: string, default: "-created_at" }
    IdempotencyKey:
      in: header
      name: Idempotency-Key
      required: true
      schema: { type: string, pattern: "^idem_[0-9A-HJKMNP-TV-Z]{26}$" }
    IfMatch:
      in: header
      name: If-Match
      required: true
      schema: { type: string }

  responses:
    Unauthorized:
      description: Missing or invalid bearer token / API key.
      content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }
    Forbidden:
      description: Caller lacks permission for this resource.
      content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }
    NotFound:
      description: Resource not found.
      content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }
    PreconditionFailed:
      description: If-Match header missing or stale.
      content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }
    IdempotencyInFlight:
      description: Concurrent request with the same Idempotency-Key is still processing.
      content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }
    IdempotencyConflictOrValidation:
      description: Idempotency-Key reused with a different body, OR validation failed.
      content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }
    CursorGone:
      description: Cursor schema version is no longer supported.
      content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }
    RateLimited:
      description: Rate limit exceeded.
      headers:
        RateLimit-Limit:     { schema: { type: integer } }
        RateLimit-Remaining: { schema: { type: integer } }
        RateLimit-Reset:     { schema: { type: integer } }
        Retry-After:         { schema: { type: integer } }
      content: { application/problem+json: { schema: { $ref: "#/components/schemas/Problem" } } }

  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
    apiKeyAuth:
      type: http
      scheme: bearer
      bearerFormat: API key

security:
  - bearerAuth: []
  - apiKeyAuth: []
```

The shared `Problem` schema lives in `openapi/problems/problem.yaml` and is `$ref`'d. Create it in this phase if Phase 1 didn't already.

### 2.2 Migration

`migrations/dataplane/000002_tenants.up.sql`:

```sql
-- Tenants: the unit of isolation within a Deployment.

CREATE TABLE tenant (
    id              text PRIMARY KEY CHECK (id LIKE 'tenant_%'),
    slug            text NOT NULL UNIQUE,
    name            text NOT NULL,
    status          text NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'suspended', 'deleted')),
    default_organization_id text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb
                    CHECK (jsonb_typeof(metadata) = 'object'
                           AND (SELECT count(*) FROM jsonb_object_keys(metadata)) <= 16),
    row_seq         bigint NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

CREATE INDEX tenant_slug_active_idx ON tenant (slug) WHERE deleted_at IS NULL;
CREATE INDEX tenant_status_idx      ON tenant (status) WHERE deleted_at IS NULL;
CREATE INDEX tenant_created_at_idx  ON tenant (created_at DESC);

-- ETag sequence trigger.
CREATE OR REPLACE FUNCTION bump_row_seq() RETURNS trigger AS $$
BEGIN
    NEW.row_seq    = OLD.row_seq + 1;
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tenant_bump_row_seq
    BEFORE UPDATE ON tenant
    FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

-- Row-Level Security. Tenants is the one tenant-bound table whose tenant_id IS its id —
-- the policy is identity. Subsequent tenant-bound tables use a tenant_id column.
ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_self_only ON tenant
    USING (id = current_setting('app.current_tenant_id', true));

-- Outbox table (one per data plane; events from all modules land here).
CREATE TABLE outbox_event (
    id              bigserial PRIMARY KEY,
    event_id        text NOT NULL UNIQUE CHECK (event_id LIKE 'evt_%'),
    type            text NOT NULL,
    event_version   integer NOT NULL DEFAULT 1,
    tenant_id       text,                       -- nullable for cross-tenant events
    deployment_id   text NOT NULL,
    occurred_at     timestamptz NOT NULL DEFAULT now(),
    payload         jsonb NOT NULL,
    published_at    timestamptz,
    delivery_attempts integer NOT NULL DEFAULT 0,
    last_error      text
);
CREATE INDEX outbox_unpublished_idx ON outbox_event (id) WHERE published_at IS NULL;

-- Idempotency record table.
CREATE TABLE idempotency_record (
    id                  bigserial PRIMARY KEY,
    tenant_id           text NOT NULL,
    idempotency_key     text NOT NULL,
    route               text NOT NULL,
    method              text NOT NULL,
    request_body_hash   bytea NOT NULL,
    response_status     integer,
    response_headers    jsonb NOT NULL DEFAULT '{}'::jsonb,
    response_body       bytea,
    in_flight           boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    UNIQUE (tenant_id, idempotency_key, route, method)
);
CREATE INDEX idempotency_expiry_idx ON idempotency_record (expires_at);
ALTER TABLE idempotency_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_record FORCE  ROW LEVEL SECURITY;
CREATE POLICY idempotency_tenant_only ON idempotency_record
    USING (tenant_id = current_setting('app.current_tenant_id', true));

-- App role grants. The app role NEVER has UPDATE/DELETE on outbox_event after publish
-- (that's enforced in Phase 10 audit). For Phase 2 the outbox is mutable.
-- The app role gets only the SELECT/INSERT/UPDATE/DELETE it needs.
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant TO PUBLIC;        -- placeholder; tightened in Phase 11c
GRANT USAGE,  SELECT ON SEQUENCE outbox_event_id_seq         TO PUBLIC;
GRANT SELECT, INSERT, UPDATE ON outbox_event                 TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_record   TO PUBLIC;
GRANT USAGE,  SELECT ON SEQUENCE idempotency_record_id_seq   TO PUBLIC;
```

`migrations/dataplane/000002_tenants.down.sql` (allowed, not required — forward-only is the policy, but down is harmless if no production data exists):

```sql
DROP TABLE IF EXISTS idempotency_record CASCADE;
DROP TABLE IF EXISTS outbox_event CASCADE;
DROP TRIGGER IF EXISTS tenant_bump_row_seq ON tenant;
DROP FUNCTION IF EXISTS bump_row_seq();
DROP TABLE IF EXISTS tenant CASCADE;
```

ADR 003 (RLS + GUC) is created in this phase. See 00-master.md for ADR list.

### 2.3 sqlc queries

`internal/dataplane/db/queries/tenants.sql`:

```sql
-- name: CreateTenant :one
INSERT INTO tenant (id, slug, name, metadata)
VALUES ($1, $2, $3, $4::jsonb)
RETURNING *;

-- name: GetTenant :one
SELECT * FROM tenant
WHERE id = $1 AND deleted_at IS NULL;

-- name: GetTenantBySlug :one
SELECT * FROM tenant
WHERE slug = $1 AND deleted_at IS NULL;

-- name: ListTenants :many
SELECT * FROM tenant
WHERE deleted_at IS NULL
  AND (
    sqlc.narg('cursor_created_at')::timestamptz IS NULL
    OR (
      created_at < sqlc.narg('cursor_created_at')::timestamptz
      OR (created_at = sqlc.narg('cursor_created_at')::timestamptz AND id < sqlc.narg('cursor_id'))
    )
  )
ORDER BY created_at DESC, id DESC
LIMIT sqlc.arg('limit')::int + 1;     -- +1 to detect has_more

-- name: UpdateTenant :one
UPDATE tenant
SET
    name     = COALESCE(sqlc.narg('name'),     name),
    status   = COALESCE(sqlc.narg('status'),   status),
    metadata = COALESCE(sqlc.narg('metadata')::jsonb, metadata)
WHERE id = $1
  AND row_seq = $2          -- optimistic concurrency (If-Match)
  AND deleted_at IS NULL
RETURNING *;

-- name: SoftDeleteTenant :one
UPDATE tenant
SET status = 'deleted',
    deleted_at = now()
WHERE id = $1
  AND row_seq = $2
  AND deleted_at IS NULL
RETURNING *;

-- name: SetDefaultOrganization :exec
UPDATE tenant SET default_organization_id = $2 WHERE id = $1;
```

Run `make sqlc-gen` to produce `internal/dataplane/db/sqlc/tenants.sql.go`.

`internal/dataplane/db/queries/outbox.sql`:

```sql
-- name: InsertOutboxEvent :one
INSERT INTO outbox_event (event_id, type, event_version, tenant_id, deployment_id, payload)
VALUES ($1, $2, $3, $4, $5, $6::jsonb)
RETURNING *;

-- name: ListUnpublishedOutbox :many
SELECT * FROM outbox_event
WHERE published_at IS NULL
ORDER BY id
LIMIT $1;

-- name: MarkOutboxPublished :exec
UPDATE outbox_event SET published_at = now() WHERE id = $1;

-- name: MarkOutboxFailed :exec
UPDATE outbox_event
SET delivery_attempts = delivery_attempts + 1, last_error = $2
WHERE id = $1;
```

`internal/dataplane/db/queries/idempotency.sql`:

```sql
-- name: ClaimIdempotencyRecord :one
INSERT INTO idempotency_record
    (tenant_id, idempotency_key, route, method, request_body_hash, expires_at)
VALUES ($1, $2, $3, $4, $5, now() + interval '24 hours')
ON CONFLICT (tenant_id, idempotency_key, route, method) DO NOTHING
RETURNING *;

-- name: GetIdempotencyRecord :one
SELECT * FROM idempotency_record
WHERE tenant_id = $1 AND idempotency_key = $2 AND route = $3 AND method = $4;

-- name: FinishIdempotencyRecord :exec
UPDATE idempotency_record
SET response_status = $2,
    response_headers = $3::jsonb,
    response_body = $4,
    in_flight = false
WHERE id = $1;

-- name: ExpireIdempotencyRecords :exec
DELETE FROM idempotency_record WHERE expires_at < now();
```

### 2.4 Domain types (`internal/dataplane/tenancy/`)

```text
internal/dataplane/tenancy/
  domain.go         # Tenant struct, Status enum, validation
  service.go        # Service (application-level orchestration)
  ports.go          # Repository interface, EventPublisher interface
  repo_pgx.go       # pgx-backed Repository implementation (uses sqlc-generated code)
  errors.go         # domain-level errors (ErrNotFound, ErrSlugTaken, ErrEtagMismatch)
  service_test.go   # unit tests (mocked repo)
  repo_pgx_test.go  # integration tests (testcontainers-go)
  security_test.go  # §17.3 authorization matrix
```

`domain.go`:

```go
package tenancy

import (
	"time"
)

type Status string

const (
	StatusActive    Status = "active"
	StatusSuspended Status = "suspended"
	StatusDeleted   Status = "deleted"
)

type Tenant struct {
	ID                    string
	Slug                  string
	Name                  string
	Status                Status
	DefaultOrganizationID *string
	Metadata              map[string]string
	RowSeq                int64
	CreatedAt             time.Time
	UpdatedAt             time.Time
	DeletedAt             *time.Time
}

func (t Tenant) ETag() string { return etagFor(t.RowSeq) }
func etagFor(seq int64) string { return `W/"v` + strconv.FormatInt(seq, 10) + `"` }
```

`ports.go`:

```go
package tenancy

import "context"

type Repository interface {
	Create(ctx context.Context, t Tenant) (Tenant, error)
	Get(ctx context.Context, id string) (Tenant, error)
	GetBySlug(ctx context.Context, slug string) (Tenant, error)
	List(ctx context.Context, limit int, cursor *ListCursor) ([]Tenant, bool, error)
	Update(ctx context.Context, id string, expectedSeq int64, patch UpdatePatch) (Tenant, error)
	SoftDelete(ctx context.Context, id string, expectedSeq int64) (Tenant, error)
}

type EventPublisher interface {
	Publish(ctx context.Context, eventType string, tenantID string, payload any) error
}

type ListCursor struct {
	CreatedAt time.Time
	ID        string
}

type UpdatePatch struct {
	Name     *string
	Status   *Status
	Metadata *map[string]string
}
```

`service.go` (orchestration; idempotency handled at handler layer):

```go
package tenancy

import (
	"context"
	"errors"
	"time"

	"github.com/oklog/ulid/v2"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

type Service struct {
	repo   Repository
	events EventPublisher
	now    func() time.Time
}

func NewService(repo Repository, events EventPublisher) *Service {
	return &Service{repo: repo, events: events, now: time.Now}
}

func (s *Service) Create(ctx context.Context, slug, name string, metadata map[string]string) (Tenant, error) {
	// Layer 2: this method takes no tenant_id explicitly because the new tenant ID *is*
	// the tenant_id — Tenants are special. All other modules' Service.Create signatures
	// MUST take tenantID as first arg after ctx.

	if _, err := s.repo.GetBySlug(ctx, slug); err == nil {
		return Tenant{}, ErrSlugTaken
	} else if !errors.Is(err, ErrNotFound) {
		return Tenant{}, err
	}
	t := Tenant{
		ID:        "tenant_" + ulid.Make().String(),
		Slug:      slug,
		Name:      name,
		Status:    StatusActive,
		Metadata:  metadata,
		RowSeq:    1,
		CreatedAt: s.now(),
		UpdatedAt: s.now(),
	}
	t, err := s.repo.Create(ctx, t)
	if err != nil {
		return Tenant{}, err
	}
	if err := s.events.Publish(ctx, "tenant.created", t.ID, map[string]any{
		"tenant_id": t.ID, "slug": t.Slug, "name": t.Name,
	}); err != nil {
		// outbox publish failure is recoverable; log + continue
		// (real implementation uses transactional outbox — see §2.6)
	}
	return t, nil
}

func (s *Service) Get(ctx context.Context, tenantID string) (Tenant, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Tenant{}, err            // layer 1: same-tenant only
	}
	return s.repo.Get(ctx, tenantID)
}

func (s *Service) List(ctx context.Context, limit int, cursor *ListCursor) ([]Tenant, bool, error) {
	// Operators can list across tenants only via control-plane impersonation (Phase 13).
	// Data-plane list returns only the caller's own tenant (one element).
	caller, ok := auth.TenantFromContext(ctx)
	if !ok {
		return nil, false, ErrUnauthorized
	}
	t, err := s.repo.Get(ctx, caller)
	if err != nil {
		return nil, false, err
	}
	return []Tenant{t}, false, nil
}

func (s *Service) Update(ctx context.Context, tenantID string, expectedSeq int64, patch UpdatePatch) (Tenant, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Tenant{}, err
	}
	t, err := s.repo.Update(ctx, tenantID, expectedSeq, patch)
	if err != nil {
		return Tenant{}, err
	}
	_ = s.events.Publish(ctx, "tenant.updated", t.ID, map[string]any{"tenant_id": t.ID})
	return t, nil
}

func (s *Service) SoftDelete(ctx context.Context, tenantID string, expectedSeq int64) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	t, err := s.repo.SoftDelete(ctx, tenantID, expectedSeq)
	if err != nil {
		return err
	}
	_ = s.events.Publish(ctx, "tenant.deleted", t.ID, map[string]any{"tenant_id": t.ID})
	return nil
}
```

**Note on `auth.AssertTenant`**: in Phase 2 this reads the mock header. In Phase 5 it reads the JWT claim. The signature does not change — only the implementation. That's the value of the port abstraction.

`internal/platform/auth/tenant.go` (Phase 2 minimal):

```go
package auth

import (
	"context"
	"errors"
	"net/http"
	"os"
)

type ctxKey struct{}

var tenantKey = ctxKey{}

// TenantFromContext returns the caller's tenant_id if any.
func TenantFromContext(ctx context.Context) (string, bool) {
	v, ok := ctx.Value(tenantKey).(string)
	return v, ok && v != ""
}

// AssertTenant returns ErrCrossTenant if the context's tenant differs from the requested tenant.
func AssertTenant(ctx context.Context, requestedTenantID string) error {
	caller, ok := TenantFromContext(ctx)
	if !ok {
		return ErrUnauthorized
	}
	if caller != requestedTenantID {
		return ErrCrossTenant
	}
	return nil
}

var (
	ErrUnauthorized = errors.New("unauthorized")
	ErrCrossTenant  = errors.New("cross-tenant access denied")
)

// MockMiddleware honors X-Mock-Tenant-Id ONLY when SAAS_ENV != "prod".
// This is the temporary auth wiring until Phase 5 swaps in real JWT verification.
func MockMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if os.Getenv("SAAS_ENV") == "prod" {
			http.Error(w, "mock middleware refused in prod", http.StatusUnauthorized)
			return
		}
		tid := r.Header.Get("X-Mock-Tenant-Id")
		if tid != "" {
			r = r.WithContext(context.WithValue(r.Context(), tenantKey, tid))
		}
		next.ServeHTTP(w, r)
	})
}
```

### 2.5 HTTP handler (strict-server)

Run `make openapi-check` to regenerate `internal/dataplane/httpapi/server.gen.go` with the Tenants endpoints. Then implement the `StrictServerInterface`:

`internal/dataplane/tenancy/handler.go`:

```go
package tenancy

import (
	"context"
	"net/http"
	"time"

	"github.com/omarss/saas/internal/dataplane/httpapi"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/cursor"
	"github.com/omarss/saas/internal/platform/problem"
)

type Handler struct{ svc *Service }

func NewHandler(svc *Service) *Handler { return &Handler{svc: svc} }

func (h *Handler) ListTenants(ctx context.Context, req httpapi.ListTenantsRequestObject) (httpapi.ListTenantsResponseObject, error) {
	limit := 25
	if req.Params.Limit != nil { limit = *req.Params.Limit }
	var cur *ListCursor
	if req.Params.Cursor != nil {
		c, err := cursor.Decode(*req.Params.Cursor)
		if err != nil {
			if err == cursor.ErrVersionMismatch {
				return httpapi.ListTenants410Response{}, nil
			}
			return httpapi.ListTenants422Response{...}, nil
		}
		cur = &ListCursor{CreatedAt: c.CreatedAt, ID: c.ID}
	}
	tenants, hasMore, err := h.svc.List(ctx, limit, cur)
	if err != nil {
		return problem.From(err, "/v1/tenants"), nil
	}
	resp := httpapi.TenantListResponse{ Pagination: httpapi.Pagination{ HasMore: hasMore } }
	for _, t := range tenants {
		resp.Data = append(resp.Data, toAPI(t))
	}
	return httpapi.ListTenants200JSONResponse(resp), nil
}

func (h *Handler) CreateTenant(ctx context.Context, req httpapi.CreateTenantRequestObject) (httpapi.CreateTenantResponseObject, error) {
	t, err := h.svc.Create(ctx, req.Body.Slug, req.Body.Name, req.Body.Metadata.AdditionalProperties)
	if err != nil {
		return problem.From(err, "/v1/tenants"), nil
	}
	return httpapi.CreateTenant201JSONResponse{
		Headers: httpapi.CreateTenant201ResponseHeaders{ ETag: t.ETag(), Location: "/v1/tenants/" + t.ID },
		Body:    httpapi.TenantResponse{ Data: toAPI(t) },
	}, nil
}

// ... GetTenant, UpdateTenant (with If-Match parsing), DeleteTenant
```

Wire into the chi router in `cmd/dataplane/main.go`:

```go
r := chi.NewRouter()
r.Use(middleware.RequestID, middleware.RealIP, middleware.Logger, middleware.Recoverer)
r.Use(middleware.Timeout(60 * time.Second))
r.Use(auth.MockMiddleware)              // Phase 2 only; replaced in Phase 5

spec, _ := httpapi.GetSwagger()
spec.Servers = nil
r.Use(oapimw.OapiRequestValidatorWithOptions(spec, &oapimw.Options{Options: openapi3filter.Options{
    AuthenticationFunc: authFunc,        // mock in Phase 2; jwx in Phase 5
}}))

r.Use(idempotency.Middleware(idempotencyStore))   // wired in §2.7
r.Get("/healthz", healthz)
httpapi.HandlerFromMuxWithBaseURL(httpapi.NewStrictHandler(tenancyHandler, nil), r, "")
```

### 2.6 Outbox dispatcher (in-process)

`internal/platform/outbox/dispatcher.go`:

```go
package outbox

import (
	"context"
	"log/slog"
	"time"

	"github.com/omarss/saas/internal/dataplane/db/sqlc"
)

type Dispatcher struct {
	q        *sqlc.Queries
	publish  Publisher
	interval time.Duration
	batch    int32
}

type Publisher interface {
	Publish(ctx context.Context, e sqlc.OutboxEvent) error
}

func New(q *sqlc.Queries, pub Publisher) *Dispatcher {
	return &Dispatcher{q: q, publish: pub, interval: 250 * time.Millisecond, batch: 100}
}

func (d *Dispatcher) Run(ctx context.Context) error {
	t := time.NewTicker(d.interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
			events, err := d.q.ListUnpublishedOutbox(ctx, d.batch)
			if err != nil { slog.Error("outbox list", "err", err); continue }
			for _, e := range events {
				if err := d.publish.Publish(ctx, e); err != nil {
					_ = d.q.MarkOutboxFailed(ctx, sqlc.MarkOutboxFailedParams{ID: e.ID, LastError: pgtype.Text{String: err.Error(), Valid: true}})
					continue
				}
				_ = d.q.MarkOutboxPublished(ctx, e.ID)
			}
		}
	}
}
```

Publisher in Phase 2: a no-op logger publisher that emits the event JSON to stdout. Real webhook delivery is post-MVP (v1).

ADR 009 records the in-process dispatcher decision and migration path to NATS/asynq.

**Transactional outbox**: the Service emits events via `EventPublisher`; the pgx-backed implementation is:

```go
type pgxPublisher struct{ q *sqlc.Queries }

func (p *pgxPublisher) Publish(ctx context.Context, eventType, tenantID string, payload any) error {
	body, _ := json.Marshal(payload)
	_, err := p.q.InsertOutboxEvent(ctx, sqlc.InsertOutboxEventParams{
		EventID:      "evt_" + ulid.Make().String(),
		Type:         eventType,
		EventVersion: 1,
		TenantID:     pgtype.Text{String: tenantID, Valid: tenantID != ""},
		DeploymentID: deploymentID,                  // env-injected
		Payload:      body,
	})
	return err
}
```

Critical: the Service.Create handler runs Repo.Create and EventPublisher.Publish in **the same transaction** so events are atomic with the state change. Refactor `service.go` to take a transactional context once `repo.Tx` is wired (Phase 3 platform pattern).

### 2.7 Idempotency middleware

`internal/platform/idempotency/middleware.go` is wired in Phase 2 with a minimum implementation that hands off to the Phase-3 promotion. For Phase 2:

```go
func Middleware(store Store) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method != http.MethodPost && r.Method != http.MethodPatch {
				next.ServeHTTP(w, r); return
			}
			key := r.Header.Get("Idempotency-Key")
			if key == "" { next.ServeHTTP(w, r); return }
			// load body once; rewind
			body, _ := io.ReadAll(r.Body)
			r.Body = io.NopCloser(bytes.NewReader(body))
			hash := sha256.Sum256(body)

			tid, _ := auth.TenantFromContext(r.Context())
			rec, err := store.Claim(r.Context(), tid, key, r.URL.Path, r.Method, hash[:])
			if err != nil { /* problem */ return }
			if !rec.Fresh {
				// Cache hit. If hash matches: replay. If different: 422 conflict. If in_flight: wait or 409.
				...
			}
			rw := &recorder{ResponseWriter: w}
			next.ServeHTTP(rw, r)
			_ = store.Finish(r.Context(), rec.ID, rw.status, rw.headers, rw.body)
		})
	}
}
```

ADR 010 records the 24h TTL + cleanup job. Real implementation lands in Phase 3 alongside the other platform primitives — Phase 2 ships a minimal version that handles the happy path so contract tests pass.

### 2.8 Tests

#### Unit tests (`service_test.go`)

Mock Repository + EventPublisher. Cases:

- Create succeeds with valid slug + name
- Create rejects duplicate slug → `ErrSlugTaken`
- Create generates a `tenant_` prefixed ULID id
- Get returns `ErrNotFound` for missing id
- Get returns `ErrCrossTenant` when ctx tenant differs (use `auth.MockContextWithTenant("tenant_X")`)
- Update bumps row_seq and updated_at
- Update rejects with `ErrEtagMismatch` when expectedSeq stale
- SoftDelete sets deleted_at and status='deleted'

#### Integration tests (`repo_pgx_test.go`)

`testcontainers-go` Postgres. Cases:

- Run migrations 000001 + 000002 on fresh DB
- CreateTenant → row exists with correct columns
- Update bumps row_seq from 1→2; updated_at advances
- RLS denies SELECT when `SET LOCAL app.current_tenant_id` is set to a different tenant
- RLS allows SELECT when GUC matches
- RLS denies SELECT when GUC is unset (defense against missing middleware)
- Soft delete preserves row but flips status + deleted_at
- Unique slug constraint rejects duplicates

#### Authorization tests (`security_test.go`) — MANDATORY per §17.3

For every Tenants endpoint:

| Test | Setup | Assert |
|---|---|---|
| Same-tenant allow | mock header = tenant_id matches resource id | 200 |
| Cross-tenant deny | mock header = tenant_A; URL = /v1/tenants/tenant_B | 403 + problem-details `forbidden` |
| Missing tenant context | no mock header | 401 |
| Mock middleware refused in prod | `SAAS_ENV=prod` | 401, regardless of header |
| `X-Tenant-Id` header ignored | set header to `tenant_FAKE`, no Authorization | 401 (NOT 200 with the fake tenant) |
| `X-Acting-Tenant-Id` without scope | set, but no impersonate scope in (mock) token | 403 |

These tests pin layer 1 of tenant isolation. If any case regresses in a later phase, the build fails.

#### Contract test (`make contract-test`)

```bash
# Start data plane
SAAS_ENV=dev DATAPLANE_DATABASE_URL=... ./bin/dataplane &
DP=$!

# Run prism proxy against the spec
prism proxy openapi/_generated/data-plane.yaml http://localhost:9090 --errors -p 4011 &

# Replay fixtures
for f in test/fixtures/tenants/*.http; do
  curl --fail-with-body @"$f"
done

kill $DP
```

`test/fixtures/tenants/create.http`:

```http
POST /v1/tenants
Host: localhost:4011
X-Mock-Tenant-Id: tenant_dummy
Idempotency-Key: idem_01HXAAAAAAAAAAAAAAAAAAAAAA
Content-Type: application/json

{"slug":"acme","name":"Acme Inc"}
```

(Note: tenant_dummy can be anything since CreateTenant is the one method that doesn't require an existing tenant context. CreateTenant in the data plane is unusual — see "Open question" below.)

### 2.9 Cursor helper

`internal/platform/cursor/cursor.go` is wired in Phase 2 with the schema-v1 format. Real promotion happens in Phase 3.

```go
type Cursor struct {
	V         int       `json:"v"`
	CreatedAt time.Time `json:"k"`
	ID        string    `json:"id"`
}

func Encode(c Cursor) string {
	if c.V == 0 { c.V = 1 }
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}

func Decode(s string) (Cursor, error) {
	raw, err := base64.RawURLEncoding.DecodeString(s)
	if err != nil { return Cursor{}, ErrBadCursor }
	var c Cursor
	if err := json.Unmarshal(raw, &c); err != nil { return Cursor{}, ErrBadCursor }
	if c.V != 1 { return Cursor{}, ErrVersionMismatch }
	return c, nil
}

var (
	ErrBadCursor       = errors.New("bad cursor")
	ErrVersionMismatch = errors.New("cursor version mismatch")    // → 410 Gone
)
```

ADR 011 records the version-bump-→-410 policy.

### 2.10 TS SDK regeneration + workflow wrapper

```bash
make sdk-ts
```

Regenerates `sdk/ts/data-plane/`. Then add a handwritten workflow wrapper at `sdk/ts/data-plane/workflows/tenants.ts`:

```typescript
import { Configuration, TenantsApi } from "../api";

export class TenantsWorkflow {
  private api: TenantsApi;
  constructor(config: Configuration) { this.api = new TenantsApi(config); }

  async create(slug: string, name: string, metadata?: Record<string, string>) {
    const idempotencyKey = "idem_" + ulid();
    const res = await this.api.createTenant({ slug, name, metadata }, { headers: { "Idempotency-Key": idempotencyKey } });
    return res.data.data;
  }
  // ... get, update with If-Match, list, delete
}
```

### 2.11 saasctl `tenant` subtree (minimal e2e)

In MVP, tenant CRUD is a Data Plane API, not Control Plane. But for an end-to-end smoke test, `saasctl tenant list --data-plane-url <url> --mock-tenant <id>` is a useful local command. Add:

```go
root.AddCommand(&cobra.Command{
    Use:   "tenant",
    Short: "Tenant operations against a Data Plane URL (dev convenience).",
})
```

The `saasctl init` wizard stub (per ADR 016, full impl in Phase 15) gets a placeholder:

```go
root.AddCommand(&cobra.Command{
    Use:   "init",
    Short: "Bootstrap a local SaaS stack (wired in Phase 15).",
    Run:   func(*cobra.Command, []string) { fmt.Println("init: not yet implemented; runs in Phase 15") },
})
```

### 2.12 Audit emission

In Phase 2 the audit module isn't built yet (Phase 10). The Service.Create/Update/Delete methods emit events via the outbox; in Phase 10 a subscriber will translate these into hash-chained `audit_event` rows. For Phase 2:

- `tenant.created`, `tenant.updated`, `tenant.deleted`, `tenant.suspended` (when status flips to suspended in Update) are inserted into `outbox_event`
- Outbox dispatcher's Publisher logs them to stdout (no real consumer yet)

### 2.13 `make contract-test` wired

Update the Makefile target from "not yet wired" to:

```make
contract-test: build openapi-overlay
	@SAAS_ENV=dev ./bin/dataplane &
	@sleep 2
	@$(PRISM) proxy /work/openapi/_generated/data-plane.yaml http://host.docker.internal:9090 --errors -p 4011 &
	@sleep 2
	@./scripts/replay-contract-fixtures.sh
	@pkill -f bin/dataplane || true
```

(`host.docker.internal` works on Linux only with `--add-host=host.docker.internal:host-gateway`. For Linux CI, prefer running the binary inside the same Docker network as Prism.)

---

## Verification checklist

```bash
# 1. Spec lints + generates clean:
$ make openapi-check
# Expected: spectral 0 errors, oapi-codegen regenerates server.gen.go, openapi-generator regenerates sdk/ts

# 2. Build:
$ make build
# Expected: all 4 binaries

# 3. Migrations apply:
$ make migrate
# Expected: tenant, outbox_event, idempotency_record tables exist

# 4. Lint:
$ make lint
# Expected: 0 findings

# 5. Unit + integration tests:
$ make test
$ make test-int
# Expected: green; integration tests cover RLS, ETag, idempotency

# 6. Authorization tests (the §17.3 matrix):
$ go test -run TestTenants_AuthZ ./internal/dataplane/tenancy/...
# Expected: same-tenant pass, cross-tenant 403, missing-ctx 401, prod-mock-refused, X-Tenant-Id ignored

# 7. Contract test:
$ make compose-up
$ make contract-test
# Expected: all fixtures replay with 200/201/204/etc per spec

# 8. End-to-end with saasctl:
$ SAAS_ENV=dev ./bin/dataplane &
$ curl -X POST http://localhost:9090/v1/tenants \
    -H "X-Mock-Tenant-Id: anything" \
    -H "Idempotency-Key: idem_01HXAAAAAAAAAAAAAAAAAAAAAA" \
    -H "Content-Type: application/json" \
    -d '{"slug":"acme","name":"Acme"}' | jq .
# Expected: 201, body has tenant_<ulid>, ETag header

# 9. TS SDK builds:
$ cd sdk/ts/data-plane && npm install && npx tsc --noEmit
# Expected: clean

# 10. Re-run idempotently:
$ curl -X POST http://localhost:9090/v1/tenants \
    -H "X-Mock-Tenant-Id: anything" \
    -H "Idempotency-Key: idem_01HXAAAAAAAAAAAAAAAAAAAAAA" \
    -H "Content-Type: application/json" \
    -d '{"slug":"acme","name":"Acme"}'
# Expected: same 201 body as the first call (cached)

# 11. Re-run with different body, same key:
$ curl -X POST http://localhost:9090/v1/tenants \
    -H "X-Mock-Tenant-Id: anything" \
    -H "Idempotency-Key: idem_01HXAAAAAAAAAAAAAAAAAAAAAA" \
    -H "Content-Type: application/json" \
    -d '{"slug":"acme","name":"Different"}'
# Expected: 422 idempotency-key-conflict

# 12. ETag enforcement:
$ ETAG=$(curl -s -i http://localhost:9090/v1/tenants/tenant_X -H "X-Mock-Tenant-Id: tenant_X" | grep -i etag | cut -d' ' -f2)
$ curl -X PATCH http://localhost:9090/v1/tenants/tenant_X \
    -H "X-Mock-Tenant-Id: tenant_X" -H "If-Match: $ETAG" -H "Idempotency-Key: idem_..." \
    -H "Content-Type: application/json" -d '{"name":"Renamed"}'
# Expected: 200 with new ETag
$ curl -X PATCH http://localhost:9090/v1/tenants/tenant_X \
    -H "X-Mock-Tenant-Id: tenant_X" -H "If-Match: $ETAG" -H "Idempotency-Key: idem_..." \
    -H "Content-Type: application/json" -d '{"name":"Again"}'
# Expected: 412 precondition failed (stale ETag)
```

---

## Anti-pattern guards

- **NEVER** add a `X-Tenant-Id` header read. Only `X-Mock-Tenant-Id` (dev-only, prod-rejected) is permitted in Phase 2; real auth is JWT-claim-only in Phase 5.
- **NEVER** write a service method that takes tenant_id from the request body. tenant_id flows from auth context only.
- **NEVER** skip the `auth.AssertTenant(ctx, requestedTenantID)` check in any Service method that takes a tenant-bound resource id from the request.
- **NEVER** `SELECT * FROM tenant WHERE id = $1` without first setting `app.current_tenant_id` GUC on the connection. The RLS policy will return zero rows even if the row exists — which is the safer failure mode, but masks the missing-middleware bug.
- **NEVER** publish an outbox event from outside the same transaction as the state change. Idempotent retry vs. lost event is a real trade-off; outbox solves it but only if the insert is transactional.
- **NEVER** invent a new `type` URI for Problem Details. Add to `openapi/problems/` first.
- **NEVER** commit a cursor without the `v` field. Schema bumps return 410, not silent re-interpretation.
- **NEVER** commit generated code that drifts from the spec. `make openapi-diff-check` in CI enforces this.
- **DO** wrap every list query's "+1 to detect has_more" sentinel in a clear helper so it doesn't leak into the response.

---

## Open question for the user

**Should `POST /v1/tenants` exist on the Data Plane at all?**

AGENTS.md §8.1 lists `POST /v1/tenants` in the Data Plane. But conceptually, in MVP, **the Deployment IS the boundary** — there's typically one tenant per Deployment (the bootstrap admin tenant created during provisioning per §6.2 step 6). Creating arbitrary tenants from the Data Plane API is only meaningful for products that have multi-tenancy *within* a Deployment.

Two readings:

(a) **Deployment = one customer = one tenant.** Tenant create is bootstrap-only via the control plane; the Data Plane only exposes `GET /v1/tenants/<self>` (and maybe Update/Delete for the caller's own tenant). MVP simpler.

(b) **Deployment = one Product Builder, hosts many tenants (each = an end customer).** Tenant create is a real Data Plane operation, idempotent, audited. MVP closer to Stripe/Auth0 model.

The current spec implies (b). The platform's positioning (§2 "B2B SaaS backend") could go either way. Phase 2 implements (b) as written, but the user should confirm before Phase 7 (Organizations) — Organizations only matter under reading (b).

---

## Phase 2 — Definition of done

- [ ] OpenAPI spec updated; `make openapi-check` green
- [ ] Migration applied
- [ ] sqlc-generated code committed
- [ ] Domain types, ports, pgx adapter, service, handler implemented
- [ ] Outbox dispatcher running (in-process goroutine in data-plane binary)
- [ ] Idempotency middleware wired (minimal Phase-2 version)
- [ ] Cursor encoder/decoder wired
- [ ] Unit + integration + authorization tests pass
- [ ] Contract test passes (prism proxy fixtures green)
- [ ] TS SDK regenerated + handwritten workflow wrapper added
- [ ] saasctl `tenant list` / `init` (stub) wired
- [ ] ADRs 003 + 009 + 010 + 011 committed
- [ ] PR follows template + `ready` label + CI green
- [ ] Open question (above) answered before merge

After Phase 2 — no checkpoint; proceed directly to Phase 3 (platform pattern promotion).

---

End of Phase 2. Next: `04-platform-patterns.md`.
