# Phase 0 — Foundations Reference

> **Read this every phase.** It is the only authority on exact library versions, exact API signatures, and verified gotchas. The values here were established by Documentation Discovery on 2026-05-24. Do not invent APIs not listed here without re-verifying.

## Source attribution

| Topic | Verified against | Confidence |
|---|---|---|
| Go stack (oapi-codegen, chi, sqlc, pgx, migrate, ulid, argon2, otel, validator, slog) | pkg.go.dev + official READMEs + release notes (Q1–Q2 2026) | High |
| OpenBao API client | pkg.go.dev `github.com/openbao/openbao/api/v2` v2.5.1, OpenBao docs | High; medium on `static` seal stance |
| Casbin v2 + adapter | pkg.go.dev `github.com/casbin/casbin/v2` v2.135.0, upstream model files | High on core API; medium on pgx-adapter freshness |
| OpenAPI tooling | spectral 6.16.0, prism 5.15.10, oapi-codegen v2.7.0, openapi-generator-cli 7.22.0 | High on versions; medium on 3.1 conformance |
| Keycloak + JWT | gocloak v14.0.3 (Apache-2.0), lestrrat-go/jwx v3.1.1 (MIT) | High |
| client-go + kustomize | k8s.io/client-go v0.36.1, sigs.k8s.io/kustomize/api v0.21.1 | High |
| Local conventions | `../qiyas/qudrat.ai/` and `../homelab/` direct reads | High |

---

## §1. Stack pins (Q2 2026)

Pin all of these in `go.mod`, `Makefile`, and `package.json`. Do not float to `latest`; do not upgrade without ADR.

### Go (module `github.com/omarss/saas`, Go 1.24)

```text
github.com/go-chi/chi/v5                                v5.3.0
github.com/jackc/pgx/v5                                 v5.9.2
github.com/oapi-codegen/oapi-codegen/v2                 v2.7.0    (build tool)
github.com/oapi-codegen/nethttp-middleware              v1.1.2
github.com/oapi-codegen/runtime                         v1.2.0
github.com/golang-migrate/migrate/v4                    v4.19.1
github.com/oklog/ulid/v2                                v2.1.1
github.com/exaring/otelpgx                              latest    (verify; needs Go 1.25)
go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp  v0.68.0
github.com/go-playground/validator/v10                  v10.latest    (WithRequiredStructEnabled)
golang.org/x/crypto                                     latest
github.com/openbao/openbao/api/v2                       v2.5.1
github.com/casbin/casbin/v2                             v2.135.0
github.com/pckhoi/casbin-pgx-adapter/v3                 v3.2.0    (verify build against casbin 2.135 first)
github.com/Nerzal/gocloak/v14                           v14.0.3
github.com/lestrrat-go/jwx/v3                           v3.1.1
k8s.io/client-go                                        v0.30.x   (match k3s minor)
sigs.k8s.io/kustomize/api                               v0.21.1
github.com/spf13/cobra                                  latest
sqlc                                                    v1.31.1   (CLI; not a go.mod dep)
```

### Node (Makefile invocations via `docker run`)

```text
@stoplight/spectral-cli         6.16.0
@stoplight/prism-cli            5.15.10
@openapitools/openapi-generator-cli  7.22.0
```

### Database

```text
PostgreSQL 16+ (host instance)
OpenBao v2.5.4 (`bao` binary)
Keycloak 26.x
```

### Pin verification command (run after any upgrade)

```bash
go mod tidy
go mod verify
go build ./...
make openapi-check
```

---

## §2. oapi-codegen — chi-server + strict-server pattern

`go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@v2.7.0 -config <cfg.yaml> <spec.yaml>`

Per-spec config files (one for control plane, one for data plane):

```yaml
# .oapi-codegen-dataplane.yaml
package: dataplaneapi
output: internal/dataplane/httpapi/server.gen.go
generate:
  models: true
  chi-server: true
  strict-server: true     # MUST pair with a server target
  embedded-spec: true
output-options:
  skip-fmt: false
  skip-prune: false
  overlay:
    path: openapi/overlays/30-downgrade.yaml
```

**Anti-patterns:**

