# Phase 9 — API Keys (argon2id + Envelope-Encrypted Prefix Index + Rotation with Grace)

> **Goal**: Ship the API Keys resource: `/v1/tenants/{tenant_id}/api-keys` CRUD, `/v1/api-keys/{id}/rotate`, `/v1/api-keys/{id}/revoke`. Secrets stored as argon2id PHC strings. Prefix-search index is envelope-encrypted via Phase 4 — constant-time auth-time lookup without exposing prefix→secret correlation. Rotation preserves the old secret for a configurable grace window (default 24h, max 7d). `last_used_at` writes are batched every 30s to avoid hot-row contention. Wire API key auth into the chi middleware chain alongside JWT.
>
> **Why now**: AGENTS.md §16 puts API Keys after Identity + Organizations + RBAC because keys are tenant-scoped, carry scopes that intersect with RBAC permissions, and member-attribution requires `member_id` (from Phase 7). Phase 10 Audit needs to log key create/rotate/revoke events. Machine-client (the §0 persona "machine") cannot integrate before this phase lands.
>
> **What this phase does NOT do**: No JWT-based API keys (refused — long-lived JWTs are an anti-pattern). No per-key per-resource ACLs beyond `scopes` (covered by RBAC for finer grain). No webhook delivery on rotation (out of MVP — Phase 5 Identity audit row is enough). No automatic key rotation on schedule (operators rotate manually).
>
> **Maps to AGENTS.md**: §8.5 (endpoints + fields), §12.6 (API keys module), §17.3 (matrix), §18.2 (storage rules), §18.3 (audit: api_key.created/rotated/revoked), §18.7 (envelope encryption posture). `01-foundations.md` §15 (argon2id params), §5 (envelope encryption), §11 (idempotency + rate limit headers).
>
> **Estimated subagent sessions**: 2-3 (one for OpenAPI + migration + argon2 + envelope index; one for auth middleware + rotation grace; one for tests + scope checks + audit).

---

## Pre-flight

1. AGENTS.md §8.5, §12.6, §18.2, §18.3, §18.7.
2. CONVENTIONS.md §10 (PII).
3. `01-foundations.md` §15 (argon2id PHC), §5 (envelope).
4. Phase 4 (envelope client healthy), Phase 8 (RBAC scope semantics).
5. Phase 5 — User.GetByID is needed by the `created_by` join.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Secret format | `<prefix>_<random>` where prefix = `live` or `test`, plus `_<8-char-randomness>` separator, plus 32 url-safe random bytes. Full example: `live_ax9_3rkP...` | UUID-only (refused — no env hint); JWT (refused — unrevocable) |
| Hash | argon2id with params from `01-foundations.md` §15 (memory=19 MiB, t=2, p=1, len=32, salt=16) | bcrypt (refused — OWASP 2024 recommends argon2id for new systems) |
| Prefix index | HMAC-SHA256(prefix_bytes, per-deployment HMAC key) → 32-byte bucket; envelope-encrypted bucket stored in `prefix_index` column for constant-time lookup | Plaintext prefix column with B-tree index (refused — enables prefix → key correlation if DB leaks) |
| Auth-time lookup | (1) hash the presented prefix; (2) decrypt prefix_index column; (3) compare; (4) verify argon2 PHC; (5) check revoked + expiry + IP allowlist + rate limit | Direct hash compare with no envelope (refused — half the point of envelope) |
| Rotation model | Old key + new key both valid until `grace_expires_at`; both rows live in DB; the rotated `api_key` row gets `successor_id` pointing at the new row | Two columns on the same row (refused — complicates audit + lookup) |
| Grace window | Default 24h, max 7d, min 0 (instant revoke) | Fixed (refused — operators have legitimate reasons to vary) |
| `last_used_at` updates | Buffered in memory; flushed every 30s to DB via batch update | Per-request UPDATE (refused — hot-row lock + WAL bloat) |
| Scope semantics | API key scopes intersect with the calling member's RBAC permissions. The principal's effective permissions = `scopes ∩ rbac_permissions`. | scopes ⊕ rbac (refused — confusing) |
| IP allowlist enforcement | At middleware boundary; CIDR-aware via `net.ParseCIDR` + `net.IP.Contains` | None (refused — §8.5 mandates) |
| Rate limit | Per-key `rate_limit_per_minute` enforced via in-memory token bucket; falls back to deployment default if null | External rate limiter (refused — overkill for MVP) |

If the user disagrees on any default, stop.

