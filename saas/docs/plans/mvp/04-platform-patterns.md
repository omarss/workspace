# Phase 3 — Platform Pattern Promotion + CONVENTIONS.md

> **Goal**: Promote the inline scaffolding that Phase 2 wrote inside `internal/dataplane/tenancy/` into reusable building blocks under `internal/platform/`. Author `CONVENTIONS.md` so all subsequent phases mechanically copy the Tenants template. Land four ADRs that pin the trickier policy decisions (x-pii enforcement, idempotency TTL + cleanup, cursor version policy, outbox dispatcher choice).
>
> **Why now**: AGENTS.md §16 Phase 3 explicitly mandates "promote patterns". Without this consolidation step, every following module re-invents tenancy, idempotency, ETag, cursor, problem-details, etc. — guaranteed drift. The §17.3 authorization matrix and §18.1 isolation invariant only stay enforceable when the shared helpers live in one place.
>
> **What this phase does NOT do**: No new endpoints. No new business modules. No host writes. No identity, RBAC, audit, notifications. This is *only* the refactor + documentation phase. If a task adds a new public surface, it belongs to a later phase.
>
> **Maps to AGENTS.md**: §3.4 folder layout, §3.6 internal architecture (hexagonal), §5 (idempotency, ETag, pagination, problem details), §18.1 tenant isolation, §18.5 PII redaction, §20 observability, §25.2 module boundaries, §25.9 Makefile. Also `01-foundations.md` §7, §11, §13, §14.
>
> **Estimated subagent sessions**: 2 (one for the file moves + ADRs, one for the test refactor + CONVENTIONS.md).

---

## Pre-flight

1. Read `AGENTS.md` (whole document; this phase touches every cross-cutting concern).
2. Read `CLAUDE.md` (global + project).
3. Read `00-master.md` — especially the §"Tenant isolation" 8-layer table; this phase materializes layers 1, 2, and 7 in shared code.
4. Read `01-foundations.md` §7 (chi middleware), §11 (idempotency / ETag / cursor), §13 (ULID), §14 (slog redaction).
5. Read `03-tenants-slice.md` end-to-end and note every place that calls something under `internal/platform/...` — those call sites must keep working after the promotion.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Idempotency TTL | 24 h from first request (per `01-foundations` §11) | 1 h (too short; clients legitimately retry the next day); 7 d (storage cost) |
| Idempotency cleanup mechanism | Background goroutine in the dataplane binary, ticks every 15 min, deletes `WHERE expires_at < now()` in batches of 1000 | pg_cron extension (requires host install); manual cron via host systemd |
| Cursor schema bump policy | Bumping `v` returns 410 Gone for old cursors; never silently re-interpret | Forgiving downgrade (refused — breaks idempotent retry semantics) |
| PII enforcement style | OpenAPI `x-oapi-codegen-extra-tags: { pii: "true" }` → struct tag → reflection middleware at persistence boundary | Manual encryption call per field (refused — too easy to forget) |
| Outbox dispatcher | In-process goroutine in dataplane binary (per ADR 009 stub in Phase 2) | External worker process (deferred to scale event) |
| Linter rule for tenancy | Custom `go-ruleguard` rule forbidding `tenant_id` read from `*http.Request.Header` or JSON body, allowed only from `auth.TenantFromContext` | Code-review-only (refused — bypassable) |

If the user disagrees with any default, **stop** and revise before promotion. The whole point of Phase 3 is that the next 13 phases copy these defaults.

---

## Tasks

### 3.1 Promote `internal/platform/auth/`

The Phase-2 `auth/tenant.go` already lives in `internal/platform/auth/`. Polish it but do **not** swap in JWT verification yet — that lands in Phase 5. What Phase 3 adds:

`internal/platform/auth/principal.go`:

```go
package auth

import (
    "context"
    "errors"
    "fmt"
    "strings"
)

// ActorType enumerates the principal kinds. Mirrors AGENTS.md §8.6 audit fields.
type ActorType string

const (
    ActorUser                   ActorType = "user"
    ActorAPIKey                 ActorType = "api_key"
    ActorOperator               ActorType = "operator"
    ActorOperatorImpersonation  ActorType = "operator_impersonation"
    ActorSystem                 ActorType = "system"
)

// Principal is the verified caller, populated by auth middleware.
type Principal struct {
    ActorType     ActorType
    ActorID       string   // user_<ulid>, apik_<ulid>, op_<ulid>, etc.
    TenantID      string   // empty for operator without impersonation
    Scopes        []string
    IPAddress     string
    UserAgent     string
    RequestID     string
}

// HasScope is a small helper; keep call sites explicit.
func (p Principal) HasScope(s string) bool {
    for _, sc := range p.Scopes {
        if sc == s { return true }
    }
    return false
}

type principalKey struct{}

func WithPrincipal(ctx context.Context, p Principal) context.Context {
    return context.WithValue(ctx, principalKey{}, p)
}

func PrincipalFromContext(ctx context.Context) (Principal, bool) {
    v, ok := ctx.Value(principalKey{}).(Principal)
    return v, ok
}

// Errors returned by the helpers below. Map to RFC 9457 problem types in handlers.
var (
    ErrUnauthorized   = errors.New("auth: unauthenticated")
    ErrCrossTenant    = errors.New("auth: cross-tenant access denied")
    ErrMissingScope   = errors.New("auth: missing scope")
    ErrDisabled       = errors.New("auth: principal disabled")
    ErrIPNotAllowed   = errors.New("auth: ip not allowlisted")
    ErrKeyRevoked     = errors.New("auth: api key revoked")
    ErrKeyExpired     = errors.New("auth: api key expired")
)

// AssertTenant returns ErrCrossTenant if ctx tenant differs.
// Layer 1 of tenant isolation (see 00-master.md).
func AssertTenant(ctx context.Context, requestedTenantID string) error {
    p, ok := PrincipalFromContext(ctx)
    if !ok || p.TenantID == "" {
        return ErrUnauthorized
    }
    if p.TenantID != requestedTenantID {
        return ErrCrossTenant
    }
    return nil
}

// RequireScope returns ErrMissingScope when the principal lacks the scope.
func RequireScope(ctx context.Context, scope string) error {
    p, ok := PrincipalFromContext(ctx)
    if !ok { return ErrUnauthorized }
    if !p.HasScope(scope) { return ErrMissingScope }
    return nil
}

// TenantFromContext is the only sanctioned reader of tenant_id.
// Forbid grepping for `r.Header.Get("X-Tenant-Id")` anywhere in the tree.
func TenantFromContext(ctx context.Context) (string, bool) {
    p, ok := PrincipalFromContext(ctx)
    if !ok { return "", false }
    return p.TenantID, p.TenantID != ""
}

// ActingTenantFromContext supports X-Acting-Tenant-Id impersonation.
// Returns the *effective* tenant after the header is honored.
// The header is only honored when the principal carries the
// "tenants.impersonate" scope; otherwise returns the principal's own tenant.
func ActingTenantFromContext(ctx context.Context) (string, bool) {
    p, ok := PrincipalFromContext(ctx)
    if !ok { return "", false }
    if act, ok := ctx.Value(actingTenantKey{}).(string); ok && act != "" {
        return act, true
    }
    return p.TenantID, p.TenantID != ""
}

type actingTenantKey struct{}

// WithActingTenant is only called by the auth middleware after the scope check
// (never by handler code).
func WithActingTenant(ctx context.Context, tid string) context.Context {
    return context.WithValue(ctx, actingTenantKey{}, tid)
}

// FormatActor returns the "actor_type:actor_id" string used in audit metadata.
func (p Principal) FormatActor() string {
    return fmt.Sprintf("%s:%s", p.ActorType, p.ActorID)
}

// Scopes is space-or-comma separated in JWTs; small parser.
func ParseScopes(claim string) []string {
    f := strings.FieldsFunc(claim, func(r rune) bool { return r == ' ' || r == ',' })
    out := make([]string, 0, len(f))
    for _, s := range f { if s = strings.TrimSpace(s); s != "" { out = append(out, s) } }
    return out
}
```

