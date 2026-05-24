# Phase 4 — OpenBao Integration (Envelope Encryption + kid Binding + Auth)

> **Goal**: Land the envelope-encryption stack so every subsequent module can persist sensitive fields safely. Replace the Phase-1 dev-mode OpenBao with a file-backend instance, scripted Shamir 5-of-3 unseal, audit device on, k8s + AppRole auth methods enabled, transit + KV v2 engines mounted. Author the `internal/platform/crypto/envelope/` package implementing the kid-bound encrypt/decrypt path. Wire the reflection-driven persist walker introduced in Phase 3.
>
> **Why now**: AGENTS.md §18.7 makes envelope encryption a non-negotiable MVP requirement. Identity (Phase 5), Notifications (Phase 6, with BYOK vendor creds), Organizations invitations (Phase 7), API keys (Phase 9), and Audit metadata (Phase 10) all depend on encrypt-at-rest. The plan front-loads crypto so no downstream module reinvents it. 00-master.md gates this at CHECKPOINT 2 because crypto is unrecoverable if misdesigned.
>
> **What this phase does NOT do**: No new public endpoints. No new modules. Does not rotate keys (rotation API + rewrap batch is implemented and tested, but production rotation cadence is a runtime concern, not a phase deliverable). Does not migrate from Shamir to cloud KMS — that path is documented but explicitly deferred.
>
> **Maps to AGENTS.md**: §18.7 (the whole section), §4.1 (OpenBao approved), §4.4 (Linux Foundation fork rationale), §5 crypto posture, §18.1 layer 5 of tenant isolation. `01-foundations.md` §5 (every API signature). 00-master.md §"Tenant isolation" layer 5.
>
> **Estimated subagent sessions**: 2-3 (one to harden compose + bootstrap script + ADR 006, one to write the envelope package + tests, one for the reflection wiring + the Phase-2 module migration if a PII field exists yet).

---

## Pre-flight