---

## Tasks

### 9.1 OpenAPI spec — `/v1/tenants/{tenant_id}/api-keys`

`openapi/data-plane.yaml` additions:

```yaml
paths:
  /v1/tenants/{tenant_id}/api-keys:
    parameters: [ { in: path, name: tenant_id, required: true, schema: { type: string } } ]
    get: { operationId: listAPIKeys, tags: [api-keys], parameters: [ { $ref: "#/components/parameters/Limit" }, { $ref: "#/components/parameters/Cursor" } ], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/APIKeyListResponse" } } } } } }
    post:
      operationId: createAPIKey
      tags: [api-keys]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/CreateAPIKeyRequest" }
      responses:
        "201":
          description: Created. The plaintext secret is returned ONCE; subsequent reads only show prefix.
          content: { application/json: { schema: { $ref: "#/components/schemas/CreateAPIKeyResponse" } } }

  /v1/api-keys/{api_key_id}:
    parameters: [ { in: path, name: api_key_id, required: true, schema: { type: string, pattern: "^apik_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    get:    { operationId: getAPIKey,    tags: [api-keys], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/APIKeyResponse" } } } } } }
    patch:  { operationId: updateAPIKey, tags: [api-keys], parameters: [ { $ref: "#/components/parameters/IfMatch" }, { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/UpdateAPIKeyRequest" } } } }, responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/APIKeyResponse" } } } } } }

  /v1/api-keys/{api_key_id}/rotate:
    post:
      operationId: rotateAPIKey
      tags: [api-keys]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/RotateAPIKeyRequest" }
      responses:
        "200":
          description: Rotated. The new plaintext secret is returned ONCE. The old secret remains valid until grace_expires_at.
          content: { application/json: { schema: { $ref: "#/components/schemas/RotateAPIKeyResponse" } } }

  /v1/api-keys/{api_key_id}/revoke:
    post:
      operationId: revokeAPIKey
      tags: [api-keys]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses:
        "200": { content: { application/json: { schema: { $ref: "#/components/schemas/APIKeyResponse" } } } }

components:
  schemas:
    APIKey:
      type: object
      required: [id, object, tenant_id, prefix, scopes, status, created_at]
      properties:
        id:          { type: string, pattern: "^apik_[0-9A-HJKMNP-TV-Z]{26}$" }
        object:      { type: string, enum: [api_key] }
        tenant_id:   { type: string }
        environment_id: { type: [string, "null"] }
        prefix:      { type: string, description: "Visible 8-char prefix (e.g. live_ax9_)" }
        name:        { type: string }
        scopes:      { type: array, items: { type: string } }
        status:      { type: string, enum: [active, revoked, rotated] }
        created_by:  { type: string, description: "member_id of creator" }
        created_at:  { type: string, format: date-time }
        expires_at:  { type: [string, "null"], format: date-time }
        last_used_at: { type: [string, "null"], format: date-time }
        revoked_at:  { type: [string, "null"], format: date-time }
        rotated_at:  { type: [string, "null"], format: date-time }
        grace_expires_at: { type: [string, "null"], format: date-time }
        successor_id: { type: [string, "null"], description: "If rotated, the new api_key_id." }
        rate_limit_per_minute: { type: [integer, "null"], minimum: 1, maximum: 100000 }
        ip_allowlist: { type: [array, "null"], items: { type: string, description: "CIDR block" } }

    CreateAPIKeyRequest:
      type: object
      required: [name, scopes]
      properties:
        name:         { type: string, minLength: 1, maxLength: 64 }
        scopes:       { type: array, items: { type: string, pattern: "^[a-z_]+\\.[a-z_]+$" } }
        environment_id: { type: string }
        expires_at:   { type: string, format: date-time }
        rate_limit_per_minute: { type: integer, minimum: 1, maximum: 100000 }
        ip_allowlist: { type: array, items: { type: string } }

    CreateAPIKeyResponse:
      type: object
      required: [data, secret]
      properties:
        data:   { $ref: "#/components/schemas/APIKey" }
        secret: { type: string, x-oapi-codegen-extra-tags: { sensitive: "true" }, description: "Shown ONCE; client must store immediately." }

    UpdateAPIKeyRequest:
      type: object
      properties:
        name:         { type: string }
        scopes:       { type: array, items: { type: string } }
        expires_at:   { type: string, format: date-time }
        rate_limit_per_minute: { type: integer }
        ip_allowlist: { type: array, items: { type: string } }

    RotateAPIKeyRequest:
      type: object
      properties:
        grace_period_seconds: { type: integer, minimum: 0, maximum: 604800, default: 86400 }

    RotateAPIKeyResponse:
      type: object
      required: [data, secret, grace_expires_at]
      properties:
        data:             { $ref: "#/components/schemas/APIKey" }
        secret:           { type: string, x-oapi-codegen-extra-tags: { sensitive: "true" } }
        grace_expires_at: { type: string, format: date-time }

    APIKeyResponse:       { type: object, properties: { data: { $ref: "#/components/schemas/APIKey" } } }
    APIKeyListResponse:   { type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/APIKey" } }, pagination: { $ref: "#/components/schemas/Pagination" } } }
```