The Phase-2 `MockMiddleware` stays in this package but gets a build tag and a stronger refusal in prod:

`internal/platform/auth/middleware_mock.go` (build tag `!prod`):

```go
//go:build !prod

package auth

import (
    "net/http"
    "os"
)

// MockMiddleware honors X-Mock-Tenant-Id ONLY when SAAS_ENV != "prod".
// This file is excluded from prod builds at the build-tag level.
// Replaced by the real JWT verifier in Phase 5.
func MockMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if os.Getenv("SAAS_ENV") == "prod" {
            http.Error(w, "mock middleware refused in prod", http.StatusUnauthorized)
            return
        }
        tid := r.Header.Get("X-Mock-Tenant-Id")
        if tid == "" { next.ServeHTTP(w, r); return }
        p := Principal{
            ActorType: ActorUser,
            ActorID:   "user_mock",
            TenantID:  tid,
            Scopes:    ParseScopes(r.Header.Get("X-Mock-Scopes")),
            RequestID: r.Header.Get("X-Request-Id"),
            IPAddress: r.RemoteAddr,
            UserAgent: r.UserAgent(),
        }
        next.ServeHTTP(w, r.WithContext(WithPrincipal(r.Context(), p)))
    })
}
```

`internal/platform/auth/middleware_prod.go` (build tag `prod`):

```go
//go:build prod

package auth

import "net/http"

// MockMiddleware is a compile-time no-op in prod builds.
// The real middleware lives in internal/platform/auth/jwt.go (Phase 5).
func MockMiddleware(next http.Handler) http.Handler { return next }
```

### 3.2 Promote `internal/platform/tenancy/`

This package contains *only* the per-request tenant binding hooks that pair with pgx and Casbin. It does NOT own the `tenant` DB table — that's `internal/dataplane/tenancy/`. Name collisions are intentional and documented in CONVENTIONS.md (`platform/tenancy` = mechanism; `dataplane/tenancy` = resource).

`internal/platform/tenancy/binding.go`:

```go
package tenancy

import (
    "context"
    "errors"

    "github.com/jackc/pgx/v5"
    "github.com/jackc/pgx/v5/pgxpool"

    "github.com/omarss/saas/internal/platform/auth"
)

// BindOnAcquire is wired into pgxpool.Config.AfterAcquire. Returns false to
// reject the connection if the request context lacks a tenant — the safer
// failure mode is to refuse to issue a connection than to allow RLS-unset
// queries.
func BindOnAcquire(ctx context.Context, conn *pgx.Conn) bool {
    tid, ok := auth.TenantFromContext(ctx)
    if !ok {
        // Allow connectionless utility queries that don't read tenant-bound
        // tables (e.g. /healthz, migrate). Those paths use pool.Acquire with
        // context.Background() — TenantFromContext returns false; we set the
        // GUC to empty so the RLS policy returns zero rows on tenant-bound
        // tables, which is the desired failure mode.
        _, err := conn.Exec(ctx, "SET LOCAL app.current_tenant_id = ''")
        return err == nil
    }
    _, err := conn.Exec(ctx, "SET LOCAL app.current_tenant_id = $1", tid)
    return err == nil
}

// MustAcquire is a small helper to keep handler code clean.
func MustAcquire(ctx context.Context, pool *pgxpool.Pool) (*pgxpool.Conn, error) {
    if _, ok := auth.TenantFromContext(ctx); !ok {
        return nil, ErrNoTenantInContext
    }
    return pool.Acquire(ctx)
}

var ErrNoTenantInContext = errors.New("tenancy: no tenant in context; refusing to acquire connection")
```

`internal/platform/tenancy/binding_test.go` proves:

- A context with tenant X sets `app.current_tenant_id = 'X'` on the acquired connection.
- A context with no tenant sets `app.current_tenant_id = ''` (RLS returns no rows).
- Re-acquiring with a different tenant sets a different GUC (no leak across requests in the pool).

### 3.3 Promote `internal/platform/pgx/`

Thin wrapper around `pgxpool` that hard-wires the tenant binding and OpenTelemetry tracer. Every handler depends on this, never on `pgxpool.NewWithConfig` directly.

`internal/platform/pgx/pool.go`:

```go
package pgx

import (
    "context"
    "fmt"

    "github.com/jackc/pgx/v5/pgxpool"
    "github.com/exaring/otelpgx"

    "github.com/omarss/saas/internal/platform/tenancy"
)

type Options struct {
    DSN              string
    MaxConns         int32 // default 16
    MinConns         int32 // default 2
    StatementTimeout string // default "5s"
    EnableTracer     bool   // default true
}

func NewPool(ctx context.Context, opts Options) (*pgxpool.Pool, error) {
    if opts.DSN == "" { return nil, fmt.Errorf("pgx: empty DSN") }
    cfg, err := pgxpool.ParseConfig(opts.DSN)
    if err != nil { return nil, fmt.Errorf("pgx: parse config: %w", err) }

    if opts.MaxConns == 0 { opts.MaxConns = 16 }
    if opts.MinConns == 0 { opts.MinConns = 2 }
    cfg.MaxConns = opts.MaxConns
    cfg.MinConns = opts.MinConns

    if opts.EnableTracer || opts.EnableTracer == false { // default on
        cfg.ConnConfig.Tracer = otelpgx.NewTracer()
    }
    cfg.AfterAcquire = tenancy.BindOnAcquire

    pool, err := pgxpool.NewWithConfig(ctx, cfg)
    if err != nil { return nil, fmt.Errorf("pgx: new pool: %w", err) }

    if err := otelpgx.RecordStats(pool); err != nil {
        // RecordStats is best-effort metrics; do not fail boot on it.
        // log only.
    }
    return pool, nil
}
```

Update `cmd/dataplane/main.go` to call `pgx.NewPool(...)` instead of constructing `pgxpool.Config` inline. Same for `cmd/controlplane/main.go`.

### 3.4 Promote `internal/platform/log/`

slog handler + PII redactor. The redactor reads from a static keyset *plus* a registry that codegen feeds at startup.

`internal/platform/log/handler.go`:

```go
package log

import (
    "log/slog"
    "os"
)

func New() *slog.Logger {
    opts := &slog.HandlerOptions{
        AddSource: false,
        Level:     slog.LevelInfo,
        ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
            if IsRedactedKey(a.Key) {
                return slog.String(a.Key, "[REDACTED]")
            }
            // For struct values, walk fields via reflection if any field has a
            // pii:"true" tag and scrub.
            if scrub, ok := scrubStruct(a.Value); ok {
                return slog.Any(a.Key, scrub)
            }
            return a
        },
    }
    return slog.New(slog.NewJSONHandler(os.Stdout, opts))
}
```

`internal/platform/log/redact.go`:

```go
package log

import (
    "strings"
    "sync"
)

// Static keyset of fields that are always redacted, regardless of struct tag.
// Add to this set when introducing a new sensitive concept (per CLAUDE.md
// project rule: "Never log secrets. The redactor list lives here.").
var staticRedactedKeys = map[string]struct{}{
    "authorization":   {},
    "cookie":          {},
    "set-cookie":      {},
    "password":        {},
    "api_key":         {},
    "api_key_secret":  {},
    "secret":          {},
    "token":           {},
    "access_token":    {},
    "refresh_token":   {},
    "bao_token":       {},
    "vault_token":     {},
    "unseal_share":    {},
    "wrapped_dek":     {},
    "dek_plaintext":   {},
    "client_secret":   {},
    "webhook_secret":  {},
    "smtp_password":   {},
    "sendgrid_api_key": {},
    "ses_secret_access_key": {},
}

var (
    dynamicMu    sync.RWMutex
    dynamicKeys  = map[string]struct{}{}
)

// RegisterRedactedKey is called at startup by codegen-emitted init() funcs that
// walk OpenAPI x-oapi-codegen-extra-tags pii:"true" markers.
func RegisterRedactedKey(k string) {
    dynamicMu.Lock()
    defer dynamicMu.Unlock()
    dynamicKeys[strings.ToLower(k)] = struct{}{}
}

func IsRedactedKey(k string) bool {
    k = strings.ToLower(k)
    if _, ok := staticRedactedKeys[k]; ok { return true }
    dynamicMu.RLock()
    defer dynamicMu.RUnlock()
    _, ok := dynamicKeys[k]
    return ok
}
```

`internal/platform/log/scrub_struct.go` walks reflection looking for fields tagged `pii:"true"` or `sensitive:"true"` and replaces them with `"[REDACTED]"` in a copy. Implementation lifted from the official slog Handler Guide.

### 3.5 Promote `internal/platform/problem/`

RFC 9457 problem-details types + mapping from domain errors.

`internal/platform/problem/types.go`:

```go
package problem

const baseURL = "https://saas.omarss.net/problems/"

type Problem struct {
    Type      string         `json:"type"`
    Title     string         `json:"title"`
    Status    int            `json:"status"`
    Detail    string         `json:"detail,omitempty"`
    Instance  string         `json:"instance,omitempty"`
    RequestID string         `json:"request_id,omitempty"`
    Errors    []FieldError   `json:"errors,omitempty"`
}

type FieldError struct {
    Field   string `json:"field"`
    Message string `json:"message"`
    Code    string `json:"code"`
}

// Catalogue. Update openapi/problems/ in lockstep.
const (
    TypeValidation        = baseURL + "validation-error"
    TypeUnauthorized      = baseURL + "unauthorized"
    TypeForbidden         = baseURL + "forbidden"
    TypeNotFound          = baseURL + "not-found"
    TypePreconditionFail  = baseURL + "precondition-failed"
    TypeIdempotencyConflict = baseURL + "idempotency-key-conflict"
    TypeIdempotencyInFlight = baseURL + "idempotency-key-in-flight"
    TypeCursorGone        = baseURL + "cursor-version-mismatch"
    TypeRateLimited       = baseURL + "rate-limited"
    TypeCrossTenant       = baseURL + "cross-tenant-access-denied"
    TypeStepUpRequired    = baseURL + "step-up-required"
    TypeKidMismatch       = baseURL + "kid-mismatch"
    TypeKeyRevoked        = baseURL + "api-key-revoked"
    TypeKeyExpired        = baseURL + "api-key-expired"
    TypeIPNotAllowed      = baseURL + "ip-not-allowlisted"
)
```

`internal/platform/problem/mapper.go`:

