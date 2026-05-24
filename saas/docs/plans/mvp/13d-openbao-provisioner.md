# Phase 12d — Per-Deployment OpenBao Provisioner (Transit Key + k8s Role + KV Path + Policy + Audit)

> **Goal**: Implement the real `OpenBaoAdapter` for the composite Provisioner. For each Deployment: create transit key `transit/keys/<deployment_id>` (aes-256-gcm, 90-day rotation), upload the per-Deployment HCL policy (rendered from `deploy/openbao/policies/deployment.hcl.tmpl` — created in Phase 4), create Kubernetes auth role `<deployment_id>` bound to the k3s SA from Phase 12b, prepare the KV v2 namespace `secret/<deployment_id>/`, enable a per-Deployment audit device entry. CHECKPOINT 8 ends in `bao read transit/keys/<dep_id>` returning a real key.
>
> **Why now**: Phase 12c stored the per-Deployment Postgres password in OpenBao KV — that read path requires the Deployment's k8s auth role + policy to already exist. Phase 12b created the SA. Phase 4 created the transit infrastructure + policy template. Phase 12d wires it all together per Deployment. Without it, Phase 12c's `bao kv put` and the data-plane's `bao kv get` would fail.
>
> **What this phase does NOT do**: No transit key rotation (the rotation API is in Phase 4; cadence is operational). No dynamic database secrets engine (deferred). No Keycloak realm-per-Deployment via OpenBao (Phase 13 handles operators MFA; data-plane realm is a single shared realm for MVP). No backup of OpenBao state (deferred — `bao operator raft snapshot save` is a runbook concern).
>
> **Maps to AGENTS.md**: §18.7 (the whole section), §6.2 step ?? (between 4 and 7 — Phase 12e orders it formally), §18.1 layer 5. `01-foundations.md` §5 (transit + KV + k8s auth role + policy + audit).
>
> **Estimated subagent sessions**: 2 (one for adapter + policy upload + k8s role; one for KV prep + audit + tests).

---

## Pre-flight

1. AGENTS.md §18.7.
2. `01-foundations.md` §5 (every API signature).
3. CHECKPOINT 7 approved.
4. Phase 4 (`05-openbao-integration.md`) completed: transit + KV v2 mounted; k8s + AppRole auth enabled; audit device on; root token revoked.
5. The platform's AppRole (control-plane identity) has the `manage` policy that lets it create transit keys, write policies, create k8s roles, and write KV. This is set up once in Phase 4's `make openbao-init` step.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Key spec | `type=aes256-gcm96`, `derived=false`, `exportable=false`, `allow_plaintext_backup=false`, `auto_rotate_period=90d` | aes128-gcm96 (refused — weaker); chacha20-poly1305 (refused — KSA compliance) |
| Policy name | Same as deployment_id (`dep_<ulid>`) | Prefixed `saas-dep-<id>` (refused — redundant) |
| k8s auth role config | `bound_service_account_names=data-plane`, `bound_service_account_namespaces=saas-<project>-<env>`, `policies=<deployment_id>`, `ttl=1h`, `max_ttl=24h` | Permissive (refused — broad SA binding) |
| KV path layout | `secret/data/<deployment_id>/postgres/app_password`, `secret/data/<deployment_id>/byod_hmac_key`, `secret/data/<deployment_id>/identity/email_hmac_key`, `secret/data/<deployment_id>/notifications/novu_api_key`, `secret/data/<deployment_id>/api_keys/prefix_hmac_key`, `secret/data/<deployment_id>/audit/metadata_hmac_key` | Flatter (refused — folder makes ops introspection easier) |
| Audit device | Single shared `/openbao/logs/audit.log` with policy name embedded in each line | Per-Deployment file (refused for MVP — file count blows up; tag-based parse is fine) |
| HMAC keys pre-population | At provision time, generate 32-byte random for each HMAC key path (byod, identity email, api_keys prefix, audit metadata) | On-demand (refused — first request slow; race-prone) |
| AAD format reminder | `deployment_id || resource_type || resource_id` (CONVENTIONS §10 + ADR 004) | None — fixed |
| Soft destroy retention for transit | DISABLE the transit key on destroy (no encrypts; decrypts still allowed during retention); DELETE on purge | Keep enabled (refused — silent reuse risk during retention window) |