### 9.2 Migration — `migrations/dataplane/000007_api_keys.up.sql`

```sql
CREATE TABLE api_key (
    id                  text PRIMARY KEY CHECK (id LIKE 'apik_%'),
    tenant_id           text NOT NULL REFERENCES tenant (id),
    environment_id      text,
    name                text NOT NULL,
    prefix              text NOT NULL,                          -- visible portion
    -- argon2id PHC string of the FULL secret (prefix + random).
    hashed_secret       text NOT NULL,
    -- HMAC bucket of the prefix, envelope-encrypted for constant-time lookup
    -- without storing plaintext prefix in an index.
    prefix_index_ciphertext  bytea NOT NULL,
    prefix_index_wrapped_dek text  NOT NULL,
    prefix_index_nonce       bytea NOT NULL,
    prefix_index_kid         text  NOT NULL,
    prefix_index_key_version integer NOT NULL,
    -- HMAC bucket for the WHERE lookup column (HMAC is deterministic, so the
    -- DB sees only the HMAC; the envelope above adds defense-in-depth).
    prefix_lookup_hash  bytea NOT NULL,
    scopes              text[] NOT NULL DEFAULT '{}',
    status              text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active','revoked','rotated')),
    created_by          text NOT NULL,
    expires_at          timestamptz,
    last_used_at        timestamptz,
    revoked_at          timestamptz,
    rotated_at          timestamptz,
    grace_expires_at    timestamptz,
    successor_id        text REFERENCES api_key (id),
    rate_limit_per_minute integer CHECK (rate_limit_per_minute IS NULL OR rate_limit_per_minute > 0),
    ip_allowlist        text[],
    row_seq             bigint NOT NULL DEFAULT 1,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX api_key_prefix_lookup_idx ON api_key (prefix_lookup_hash) WHERE status IN ('active','rotated');
CREATE INDEX api_key_tenant_idx       ON api_key (tenant_id, status, created_at DESC);
CREATE TRIGGER api_key_bump_row_seq BEFORE UPDATE ON api_key FOR EACH ROW EXECUTE FUNCTION bump_row_seq();
ALTER TABLE api_key ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_key FORCE  ROW LEVEL SECURITY;
CREATE POLICY api_key_tenant_only ON api_key USING (tenant_id = current_setting('app.current_tenant_id', true));

-- last_used_at batch buffer (writes coalesced every 30s).
-- Implemented as an unlogged table for speed; the buffer flush updates api_key.
CREATE UNLOGGED TABLE api_key_usage_buffer (
    api_key_id  text PRIMARY KEY,
    last_used_at timestamptz NOT NULL DEFAULT now()
);

-- API key permissions to seed into permission catalogue.
INSERT INTO permission (id, resource_type, action, description) VALUES
    ('perm_apikey_create', 'api_key', 'create', 'Create new API keys'),
    ('perm_apikey_rotate', 'api_key', 'rotate', 'Rotate API key secrets'),
    ('perm_apikey_revoke', 'api_key', 'revoke', 'Revoke API keys')
ON CONFLICT (resource_type, action) DO NOTHING;
```

### 9.3 Module — `internal/dataplane/apikeys/`

```text
internal/dataplane/apikeys/
  domain.go          # APIKey, Status, secret generator
  ports.go           # Repository, PrefixIndexer, RateLimiter
  service.go
  repo_pgx.go
  secret.go          # generate, format, parse
  argon2.go          # PHC encode/decode + verify (or use alexedwards/argon2id)
  prefix_indexer.go  # HMAC + envelope
  rate_limiter.go    # in-memory token bucket per key
  usage_buffer.go    # last_used_at coalescing
  middleware.go      # API key auth middleware (sits alongside JWT verifier in chain)
  handler.go
  errors.go
  service_test.go
  middleware_test.go
  security_test.go
```