```go
package problem

import (
    "errors"
    "net/http"

    "github.com/omarss/saas/internal/platform/auth"
)

// From maps a domain error to a Problem. Returns ok=false if the error is not
// a known problem-type — caller logs and returns 500 + generic body.
func From(err error, instance string) (Problem, bool) {
    switch {
    case errors.Is(err, auth.ErrUnauthorized):
        return Problem{Type: TypeUnauthorized, Title: "Unauthorized", Status: http.StatusUnauthorized, Instance: instance}, true
    case errors.Is(err, auth.ErrCrossTenant):
        return Problem{Type: TypeCrossTenant, Title: "Cross-tenant access denied", Status: http.StatusForbidden, Instance: instance}, true
    case errors.Is(err, auth.ErrMissingScope):
        return Problem{Type: TypeForbidden, Title: "Forbidden", Status: http.StatusForbidden, Instance: instance}, true
    case errors.Is(err, auth.ErrKeyRevoked):
        return Problem{Type: TypeKeyRevoked, Title: "API key revoked", Status: http.StatusUnauthorized, Instance: instance}, true
    case errors.Is(err, auth.ErrKeyExpired):
        return Problem{Type: TypeKeyExpired, Title: "API key expired", Status: http.StatusUnauthorized, Instance: instance}, true
    case errors.Is(err, auth.ErrIPNotAllowed):
        return Problem{Type: TypeIPNotAllowed, Title: "IP not allowlisted", Status: http.StatusForbidden, Instance: instance}, true
    }
    return Problem{}, false
}
```

`openapi/problems/problem.yaml` is the spec-level Problem schema (created in Phase 2 as a stub; promote to authoritative here). Every endpoint references it.

### 3.6 Promote `internal/platform/idempotency/`

Full implementation of the 24h Idempotency-Key contract from `01-foundations.md` §11.

`internal/platform/idempotency/store.go`:

```go
package idempotency

import (
    "context"
    "errors"
    "time"
)

type Record struct {
    ID              int64
    TenantID        string
    Key             string
    Route           string
    Method          string
    RequestBodyHash []byte
    ResponseStatus  int
    ResponseHeaders map[string][]string
    ResponseBody    []byte
    InFlight        bool
    CreatedAt       time.Time
    ExpiresAt       time.Time
}

type Store interface {
    // Claim returns the existing record if any (with fresh=false) and creates
    // a new in-flight record if none exists (with fresh=true).
    Claim(ctx context.Context, tenantID, key, route, method string, bodyHash []byte) (rec Record, fresh bool, err error)
    Finish(ctx context.Context, id int64, status int, headers map[string][]string, body []byte) error
    Expire(ctx context.Context, before time.Time) (int64, error)
}

var (
    ErrConflict = errors.New("idempotency: same key, different body")
    ErrInFlight = errors.New("idempotency: concurrent request still in flight")
)
```

`internal/platform/idempotency/middleware.go`:

```go
package idempotency

import (
    "bytes"
    "crypto/sha256"
    "encoding/json"
    "io"
    "net/http"
    "time"

    "github.com/omarss/saas/internal/platform/auth"
    "github.com/omarss/saas/internal/platform/problem"
)

const inFlightPollInterval = 250 * time.Millisecond
const inFlightTimeout      = 30 * time.Second

func Middleware(store Store) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            if r.Method != http.MethodPost && r.Method != http.MethodPatch {
                next.ServeHTTP(w, r); return
            }
            key := r.Header.Get("Idempotency-Key")
            if key == "" {
                next.ServeHTTP(w, r); return
            }
            tid, ok := auth.TenantFromContext(r.Context())
            if !ok {
                writeProblem(w, problem.Problem{Type: problem.TypeUnauthorized, Status: 401, Title: "Unauthorized"}); return
            }
            body, _ := io.ReadAll(r.Body)
            r.Body = io.NopCloser(bytes.NewReader(body))
            hash := sha256.Sum256(body)

            ctx, cancel := context.WithTimeout(r.Context(), inFlightTimeout+time.Second)
            defer cancel()

            rec, fresh, err := store.Claim(ctx, tid, key, r.URL.Path, r.Method, hash[:])
            if err != nil {
                writeProblem(w, problem.Problem{Type: problem.TypeIdempotencyConflict, Status: 422, Title: "Idempotency-Key conflict"}); return
            }
            if !fresh {
                if !bytes.Equal(rec.RequestBodyHash, hash[:]) {
                    writeProblem(w, problem.Problem{Type: problem.TypeIdempotencyConflict, Status: 422, Title: "Idempotency-Key reused with different body"}); return
                }
                if rec.InFlight {
                    // Poll until completion or timeout.
                    deadline := time.Now().Add(inFlightTimeout)
                    for time.Now().Before(deadline) {
                        time.Sleep(inFlightPollInterval)
                        rec, _, err = store.Claim(ctx, tid, key, r.URL.Path, r.Method, hash[:])
                        if err == nil && !rec.InFlight { break }
                    }
                    if rec.InFlight {
                        writeProblem(w, problem.Problem{Type: problem.TypeIdempotencyInFlight, Status: 409, Title: "Concurrent request still in flight"}); return
                    }
                }
                // Replay cached response.
                for k, vs := range rec.ResponseHeaders {
                    for _, v := range vs { w.Header().Add(k, v) }
                }
                w.WriteHeader(rec.ResponseStatus)
                _, _ = w.Write(rec.ResponseBody)
                return
            }

            rec2 := newRecorder(w)
            next.ServeHTTP(rec2, r)
            _ = store.Finish(ctx, rec.ID, rec2.status, rec2.headers, rec2.body.Bytes())
        })
    }
}

func writeProblem(w http.ResponseWriter, p problem.Problem) {
    w.Header().Set("Content-Type", "application/problem+json")
    w.WriteHeader(p.Status)
    _ = json.NewEncoder(w).Encode(p)
}
```

A small response recorder buffers headers + body for replay.

`internal/platform/idempotency/cleanup.go` runs the periodic expire job (ticker every 15 min, deletes in batches; logs the count). Wired into `cmd/dataplane/main.go` alongside the outbox dispatcher.

`internal/platform/idempotency/store_pgx.go` implements `Store` against `idempotency_record` from Phase 2's migration.

### 3.7 Promote `internal/platform/pagination/cursor/`