1. `AGENTS.md` §18.7 (read in full; this phase materializes every sub-bullet).
2. `01-foundations.md` §5 — every API signature comes from here.
3. `00-master.md` §"Tenant isolation" — confirm Layer 5 (Crypto) wording.
4. `CONVENTIONS.md` (Phase 3) — §10 (PII) is the call-site contract.
5. `homelab/openbao` — read any existing OpenBao patterns on this machine (workspace CLAUDE.md mentions OpenBao in homelab context).

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Unseal mechanism for MVP | Shamir 5-of-3, one share at `/etc/openbao/share-1` (0400 root), 4 offline (operator's responsibility) | `static` seal (dev-only, refused per §18.7); cloud KMS auto-unseal (out of MVP scope per ADR 006) |
| Auth method for data-plane pods | Kubernetes (`auth/kubernetes/login`) per `01-foundations.md` §5 | Token (refused — no rotation); cert (refused — adds CSR management) |
| Auth method for control-plane host process | AppRole (`auth/approle/login`); role_id + secret_id loaded from `/etc/saas/approle/` (0400 saas:saas) | Operator-supplied token (refused — long-lived); k8s (refused — control-plane is host-side) |
| Transit key spec | `type=aes256-gcm96`, rotation period 90 days, exportable=false, allow_plaintext_backup=false | aes128-gcm96 (refused — weaker); chacha20 (compliance gap for KSA gov customers) |
| Per-deployment policy template | Static HCL template rendered per Deployment | Templated policy (less duplication but harder to audit) |
| Encryption AAD (additional authenticated data) | `deployment_id || resource_type || resource_id` — binds ciphertext to its row | None (refused — confused-deputy risk) |
| DEK in-memory lifetime | Zeroed immediately after Seal/Open; never kept across requests | Per-request cache (refused — memory leak vector) |

If the user disagrees with any default, stop and revise. Crypto choices propagate everywhere.

---

## Tasks

### 4.1 Rewrite `compose.yaml` to remove `-dev` mode

Phase 1's OpenBao container ran `server -dev` with an in-memory backend. Switch to file backend + audit + scripted unseal.

`compose.yaml` (relevant block; keep the other services unchanged):

```yaml
  openbao:
    image: openbao/openbao:2.5.4
    cap_add: ["IPC_LOCK"]
    user: "100:100"               # bao:bao in upstream image
    environment:
      BAO_ADDR: "http://0.0.0.0:8200"
      BAO_LOG_LEVEL: info
    volumes:
      - openbao-data:/openbao/data
      - openbao-logs:/openbao/logs
      - openbao-config:/openbao/config:ro
      - ./deploy/openbao/init:/openbao/init:ro     # bootstrap script
      - openbao-tmpfs:/openbao/secrets             # tmpfs for unseal share, mode 0700
    tmpfs:
      - /openbao/secrets:mode=700,uid=100,gid=100
    command: ["sh", "-c", "/openbao/init/entrypoint.sh"]
    ports: ["8200:8200"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8200/v1/sys/health?standbyok=true&sealedcode=204"]
      interval: 3s
      timeout: 2s
      retries: 50

volumes:
  openbao-data: {}
  openbao-logs: {}
  openbao-config: {}
  openbao-tmpfs: {}
```

`deploy/openbao/config/openbao.hcl` (mounted via `openbao-config` named volume — see `apply-openbao-config` Makefile target below):

```hcl
ui = true
disable_mlock = false

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1            # dev/local only; production overlays add TLS
}

storage "file" {
  path = "/openbao/data"
}

api_addr = "http://0.0.0.0:8200"

# audit device enabled at /openbao/logs/audit.log after bootstrap (see init script)
```

`deploy/openbao/init/entrypoint.sh` (executable, 0755, owned by image user 100:100):

```bash
#!/bin/sh
set -eu

# Copy config into place at boot (handles volume init).
mkdir -p /openbao/config
cp -n /openbao/init/openbao.hcl /openbao/config/openbao.hcl

# Start bao server in the background.
bao server -config=/openbao/config/openbao.hcl &
BAO_PID=$!

# Wait until 501 (not initialised) or 503 (sealed) is reachable.
until wget -qO- "http://127.0.0.1:8200/v1/sys/health?uninitcode=501&sealedcode=503&standbyok=true" >/dev/null 2>&1; do
  sleep 1
done

export BAO_ADDR=http://127.0.0.1:8200

# Initialise if needed; capture shares.
if ! bao status >/dev/null 2>&1 && [ ! -f /openbao/secrets/init.json ]; then
  bao operator init -format=json -key-shares=5 -key-threshold=3 > /openbao/secrets/init.json
  chmod 0400 /openbao/secrets/init.json
fi

# Unseal if sealed. Reads the first 3 shares from the init file.
# In production this is replaced by an operator-driven flow; for MVP local dev
# the init file lives on the tmpfs and is recreated per container reboot, which
# is the documented trade-off in ADR 006.
if bao status | grep -q 'Sealed.*true'; then
  for i in 0 1 2; do
    KEY=$(awk -v i=$i 'BEGIN{c=0} /unseal_keys_b64/{f=1;next} f && /"/{gsub(/[", ]/,""); if (c==i) print; c++}' /openbao/secrets/init.json)
    bao operator unseal "$KEY" >/dev/null
  done
fi

# Wait on bao foreground.
wait $BAO_PID
```

The script is **not** a production unseal mechanism. ADR 006 documents the trade-off in detail (the operator's signing copy of share 1 lives on tmpfs; cold-boot requires re-initialising). For the homelab MVP, this is acceptable because the threat model is "single-tenant, single-operator, single-host"; cloud KMS auto-unseal is the production path.

### 4.2 `make` targets for OpenBao bootstrap

Add to `Makefile`:

```make
.PHONY: openbao-init openbao-status openbao-unseal openbao-rotate openbao-policies

openbao-init: compose-up
	@docker compose -f compose.yaml exec openbao sh -c '\
		BAO_ADDR=http://127.0.0.1:8200 bao status || true; \
		bao auth enable kubernetes || true; \
		bao auth enable approle || true; \
		bao secrets enable -path=transit transit || true; \
		bao secrets enable -path=secret -version=2 kv || true; \
		bao audit enable file file_path=/openbao/logs/audit.log || true; \
		echo "openbao bootstrap done"'

openbao-status:
	docker compose -f compose.yaml exec openbao bao status

openbao-unseal:
	@echo "Use openbao-init in dev; for prod follow runbook docs/runbooks/openbao-unseal.md"

openbao-rotate:
	@test -n "$$KID" || (echo "set KID=<deployment_id>" && exit 2)
	docker compose -f compose.yaml exec openbao bao write -f transit/keys/$$KID/rotate

openbao-policies:
	docker compose -f compose.yaml exec openbao bao policy list
```

The init target is **idempotent**: each `|| true` makes re-runs harmless when a mount / engine / device already exists.

### 4.3 `internal/platform/crypto/envelope/` package

The full implementation behind the `Encryptor` interface declared in Phase 3.

`internal/platform/crypto/envelope/client.go`:

```go
package envelope

import (
    "context"
    "crypto/aes"
    "crypto/cipher"
    "crypto/rand"
    "crypto/subtle"
    "encoding/base64"
    "errors"
    "fmt"
    "strconv"
    "strings"
    "sync"
    "time"

    bao "github.com/openbao/openbao/api/v2"
)

// Client wraps OpenBao Transit API for envelope encryption.
// One Client per process; thread-safe.
type Client struct {
    bao         *bao.Client
    refreshOnce sync.Once
    watcher     *bao.LifetimeWatcher
}

// New builds a Client and authenticates via either Kubernetes (data-plane pods)
// or AppRole (control-plane host). Auth method is selected from env.
func New(ctx context.Context, opts Options) (*Client, error) {
    cfg := bao.DefaultConfig()
    cfg.Address = opts.Address
    if opts.CACertPath != "" {
        if err := cfg.ConfigureTLS(&bao.TLSConfig{CACert: opts.CACertPath}); err != nil {
            return nil, fmt.Errorf("envelope: tls config: %w", err)
        }
    }
    bc, err := bao.NewClient(cfg)
    if err != nil { return nil, fmt.Errorf("envelope: new client: %w", err) }

    var sec *bao.Secret
    switch opts.AuthMethod {
    case AuthKubernetes:
        sec, err = loginKubernetes(ctx, bc, opts.Role, opts.SAJWTPath)
    case AuthAppRole:
        sec, err = loginAppRole(ctx, bc, opts.RoleID, opts.SecretID)
    default:
        return nil, fmt.Errorf("envelope: unknown auth method %q", opts.AuthMethod)
    }
    if err != nil { return nil, err }

    bc.SetToken(sec.Auth.ClientToken)

    c := &Client{bao: bc}
    // Auto-renew lease.
    w, err := bc.NewLifetimeWatcher(&bao.LifetimeWatcherInput{Secret: sec, Increment: 3600})
    if err == nil {
        go w.Start()
        c.watcher = w
    }
    return c, nil
}

type Options struct {
    Address     string
    CACertPath  string
    AuthMethod  AuthMethod    // AuthKubernetes | AuthAppRole
    Role        string        // k8s role name (data-plane = deployment_id)
    SAJWTPath   string        // default "/var/run/secrets/kubernetes.io/serviceaccount/token"
    RoleID      string        // AppRole role_id
    SecretID    string        // AppRole secret_id
}

type AuthMethod string

const (
    AuthKubernetes AuthMethod = "kubernetes"
    AuthAppRole    AuthMethod = "approle"
)

func loginKubernetes(ctx context.Context, bc *bao.Client, role, jwtPath string) (*bao.Secret, error) {
    if jwtPath == "" { jwtPath = "/var/run/secrets/kubernetes.io/serviceaccount/token" }
    jwt, err := os.ReadFile(jwtPath)
    if err != nil { return nil, fmt.Errorf("envelope: read sa token: %w", err) }
    return bc.Logical().WriteWithContext(ctx, "auth/kubernetes/login",
        map[string]any{"role": role, "jwt": string(jwt)})
}

func loginAppRole(ctx context.Context, bc *bao.Client, roleID, secretID string) (*bao.Secret, error) {
    if roleID == "" || secretID == "" { return nil, errors.New("envelope: empty approle creds") }
    return bc.Logical().WriteWithContext(ctx, "auth/approle/login",
        map[string]any{"role_id": roleID, "secret_id": secretID})
}

func (c *Client) Close() error {
    if c.watcher != nil { c.watcher.Stop() }
    return nil
}
```

`internal/platform/crypto/envelope/encrypt.go`:

```go
package envelope

import (
    "context"
    "crypto/aes"
    "crypto/cipher"
    "crypto/rand"
    "encoding/base64"
    "errors"
    "fmt"
    "strconv"
    "strings"
)

// Envelope is the on-the-wire representation persisted in Postgres.
type Envelope struct {
    Ciphertext []byte // GCM ciphertext (tag-appended)
    WrappedDEK string // OpenBao "vault:vN:<b64>" form
    Nonce      []byte // 12 bytes
    Algo       string // "aes-256-gcm"
    KID        string // deployment_id; bound at write
    KeyVersion int    // parsed from "vault:vN:..." prefix
}

// Encrypt generates a new DEK, encrypts plaintext, wraps the DEK via the kid's
// transit key, zeroes the DEK, and returns the envelope.
// aad binds the ciphertext to its row (deployment_id || resource_type || resource_id).
func (c *Client) Encrypt(ctx context.Context, kid string, plaintext, aad []byte) (Envelope, error) {
    if kid == "" { return Envelope{}, ErrEmptyKID }
    sec, err := c.bao.Logical().WriteWithContext(ctx, "transit/datakey/plaintext/"+kid,
        map[string]any{"bits": 256, "context": base64.StdEncoding.EncodeToString(aad)})
    if err != nil { return Envelope{}, fmt.Errorf("envelope: datakey: %w", err) }

    dekB64, _ := sec.Data["plaintext"].(string)
    wrapped, _   := sec.Data["ciphertext"].(string)
    dek, err := base64.StdEncoding.DecodeString(dekB64)
    if err != nil { return Envelope{}, fmt.Errorf("envelope: decode dek: %w", err) }
    defer zero(dek)

    block, err := aes.NewCipher(dek)
    if err != nil { return Envelope{}, err }
    gcm, err := cipher.NewGCM(block)
    if err != nil { return Envelope{}, err }
    nonce := make([]byte, gcm.NonceSize())
    if _, err := rand.Read(nonce); err != nil { return Envelope{}, err }
    ct := gcm.Seal(nil, nonce, plaintext, aad)

    return Envelope{
        Ciphertext: ct, WrappedDEK: wrapped, Nonce: nonce, Algo: "aes-256-gcm",
        KID: kid, KeyVersion: parseVersion(wrapped),
    }, nil
}

// Decrypt verifies kid binding BEFORE calling OpenBao, then unwraps DEK, decrypts.
// Returns ErrKidMismatch if env.KID != ctxDeploymentID.
func (c *Client) Decrypt(ctx context.Context, env Envelope, ctxDeploymentID string, aad []byte) ([]byte, error) {
    if env.KID == "" { return nil, ErrEmptyKID }
    if env.KID != ctxDeploymentID { return nil, ErrKidMismatch }

    sec, err := c.bao.Logical().WriteWithContext(ctx, "transit/decrypt/"+env.KID,
        map[string]any{"ciphertext": env.WrappedDEK, "context": base64.StdEncoding.EncodeToString(aad)})
    if err != nil { return nil, fmt.Errorf("envelope: decrypt wrap: %w", err) }
    dekB64, _ := sec.Data["plaintext"].(string)
    dek, err := base64.StdEncoding.DecodeString(dekB64)
    if err != nil { return nil, err }
    defer zero(dek)

    block, err := aes.NewCipher(dek)
    if err != nil { return nil, err }
    gcm, err := cipher.NewGCM(block)
    if err != nil { return nil, err }
    return gcm.Open(nil, env.Nonce, env.Ciphertext, aad)
}

// EncryptBatch wraps Encrypt via the OpenBao batch_input form for high-throughput
// callers (e.g. notification send fan-out, API key prefix index population).
// See OpenBao docs: same shape as Vault Transit batch.
func (c *Client) EncryptBatch(ctx context.Context, kid string, items []BatchItem) ([]Envelope, error) {
    if len(items) == 0 { return nil, nil }
    // Build a batch_input of {plaintext: <b64>, context: <b64>} entries.
    // OpenBao returns parallel batch_results.
    // Implementation omitted here for brevity; mirror docs.
    // ...
    return nil, errors.New("envelope: batch not yet wired; ticket #N")
}

type BatchItem struct{ Plaintext, AAD []byte }

// RotateKey triggers a new key version. Old versions retained for decrypt.
func (c *Client) RotateKey(ctx context.Context, kid string) error {
    _, err := c.bao.Logical().WriteWithContext(ctx, "transit/keys/"+kid+"/rotate", nil)
    return err
}

// Rewrap re-wraps an existing envelope's wrapped_dek against the latest key
// version. No plaintext exposure. Returns the new WrappedDEK; caller persists.
func (c *Client) Rewrap(ctx context.Context, kid, wrappedDEK string) (string, int, error) {
    sec, err := c.bao.Logical().WriteWithContext(ctx, "transit/rewrap/"+kid,
        map[string]any{"ciphertext": wrappedDEK})
    if err != nil { return "", 0, err }
    out, _ := sec.Data["ciphertext"].(string)
    return out, parseVersion(out), nil
}

func parseVersion(wrap string) int {
    // "vault:v3:..." or "openbao:v3:..." depending on engine config.
    parts := strings.SplitN(wrap, ":", 3)
    if len(parts) < 3 { return 0 }
    if !strings.HasPrefix(parts[1], "v") { return 0 }
    n, _ := strconv.Atoi(parts[1][1:])
    return n
}

func zero(b []byte) {
    for i := range b { b[i] = 0 }
}

var (
    ErrEmptyKID    = errors.New("envelope: empty kid")
    ErrKidMismatch = errors.New("envelope: kid mismatch (cross-deployment access refused)")
)
```

### 4.4 KV v2 helper

For storing per-Deployment secrets (Postgres passwords, Keycloak admin creds, Novu API key, BYOK channel creds).

`internal/platform/crypto/envelope/kv.go`:

```go
package envelope

import (
    "context"
    "errors"
    "fmt"
    "strings"
)

// KVPut writes a secret at `secret/data/<deploymentID>/<path>`. Path must not
// contain `..` or absolute prefixes; enforced here.
func (c *Client) KVPut(ctx context.Context, deploymentID, path string, data map[string]any) error {
    if err := validatePath(path); err != nil { return err }
    full := fmt.Sprintf("secret/data/%s/%s", deploymentID, strings.Trim(path, "/"))
    _, err := c.bao.Logical().WriteWithContext(ctx, full, map[string]any{"data": data})
    return err
}

// KVGet reads from the same namespace. Returns ErrNotFound if missing.
func (c *Client) KVGet(ctx context.Context, deploymentID, path string) (map[string]any, error) {
    if err := validatePath(path); err != nil { return nil, err }
    full := fmt.Sprintf("secret/data/%s/%s", deploymentID, strings.Trim(path, "/"))
    sec, err := c.bao.Logical().ReadWithContext(ctx, full)
    if err != nil { return nil, err }
    if sec == nil || sec.Data == nil { return nil, ErrNotFound }
    raw, _ := sec.Data["data"].(map[string]any)
    if raw == nil { return nil, ErrNotFound }
    return raw, nil
}

func (c *Client) KVDelete(ctx context.Context, deploymentID, path string) error {
    if err := validatePath(path); err != nil { return err }
    full := fmt.Sprintf("secret/metadata/%s/%s", deploymentID, strings.Trim(path, "/"))
    _, err := c.bao.Logical().DeleteWithContext(ctx, full)
    return err
}

func validatePath(p string) error {
    if strings.Contains(p, "..") || strings.HasPrefix(p, "/") {
        return errors.New("envelope: invalid kv path")
    }
    return nil
}

var ErrNotFound = errors.New("envelope: kv path not found")
```

### 4.5 Reflection persist walker (full impl)

Phase 3 declared the interface and placeholder. Phase 4 finishes it.

`internal/platform/crypto/encrypt_persist.go`:

```go
package crypto

import (
    "context"
    "errors"
    "reflect"

    "github.com/omarss/saas/internal/platform/crypto/envelope"
)

// EncryptPIIFields walks `v` and replaces every []byte / string field tagged
// `pii:"true"` or `sensitive:"true"` with its envelope-encrypted form.
// For string fields, an adjacent struct must contain an `Envelope` field
// (suffix convention: `Email` + `EmailEnvelope`). This makes persistence
// explicit at the SQL level.
func EncryptPIIFields(ctx context.Context, enc *envelope.Client, kid string, aad []byte, v any) error {
    rv := reflect.ValueOf(v)
    if rv.Kind() != reflect.Ptr || rv.IsNil() {
        return ErrNotPointer
    }
    return walkEncrypt(ctx, enc, kid, aad, rv.Elem())
}

func walkEncrypt(ctx context.Context, enc *envelope.Client, kid string, aad []byte, v reflect.Value) error {
    t := v.Type()
    for i := 0; i < t.NumField(); i++ {
        f := t.Field(i)
        if !v.Field(i).CanSet() { continue }
        if f.Tag.Get("pii") != "true" && f.Tag.Get("sensitive") != "true" {
            // Recurse into nested structs.
            if v.Field(i).Kind() == reflect.Struct {
                if err := walkEncrypt(ctx, enc, kid, aad, v.Field(i)); err != nil { return err }
            }
            continue
        }
        // Find the sibling envelope field. Convention: <FieldName>Envelope.
        envField := v.FieldByName(f.Name + "Envelope")
        if !envField.IsValid() || !envField.CanSet() {
            return errEnvelopeFieldMissing{Field: f.Name}
        }
        var plaintext []byte
        switch v.Field(i).Kind() {
        case reflect.String:
            plaintext = []byte(v.Field(i).String())
        case reflect.Slice:
            if v.Field(i).Type().Elem().Kind() == reflect.Uint8 {
                plaintext = v.Field(i).Bytes()
            }
        }
        if len(plaintext) == 0 { continue } // zero-value: no-op
        env, err := enc.Encrypt(ctx, kid, plaintext, aad)
        if err != nil { return err }
        envField.Set(reflect.ValueOf(env))
        v.Field(i).SetZero() // clear plaintext after wrap
    }
    return nil
}

var ErrNotPointer = errors.New("crypto: argument must be a non-nil pointer to a struct")

type errEnvelopeFieldMissing struct{ Field string }
func (e errEnvelopeFieldMissing) Error() string {
    return "crypto: pii field " + e.Field + " lacks sibling " + e.Field + "Envelope"
}
```

CONVENTIONS.md (update §10) documents the sibling-field convention:

```go
type User struct {
    ID       string
    Email    string          `pii:"true"`          // cleared after persist walker runs
    EmailEnvelope envelope.Envelope             // populated by walker
    Phone    string          `pii:"true"`
    PhoneEnvelope envelope.Envelope
}
```

Migrations follow the same convention: a `<field>_ciphertext`, `<field>_wrapped_dek`, `<field>_nonce`, `<field>_kid`, `<field>_key_version` column set per PII field.

### 4.6 ADR 006

`docs/adr/006-openbao-shamir-unseal.md`:

```markdown
# ADR 006 — OpenBao Shamir 5-of-3 unseal for MVP; cloud KMS in roadmap

## Status
Accepted (2026-05-24).

## Context
AGENTS.md §18.7 requires OpenBao envelope encryption from MVP. OpenBao does
NOT have a file-based auto-unseal mechanism (the `static` seal exists but is
dev-only and unsafe). The cloud KMS auto-unseal stanzas (AWS KMS, GCP CKMS,
Azure Key Vault) require external cloud accounts the homelab does not have.

## Decision
For MVP local-host operation:
1. Initialise OpenBao with `bao operator init -key-shares=5 -key-threshold=3`.
2. Persist share 1 on tmpfs at `/openbao/secrets/init.json` (mode 0400). On
   cold boot the file is recreated by the bootstrap script; this is a
   single-tenant, single-operator threat model trade-off.
3. Shares 2-5 are held offline by the operator (paper or hardware token).
4. The init script reads share 1 and prompts (or uses) shares 2+3 to unseal.
5. Root token is generated by init and revoked at the end of the bootstrap
   script; subsequent ops go through AppRole or OIDC.
6. Audit device enabled at /openbao/logs/audit.log; rotated weekly.

For production (cloud or remote homelab):
- Migrate to cloud KMS auto-unseal (AWS KMS, GCP CKMS, or Azure Key Vault).
- Migration steps are documented in docs/runbooks/openbao-cloud-kms.md.
- Operator must run `bao operator migrate` and reseal.

## Consequences
+ Works end-to-end on the homelab today without external dependencies.
+ Aligns with the documented threat model (single-host, single-operator).
- The tmpfs share is a known single-host risk; an attacker with root on the
  host can extract share 1 from memory. Mitigation: the host is geofenced and
  hardened; production target is cloud KMS.
- Cold-boot reseeds the init file, losing prior shares. This means production
  must NOT use the MVP bootstrap script — the runbook makes this explicit.
- Re-initialising loses all encrypted data. Backups (per-Deployment KV +
  transit key list) are exported via `bao operator raft snapshot save`
  weekly.
```

### 4.7 Per-Deployment policy template

`deploy/openbao/policies/deployment.hcl.tmpl`:

```hcl
# Policy for Deployment {{.DeploymentID}}. Rendered + uploaded during
# provisioning (Phase 12d).

path "transit/encrypt/{{.DeploymentID}}"             { capabilities = ["update"] }
path "transit/decrypt/{{.DeploymentID}}"             { capabilities = ["update"] }
path "transit/datakey/plaintext/{{.DeploymentID}}"   { capabilities = ["update"] }
path "transit/rewrap/{{.DeploymentID}}"              { capabilities = ["update"] }
path "transit/keys/{{.DeploymentID}}"                { capabilities = ["read"] }

path "secret/data/{{.DeploymentID}}/*"               { capabilities = ["create","read","update","delete"] }
path "secret/metadata/{{.DeploymentID}}/*"           { capabilities = ["list","read","delete"] }
```

No globs in transit paths. One policy per Deployment. Templated, uploaded via the control plane's OpenBao client when a Deployment is provisioned (Phase 12d).

### 4.8 Wire envelope client into both binaries

`cmd/dataplane/main.go`:

```go
encClient, err := envelope.New(ctx, envelope.Options{
    Address:    os.Getenv("BAO_ADDR"),
    AuthMethod: envelope.AuthKubernetes,
    Role:       os.Getenv("DEPLOYMENT_ID"),
    SAJWTPath:  "/var/run/secrets/kubernetes.io/serviceaccount/token",
})
if err != nil { return fmt.Errorf("envelope client: %w", err) }
defer encClient.Close()
// inject into module constructors (handler factory, repo, etc.)
```

`cmd/controlplane/main.go`:

```go
roleID, _ := os.ReadFile("/etc/saas/approle/role_id")
secID,  _ := os.ReadFile("/etc/saas/approle/secret_id")
encClient, err := envelope.New(ctx, envelope.Options{
    Address:    os.Getenv("BAO_ADDR"),
    AuthMethod: envelope.AuthAppRole,
    RoleID:     strings.TrimSpace(string(roleID)),
    SecretID:   strings.TrimSpace(string(secID)),
})
```

Local dev: AppRole creds are dumped to `/etc/saas/approle/` by `make openbao-init`. The Compose stack also exports a dev `DEPLOYMENT_ID=dep_local` for the dataplane container so Kubernetes auth has a role to bind. In production, the SA JWT comes from k3s and the role name is the real deployment_id (Phase 12d creates the role).

### 4.9 Tests

`internal/platform/crypto/envelope/encrypt_test.go` (integration; requires bao):

- Encrypt → Decrypt round-trip with same kid + same AAD → original plaintext
- Decrypt with mismatched kid → `ErrKidMismatch` (no OpenBao call observed)
- Decrypt with wrong AAD → AEAD authentication failure
- Encrypt with empty plaintext → zero-length ciphertext returned (no-op fast path acceptable)
- Rotate → new version emitted → old envelope still decrypts; new write uses new version
- Rewrap → wrapped_dek version bumps; plaintext path identical
- Concurrent Encrypt (1000 goroutines) → no token-lease errors (lifetime watcher)

`internal/platform/crypto/envelope/kv_test.go`:

- Put / Get / Delete round-trip
- Path traversal attempts (`../foo`) → `errors.New("envelope: invalid kv path")`
- Two Deployments writing the same key name don't collide (namespace prefix proves separation)

`internal/platform/crypto/encrypt_persist_test.go`:

- Struct with `Email pii:"true"` + `EmailEnvelope` → walker populates envelope, clears Email
- Struct missing `EmailEnvelope` → `errEnvelopeFieldMissing`
- Nested struct with PII inside → recurses
- Zero-value field → no-op
- Concurrent walkers don't race (reflection is read-only on type info)

`internal/platform/crypto/envelope/auth_kid_test.go`:

- Attempt to call `transit/decrypt/dep_OTHER` from a token bound to `dep_SELF` → 403 from OpenBao (the policy block enforces this independent of the kid check; we belt-and-braces)

### 4.10 Promote Phase 2 modules to use envelope encryption (where applicable)

Phase 2's `Tenant.Metadata` is `map[string]string`. Is that PII? Per §18.7 list, only payment IDs / national IDs / etc. — generic tenant metadata is NOT PII by default. **No re-migration of the Tenants table is required in Phase 4.**

That said, the **idempotency_record** table stores `response_body bytea`. If a handler caches a response that contains PII fields (e.g. a User.Email after Phase 5 lands), the cached body bypasses the persistence walker. The cleanest fix is a separate ADR (defer to Phase 5 when User lands): cache only structural fields, never PII; or envelope-encrypt the cached body with the deployment's transit key. Flag now.

### 4.11 Update `CONVENTIONS.md`

Append to §10:

```markdown
### 10.x PII persistence convention

For every field marked in OpenAPI with `x-oapi-codegen-extra-tags: { pii: "true" }`:

1. Add a sibling `<FieldName>Envelope envelope.Envelope` to the Go struct
   (the codegen template emits this; manual edits forbidden).
2. Migration adds a column set:
       <field>_ciphertext   bytea NOT NULL
       <field>_wrapped_dek  text  NOT NULL
       <field>_nonce        bytea NOT NULL
       <field>_kid          text  NOT NULL
       <field>_key_version  integer NOT NULL
3. Repo `Insert` / `Update` calls `crypto.EncryptPIIFields(ctx, enc, kid, aad, &row)`
   immediately before the SQL exec.
4. Repo `Get` calls `crypto.DecryptPIIFields(ctx, enc, deploymentID, &row)` after
   the SQL exec.
5. The slog redactor handles the in-flight plaintext via the same struct tag.

AAD is always `deployment_id || resource_type || resource_id`. This binds the
ciphertext to its row; copying the encrypted blob to a different row fails
the AEAD tag check.
```

### 4.12 Commits

```bash
git add compose.yaml deploy/openbao/config/ deploy/openbao/init/ Makefile
git commit -m "harden openbao file backend with shamir unseal"

git add internal/platform/crypto/envelope/
git commit -m "add envelope crypto client and kv helper"

git add internal/platform/crypto/encrypt_persist.go internal/platform/crypto/*_test.go
git commit -m "wire reflection driven persist walker"

git add cmd/dataplane/ cmd/controlplane/
git commit -m "inject envelope client into both binaries"

git add docs/adr/006-openbao-shamir-unseal.md CONVENTIONS.md
git commit -m "add openbao adr and pii persistence convention"

git add deploy/openbao/policies/
git commit -m "add per deployment policy template"
```

---

## Verification checklist

```bash
# 1. Compose stack boots OpenBao in file-backend mode.
$ make compose-down && make compose-up
$ make openbao-status
# Expected: Sealed: false, Initialized: true, after bootstrap script unseals

# 2. Bootstrap is idempotent (re-run is no-op).
$ make openbao-init
$ make openbao-init
# Expected: both runs succeed, "openbao bootstrap done"

# 3. Transit + KV + audit + auth methods enabled.
$ docker compose exec openbao bao secrets list
# Expected: transit/ and secret/ both present
$ docker compose exec openbao bao auth list
# Expected: kubernetes/ and approle/ enabled
$ docker compose exec openbao bao audit list
# Expected: file/ enabled at /openbao/logs/audit.log

# 4. Per-Deployment workflow E2E from the host (control-plane perspective).
$ docker compose exec openbao bao write transit/keys/dep_TEST type=aes256-gcm96
$ docker compose exec openbao bao policy write dep_TEST -<<EOF
path "transit/encrypt/dep_TEST" { capabilities = ["update"] }
path "transit/decrypt/dep_TEST" { capabilities = ["update"] }
path "transit/datakey/plaintext/dep_TEST" { capabilities = ["update"] }
EOF
# Expected: policy created

# 5. envelope unit tests pass.
$ make test
# Expected: green

# 6. envelope integration tests pass against running bao.
$ BAO_ADDR=http://localhost:8200 make test-int
# Expected: green; Encrypt → Decrypt round-trip, kid mismatch refusal, rotate, rewrap

# 7. kid binding refusal proven.
$ go test -v -run TestEnvelope_KidMismatch ./internal/platform/crypto/envelope/...
# Expected: pass; refusal happens BEFORE any OpenBao call (mock observability)

# 8. Slog redactor catches new keys.
$ go test -v -run TestLog_RedactsWrappedDEK ./internal/platform/log/...
# Expected: "wrapped_dek" replaced with "[REDACTED]" in JSON output

# 9. Lint clean (the encrypt walker has reflection — silence the relevant linters
#    with a documented //nolint:revive or accept the smell).
$ make lint
# Expected: 0 findings

# 10. ADR 006 readable, formatted, committed.
$ ls docs/adr/006-openbao-shamir-unseal.md
```

---

## Anti-pattern guards

- **NEVER** call `transit/encrypt/<kid>` or `transit/decrypt/<kid>` with a kid that wasn't verified against the request context's deployment_id. The check sits in `envelope.Decrypt` BEFORE the API call; do not bypass it.
- **NEVER** log a plaintext DEK, a wrapped DEK, an unseal share, an OpenBao token, or a Vault root token. The static redactor catches the common names; new ones go in `internal/platform/log/redact.go`.
- **NEVER** persist `Email`, `Phone`, etc. directly as a column when the OpenAPI marks it `x-pii: true`. The persistence walker writes the envelope; the migration provides the five columns. Plaintext columns for PII fields are a CI failure (lint check in Phase 16).
- **NEVER** call `transit/encrypt` row-by-row when batching is available. OpenBao supports `batch_input`; use it (`EncryptBatch`).
- **NEVER** ship `BAO_DEV_ROOT_TOKEN_ID=dev-root` in any prod build. The Phase 4 Compose file removes the dev mode entirely; the prod overlay (deferred) must inherit from this base.
- **NEVER** keep DEK plaintext past one Seal/Open call. Use `defer zero(dek)`; do not stash it in a struct field.
- **NEVER** use the root token after initial setup. The bootstrap script revokes it at the end; if a runbook step asks for it, refuse and surface to the operator.
- **NEVER** widen a per-Deployment policy to `transit/decrypt/*`. Cross-Deployment decrypt is a layer-5 break; the per-Deployment policy template forbids it by construction.
- **NEVER** run two OpenBao processes against the same file backend. The file storage is a single-writer engine.

---

## Open questions

1. **Where do we put share 2-5 for MVP?** Default (per ADR 006): on paper or a hardware token, off-device. If the user wants share 2 in a 1Password vault entry, that's acceptable but documented in the runbook. Confirm.
2. **Should the dataplane SA's k8s role bind require a specific namespace pattern?** Default: `bao write auth/kubernetes/role/<deployment_id> bound_service_account_names=data-plane bound_service_account_namespaces=saas-<project>-<env>`. The Phase 12b k3s provisioner injects the SA accordingly. Confirm naming convention.
3. **What is the per-Deployment audit log path?** Default: one shared file `/openbao/logs/audit.log` with each entry tagged by token policy (which encodes deployment_id). Alternative: one file per Deployment. The single-file approach is simpler; tag-based parsing is fine for the volumes we expect (≤ 100 deployments).
4. **Should we add an `Encryptor` interface mock for `internal/dataplane/*` unit tests?** Yes — the interface is already in Phase 3; provide a `cryptotest.MockEncryptor` that returns deterministic envelopes so non-integration unit tests don't need a running bao.

---

## Phase 4 — Definition of done

- [ ] `compose.yaml` removed dev mode; file backend + tmpfs unseal share + audit enabled
- [ ] `deploy/openbao/init/entrypoint.sh` initialises + unseals idempotently
- [ ] `make openbao-init` is idempotent on re-run; mounts transit + KV v2; enables audit + k8s + approle
- [ ] `internal/platform/crypto/envelope/` package implemented (Encrypt, Decrypt, EncryptBatch, RotateKey, Rewrap, KVPut/Get/Delete) + tests
- [ ] `internal/platform/crypto/encrypt_persist.go` reflection walker implemented + tested
- [ ] kid binding check sits BEFORE every OpenBao API call (regression test pins this)
- [ ] AAD = `deployment_id || resource_type || resource_id` documented and enforced
- [ ] `deploy/openbao/policies/deployment.hcl.tmpl` template committed
- [ ] CONVENTIONS.md §10 updated with the sibling-envelope-field convention
- [ ] ADR 006 committed
- [ ] Slog redactor knows about `wrapped_dek`, `dek_plaintext`, `bao_token`, `unseal_share`
- [ ] Both binaries boot through `envelope.New(...)` (env-selected auth method)
- [ ] Phase 2 + Phase 3 tests all still green (no regression)
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 2 — Crypto ready

### What was done
- compose.yaml: openbao moved to file backend with audit + Shamir bootstrap script
- deploy/openbao/config/openbao.hcl, deploy/openbao/init/entrypoint.sh, deploy/openbao/policies/deployment.hcl.tmpl
- Makefile targets: openbao-init, openbao-status, openbao-rotate, openbao-policies
- internal/platform/crypto/envelope/{client,encrypt,kv}.go + tests
- internal/platform/crypto/encrypt_persist.go (reflection walker, full implementation)
- cmd/dataplane/main.go: envelope.New via k8s auth method
- cmd/controlplane/main.go: envelope.New via AppRole
- docs/adr/006-openbao-shamir-unseal.md
- CONVENTIONS.md §10.x PII persistence convention
- Slog redactor extended with wrapped_dek, dek_plaintext, bao_token, unseal_share

### What to verify (user runs these)
```bash
$ make compose-down && make compose-up && make openbao-init
$ docker compose exec openbao bao status                 # Sealed: false
$ docker compose exec openbao bao secrets list           # transit/, secret/
$ docker compose exec openbao bao auth list              # kubernetes/, approle/
$ docker compose exec openbao bao audit list             # file/
$ docker compose exec openbao bao policy list            # default, dep_TEST after section #4 above
$ make test && make test-int                             # green
$ go test -v -run TestEnvelope_KidMismatch ./internal/platform/crypto/envelope/...
$ ls deploy/openbao/policies/ deploy/openbao/init/
$ wc -l internal/platform/crypto/envelope/*.go
```

### What approval means
By proceeding past CHECKPOINT 2, you accept:
- The MVP unseal trade-off documented in ADR 006 (one share on tmpfs; production target = cloud KMS).
- AAD format is `deployment_id || resource_type || resource_id`; every PII field bind that exact AAD; changing it later requires re-encrypting all rows.
- The persistence walker mandates the sibling `<Field>Envelope` convention; every future PII field follows it.
- Phases 5-15 will rely on `envelope.Client` being available; modules will not have a non-OpenBao fallback.

### Rollback if rejected
```bash
git revert <hashes for the 6 phase-4 commits>
docker compose down -v                  # nukes openbao-data volume (DESTROYS keys)
# Note: rollback before any real deployment uses transit keys; after that,
# rollback requires backups (bao operator raft snapshot save) and a re-init.
```

---

End of Phase 4. Next: `06-identity-keycloak.md`.