- `strict-server: true` alone → generates nothing; always pair with `chi-server: true`.
- Calling `r.PathValue("name")` in handlers → the chi target uses `chi.URLParam(r, "name")`; mixing breaks routing.
- Setting `spec.Servers` and trying to use the validator middleware → it rejects on Host mismatch. Set `spec.Servers = nil` at startup before installing the validator.
- Assuming auth middleware is generated → it isn't (issue #1524). Wire `nethttp-middleware` with `AuthenticationFunc`:

```go
import (
    middleware "github.com/oapi-codegen/nethttp-middleware"
    "github.com/getkin/kin-openapi/openapi3filter"
)
opts := &middleware.Options{Options: openapi3filter.Options{
    AuthenticationFunc: func(ctx context.Context, ai *openapi3filter.AuthenticationInput) error {
        // verify JWT / API key from ai.RequestValidationInput.Request
    },
}}
r.Use(middleware.OapiRequestValidatorWithOptions(spec, opts))
```

**`x-` extensions oapi-codegen surfaces:**

- `x-go-name`, `x-go-type`, `x-go-type-skip-optional-pointer`
- `x-oapi-codegen-extra-tags` — **this is how we tag PII fields** (see §3).
- Arbitrary extensions like `x-pii` do NOT auto-propagate. ADR 004 documents the workaround.

---

## §3. OpenAPI 3.1 with overlay-downgrade