Move Phase 2's `cursor` package under `pagination/cursor/` and add typed helpers.

`internal/platform/pagination/cursor/cursor.go`:

```go
package cursor

import (
    "encoding/base64"
    "encoding/json"
    "errors"
    "time"
)

const CurrentVersion = 1

type Cursor struct {
    V         int       `json:"v"`
    CreatedAt time.Time `json:"k"`
    ID        string    `json:"id"`
}

func Encode(c Cursor) string {
    if c.V == 0 { c.V = CurrentVersion }
    b, _ := json.Marshal(c)
    return base64.RawURLEncoding.EncodeToString(b)
}

func Decode(s string) (Cursor, error) {
    raw, err := base64.RawURLEncoding.DecodeString(s)
    if err != nil { return Cursor{}, ErrBadCursor }
    var c Cursor
    if err := json.Unmarshal(raw, &c); err != nil { return Cursor{}, ErrBadCursor }
    if c.V != CurrentVersion { return Cursor{}, ErrVersionMismatch }
    return c, nil
}

var (
    ErrBadCursor       = errors.New("pagination: invalid cursor")
    ErrVersionMismatch = errors.New("pagination: cursor version mismatch")
)
```

`internal/platform/pagination/list.go` exposes a typed `Page[T]` envelope that handlers use to render the `TenantListResponse`-style payloads.

### 3.8 Promote `internal/platform/etag/`

Weak-ETag formatter + If-Match parser.

`internal/platform/etag/etag.go`:

```go
package etag

import (
    "errors"
    "strconv"
    "strings"
)

func ForSeq(seq int64) string { return `W/"v` + strconv.FormatInt(seq, 10) + `"` }

func ParseIfMatch(h string) (int64, error) {
    h = strings.TrimSpace(h)
    if !strings.HasPrefix(h, `W/"v`) || !strings.HasSuffix(h, `"`) {
        return 0, ErrMalformed
    }
    return strconv.ParseInt(h[len(`W/"v`):len(h)-1], 10, 64)
}

var ErrMalformed = errors.New("etag: malformed If-Match header")
```

### 3.9 Promote `internal/platform/id/`

ULID helper with prefix table.

`internal/platform/id/id.go`:

```go
package id

import "github.com/oklog/ulid/v2"

// Prefix table mirrors AGENTS.md §11.5.
const (
    PrefixOperator    = "op_"
    PrefixDeployment  = "dep_"
    PrefixTenant      = "tenant_"
    PrefixOrg         = "org_"
    PrefixUser        = "user_"
    PrefixMember      = "member_"
    PrefixRole        = "role_"
    PrefixPermission  = "perm_"
    PrefixAPIKey      = "apik_"
    PrefixAudit       = "audit_"
    PrefixEvent       = "evt_"
    PrefixIdempotency = "idem_"
    PrefixInvitation  = "inv_"
    PrefixDomain      = "dom_"
    PrefixChannel     = "chan_"
    PrefixWorkflow    = "wf_"
    PrefixNotification = "notif_"
)

// New returns a fresh prefixed ULID. ulid.Make is thread-safe.
func New(prefix string) string { return prefix + ulid.Make().String() }
```

### 3.10 Promote `internal/platform/validator/`

go-playground/validator wired with `WithRequiredStructEnabled` (the v11 default).

`internal/platform/validator/validator.go`:

```go
package validator

import (
    "errors"
    "strings"

    v10 "github.com/go-playground/validator/v10"
)

var V = newValidator()

func newValidator() *v10.Validate {
    v := v10.New(v10.WithRequiredStructEnabled())
    // Register custom tags here as modules introduce them (e.g. "ulid_prefix").
    return v
}

func Struct(s any) error {
    if err := V.Struct(s); err != nil {
        var ve v10.ValidationErrors
        if errors.As(err, &ve) {
            // Map to RFC 9457 problem field errors at the handler layer.
            return err
        }
        return err
    }
    return nil
}

// LowercaseField returns the JSON-style field name for an error.
func LowercaseField(field string) string { return strings.ToLower(field) }
```

### 3.11 Promote `internal/platform/outbox/`

Keep the in-process dispatcher from Phase 2 unchanged in shape, but lift it into the platform package and add metrics + structured log fields.

`internal/platform/outbox/dispatcher.go` (move from `internal/dataplane/...`, no behavioural change). Add `otelmetric.Int64Counter` for `saas.outbox.publish.success_total` and `..._fail_total`.

### 3.12 Promote `internal/platform/otel/`

A tiny `init.go` that sets up OTLP gRPC exporter, resource attributes, propagator. Wired in `cmd/controlplane/main.go` and `cmd/dataplane/main.go`. SigNoz is the default backend (deferred to Phase 15 to actually run the container).

`internal/platform/otel/init.go`:

```go
package otel

import (
    "context"
    "os"

    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/propagation"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
    semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
    "go.opentelemetry.io/otel/sdk/resource"
)

func Init(ctx context.Context, service string) (func(context.Context) error, error) {
    endpoint := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint == "" {
        // No exporter — return no-op shutdown.
        return func(context.Context) error { return nil }, nil
    }
    exp, err := otlptracegrpc.New(ctx, otlptracegrpc.WithEndpoint(endpoint), otlptracegrpc.WithInsecure())
    if err != nil { return nil, err }

    res, _ := resource.New(ctx, resource.WithAttributes(semconv.ServiceName(service)))

    tp := sdktrace.NewTracerProvider(sdktrace.WithBatcher(exp), sdktrace.WithResource(res))
    otel.SetTracerProvider(tp)
    otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
    return tp.Shutdown, nil
}
```

### 3.13 Reflection middleware for `x-pii` enforcement (ADR 004)

`internal/platform/crypto/encrypt_persist.go` is **declared** in Phase 3 but **not wired** — the envelope encryptor it depends on lands in Phase 4. The Phase 3 deliverable is the reflection walker + a panicking placeholder for the encrypt call so callers fail fast if Phase 4 hasn't landed:

```go
package crypto

import (
    "context"
    "reflect"
)