If user disagrees, stop. The KV path layout in particular is hard to change later (consumers everywhere depend on the exact paths).

---

## Tasks

### 12d.1 Adapter — `internal/controlplane/provision/openbao/`

```text
internal/controlplane/provision/openbao/
  adapter.go        # OpenBaoAdapter
  transit.go        # create/disable/delete transit keys
  policy.go         # render policy from template + upload
  k8sauth.go        # create/delete k8s auth role
  kv.go             # KV path prep + HMAC key generation
  audit.go          # audit device + per-policy log capture
  adapter_test.go
```

`adapter.go`:

```go
package openbao

import (
    "context"
    "fmt"
    "text/template"

    bao "github.com/openbao/openbao/api/v2"
    _ "embed"

    "github.com/omarss/saas/internal/platform/crypto/envelope"
)

//go:embed policies/deployment.hcl.tmpl
var policyTmplBytes []byte

type Adapter struct {
    Client *bao.Client                     // control-plane's authenticated client (AppRole)
    Enc    *envelope.Client                // for KV reads/writes when needed
    Tmpl   *template.Template
}

func New(c *bao.Client, enc *envelope.Client) (*Adapter, error) {
    t, err := template.New("policy").Parse(string(policyTmplBytes))
    if err != nil { return nil, err }
    return &Adapter{Client: c, Enc: enc, Tmpl: t}, nil
}

// Provision is steps 4ish of §6.2 (interspersed with Phase 12c per Phase 12e ordering).
func (a *Adapter) Provision(ctx context.Context, dep *Deployment) error {
    if err := a.createTransitKey(ctx, dep.ID); err != nil { return fmt.Errorf("transit key: %w", err) }
    if err := a.uploadPolicy(ctx, dep.ID); err != nil { return fmt.Errorf("policy: %w", err) }
    if err := a.createK8sAuthRole(ctx, dep); err != nil { return fmt.Errorf("k8s role: %w", err) }
    if err := a.prepareKVNamespace(ctx, dep.ID); err != nil { return fmt.Errorf("kv prep: %w", err) }
    if err := a.generateHMACKeys(ctx, dep.ID); err != nil { return fmt.Errorf("hmac keys: %w", err) }
    return nil
}

// Destroy disables the transit key (decrypts still possible during retention).
// Purge deletes the key + policy + auth role + KV.
func (a *Adapter) Destroy(ctx context.Context, dep *Deployment) error {
    return a.disableTransitKey(ctx, dep.ID)
}

func (a *Adapter) Purge(ctx context.Context, dep *Deployment) error {
    var errs []error
    if err := a.deleteTransitKey(ctx, dep.ID);    err != nil { errs = append(errs, err) }
    if err := a.deletePolicy(ctx, dep.ID);        err != nil { errs = append(errs, err) }
    if err := a.deleteK8sAuthRole(ctx, dep.ID);   err != nil { errs = append(errs, err) }
    if err := a.deleteKVNamespace(ctx, dep.ID);   err != nil { errs = append(errs, err) }
    return errors.Join(errs...)
}

// FreezeKeys disables the transit key without deleting it. Used for incident
// response per §18.7. Wired to /control/v1/deployments/{id}/freeze-keys
// (Phase 12e endpoint).
func (a *Adapter) FreezeKeys(ctx context.Context, depID string) error {
    return a.disableTransitKey(ctx, depID)
}
```

### 12d.2 Transit key

`transit.go`:

```go
func (a *Adapter) createTransitKey(ctx context.Context, depID string) error {
    // Idempotent: read first; if exists, no-op.
    if sec, err := a.Client.Logical().ReadWithContext(ctx, "transit/keys/"+depID); err == nil && sec != nil {
        return nil
    }
    _, err := a.Client.Logical().WriteWithContext(ctx, "transit/keys/"+depID, map[string]any{
        "type":                    "aes256-gcm96",
        "derived":                 false,
        "exportable":              false,
        "allow_plaintext_backup":  false,
        "auto_rotate_period":      "2160h",  // 90 days
    })
    return err
}

func (a *Adapter) disableTransitKey(ctx context.Context, depID string) error {
    _, err := a.Client.Logical().WriteWithContext(ctx, "transit/keys/"+depID+"/config", map[string]any{
        "deletion_allowed": true,
        "min_decryption_version": 1,
        "min_encryption_version": 0,   // 0 = disable encryption; old decrypts still work
    })
    return err
}

func (a *Adapter) deleteTransitKey(ctx context.Context, depID string) error {
    // Must `deletion_allowed=true` first (set by disableTransitKey).
    _, err := a.Client.Logical().DeleteWithContext(ctx, "transit/keys/"+depID)
    return err
}
```