**oapi-codegen v2.7 still does not natively support OpenAPI 3.1** (issue #373; blocked on Go 1.26). The platform authors specs in 3.1 and uses Overlay-down-convert to 3.0 before generating Go server stubs.

`openapi/overlays/30-downgrade.yaml`:

```yaml
overlay: 1.0.0
info: { title: Downgrade for oapi-codegen, version: 0.0.0 }
actions:
  - target: "$.openapi"
    update: "3.0.3"
  - target: '$.components.schemas..properties[?(@.type && length(@.type) == 2)]'
    update: { type: string, nullable: true }
```

`make openapi-check` pipeline:

```text
1. spectral lint openapi/control-plane.yaml openapi/data-plane.yaml   (3.1 native)
2. apply overlay → openapi/_generated/control-plane-30.yaml + data-plane-30.yaml
3. oapi-codegen --config <cfg> openapi/_generated/<plane>-30.yaml     (Go server stubs)
4. openapi-generator-cli typescript-axios --config <cfg>              (TS SDK)
5. git diff --exit-code on generated/ — fail if dirty (CI policy)
```

**`x-pii` enforcement strategy (ADR 004):**

In the OpenAPI schema, mark fields with `x-oapi-codegen-extra-tags`:

```yaml
properties:
  email:
    type: string
    format: email
    x-oapi-codegen-extra-tags:
      pii: "true"
      sensitive: "true"
```

oapi-codegen emits `Email string \`json:"email" pii:"true" sensitive:"true"\``. A runtime middleware (`internal/platform/crypto/encrypt_persist.go`) walks structs via reflection at the persistence boundary and calls the envelope encryptor for any `pii:"true"` field. The slog redactor uses the same tag list to scrub log records.

---

## §4. sqlc + pgx + migrations

### `sqlc.yaml` (v2, copied pattern from qudrat.ai)

```yaml
version: "2"
sql:
  - engine: "postgresql"
    queries: "internal/db/queries"           # *.sql with -- name: directives
    schema:  "migrations/dataplane"          # forward-only .up.sql files
    gen:
      go:
        package: "db"
        out: "internal/db/sqlc"
        sql_package: "pgx/v5"
        emit_json_tags: true
        emit_interface: true
        emit_pointers_for_null_types: true
        emit_enum_valid_method: true
        overrides:
          - db_type: "uuid"
            go_type: { import: "github.com/google/uuid", package: uuid, type: UUID }
```

Two `sqlc.yaml` files: one for control plane, one for data plane (they generate into different packages with different schemas).

### Query annotations

- `:exec` (error only), `:execrows` (int64+err), `:execresult`
- `:one` (row+err), `:many` ([]row+err)
- `:batchexec`, `:batchone`, `:batchmany` (pgx batch)
- `:copyfrom` (bulk via COPY)

### pgxpool init

```go
cfg, err := pgxpool.ParseConfig(dsn)            // sslmode=verify-full
cfg.ConnConfig.Tracer = otelpgx.NewTracer()     // OpenTelemetry
cfg.AfterAcquire = setTenantGUC                 // session-level RLS binding
pool, err := pgxpool.NewWithConfig(ctx, cfg)
otelpgx.RecordStats(pool)
```

`setTenantGUC` runs `SET LOCAL app.current_tenant_id = $1` for each acquired conn, sourcing from `auth.TenantFromContext(ctx)`. **This is layer 3 of tenant isolation.** Without this hook RLS does nothing.

### golang-migrate (forward-only)

```go
//go:embed migrations/dataplane/*.up.sql
var migrationsFS embed.FS

d, _ := iofs.New(migrationsFS, "migrations/dataplane")
m, _ := migrate.NewWithSourceInstance("iofs", d, dsn)
_ = m.Up()
```

File naming: `NNNNNN_name.up.sql`. Down files allowed but not required (forward-only per §25.4). Use `x-migrations-table=schema_migrations_dataplane` in the DSN if both planes share a DB during dev.

**Anti-patterns:**

- `CREATE INDEX CONCURRENTLY` in a transactional migration — must be its own file with `x-multi-statement=true`.
- Mixing pgx versions — sqlc's `sql_package: pgx/v5` is sticky; switching after the fact requires regenerating every query file.
- Forgetting `cfg.AfterAcquire = setTenantGUC` → RLS allows everything.

---

## §5. OpenBao envelope encryption

### Client init

```go
import bao "github.com/openbao/openbao/api/v2"

cfg := bao.DefaultConfig()
cfg.Address = os.Getenv("BAO_ADDR")
_ = cfg.ConfigureTLS(&bao.TLSConfig{CACert: caPath})
client, _ := bao.NewClient(cfg)
```

### Auth: k8s for data-plane pods, AppRole for control-plane

Data plane (in-cluster pod):

```go
saJWT, _ := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/token")
sec, _ := client.Logical().WriteWithContext(ctx, "auth/kubernetes/login",
    map[string]any{"role": deploymentID, "jwt": string(saJWT)})
client.SetToken(sec.Auth.ClientToken)
w, _ := client.NewLifetimeWatcher(&bao.LifetimeWatcherInput{Secret: sec, Increment: 3600})
go w.Start()
```

Control plane (host process):

```go
sec, _ := client.Logical().WriteWithContext(ctx, "auth/approle/login",
    map[string]any{"role_id": roleID, "secret_id": secretID})
client.SetToken(sec.Auth.ClientToken)
```

### Envelope — `transit/datakey/plaintext/:name` (recommended)

```go
// Request:
sec, err := client.Logical().WriteWithContext(ctx, "transit/datakey/plaintext/"+kid,
    map[string]any{"bits": 256})
// Response data:
//   data.plaintext  = base64(32 random bytes)  -- the DEK
//   data.ciphertext = "vault:v1:<b64 wrapped DEK>"

dek, _ := base64.StdEncoding.DecodeString(sec.Data["plaintext"].(string))
block, _ := aes.NewCipher(dek)
gcm, _ := cipher.NewGCM(block)
nonce := make([]byte, gcm.NonceSize())
_, _ = rand.Read(nonce)
ct := gcm.Seal(nil, nonce, plaintext, aad)

// Store: {ciphertext: ct, wrapped_dek: sec.Data["ciphertext"], nonce, algo: "aes-256-gcm",
//         kid: deploymentID, key_version: parsedFromWrappedDek}
// Zero(dek)
```

### Decrypt — verify `kid == deployment_id` BEFORE the API call

```go
if row.Kid != ctx.DeploymentID {
    return nil, ErrKidMismatch       // refuse; do not call OpenBao
}
sec, _ := client.Logical().WriteWithContext(ctx, "transit/decrypt/"+row.Kid,
    map[string]any{"ciphertext": row.WrappedDek})
dek, _ := base64.StdEncoding.DecodeString(sec.Data["plaintext"].(string))
block, _ := aes.NewCipher(dek)
gcm, _ := cipher.NewGCM(block)
plaintext, _ := gcm.Open(nil, row.Nonce, row.Ciphertext, aad)
// Zero(dek)
```

**The ciphertext blob `vault:v<N>:<b64>` does NOT contain the key NAME — only the key version.** The kid binding is enforced solely by which URL path the app chooses at decrypt time. Layer 5 of tenant isolation depends on this check being unforgeable.

### Key rotation

```text
POST /v1/transit/keys/<kid>/rotate     → new key_version, old retained for decrypt
POST /v1/transit/rewrap/<kid>          → re-wrap old wrapped_dek against latest version
                                          (background batch job, no plaintext exposure)
```

### MVP unseal — Shamir 5-of-3 with scripted unseal on boot

OpenBao has **no file-based auto-unseal seal**; `static` exists but is dev-only. Real MVP path:

1. `bao operator init -key-shares=5 -key-threshold=3 -format=json` → captures 5 shares.
2. Shares are split: 1 in a 0400 file on the host (boot-time auto-unseal — accepts dev-grade threat model), 4 held offline by operator.
3. systemd unit reads share-1 + 2 prompted shares at first unseal; subsequent reboots use 3 shares from disk (sealed envelope, age-encrypted with operator passphrase entered manually).
4. Production target: cloud KMS auto-unseal (documented; out of MVP scope).

ADR 006 records this trade-off.

### Per-deployment policy (HCL)

```hcl
# policies/dep-<id>.hcl
path "transit/encrypt/<id>"            { capabilities = ["update"] }
path "transit/decrypt/<id>"            { capabilities = ["update"] }
path "transit/datakey/plaintext/<id>"  { capabilities = ["update"] }
path "transit/rewrap/<id>"             { capabilities = ["update"] }
path "transit/keys/<id>"               { capabilities = ["read"] }
path "secret/data/<id>/*"              { capabilities = ["create","read","update","delete"] }
path "secret/metadata/<id>/*"          { capabilities = ["list","read","delete"] }
```

No globs in transit paths — one policy file per Deployment, templated.

### Anti-patterns

- Reading `vault:v<N>:...` and inferring the key name from the URL path the **caller** chose → kid binding only holds if the caller is trusted. Always check `row.Kid` in DB against `ctx.DeploymentID`.
- Storing DEK plaintext anywhere — zero with `crypto/subtle` and explicit slice zero after `gcm.Seal`/`gcm.Open`.
- Logging OpenBao tokens, unseal shares, or wrapped DEKs (§18.5 redactor list).
- Using the root token past initial setup — revoke it.
- Calling `transit/encrypt` per row instead of `batch_input` → RTT-bound.

---

## §6. Casbin RBAC-with-domains

### Model file (verbatim from upstream `rbac_with_domains_model.conf`)

```ini
[request_definition]
r = sub, dom, obj, act

[policy_definition]
p = sub, dom, obj, act

[role_definition]
g = _, _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub, r.dom) && r.dom == p.dom && r.obj == p.obj && r.act == p.act
```

`sub` = `member_id` (prefix `m:`), `dom` = `tenant_id`, `obj` = resource_type, `act` = action.

### §8.4 check API → enforce mapping

```text
POST /v1/authorization/check
  { member_id, permission: "invoice.read", tenant_id }
→ obj, act := strings.Cut(permission, ".")     // split at handler boundary
→ allowed, matched, _ := enforcer.EnforceEx(memberID, tenantID, obj, act)
→ viaRole = matched[0]  // the p-row's sub column
```

### Enforcer construction (pgx adapter)

```go
import (
    "github.com/casbin/casbin/v2"
    pgxadapter "github.com/pckhoi/casbin-pgx-adapter/v3"
)
a, _ := pgxadapter.NewAdapter(pool,
    pgxadapter.WithConnectionPool(pool),
    pgxadapter.WithTableName("casbin_rule"),
    pgxadapter.WithSchema("public"))
e, _ := casbin.NewEnforcer("internal/dataplane/authorization/rbac.conf", a)
e.EnableAutoSave(true)
_ = e.LoadPolicy()
```

**Verify pckhoi/casbin-pgx-adapter v3.2.0 builds against casbin/v2 v2.135.0 before pinning.** Last adapter release was Aug 2024; the adapter interface in v2 has been stable but check first. If broken, fall back to a thin sqlc-driven adapter (~80 LoC implementing `persist.Adapter`).

### Layer-6 enforcement: forbid wildcard `dom`

```sql
ALTER TABLE casbin_rule
  ADD CONSTRAINT casbin_rule_no_wildcard_domain
  CHECK (ptype <> 'p' OR v1 <> '*')
  ADD CONSTRAINT casbin_rule_no_wildcard_grouping
  CHECK (ptype <> 'g' OR v2 <> '*');
```

### Watcher (multi-replica sync)

MVP: single replica, no watcher. When scaling, use `github.com/casbin/redis-watcher/v2` v2.8.0; **no Go LISTEN/NOTIFY watcher exists**.

ADR 005 records the model + scaling path.

---

## §7. chi middleware chain

Copied pattern from `../qiyas/qudrat.ai/internal/api/server/server.go`:

```go
import (
    "github.com/go-chi/chi/v5"
    "github.com/go-chi/chi/v5/middleware"
    "go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)

r := chi.NewRouter()
r.Use(middleware.RequestID)
r.Use(middleware.RealIP)
r.Use(middleware.Logger)
r.Use(middleware.Recoverer)
r.Use(middleware.Timeout(60 * time.Second))
// then auth (OapiRequestValidator with AuthenticationFunc), tenant, idempotency, etag
r.Get("/healthz", healthz)

srv := &http.Server{Handler: otelhttp.NewHandler(r, "saas-dataplane")}
```

`auth.TenantFromContext(ctx)` returns the tenant_id verified from the bearer token (JWT or API key). No middleware writes `tenant_id` from headers — header sources are physically rejected.

---

## §8. Keycloak via gocloak v14

```go
import "github.com/Nerzal/gocloak/v14"

client := gocloak.NewClient(authBaseURL)
tok, _ := client.LoginClient(ctx, "saas-controlplane", clientSecret, "operators")

// Create user (data-plane realm "saas-data-<dep_id>")
userID, _ := client.CreateUser(ctx, tok.AccessToken, realm, gocloak.User{
    Username:      gocloak.StringP("alice"),
    Email:         gocloak.StringP("alice@example.com"),
    Enabled:       gocloak.BoolP(true),
    EmailVerified: gocloak.BoolP(false),
    Attributes:    &map[string][]string{"platform_user_id": {pid}},
})

// Disable
_ = client.UpdateUser(ctx, tok.AccessToken, realm, gocloak.User{
    ID:      gocloak.StringP(userID),
    Enabled: gocloak.BoolP(false),
})

// Trigger reset-password / verify-email
_ = client.ExecuteActionsEmail(ctx, tok.AccessToken, realm, gocloak.ExecuteActionsEmail{
    UserID:  gocloak.StringP(userID),
    Actions: &[]string{"UPDATE_PASSWORD"},
})
```

### Realm import (bootstrap only)

`/opt/keycloak/data/import/operators-realm.json` + `kc.sh start --import-realm`. **Subsequent changes go through gocloak**, not file re-import (Keycloak silently skips realms that already exist).

### Audience claim

Use per-Deployment Keycloak **client** (recommended in ADR 007). For each Deployment:
- Client `saas-data-<dep_id>`, audience `saas-data-<dep_id>`
- Audience protocol mapper of type `oidc-audience-mapper`

### JWT verification (jwx v3)

```go
import (
    "github.com/lestrrat-go/jwx/v3/jwk"
    "github.com/lestrrat-go/jwx/v3/jwt"
)

cache, _ := jwk.NewCache(ctx, jwk.WithRefreshInterval(15*time.Minute))
_ = cache.Register(jwksURL)
ks, _ := cache.Get(ctx, jwksURL)

tok, err := jwt.Parse(raw,
    jwt.WithKeySet(ks),
    jwt.WithValidate(true),
    jwt.WithIssuer(issuer),
    jwt.WithAudience(expectedAudience),     // saas-control or saas-data-<dep_id>
)
var tid string
_ = tok.Get("tenant_id", &tid)
```

**Anti-patterns:**

- `LoginAdmin` (username/password) in production → use `LoginClient` with service-account credentials.
- Re-importing realm JSON to apply config drift → import is bootstrap-only; use gocloak.
- Verifying `tenant_id` before `aud` → always verify audience first; otherwise a data-plane token forged with a control-plane tenant_id might pass.

---

## §9. client-go + kustomize (k3s provisioning)

### Typed apply with field manager `saas-controlplane`

```go
import (
    corev1ac "k8s.io/client-go/applyconfigurations/core/v1"
    appsv1ac "k8s.io/client-go/applyconfigurations/apps/v1"
    metav1   "k8s.io/apimachinery/pkg/apis/meta/v1"
)
const fm = "saas-controlplane"

ns := corev1ac.Namespace(nsName).WithLabels(map[string]string{
    "saas.omarss.net/deployment-id": depID,
})
_, _ = clientset.CoreV1().Namespaces().Apply(ctx, ns,
    metav1.ApplyOptions{FieldManager: fm, Force: true})
```

### Rollout wait — `apimachinery wait`

```go
err := wait.PollUntilContextTimeout(ctx, 2*time.Second, 5*time.Minute, true,
    func(ctx context.Context) (bool, error) {
        d, err := clientset.AppsV1().Deployments(ns).Get(ctx, name, metav1.GetOptions{})
        if err != nil { return false, err }
        if d.Generation != d.Status.ObservedGeneration { return false, nil }
        if d.Status.AvailableReplicas < *d.Spec.Replicas { return false, nil }
        for _, c := range d.Status.Conditions {
            if c.Type == appsv1.DeploymentProgressing && c.Reason == "ProgressDeadlineExceeded" {
                return false, fmt.Errorf("rollout failed: %s", name)
            }
        }
        return true, nil
    })
```

### Kustomize Go API

```go
import (
    "sigs.k8s.io/kustomize/api/krusty"
    "sigs.k8s.io/kustomize/kyaml/filesys"
)
opts := krusty.MakeDefaultOptions()
k := krusty.MakeKustomizer(opts)
fSys := filesys.MakeFsOnDisk()    // or MakeFsInMemory + copy embed.FS
resMap, _ := k.Run(fSys, "deploy/k3s/overlays/"+depID)
yamlBytes, _ := resMap.AsYaml()
// decode and apply per-doc by GVR
```

Templating via `replacements` in `kustomization.yaml`. **Do not use string templates** (§4.1).

### NetworkPolicy — layer-4 tenant isolation

Every Deployment namespace gets:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: default-deny }
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# Allow ingress only from the cluster's nginx ingress controller (host nginx is out-of-cluster
# and reaches in via the NodePort service — restrict to controller's source range)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-from-ingress }
spec:
  podSelector: { matchLabels: { app: data-plane } }
  ingress:
    - from: [{ ipBlock: { cidr: <host-source-cidr> } }]
      ports: [{ port: 8080 }]