// EncryptPIIFields walks v and calls Encryptor.Encrypt on every field tagged
// pii:"true" or sensitive:"true". v must be a pointer to a struct. The
// Encryptor interface is defined here; the OpenBao-backed implementation
// lands in Phase 4 (internal/platform/crypto/envelope/).
type Encryptor interface {
    EncryptField(ctx context.Context, kid string, plaintext []byte, aad []byte) (Envelope, error)
}

type Envelope struct {
    Ciphertext []byte
    WrappedDEK string
    Nonce      []byte
    Algo       string
    KID        string
    KeyVersion int
}

func EncryptPIIFields(ctx context.Context, enc Encryptor, kid string, v any) error {
    rv := reflect.ValueOf(v)
    if rv.Kind() != reflect.Ptr || rv.IsNil() {
        return ErrNotPointer
    }
    return walk(ctx, enc, kid, rv.Elem())
}

// walk + helpers below; implementation is straightforward reflection.
```

The integration point is at the persistence boundary in each module's repo adapter. CONVENTIONS.md documents the call-site idiom.

### 3.14 Refactor Phase-2 Tenants to depend on the promoted packages

Concrete edit list:

| File | Change |
|---|---|
| `internal/dataplane/tenancy/service.go` | Replace inline `auth.AssertTenant` import path (no change if already pointing at `internal/platform/auth`); call `id.New(id.PrefixTenant)` instead of literal string concat. |
| `internal/dataplane/tenancy/handler.go` | Use `problem.From` for error mapping; use `etag.ForSeq` / `etag.ParseIfMatch`; use `cursor.Encode/Decode`; use `pagination.Page[T]`. |
| `internal/dataplane/tenancy/repo_pgx.go` | Switch to acquiring connections via `tenancy.MustAcquire(ctx, pool)` to get the early-failure on missing tenant context. |
| `cmd/dataplane/main.go` | Use `pgx.NewPool`, `otel.Init`, `log.New`, `auth.MockMiddleware` (build-tag gated), `idempotency.Middleware`, `outbox.NewDispatcher`. |
| `cmd/controlplane/main.go` | Same wiring as dataplane (minus tenant binding — the operator context binds `deployment_id`, not `tenant_id`; the platform/pgx pool used by the control plane skips the AfterAcquire hook). Configure via `pgx.NewPool(... AfterAcquire: nil)` — add an `Options.SkipTenantBinding` flag. |

After this refactor, `internal/dataplane/tenancy/` contains only the Tenants resource: domain types, service, port, adapter, sqlc, handler, tests. All cross-cutting concerns live in `internal/platform/`.

### 3.15 Linter rules

`.golangci.yml`: add a `forbidigo` block:

```yaml
linters:
  enable:
    - forbidigo
linters-settings:
  forbidigo:
    forbid:
      - p: '\\bHeader\\.Get\\("X-Tenant-Id"\\)'
        msg: 'X-Tenant-Id is rejected by design. Use auth.TenantFromContext.'
      - p: '\\bHeader\\.Get\\("X-Mock-Tenant-Id"\\)'
        msg: 'Only auth.MockMiddleware may read this header. Production builds drop it via build tag.'
      - p: 'os\\.Getenv\\("OPENBAO_TOKEN"\\)'
        msg: 'Read OpenBao token via the api/v2 client, never via env at call sites.'
```

Plus an `analyzers` block enabling `errorlint` (`errors.Is`/`errors.As`) and `nilerr` (`if err != nil { return nil }`).

### 3.16 CONVENTIONS.md

Author `/home/omar/workspace_personal/saas/CONVENTIONS.md`. Sections:

1. **Module skeleton** — copy-paste tree for a new domain module:

   ```text
   internal/<plane>/<module>/
     domain.go       # types, enums, validation
     ports.go        # Repository, EventPublisher, optional adapters
     service.go      # orchestration; first non-ctx arg is tenantID for tenant-bound modules
     repo_pgx.go     # pgx-backed repository
     handler.go      # strict-server interface implementation
     errors.go
     service_test.go
     repo_pgx_test.go
     security_test.go    # §17.3 matrix (mandatory for tenant-bound)
   internal/<plane>/db/queries/<module>.sql
   migrations/<plane>/NNNNNN_<module>.up.sql
   openapi/<plane>.yaml  # add tag + paths + schemas
   sdk/ts/<plane>/workflows/<module>.ts
   ```

2. **Service method signatures** — every tenant-bound method starts with `(ctx context.Context, tenantID string, ...)`.

3. **Handler error mapping** — `problem.From(err, instance)`; never write a raw `http.Error`.

4. **Migrations** — forward-only; new tenant-bound table requires RLS + policy + index on `(tenant_id, ...)`.

5. **Tests** — `_test.go` unit, `_test.go` with build tag `integration` for testcontainers, `security_test.go` for the §17.3 matrix. Test naming: `TestModule_AuthZ_CrossTenant`, `TestModule_ETag_Stale`, etc.

6. **Log fields** — always emit `{tenant_id, request_id, deployment_id}`; never emit `secret`, `password`, `token`, `api_key`, anything tagged PII.

7. **Idempotency** — every POST and state-transition PATCH requires `Idempotency-Key`. Add the OpenAPI parameter and the middleware wires up automatically.

8. **ETag** — every mutable resource has `row_seq bigint NOT NULL DEFAULT 1` + the shared `bump_row_seq()` trigger. Service returns the new `row_seq`; handler formats with `etag.ForSeq`.

9. **Events** — emit via `EventPublisher`; types follow `<resource>.<verb>` (lowercase). Update `openapi/events/` catalogue (created in Phase 9 alongside audit; for now keep a TODO).

10. **PII** — mark with `x-oapi-codegen-extra-tags: { pii: "true" }`; codegen emits `pii:"true"` struct tag; the encrypt walker handles persistence; the slog redactor handles logging.

11. **Cursors** — version 1 schema; bump requires ADR and 410 Gone for old.

12. **Commit messages** — lowercase, ≤ 50 chars, no Co-Authored-By, no emoji. Examples:
    - `promote platform patterns`
    - `add idempotency middleware`
    - `wire pgx pool tenant binding`

13. **PR template** — `.github/PULL_REQUEST_TEMPLATE.md`; add `ready` label to trigger CI.

### 3.17 ADRs

Create four ADRs under `docs/adr/`:

`004-x-pii-enforcement.md`:

```markdown
# ADR 004 — x-pii enforcement via x-oapi-codegen-extra-tags + reflection middleware