### 12d.3 Policy

`policy.go`:

```go
func (a *Adapter) uploadPolicy(ctx context.Context, depID string) error {
    var buf bytes.Buffer
    if err := a.Tmpl.Execute(&buf, struct{ DeploymentID string }{DeploymentID: depID}); err != nil {
        return err
    }
    return a.Client.Sys().PutPolicyWithContext(ctx, depID, buf.String())
}

func (a *Adapter) deletePolicy(ctx context.Context, depID string) error {
    return a.Client.Sys().DeletePolicyWithContext(ctx, depID)
}
```

The policy template `deploy/openbao/policies/deployment.hcl.tmpl` was created in Phase 4. Verbatim (mirroring `01-foundations.md` §5):

```hcl
path "transit/encrypt/{{.DeploymentID}}"             { capabilities = ["update"] }
path "transit/decrypt/{{.DeploymentID}}"             { capabilities = ["update"] }
path "transit/datakey/plaintext/{{.DeploymentID}}"   { capabilities = ["update"] }
path "transit/rewrap/{{.DeploymentID}}"              { capabilities = ["update"] }
path "transit/keys/{{.DeploymentID}}"                { capabilities = ["read"] }

path "secret/data/{{.DeploymentID}}/*"               { capabilities = ["create","read","update","delete"] }
path "secret/metadata/{{.DeploymentID}}/*"           { capabilities = ["list","read","delete"] }
```

No globs in transit paths — explicit path per Deployment.

### 12d.4 Kubernetes auth role

`k8sauth.go`:

```go
func (a *Adapter) createK8sAuthRole(ctx context.Context, dep *Deployment) error {
    body := map[string]any{
        "bound_service_account_names":      "data-plane",
        "bound_service_account_namespaces": dep.Namespace,
        "policies":                         dep.ID,
        "token_ttl":                        "3600",
        "token_max_ttl":                    "86400",
        "token_no_default_policy":          true,        // we don't want the default policy
        "token_type":                       "service",
    }
    _, err := a.Client.Logical().WriteWithContext(ctx, "auth/kubernetes/role/"+dep.ID, body)
    return err
}

func (a *Adapter) deleteK8sAuthRole(ctx context.Context, depID string) error {
    _, err := a.Client.Logical().DeleteWithContext(ctx, "auth/kubernetes/role/"+depID)
    return err
}
```