---
# Allow egress to host Postgres + host OpenBao + DNS only
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: allow-egress-platform }
spec:
  podSelector: { matchLabels: { app: data-plane } }
  egress:
    - to: [{ ipBlock: { cidr: <host-cidr> } }]
      ports:
        - { port: 5432, protocol: TCP }    # Postgres
        - { port: 8200, protocol: TCP }    # OpenBao
        - { port: 53,   protocol: UDP }    # DNS
        - { port: 53,   protocol: TCP }
```

---

## §10. nginx + certbot (host-side)

### Vhost file pattern (pre-certbot, mirrors `../homelab/nginx/`)

```nginx
# Managed by saas-controlplane — this is the pre-certbot base config.
# After install: sudo certbot --nginx -d <env>.<project>.saas.omarss.net
# Do NOT run homelab's bulk apply-nginx — it clobbers certbot blocks.

server {
    listen 80;
    server_name <env>.<project>.saas.omarss.net;

    include /etc/nginx/snippets/saas-security-headers.conf;

    location / {
        include /etc/nginx/snippets/saas-security-headers.conf;
        proxy_pass http://127.0.0.1:<nodeport>;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Provisioning sequence (per vhost)

```bash
install -o root -g root -m 644 deploy/nginx/<vhost>.conf /etc/nginx/sites-available/saas-<vhost>.conf
ln -sf /etc/nginx/sites-available/saas-<vhost>.conf /etc/nginx/sites-enabled/saas-<vhost>.conf
sudo /usr/sbin/nginx -t
sudo /usr/sbin/nginx -s reload
sudo /usr/bin/certbot --nginx -d <vhost> --non-interactive --agree-tos -m ops@omarss.net --redirect
```

### Sudoers (`/etc/sudoers.d/saas-controlplane`, mode 0440, validated with `visudo -cf`)

```text
Cmnd_Alias SAAS_NGINX = /usr/sbin/nginx -t, /usr/sbin/nginx -s reload, /usr/bin/systemctl reload nginx
Cmnd_Alias SAAS_CERTBOT = /usr/bin/certbot --nginx -d *.saas.omarss.net --non-interactive --agree-tos -m *
saas ALL=(root) NOPASSWD: SAAS_NGINX, SAAS_CERTBOT
```

Files in `/etc/nginx/sites-{available,enabled}/saas-*.conf` are owned `saas:saas` mode 644 so the platform process writes them WITHOUT sudo; only reload + certbot need sudo. The shared snippet `/etc/nginx/snippets/saas-security-headers.conf` is installed once by an idempotent setup script.

### Anti-patterns

- Running `make -C homelab apply-nginx` — clobbers certbot blocks (workspace gotcha #1).
- Writing files under `/etc/nginx/sites-available/` without the `saas-` prefix — collides with homelab namespace.
- Wildcard sudoers without absolute paths — security hole.
- Allowing certbot to manage domains outside `*.saas.omarss.net` — sudoers wildcard restricts.

### Wildcard cert via DNS-01 (ADR 008)

If deployments scale past ~30/week, Let's Encrypt's 50-certs/registered-domain/week rate limit on `omarss.net` becomes a constraint. ADR 008 evaluates wildcard `*.saas.omarss.net` via DNS-01 vs per-vhost HTTP-01.

---

## §11. Idempotency + ETag + cursor (RFC + spec details)

### Idempotency-Key (§5.2)

```text
TTL                                    24 hours from first request
Same key + same body hash              return cached response
Same key + different body              422 problem-details "idempotency-key-conflict"
Same key + concurrent in-flight        second blocks ≤ 30s; on timeout 409
Different key                          new request
```

Table:

```sql
CREATE TABLE idempotency_record (
    id                   bigserial PRIMARY KEY,
    tenant_id            text NOT NULL,
    idempotency_key      text NOT NULL,
    route                text NOT NULL,
    method               text NOT NULL,
    request_body_hash    bytea NOT NULL,
    response_status      int,
    response_headers     jsonb,
    response_body        bytea,
    created_at           timestamptz NOT NULL DEFAULT now(),
    expires_at           timestamptz NOT NULL,
    in_flight            bool NOT NULL DEFAULT false,
    UNIQUE (tenant_id, idempotency_key, route, method)
);
CREATE INDEX ON idempotency_record (expires_at);
ALTER TABLE idempotency_record ENABLE ROW LEVEL SECURITY;
CREATE POLICY t ON idempotency_record USING (tenant_id = current_setting('app.current_tenant_id'));
```

Required on: POST, state-transition PATCH, billing mutations (v1), usage ingest (v1), notification sends (v1), webhook retry triggers (v1), file completion (v1), API key rotation.

### ETag

Format: `W/"v<sequence>"`. Sequence is a monotonic per-row column (`row_seq bigint NOT NULL`). Computed in the DB via trigger on UPDATE. Returned on every read; required as `If-Match` on PATCH/PUT/DELETE. Stale → 412.

### Cursor pagination

```text
cursor = base64url(json{"v":1, "k":"<sort key tuple>", "id":"<resource id>"})
limit  = default 25, max 200
sort   = "created_at" (asc) or "-created_at" (desc); default -created_at
```

Schema bump → 410 Gone for old cursors (no silent re-interpret). `v` field is mandatory.

---

## §12. RFC 9457 Problem Details

`Content-Type: application/problem+json`

```json
{
  "type": "https://saas.omarss.net/problems/validation-error",
  "title": "Validation failed",
  "status": 422,
  "detail": "One or more fields are invalid.",
  "instance": "/v1/tenants",
  "request_id": "req_01HXY...",
  "errors": [{"field": "name", "message": "must not be blank", "code": "not_blank"}]
}
```

`type` URIs catalogued in `openapi/problems/`. Do not invent ad-hoc error shapes.

---

## §13. ULID + ID prefixes

```go
import "github.com/oklog/ulid/v2"
id := "tenant_" + ulid.Make().String()         // 26-char Crockford Base32
```

Prefix table from §11.5: `op_`, `dep_`, `tenant_`, `org_`, `user_`, `member_`, `role_`, `perm_`, `apik_`, `audit_`, `evt_`. ULID is the random part — lexicographically sortable, monotonic within a millisecond.

**`ulid.Make()`** is thread-safe (internal locked monotonic entropy). **`ulid.Monotonic`** is NOT — wrap with a mutex if you avoid `Make()`.

---

## §14. slog with PII redaction

```go
opts := &slog.HandlerOptions{
    ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
        if redact.IsRedactedKey(a.Key) {
            return slog.String(a.Key, "[REDACTED]")
        }
        return a
    },
}
slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, opts)))
```

`internal/platform/log/redact.go` exports `IsRedactedKey(string) bool` reading from a static keyset + tags discovered at codegen time (via `x-oapi-codegen-extra-tags: { pii: "true" }`). Wrapping handler pattern documented in the official slog handler guide if richer scrubbing is needed.

---

## §15. argon2id parameters (OWASP 2024)

```go
import "golang.org/x/crypto/argon2"

const (
    argonTime    uint32 = 2
    argonMemory  uint32 = 19 * 1024     // 19 MiB
    argonThreads uint8  = 1
    argonKeyLen  uint32 = 32
)

salt := make([]byte, 16)
_, _ = rand.Read(salt)
hash := argon2.IDKey(password, salt, argonTime, argonMemory, argonThreads, argonKeyLen)

// PHC string format:
// $argon2id$v=19$m=19456,t=2,p=1$<b64 salt>$<b64 hash>
encoded := fmt.Sprintf("$argon2id$v=19$m=%d,t=%d,p=%d$%s$%s",
    argonMemory, argonTime, argonThreads,
    base64.RawStdEncoding.EncodeToString(salt),
    base64.RawStdEncoding.EncodeToString(hash))
```

Optional: `github.com/alexedwards/argon2id` (MIT) provides a vetted PHC parser if you don't want to maintain ~6 LoC.

---

## §16. OpenAPI tooling Makefile pin set

```make
OAPI_CODEGEN_VERSION       := v2.7.0
OPENAPI_GENERATOR_VERSION  := 7.22.0
PRISM_VERSION              := 5.15.10
SPECTRAL_VERSION           := 6.16.0

DOCKER_RUN := docker run --rm -v $(PWD):/work -w /work
SPECTRAL   := $(DOCKER_RUN) stoplight/spectral:$(SPECTRAL_VERSION)
PRISM      := $(DOCKER_RUN) -p 4010:4010 -p 4011:4011 stoplight/prism:$(PRISM_VERSION)
OPENAPI_GEN:= $(DOCKER_RUN) openapitools/openapi-generator-cli:v$(OPENAPI_GENERATOR_VERSION)
OAPI_CODEGEN := go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@$(OAPI_CODEGEN_VERSION)
```

---

## §17. Local conventions to mirror

Source: `../qiyas/qudrat.ai/`.

- `go.mod`: `module github.com/omarss/saas` (mirror style).
- Folder layout: `cmd/`, `internal/`, `db/migrations`, `db/queries`, `pkg/` (only for vendored or genuinely public).
- `.golangci.yml`: copy verbatim from `qudrat.ai/.golangci.yml`, change `local-prefixes` to `github.com/omarss/saas`.
- `.github/PULL_REQUEST_TEMPLATE.md`: copy from `qudrat.ai/.github/PULL_REQUEST_TEMPLATE.md`, update Scope checkboxes for SaaS modules.
- Makefile target naming convention: `make build`, `make test`, `make test-int`, `make lint`, `make sqlc-gen`, `make migrate-up`, `make migrate-down`, `make image-<service>`.
- chi middleware stack: `RequestID, RealIP, Logger, Recoverer, Timeout` (then auth/tenant/idempotency).

---

## §18. Confidence + gaps (close before relying)

| Item | Risk | Mitigation in plan |
|---|---|---|
| pckhoi/casbin-pgx-adapter v3.2.0 vs casbin v2.135.0 | Adapter last released Aug 2024; possible API drift | Phase 7 starts with a 30-min compile-check; if broken, fall back to a thin sqlc adapter (Phase 7 contingency). |
| oapi-codegen 3.1 support | Native 3.1 blocked on Go 1.26; overlay-downgrade required | ADR 002 + overlay file in `openapi/overlays/30-downgrade.yaml`; revisit when issue #373 closes. |
| OpenBao `static` seal in production | Dev-only; cannot ship | ADR 006 + Shamir 5-of-3 with scripted unseal; cloud KMS in roadmap. |
| Keycloak `--features=admin-fine-grained-authz:v2` | Not verified on KC 26.x exact image | Phase 12 verifies against pinned KC image before deploying. |
| `transit/datakey/plaintext` requires `bits` param | OpenBao default may differ from Vault | Phase 6 includes a quick `bao read` integration test for the endpoint. |
| Per-Deployment KC client vs single client | Scaling vs revocation trade-off | ADR 007 in Phase 4. |
| Wildcard cert vs per-vhost | LE rate limit at scale | ADR 008 in Phase 11a. |

---

End of foundations. Next: `02-walking-skeleton.md`.