## Status
Accepted (2026-05-24).

## Context
AGENTS.md §18.5 mandates that PII fields are never logged in plaintext.
§18.7 mandates envelope encryption for fields declared `x-pii: true`.
oapi-codegen does NOT forward arbitrary `x-` extensions to struct tags
(01-foundations.md §2, §3). We need a mechanism that survives codegen.

## Decision
Author the OpenAPI fields with:

    x-oapi-codegen-extra-tags:
      pii: "true"
      sensitive: "true"

oapi-codegen emits the struct field with the `pii:"true"` Go tag.
Two consumers read it:

1. `internal/platform/log/scrub_struct.go` walks reflection and redacts
   tagged fields in slog records (`ReplaceAttr` hook).
2. `internal/platform/crypto/encrypt_persist.go` walks reflection at the
   persistence boundary and calls the envelope encryptor for tagged
   fields (implementation in Phase 4).

## Consequences
- Authors annotate fields in OpenAPI, not in Go. Single source of truth.
- A field added without the tag silently leaks; mitigation: code review +
  the redactor's static keyset catches the obvious names.
- The reflection walker is hot-path code. Benchmark before each minor
  release.
```

`010-idempotency-ttl-cleanup.md`: 24h window; 15-min cleanup ticker; rationale + storage estimate.

`011-cursor-version-bump-410.md`: schema bump → 410 Gone; never silently re-interpret.

`009-outbox-dispatcher.md`: in-process goroutine; future migration path to NATS or `asynq`.

### 3.18 Wire tests

`internal/platform/idempotency/middleware_test.go` covers:

- Missing Idempotency-Key on POST → handler runs normally
- Fresh key → handler runs once, record persisted with response
- Same key + same body → replay (handler not invoked twice)
- Same key + different body → 422 problem-details `idempotency-key-conflict`
- Concurrent same-key requests → second blocks ≤ 30s, then 409 if first still in-flight
- Expired record (TTL+1s) → behaves as fresh

`internal/platform/etag/etag_test.go` covers seq formatting + parsing edge cases.

`internal/platform/pagination/cursor/cursor_test.go` covers v=1 round-trip, v=2 → `ErrVersionMismatch`, malformed input.

`internal/platform/log/redact_test.go` covers static keyset hits, dynamic registration, and the struct walker.

### 3.19 Update `make sqlc-gen` to include both planes

Phase 1's `sqlc.yaml` already has both stanzas. Sanity-check it generates clean and CI runs `make sqlc-gen` then `git diff --exit-code` to catch drift.

### 3.20 Update `make openapi-check`

Add the `openapi/problems/` directory to the spectral lint set (one file per Problem type per the catalogue in §3.5).

### 3.21 Commit and prepare for checkpoint

Atomic commits per global CLAUDE.md:

```bash
git add internal/platform/auth/ internal/platform/tenancy/ internal/platform/pgx/
git commit -m "promote auth tenancy pgx platform pkgs"

git add internal/platform/log/ internal/platform/problem/
git commit -m "promote log redaction and problem details"

git add internal/platform/idempotency/ internal/platform/pagination/ internal/platform/etag/ internal/platform/id/ internal/platform/validator/
git commit -m "promote idempotency etag pagination helpers"

git add internal/platform/outbox/ internal/platform/otel/ internal/platform/crypto/
git commit -m "promote outbox otel and crypto interface"

git add internal/dataplane/tenancy/ cmd/dataplane/ cmd/controlplane/
git commit -m "rewire tenants on platform pkgs"

git add CONVENTIONS.md docs/adr/004-*.md docs/adr/009-*.md docs/adr/010-*.md docs/adr/011-*.md
git commit -m "author conventions and platform adrs"

git add .golangci.yml openapi/problems/
git commit -m "lint forbidden patterns and problem catalog"
```

---

## Verification checklist

```bash
# 1. Build + lint:
$ make build
$ make lint
# Expected: 0 findings (forbidigo + errorlint catch the patterns)

# 2. OpenAPI still round-trips clean:
$ make openapi-check
# Expected: 0 errors, 0 drift

# 3. Unit + integration tests:
$ make test
$ make test-int
# Expected: green; new platform packages have their own tests

# 4. Tenants security tests still green (regression catch):
$ go test -run TestTenants_AuthZ -v ./internal/dataplane/tenancy/...
# Expected: same-tenant, cross-tenant, missing-ctx, prod-mock-refused, X-Tenant-Id-ignored — all pass

# 5. Tenants contract tests still green:
$ make contract-test
# Expected: all fixtures replay

# 6. Linter catches a new bad pattern (proof the rule works):
$ echo 'func foo(r *http.Request) { _ = r.Header.Get("X-Tenant-Id") }' > /tmp/bad.go
$ cd internal/dataplane/tenancy && cp /tmp/bad.go bad_test_dummy.go && go vet . ; rm bad_test_dummy.go
# Expected: lint complains; cleanup removes the file

# 7. End-to-end Tenants smoke:
$ SAAS_ENV=dev ./bin/dataplane &
$ curl -s -X POST http://localhost:9090/v1/tenants \
    -H "X-Mock-Tenant-Id: tenant_self" \
    -H "Idempotency-Key: idem_01HXAAAAAAAAAAAAAAAAAAAAAA" \
    -H "Content-Type: application/json" \
    -d '{"slug":"acme","name":"Acme"}' | jq .
# Expected: 201 + tenant_<ulid>

# 8. PII redaction smoke (slog):
$ go test -run TestLog_RedactsPII ./internal/platform/log/...
# Expected: emails / phones / wrapped_dek replaced with "[REDACTED]" in JSON output