### 9.4 Secret generation

`secret.go`:

```go
package apikeys

import (
    "crypto/rand"
    "encoding/base64"
    "fmt"
    "strings"
)

// Secret formats as `<env>_<prefix-rand>_<full-rand>`.
// `<env>` is `live` or `test`. `<prefix-rand>` is 8 char URL-safe random.
// `<full-rand>` is 32 bytes URL-safe random (43 chars after b64).
// The visible prefix shown in the API is `<env>_<prefix-rand>_`.
type Secret struct {
    Plaintext string
    Prefix    string
}

func NewSecret(env string) (Secret, error) {
    if env != "live" && env != "test" { env = "live" }
    pre := make([]byte, 6) // 8 chars after b64
    if _, err := rand.Read(pre); err != nil { return Secret{}, err }
    rest := make([]byte, 32)
    if _, err := rand.Read(rest); err != nil { return Secret{}, err }
    preEnc  := base64.RawURLEncoding.EncodeToString(pre)
    restEnc := base64.RawURLEncoding.EncodeToString(rest)
    plain := fmt.Sprintf("%s_%s_%s", env, preEnc, restEnc)
    prefix := fmt.Sprintf("%s_%s_", env, preEnc)
    return Secret{Plaintext: plain, Prefix: prefix}, nil
}

// SplitPrefix returns the visible prefix from a full secret. Returns the
// prefix portion (live_ax9_) or empty if malformed.
func SplitPrefix(s string) string {
    parts := strings.SplitN(s, "_", 3)
    if len(parts) < 3 { return "" }
    return parts[0] + "_" + parts[1] + "_"
}
```

### 9.5 argon2id PHC

Use `github.com/alexedwards/argon2id v1.0.0` (MIT, 6-LoC parser already vetted, listed in `01-foundations.md` §15). Alternative: hand-roll. Default: alexedwards.

```go
import "github.com/alexedwards/argon2id"

var argonParams = &argon2id.Params{
    Memory: 19 * 1024, Iterations: 2, Parallelism: 1, SaltLength: 16, KeyLength: 32,
}

func hashSecret(secret string) (string, error) {
    return argon2id.CreateHash(secret, argonParams)
}

func verifySecret(secret, phc string) (bool, error) {
    return argon2id.ComparePasswordAndHash(secret, phc)
}
```

### 9.6 Prefix indexer

`prefix_indexer.go`:

```go
package apikeys

import (
    "context"
    "crypto/hmac"
    "crypto/sha256"

    "github.com/omarss/saas/internal/platform/crypto/envelope"
)

type PrefixIndexer struct {
    enc *envelope.Client
    deploymentID string
    hmacKey []byte  // 32 bytes; loaded once at startup from OpenBao KV
}

// IndexHash returns the deterministic HMAC bucket for the prefix.
func (p *PrefixIndexer) IndexHash(prefix string) []byte {
    h := hmac.New(sha256.New, p.hmacKey)
    h.Write([]byte(prefix))
    return h.Sum(nil)
}

// IndexEnvelope produces the envelope-encrypted form to be stored alongside
// the HMAC bucket. AAD = deployment_id || "api_key_prefix_index" || api_key_id.
func (p *PrefixIndexer) IndexEnvelope(ctx context.Context, apiKeyID string, hash []byte) (envelope.Envelope, error) {
    aad := []byte(p.deploymentID + "|api_key_prefix_index|" + apiKeyID)
    return p.enc.Encrypt(ctx, p.deploymentID, hash, aad)
}
```

The HMAC key is loaded once at process start from `secret/data/<deployment_id>/api_keys/prefix_hmac_key` in OpenBao KV. Bootstrapped during provisioning (Phase 12d).

### 9.7 API key auth middleware

`middleware.go`:

```go
package apikeys

import (
    "errors"
    "net"
    "net/http"
    "strings"
    "time"

    "github.com/omarss/saas/internal/platform/auth"
    "github.com/omarss/saas/internal/platform/problem"
)

func (s *Service) Middleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        h := r.Header.Get("Authorization")
        if !strings.HasPrefix(h, "Bearer ") {
            next.ServeHTTP(w, r); return
        }
        token := strings.TrimPrefix(h, "Bearer ")
        // Cheap discriminator: API keys start with "live_" or "test_"; JWTs are "eyJ...".
        if !strings.HasPrefix(token, "live_") && !strings.HasPrefix(token, "test_") {
            next.ServeHTTP(w, r); return
        }

        prefix := SplitPrefix(token)
        if prefix == "" { writeProblem(w, problem.TypeUnauthorized, 401); return }

        keys, err := s.repo.LookupByPrefixHash(r.Context(), s.indexer.IndexHash(prefix))
        if err != nil { writeProblem(w, problem.TypeUnauthorized, 401); return }
        if len(keys) == 0 { writeProblem(w, problem.TypeUnauthorized, 401); return }

        var matched *APIKey
        for i := range keys {
            // Defense-in-depth: decrypt prefix envelope and verify it matches.
            hash, derr := s.indexer.DecryptIndexEnvelope(r.Context(), keys[i])
            if derr != nil || !hmacEqual(hash, s.indexer.IndexHash(prefix)) { continue }
            // argon2id verify.
            ok, _ := verifySecret(token, keys[i].HashedSecret)
            if ok { matched = &keys[i]; break }
        }
        if matched == nil { writeProblem(w, problem.TypeUnauthorized, 401); return }

        // Validate state.
        if matched.Status == "revoked" {
            writeProblem(w, problem.TypeKeyRevoked, 401); return
        }
        if matched.ExpiresAt != nil && time.Now().After(*matched.ExpiresAt) {
            writeProblem(w, problem.TypeKeyExpired, 401); return
        }
        if matched.Status == "rotated" && matched.GraceExpiresAt != nil && time.Now().After(*matched.GraceExpiresAt) {
            writeProblem(w, problem.TypeKeyExpired, 401); return
        }
        // IP allowlist.
        if len(matched.IPAllowlist) > 0 && !ipAllowed(r.RemoteAddr, matched.IPAllowlist) {
            writeProblem(w, problem.TypeIPNotAllowed, 403); return
        }
        // Rate limit.
        if !s.limiter.Allow(matched.ID, matched.RateLimitPerMinute) {
            w.Header().Set("RateLimit-Remaining", "0")
            w.Header().Set("Retry-After", "60")
            writeProblem(w, problem.TypeRateLimited, 429); return
        }

        p := auth.Principal{
            ActorType: auth.ActorAPIKey,
            ActorID:   matched.ID,
            TenantID:  matched.TenantID,
            Scopes:    matched.Scopes,
            IPAddress: r.RemoteAddr,
            RequestID: r.Header.Get("X-Request-Id"),
        }
        s.usageBuffer.Record(matched.ID, time.Now())
        next.ServeHTTP(w, r.WithContext(auth.WithPrincipal(r.Context(), p)))
    })
}
```

This middleware sits BEFORE the JWT verifier in the chain. If the bearer is a JWT (`eyJ...` prefix), it passes through to the JWT middleware. If it's an API key, the JWT middleware later sees an already-populated principal and is a no-op.

### 9.8 Rotation with grace

`Rotate`:

```go
func (s *Service) Rotate(ctx context.Context, tenantID, apiKeyID string, gracePeriodSeconds int) (APIKey, string, error) {
    if err := auth.AssertTenant(ctx, tenantID); err != nil { return APIKey{}, "", err }
    if gracePeriodSeconds < 0 || gracePeriodSeconds > 604800 { return APIKey{}, "", ErrGraceTooLong }

    old, err := s.repo.Get(ctx, tenantID, apiKeyID)
    if err != nil { return APIKey{}, "", err }
    if old.Status != "active" { return APIKey{}, "", ErrNotRotatable }

    env := environmentForOld(old)
    sec, err := NewSecret(env)
    if err != nil { return APIKey{}, "", err }
    hashed, err := hashSecret(sec.Plaintext)
    if err != nil { return APIKey{}, "", err }
    pidx := s.indexer.IndexHash(sec.Prefix)
    pidxEnv, err := s.indexer.IndexEnvelope(ctx, "", pidx)   // ID filled after insert
    if err != nil { return APIKey{}, "", err }

    newID := id.New(id.PrefixAPIKey)
    newKey := APIKey{
        ID: newID, TenantID: tenantID, EnvironmentID: old.EnvironmentID, Name: old.Name + " (rotated)",
        Prefix: sec.Prefix, HashedSecret: hashed, PrefixLookupHash: pidx, PrefixIndexEnvelope: pidxEnv,
        Scopes: old.Scopes, Status: "active", CreatedBy: callerMemberID(ctx),
        ExpiresAt: old.ExpiresAt, RateLimitPerMinute: old.RateLimitPerMinute, IPAllowlist: old.IPAllowlist,
    }
    if err := s.repo.CreateInTx(ctx, &newKey, &old, gracePeriodSeconds); err != nil {
        return APIKey{}, "", err
    }
    _ = s.events.Publish(ctx, "api_key.rotated", tenantID, map[string]any{
        "api_key_id": old.ID, "successor_id": newKey.ID, "grace_period_seconds": gracePeriodSeconds,
    })
    return newKey, sec.Plaintext, nil
}
```