The role name === deployment_id; the data-plane code reads this role name from `DEPLOYMENT_ID` env var to authenticate (per Phase 4's `envelope.Client` setup).

### 12d.5 KV namespace prep + HMAC key generation

`kv.go`:

```go
func (a *Adapter) prepareKVNamespace(ctx context.Context, depID string) error {
    // KV v2 doesn't require explicit "create namespace"; first PUT creates the
    // metadata. We seed a marker so listing works for operators.
    return a.Enc.KVPut(ctx, depID, "_meta", map[string]any{
        "provisioned_at": time.Now().UTC().Format(time.RFC3339),
        "deployment_id":  depID,
    })
}

func (a *Adapter) generateHMACKeys(ctx context.Context, depID string) error {
    keys := []string{
        "byod_hmac_key",
        "identity/email_hmac_key",
        "api_keys/prefix_hmac_key",
        "audit/metadata_hmac_key",
        "invitations/token_hmac_key",
    }
    for _, k := range keys {
        // Idempotent: skip if exists.
        if _, err := a.Enc.KVGet(ctx, depID, k); err == nil { continue }
        raw := make([]byte, 32)
        if _, err := rand.Read(raw); err != nil { return err }
        if err := a.Enc.KVPut(ctx, depID, k, map[string]any{
            "key": base64.StdEncoding.EncodeToString(raw),
        }); err != nil { return err }
    }
    return nil
}

func (a *Adapter) deleteKVNamespace(ctx context.Context, depID string) error {
    // KV v2 needs explicit metadata delete per path. Iterate keys.
    // Implementation: list secret/metadata/<depID>/ recursively + DELETE each.
    return iterateAndDelete(ctx, a.Enc, depID, "")
}
```

The HMAC key paths must match exactly what the data-plane code reads:

- `byod_hmac_key` — Phase 11 (BYOD domain TXT verification token HMAC). NOTE: Phase 11 used an in-memory placeholder; this phase makes it real.
- `identity/email_hmac_key` — Phase 5 (user email lookup HMAC).
- `api_keys/prefix_hmac_key` — Phase 9 (API key prefix index HMAC).
- `audit/metadata_hmac_key` — Phase 10 (forensic metadata recovery; not strictly an HMAC but a deterministic key for the envelope AAD anchor).
- `invitations/token_hmac_key` — Phase 7 (invitation token lookup).

If any of these paths is later renamed, the data-plane reads break. The path map is centralised in `internal/platform/crypto/envelope/kv_paths.go`:

```go
package envelope

const (
    PathBYODHMAC          = "byod_hmac_key"
    PathIdentityEmailHMAC = "identity/email_hmac_key"
    PathAPIKeyPrefixHMAC  = "api_keys/prefix_hmac_key"
    PathAuditMetadataHMAC = "audit/metadata_hmac_key"
    PathInvitationHMAC    = "invitations/token_hmac_key"
    PathPostgresAppPass   = "postgres/app_password"
    PathNovuAPIKey        = "notifications/novu_api_key"
)
```

Every module imports this. CONVENTIONS.md §10.x updated.

### 12d.6 Audit

`audit.go`:

```go
func (a *Adapter) tagAuditEntry(ctx context.Context, depID string) error {
    // No-op: the audit device was enabled in Phase 4 (single shared file).
    // Each operation under the policy will appear in the audit log tagged
    // with the policy name (i.e. deployment_id). Operators grep by depID.
    return nil
}
```

If per-Deployment audit files are wanted later, an additional file device is enabled here. For MVP the shared file is acceptable.

### 12d.7 Composite Provisioner wiring (full order per §6.2)

```go
type CompositeProvisioner struct {
    Postgres *postgres.Adapter
    K3s      *k3s.Adapter
    Nginx    *nginx.Adapter
    OpenBao  *openbao.Adapter
}

func (c *CompositeProvisioner) Provision(ctx context.Context, d *Deployment) (BootstrapResult, error) {
    // §6.2 order:
    // 4. CREATE DATABASE + role  →  Postgres.Provision (creates DB + role + grants; needs OpenBao KV password write to land first)
    // 5. Apply data-plane migrations
    // 6. Seed bootstrap tenant + API key
    // 7. Render k3s manifests
    // 8. kubectl apply
    // 9. Render nginx vhost
    // 10. apply-nginx + certbot
    // 11. Wait for /healthz
    // 12. Flip status + emit deployment.provisioned
    // 13. Return bootstrap API key

    // Order chosen for safe rollback: cheapest+revocable first; host-state writes last.
    // 1. OpenBao transit key + policy + k8s role + KV namespace + HMAC keys.
    if err := c.OpenBao.Provision(ctx, d); err != nil { return BootstrapResult{}, fmt.Errorf("openbao: %w", err) }
    // 2. Postgres DB + role + migrations + grants + password to KV.
    if err := c.Postgres.Provision(ctx, d); err != nil { return BootstrapResult{}, fmt.Errorf("postgres: %w", err) }
    // 3. Seed bootstrap tenant + API key.
    boot, err := c.seedBootstrap(ctx, d); if err != nil { return boot, fmt.Errorf("seed: %w", err) }
    // 4. k3s namespace + pods.
    if err := c.K3s.Provision(ctx, d); err != nil { return boot, fmt.Errorf("k3s: %w", err) }
    // 5. Nginx vhost.
    if err := c.Nginx.ApplyVhost(ctx, vhostInput(d)); err != nil { return boot, fmt.Errorf("nginx: %w", err) }
    // 6. Cert.
    if err := c.Nginx.IssueCertificate(ctx, d.ID, d.PrimaryVhost, d.CustomDomains); err != nil { return boot, fmt.Errorf("certbot: %w", err) }
    // 7. Healthz.
    if err := c.waitForPublicHealth(ctx, d); err != nil { return boot, fmt.Errorf("health: %w", err) }
    return boot, nil
}
```

Note: Phase 12e re-orders + adds the destroy reconciler.

### 12d.8 Tests

`adapter_test.go`:

- Create transit key → `bao read transit/keys/<id>` returns key
- Re-Create → idempotent no-op
- Upload policy → `bao policy read <id>` returns the rendered HCL
- Create k8s role → `bao read auth/kubernetes/role/<id>` returns the role
- HMAC keys exist at the canonical paths
- Cross-Deployment policy denial: a token bound to dep_A cannot read `secret/data/dep_B/_meta` → 403
- Disable + delete transit: subsequent encrypt returns error; subsequent decrypt still works for old versions (verifies the design)
- Purge → none of the artifacts exist
- KV path consistency: every constant in `kv_paths.go` is present after Provision

`integration_test.go` (real bao):

- Provision a test deployment
- Use a token bound to the deployment's k8s role to encrypt → decrypt → success
- Use the SAME token to attempt cross-Deployment encrypt → 403

### 12d.9 Commits

```bash
git add internal/controlplane/provision/openbao/
git commit -m "implement per deployment openbao provisioner"

git add internal/platform/crypto/envelope/kv_paths.go
git commit -m "centralize openbao kv path constants"

git add cmd/controlplane/main.go internal/controlplane/deployments/
git commit -m "wire openbao adapter into composite provisioner"

git add CONVENTIONS.md
git commit -m "document kv path map convention"
```

---

## Verification checklist

```bash
# 1. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 2. Provision a deployment.
$ ./bin/saasctl deployment create --project baotest --environment dev --image v0.3.1

# 3. Transit key exists.
$ docker compose exec openbao bao read transit/keys/dep_...
# Expected: type=aes256-gcm96, keys version=1, ...

# 4. Policy exists.
$ docker compose exec openbao bao policy read dep_...
# Expected: the rendered HCL with paths bound to dep_... only

# 5. k8s auth role exists.
$ docker compose exec openbao bao read auth/kubernetes/role/dep_...
# Expected: bound_service_account_names=data-plane, bound_service_account_namespaces=saas-baotest-dev, policies=dep_...

# 6. KV namespace + HMAC keys.
$ docker compose exec openbao bao kv list secret/dep_.../
# Expected: _meta, byod_hmac_key, identity/, api_keys/, audit/, invitations/, postgres/
$ docker compose exec openbao bao kv get -field=key secret/dep_.../byod_hmac_key
# Expected: base64-encoded 32 bytes (44 chars)

# 7. Data-plane pod authenticates via k8s SA + reads its own postgres password.
$ kubectl -n saas-baotest-dev logs deploy/data-plane | grep -E "envelope|kv"
# Expected: "envelope: authenticated via kubernetes role dep_..."

# 8. Cross-Deployment denial.
$ # Get the dep_A SA token; try to read dep_B's KV.
$ TOKEN=$(kubectl -n saas-baotest-dev exec deploy/data-plane -- cat /var/run/secrets/kubernetes.io/serviceaccount/token)
$ AUTH=$(docker compose exec openbao sh -c "VAULT_ADDR=http://127.0.0.1:8200 bao write -field=token auth/kubernetes/login role=dep_BAOTEST jwt=$TOKEN" )
$ docker compose exec openbao sh -c "VAULT_TOKEN=$AUTH bao kv get secret/dep_OTHER/_meta"
# Expected: permission denied

# 9. Audit log shows reads tagged by policy.
$ docker compose exec openbao tail -20 /openbao/logs/audit.log
# Expected: entries with policy="dep_..." for transit/decrypt and secret/data ops

# 10. Purge cleans up.
$ ./bin/saasctl deployment delete dep_... --retain-days 0
$ ./bin/saasctl deployment purge dep_...
$ docker compose exec openbao bao read transit/keys/dep_...
# Expected: No value found
$ docker compose exec openbao bao policy read dep_...
# Expected: No policy named: dep_...
```

---

## Anti-pattern guards

- **NEVER** create a transit key with `exportable=true`. Even for backup; backups encrypt under a separate `transit/keys/backups-master` (§18.7).
- **NEVER** widen the per-Deployment policy to `transit/decrypt/*`. Cross-Deployment decrypt is layer 5 breach; the policy template forbids by construction.
- **NEVER** issue a token outside the AppRole or k8s auth flows. Direct root-token use is a security incident; the bootstrap script revoked root.
- **NEVER** rename a KV path in `kv_paths.go` without an ADR and a coordinated upgrade of every consumer. Old deployments will silently break.
- **NEVER** allow purge before destroy. Phase 11's state machine enforces; double-check here.
- **NEVER** generate HMAC keys with less than 32 bytes. Crypto-strong randomness only (crypto/rand).
- **NEVER** put plaintext secrets in `_meta`. The marker is metadata only.
- **NEVER** skip the `min_encryption_version=0` step on destroy. Without it, the disabled key still encrypts (silent reuse).
- **NEVER** delete a transit key without first setting `deletion_allowed=true`. The default is `false`; bypassing requires explicit policy.

---

## Open questions

1. **HMAC key rotation cadence.** Out of MVP; rotation requires re-keying all the lookup hashes (api_key prefixes, email lookups, invitation tokens). v1 roadmap.
2. **Audit per-Deployment file.** Default: shared file with tagging. If operators want per-Deployment files, enable a second file device per Deployment — adds an inotify-watcher to clean up on purge. Confirm shared file OK for MVP.
3. **Token TTL/max_ttl.** Default 1h/24h. The lifetime watcher (envelope.Client) renews. Confirm adequate.
4. **What if OpenBao is unavailable during provision?** Default: fail the provision early (step 1); no other host writes have happened yet, so rollback is trivial (just mark status=failed). Confirm.

---

## Phase 12d — Definition of done

- [ ] `internal/controlplane/provision/openbao/` complete: adapter, transit, policy, k8sauth, kv, audit, tests
- [ ] Transit key created per Deployment with aes-256-gcm + 90d auto-rotate
- [ ] Per-Deployment policy uploaded from rendered template
- [ ] Kubernetes auth role bound to `data-plane` SA in correct namespace
- [ ] KV namespace prepped + HMAC keys generated at canonical paths
- [ ] `kv_paths.go` constants used by every consumer module
- [ ] Cross-Deployment policy denial verified (real test)
- [ ] Destroy disables the transit key; subsequent encrypts fail
- [ ] Purge deletes transit key + policy + auth role + KV namespace
- [ ] CompositeProvisioner provisions OpenBao before Postgres (correct order)
- [ ] Data-plane pod authenticates via k8s SA + can read its KV at boot
- [ ] All Phase 2-12c tests still green
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 8 — First real per-Deployment OpenBao transit key

### What was done
- internal/controlplane/provision/openbao/ adapter + tests
- Per-Deployment transit key (aes-256-gcm, 90d rotate)
- Per-Deployment policy bound by path to dep_id
- Kubernetes auth role bound to data-plane SA in saas-<project>-<env> ns
- KV namespace with 5 HMAC keys pre-populated
- internal/platform/crypto/envelope/kv_paths.go (single source of truth)

### What to verify (user runs these)
```bash
$ docker compose exec openbao bao read transit/keys/<dep_id>
$ docker compose exec openbao bao policy read <dep_id>
$ docker compose exec openbao bao read auth/kubernetes/role/<dep_id>
$ docker compose exec openbao bao kv list secret/<dep_id>/
$ docker compose exec openbao bao kv get secret/<dep_id>/_meta
# Each should return its expected shape.

# Cross-Deployment denial
$ # See §12d.6 example: token from dep_A pod cannot read dep_B's KV.

# Audit log shows policy tagging
$ docker compose exec openbao tail /openbao/logs/audit.log | grep "policy.*<dep_id>"
```

### What approval means
By proceeding past CHECKPOINT 8, you accept:
- Every Deployment has its own transit key and policy; cross-Deployment encrypt/decrypt is policy-blocked.
- The data-plane pod identity = its k8s SA = its OpenBao auth role = its policy. The chain of trust is rooted in the k8s SA token.
- KV path layout is frozen (changing paths breaks every downstream module).
- Disable on destroy + delete on purge is the lifecycle; recovery requires backups.

### Rollback if rejected
```bash
$ ./bin/saasctl deployment purge <dep_id>       # cleans up bao artifacts via Purge
$ git revert <hashes for the 4 phase-12d commits>
```

---

End of Phase 12d. Next: `13e-provisioning-sequence.md`.