# 9. Idempotency cleanup ticker runs:
$ SAAS_ENV=dev IDEMPOTENCY_CLEANUP_INTERVAL=2s ./bin/dataplane &
$ sleep 5 && grep "idempotency.cleanup" dataplane.log
# Expected: at least 2 cleanup ticks logged
```

---

## Anti-pattern guards

- **NEVER** add a new public surface in this phase. The only output is refactored shared code + CONVENTIONS.md + ADRs.
- **NEVER** read `tenant_id` from a request body, query string, or path parameter. Only `auth.TenantFromContext`.
- **NEVER** read `X-Tenant-Id` or `X-Mock-Tenant-Id` outside `internal/platform/auth/`. The linter rule enforces this; do not add `//nolint:forbidigo`.
- **NEVER** acquire a pgx connection without a tenant in context for tenant-bound queries. `tenancy.MustAcquire` returns `ErrNoTenantInContext` — surface it as 401, not 500.
- **NEVER** add a Problem `type` URI without adding a fragment under `openapi/problems/`. The catalogue must round-trip.
- **NEVER** modify `internal/dataplane/tenancy/` behavior in this phase. The promotion is *only* swapping import paths to the shared packages — the §17.3 matrix must still pass.
- **NEVER** silently downgrade an unknown cursor version. ADR 011 returns 410.
- **NEVER** introduce a panic in middleware. All errors flow through `problem.Problem` with a status code.
- **NEVER** log a tenant_id collision (two tenant_ids in one record) without an explicit `slog.Warn("possible isolation breach", ...)` — masking the symptom hides incidents.

---

## Open questions

1. **build tag `prod` vs env var.** Default: `go build -tags prod` produces the prod binary; the mock middleware is excluded at compile time. Alternative: a runtime check on `SAAS_ENV=prod`. Build tag is stronger (the code cannot reach prod). Confirm before finalizing the Dockerfile.

2. **Should the platform/pgx pool wrap acquire failures with a slog warning?** Risk: noisy log. Reward: faster diagnosis of missing-middleware bugs. Default: yes, single warn-level line per minute, throttled.

3. **Where does the `deployment_id` flow into the outbox publisher?** Phase 2 reads from an env var at startup. After Phase 11 lands real provisioning, the dataplane binary's deployment_id should come from a k8s downward API field. Phase 11 will swap; flag now so we don't forget.

---

## Phase 3 — Definition of done

- [ ] All seven `internal/platform/` packages exist with tests and godoc on every exported symbol
- [ ] `internal/dataplane/tenancy/` uses only platform packages for cross-cutting concerns
- [ ] `cmd/dataplane/main.go` and `cmd/controlplane/main.go` boot through `pgx.NewPool`, `otel.Init`, `log.New`, `auth.MockMiddleware` (tag-gated), `idempotency.Middleware`, `outbox.Dispatcher`
- [ ] `CONVENTIONS.md` authored and committed at repo root
- [ ] ADRs 004, 009, 010, 011 committed
- [ ] `make lint` enforces the forbidden-pattern set
- [ ] All Phase 2 tests still green (no regression)
- [ ] New platform packages each have ≥ 80% coverage
- [ ] `make openapi-check` clean; `git diff --exit-code` on generated code clean
- [ ] PR template merged, `ready` label added, CI green

---

## CHECKPOINT 1 — Patterns ready

### What was done
- `internal/platform/auth/` — Principal type, AssertTenant, RequireScope, build-tag-gated MockMiddleware
- `internal/platform/tenancy/binding.go` — pgx AfterAcquire hook that sets `app.current_tenant_id` GUC
- `internal/platform/pgx/pool.go` — wrapper around pgxpool that hard-wires the tenant binding + otelpgx tracer
- `internal/platform/log/` — slog handler + static + dynamic PII redactor + struct walker
- `internal/platform/problem/` — RFC 9457 types + domain-error → Problem mapper + catalogue
- `internal/platform/idempotency/` — 24h Store + middleware + pgx store + 15-min cleanup ticker
- `internal/platform/pagination/cursor/` — versioned cursor (v=1) with 410 on bump
- `internal/platform/etag/` — weak ETag formatter + If-Match parser
- `internal/platform/id/` — ULID helper with the full prefix table from §11.5
- `internal/platform/validator/` — go-playground/validator v10 with `WithRequiredStructEnabled`
- `internal/platform/outbox/` — in-process dispatcher (moved from dataplane)
- `internal/platform/otel/` — OTLP gRPC exporter init (no-op when endpoint unset)
- `internal/platform/crypto/encrypt_persist.go` — reflection walker (interface only; encryptor in Phase 4)
- `internal/dataplane/tenancy/*.go` — rewired to platform packages, no behaviour change
- `CONVENTIONS.md` — 13-section authoring guide
- `docs/adr/004-x-pii-enforcement.md`, `009-outbox-dispatcher.md`, `010-idempotency-ttl-cleanup.md`, `011-cursor-version-bump-410.md`
- `.golangci.yml` — forbidigo + errorlint + nilerr enabled

### What to verify (user runs these)
```bash
$ make build                           # expected: all 4 binaries
$ make lint                            # expected: 0 findings
$ make openapi-check                   # expected: 0 errors, 0 drift
$ make test                            # expected: green
$ make test-int                        # expected: green (testcontainers Postgres)
$ ls internal/platform/                # expected: 13 subdirectories
$ wc -l CONVENTIONS.md                 # expected: ~200-300 lines
$ ls docs/adr/                         # expected: ADRs 001, 002, 003 (Phase 2), 004, 009, 010, 011
$ git log --oneline -10                # expected: 7-ish atomic commits with lowercase ≤50char titles
```

### What approval means
By proceeding past CHECKPOINT 1, you accept that the next 13 phases will mechanically copy the patterns landed here. Specifically:
- Every new module's service-layer method takes `(ctx, tenantID, ...)` as the first two params.
- Every tenant-bound endpoint requires the §17.3 authorization matrix to land in the SAME PR as the endpoint.
- Every PII field is declared in OpenAPI with `x-oapi-codegen-extra-tags pii:"true"` — never tagged in Go directly.
- Every mutating endpoint requires `Idempotency-Key` and `If-Match` (where stateful).
- Cursors are v=1; bumping requires an ADR + 410 Gone on old cursors.
- The Phase-2 `MockMiddleware` keeps reading `X-Mock-Tenant-Id` until Phase 5 swaps it for real JWT verification — production builds drop it at the build-tag level, not at runtime.

### Rollback if rejected
```bash
git revert HEAD~7..HEAD                # undo the 7 phase-3 commits
make build && make test                # confirm Phase 2 state restored
```

---

End of Phase 3. Next: `05-openbao-integration.md`.