`CreateInTx` runs in one transaction:

1. INSERT new row (status=active).
2. UPDATE old row: status='rotated', rotated_at=now(), grace_expires_at=now()+gracePeriodSeconds, successor_id=new.ID.

### 9.9 Revoke

```go
func (s *Service) Revoke(ctx context.Context, tenantID, apiKeyID string) error {
    if err := auth.AssertTenant(ctx, tenantID); err != nil { return err }
    if err := s.repo.Revoke(ctx, tenantID, apiKeyID); err != nil { return err }
    _ = s.events.Publish(ctx, "api_key.revoked", tenantID, map[string]any{"api_key_id": apiKeyID})
    return nil
}
```

Revoke is immediate; no grace. Setting `status='revoked'` + `revoked_at=now()` is enough — the middleware checks.

### 9.10 Usage buffer

`usage_buffer.go`:

```go
package apikeys

import (
    "context"
    "sync"
    "time"
)

type UsageBuffer struct {
    mu    sync.Mutex
    seen  map[string]time.Time
    repo  Repository
    flush time.Duration
}

func NewUsageBuffer(repo Repository, flush time.Duration) *UsageBuffer {
    return &UsageBuffer{seen: map[string]time.Time{}, repo: repo, flush: flush}
}

func (b *UsageBuffer) Record(apiKeyID string, t time.Time) {
    b.mu.Lock()
    defer b.mu.Unlock()
    // Keep the latest; subsequent record() within the window overwrites.
    b.seen[apiKeyID] = t
}

func (b *UsageBuffer) Run(ctx context.Context) error {
    t := time.NewTicker(b.flush)
    defer t.Stop()
    for {
        select {
        case <-ctx.Done(): return ctx.Err()
        case <-t.C: _ = b.flushNow(ctx)
        }
    }
}

func (b *UsageBuffer) flushNow(ctx context.Context) error {
    b.mu.Lock()
    snap := b.seen
    b.seen = map[string]time.Time{}
    b.mu.Unlock()
    if len(snap) == 0 { return nil }
    return b.repo.BulkUpdateLastUsed(ctx, snap)
}
```

`Repository.BulkUpdateLastUsed` uses a single SQL `UPDATE api_key SET last_used_at = data.t FROM (VALUES ...) AS data(id, t) WHERE api_key.id = data.id`. Batch size capped at 1000; spillover deferred to next tick.

### 9.11 Rate limiter (in-memory token bucket)

`rate_limiter.go`:

```go
type RateLimiter struct {
    mu      sync.Mutex
    buckets map[string]*bucket
    default int
}

type bucket struct{ tokens float64; last time.Time; limit int }

func (r *RateLimiter) Allow(keyID string, perMinute *int) bool {
    limit := r.default
    if perMinute != nil { limit = *perMinute }
    r.mu.Lock(); defer r.mu.Unlock()
    b, ok := r.buckets[keyID]
    if !ok { b = &bucket{tokens: float64(limit), last: time.Now(), limit: limit}; r.buckets[keyID] = b }
    now := time.Now()
    elapsed := now.Sub(b.last).Seconds()
    b.tokens = math.Min(float64(b.limit), b.tokens + (float64(b.limit)/60.0)*elapsed)
    b.last = now
    if b.tokens < 1.0 { return false }
    b.tokens -= 1.0
    return true
}
```

Multi-replica path (deferred): Redis-backed rate limiter. The Casbin watcher decision (ADR 005) and this one share the same Redis dep when scale lands.

### 9.12 §17.3 authorization matrix tests

| Test | Assert |
|---|---|
| Same-tenant key authenticates | 200 |
| Revoked key | 401 + `api-key-revoked` |
| Expired key | 401 + `api-key-expired` |
| Rotated key after grace | 401 + `api-key-expired` |
| Rotated key during grace | 200 |
| New key after rotation | 200 |
| Missing scope for endpoint | 403 + `missing-scope` |
| IP outside allowlist | 403 + `ip-not-allowlisted` |
| Rate limit exceeded | 429 + RateLimit headers + Retry-After |
| Cross-tenant access with valid key | 403 (or 404 for non-path-tenant URLs) |
| Idempotent rotate replay | 200 with same successor_id |
| Rotate non-active key | 422 |
| Rotate with grace > 7d | 422 |
| Create key as non-permitted member | 403 |

### 9.13 saasctl

```text
saasctl api-key create --tenant <id> --name <n> --scopes scope1,scope2 [--expires-at ...] [--rate-limit 100] [--ip-allowlist 10.0.0.0/24]
saasctl api-key rotate <apik_id> [--grace-period-seconds 86400]
saasctl api-key revoke <apik_id>
saasctl api-key list --tenant <id>
```

`saasctl api-key create` prints the secret once, ostentatiously: `IMPORTANT: copy this secret NOW. It will not be shown again.`

### 9.14 ADR — not new

No new ADR is mandated by the master table for Phase 9. The argon2id + envelope-prefix-index pattern is documented inline in CONVENTIONS.md §10.x (Phase 4 PII appendix).

If the user wants a dedicated ADR for the prefix-index design, create `docs/adr/019-api-key-prefix-index.md` covering rationale, HMAC-vs-encrypt-only, and the multi-replica rate limiter path.

### 9.15 TS SDK + workflow

`sdk/ts/data-plane/workflows/apiKeys.ts`:

```typescript
export class APIKeysWorkflow {
  async create(tenantId, name, scopes, options?) {
    const res = await api.createAPIKey(tenantId, { name, scopes, ...options }, idempotencyHeaders());
    return { apiKey: res.data.data, secret: res.data.secret };   // secret returned once
  }
  async rotate(apiKeyId, gracePeriodSeconds = 86400) { ... }
  async revoke(apiKeyId) { ... }
}
```

### 9.16 Commits

```bash
git add openapi/data-plane.yaml openapi/problems/
git commit -m "add api keys endpoints"

git add migrations/dataplane/000007_api_keys.up.sql internal/dataplane/db/queries/api_keys.sql
git commit -m "add api key table and usage buffer"

git add internal/dataplane/apikeys/
git commit -m "implement api keys module"

git add cmd/dataplane/main.go
git commit -m "wire api key middleware and usage buffer"

git add sdk/ts/data-plane/workflows/apiKeys.ts cmd/saasctl/
git commit -m "ts sdk and saasctl api key coverage"
```

---

## Verification checklist

```bash
# 1. Migrations apply.
$ make migrate
$ psql -c "\d api_key" -c "\d api_key_usage_buffer"

# 2. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 3. Create + use a key.
$ R=$(curl -s -X POST http://localhost:9090/v1/tenants/<t>/api-keys -H "Authorization: Bearer $JWT" -H "Idempotency-Key: idem_..." -d '{"name":"k1","scopes":["tenant.read"]}')
$ SECRET=$(echo "$R" | jq -r .secret)
$ curl -s http://localhost:9090/v1/tenants/<t> -H "Authorization: Bearer $SECRET" | jq
# Expected: 200 with tenant body

# 4. Rotate; both work during grace.
$ R=$(curl -s -X POST http://localhost:9090/v1/api-keys/<old>/rotate -H "Authorization: Bearer $JWT" -H "Idempotency-Key: idem_..." -d '{"grace_period_seconds":86400}')
$ NEW=$(echo "$R" | jq -r .secret)
$ curl -s http://localhost:9090/v1/tenants/<t> -H "Authorization: Bearer $SECRET"   # old still works
$ curl -s http://localhost:9090/v1/tenants/<t> -H "Authorization: Bearer $NEW"      # new works

# 5. Force grace expiry, old key 401.
$ psql -c "UPDATE api_key SET grace_expires_at = now() - interval '1 minute' WHERE id = '<old>';"
$ curl -i http://localhost:9090/v1/tenants/<t> -H "Authorization: Bearer $SECRET"
# Expected: 401 api-key-expired

# 6. Revoke.
$ curl -s -X POST http://localhost:9090/v1/api-keys/<new>/revoke -H "Authorization: Bearer $JWT" -H "Idempotency-Key: idem_..."
$ curl -i http://localhost:9090/v1/tenants/<t> -H "Authorization: Bearer $NEW"
# Expected: 401 api-key-revoked

# 7. IP allowlist.
$ curl -s -X POST http://localhost:9090/v1/tenants/<t>/api-keys -H "Authorization: Bearer $JWT" ... \
    -d '{"name":"ip_test","scopes":["tenant.read"],"ip_allowlist":["10.0.0.0/24"]}'
$ # Use the secret from a non-matching IP
$ curl -i http://localhost:9090/v1/tenants/<t> -H "Authorization: Bearer $..."
# Expected: 403 ip-not-allowlisted

# 8. Rate limit.
$ for i in $(seq 1 101); do curl -s -o /dev/null -w "%{http_code}\n" http://localhost:9090/v1/tenants/<t> -H "Authorization: Bearer $..."; done | tail
# Expected: ends with 429s; Retry-After header present

# 9. last_used_at batches.
$ # Hit the API a few times; observe DB lag (≤ 30s).
$ psql -c "SELECT last_used_at FROM api_key WHERE id = '<id>';"
# Expected: NULL or recent (≤ 30s old) timestamp

# 10. §17.3 matrix.
$ go test -run TestAPIKeys_AuthZ -v ./internal/dataplane/apikeys/...
```

---

## Anti-pattern guards

- **NEVER** return the plaintext secret on any path other than `POST /v1/.../api-keys` (initial create) or `POST /v1/api-keys/{id}/rotate`. The OpenAPI shape forbids it elsewhere.
- **NEVER** log the secret. The slog redactor catches `secret`, `api_key`, `api_key_secret`. New aliases go in the static list.
- **NEVER** store the prefix in a plaintext-indexed column. The HMAC bucket + envelope provide constant-time lookup without exposing prefix→key correlation.
- **NEVER** compare argon2 hashes manually with `==`. Use the constant-time `argon2id.ComparePasswordAndHash`.
- **NEVER** allow the same secret to be returned twice — even idempotent rotate uses the Idempotency-Key replay mechanism (Phase 3) so the second call returns the cached 200 from the FIRST rotation; the secret string is reproduced from the cached response body.
- **NEVER** check IP allowlist against `X-Forwarded-For` without trusting the upstream proxy. Use `chi/middleware/realip` (already in chain) which sets `r.RemoteAddr`.
- **NEVER** write `last_used_at` per request. The buffer coalesces; 30s lag is the documented trade-off.
- **NEVER** create an API key with `*` in scopes. The validator pattern `^[a-z_]+\\.[a-z_]+$` forbids; bypass attempt = 422.
- **NEVER** allow `grace_period_seconds > 604800` (7 days). Beyond that is operator policy abuse.

---

## Open questions

1. **Should `last_used_at` accuracy be tunable?** Default: 30s flush. Alternative: per-key `precise_last_used` flag (refused for MVP — adds complexity for negligible benefit).
2. **What's the default `rate_limit_per_minute` when null?** Default: 600 RPM (10/sec). Configurable per Deployment via env var `SAAS_DEFAULT_API_KEY_RPM`. Confirm.
3. **Are operator API keys ever created in the data plane?** No — operators use control-plane JWTs (Phase 13). API keys are tenant-bound only.
4. **Multi-replica rate limit.** Deferred to scale event. Single replica MVP is fine; document in CONVENTIONS.md §6 (Log fields) that `rate_limit_remaining` is per-replica until Redis lands.

---

## Phase 9 — Definition of done

- [ ] OpenAPI updated; `make openapi-check` green
- [ ] Migrations 000007 applied; `api_key`, `api_key_usage_buffer` exist with RLS + CHECKs
- [ ] `internal/dataplane/apikeys/` complete with all sub-files + tests
- [ ] Secret format `<env>_<8>_<43>`; argon2id PHC hash stored
- [ ] Prefix index: HMAC bucket + envelope envelope-encrypted alongside
- [ ] Rotation with grace window functional; both keys valid during grace; old → 401 after grace
- [ ] Revoke immediate; subsequent requests 401
- [ ] IP allowlist CIDR matching works
- [ ] Per-key rate limiter token bucket; 429 with Retry-After
- [ ] last_used_at batches every 30s; verified via test
- [ ] Audit events emitted: api_key.created, .rotated, .revoked (Phase 10 consumes)
- [ ] §17.3 matrix passes
- [ ] TS SDK regenerated + workflow wrapper
- [ ] saasctl `api-key` subtree
- [ ] All Phase 2-8 tests still green
- [ ] PR template, `ready` label, CI green

---

End of Phase 9. Next: `11-audit-logs.md`.
