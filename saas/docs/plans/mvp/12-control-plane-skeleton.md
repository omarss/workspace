# Phase 11 — Control Plane Skeleton (Local-Mode Provisioner + BYOD Endpoints)

> **Goal**: Ship the operator-only Control Plane API at `https://control.saas.omarss.net`. Surface the `/control/v1/deployments` CRUD endpoints from §8.0 + the BYOD custom-domain endpoints (`/control/v1/deployments/{id}/domains/*`). Implement a LOCAL-MODE provisioner that ONLY: (1) creates a Postgres database on the dev host, (2) runs data-plane migrations, (3) seeds a bootstrap admin tenant + first API key. No host nginx writes, no k3s API calls, no certbot, no real OpenBao transit-key creation. Stop at CHECKPOINT 4 so the user reviews sudoers + certbot + nginx layout + k3s manifest templates BEFORE any Phase 12 sub-phase touches real host state.
>
> **Why now**: AGENTS.md §16 mandates control-plane work after data-plane completion. Phase 12 will split into 5 sub-phases (nginx, k3s, postgres, openbao, sequence) each touching a different host system; Phase 11 is the contract scaffolding that all five attach to. The BYOD scope-change (00-master.md ADR 015) is grafted here so the eventual Phase 12a nginx work has the multi-server_name shape baked in from day one. The local-mode provisioner gives operators a working CRUD surface BEFORE any irreversible host write, exactly the safety property CHECKPOINT 4 gates.
>
> **What this phase does NOT do**: No real provisioning (Phase 12a-e). No certbot. No k3s. No host Postgres role creation (just a database; uses the platform's existing `saas` role for app access in local mode). No operator MFA / step-up (Phase 13). No backups / restore (Phase 12e). No purge — local-mode DELETE marks status=destroyed in the control plane DB.
>
> **Maps to AGENTS.md**: §0 personas (Operator), §3.1 control plane vs data plane, §6 homelab model (sequence + gotchas — Phase 12 implements these), §8.0 (control plane endpoints), §11.5 (`op_`, `dep_` prefixes), §12.1 (Deployments module — control plane), §16 phase ordering, §17.4 provisioning tests (skeletal in this phase, full in Phase 12e), §18.4 (operator auth — Phase 13 wires MFA). `01-foundations.md` §9 (client-go anti-patterns are noted but not used yet), §13 (ID prefixes).
>
> **Estimated subagent sessions**: 3 (one for OpenAPI + control-plane DB schema + module skeleton; one for BYOD endpoints + domain verification flow + local provisioner; one for saasctl + tests + ADR 015).

---

## Pre-flight

1. AGENTS.md §0, §3.1, §6, §8.0, §11.5, §12.1, §17.4, §18.4.
2. 00-master.md scope-change row for BYOD (ADR 015).
3. `01-foundations.md` §9 (client-go field-manager pattern — Phase 12b uses this; Phase 11 reads for context).
4. `04-platform-patterns.md` (Phase 3) — control plane reuses the same platform helpers.
5. `02-walking-skeleton.md` (Phase 1) — control-plane main.go already exists with `/healthz`.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Provisioner mode in Phase 11 | LOCAL-MODE only — creates a Postgres database on the dev host, runs data-plane migrations, seeds a bootstrap tenant; emits all events as if real | Stub (refused — too disconnected from real flow); real (refused — gates at CHECKPOINT 4 before any host write) |
| BYOD verification method | DNS TXT record `_saas-verify.<custom_domain> -> saas-verify=<token>` checked synchronously by the control plane; verified on `POST /domains/{id}/verify` | HTTP-01 challenge (refused — needs port 80 reachable; many BYOD orgs don't have that ready upfront) |
| BYOD domain limit | 5 custom domains per Deployment by default; configurable via Deployment.metadata.byod_limit | Unlimited (refused — certbot LE rate limits) |
| Operator JWT audience | `aud=saas-control`, separate from data-plane | Single audience with claim discrimination (refused — §18.4) |
| Operator JWT issuer | The local Keycloak `operators` realm (created in Phase 5 only for Phase 13 to extend; Phase 11 uses a stub `op_local` Keycloak client until Phase 13) | External IdP (refused — homelab) |
| Bootstrap admin tenant id | Deterministic: `tenant_bootstrap_<dep_id_suffix>` so operators can find it | Random ULID (refused — operator UX) |
| Bootstrap API key scope | `*` (all scopes) — wide because it's the first key; operators rotate to narrower scoped keys after | Read-only (refused — first key must be powerful enough to create more keys) |
| Deployment soft-delete vs hard-delete | Soft: DELETE flips status='destroyed' + retention 30d; hard delete is `/purge` (Phase 12e) | Hard only (refused — §6.4) |
| Status state machine | provisioning → active → upgrading → active OR failed; destroyed; restoring; rollback; purged | Single status enum (refused — sub-states matter for §17.4) |

If the user disagrees on any default, stop. Decisions touch the control-plane schema.

---

## Tasks

### 11.1 Control-plane OpenAPI surface

`openapi/control-plane.yaml`:

```yaml
tags:
  - name: deployments
    description: Provision, operate, and decommission isolated SaaS deployments.
  - name: domains
    description: Bring-Your-Own-Domain attachments for a Deployment.
  - name: operators
    description: Operator inventory (extended in Phase 13).

paths:
  /control/v1/deployments:
    get:
      operationId: listDeployments
      tags: [deployments]
      parameters:
        - $ref: "#/components/parameters/Limit"
        - $ref: "#/components/parameters/Cursor"
        - { in: query, name: status, schema: { type: string } }
      responses:
        "200": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentListResponse" } } } }
    post:
      operationId: createDeployment
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody:
        content: { application/json: { schema: { $ref: "#/components/schemas/CreateDeploymentRequest" } } }
      responses:
        "201":
          headers: { ETag: { schema: { type: string } } }
          content: { application/json: { schema: { $ref: "#/components/schemas/CreateDeploymentResponse" } } }

  /control/v1/deployments/{deployment_id}:
    parameters: [ { in: path, name: deployment_id, required: true, schema: { type: string, pattern: "^dep_[0-9A-HJKMNP-TV-Z]{26}$" } } ]
    get:    { operationId: getDeployment,    tags: [deployments], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentResponse" } } } } } }
    patch:  { operationId: updateDeployment, tags: [deployments], parameters: [ { $ref: "#/components/parameters/IfMatch" }, { $ref: "#/components/parameters/IdempotencyKey" } ], requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/UpdateDeploymentRequest" } } } }, responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentResponse" } } } } } }
    delete: { operationId: deleteDeployment, tags: [deployments], parameters: [ { $ref: "#/components/parameters/IfMatch" }, { in: query, name: retain_days, schema: { type: integer, minimum: 0, maximum: 365, default: 30 } } ], responses: { "204": { description: Soft-deleted; retention applies. } } }

  /control/v1/deployments/{deployment_id}/upgrade:
    post:
      operationId: upgradeDeployment
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/UpgradeDeploymentRequest" } } } }
      responses: { "202": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentResponse" } } } } }

  /control/v1/deployments/{deployment_id}/rollback:
    post:
      operationId: rollbackDeployment
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses: { "202": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentResponse" } } } } }

  /control/v1/deployments/{deployment_id}/restart:
    post:
      operationId: restartDeployment
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses: { "202": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentResponse" } } } } }

  /control/v1/deployments/{deployment_id}/restore:
    post:
      operationId: restoreDeployment
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/RestoreDeploymentRequest" } } } }
      responses: { "202": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentResponse" } } } } }

  /control/v1/deployments/{deployment_id}/purge:
    post:
      operationId: purgeDeployment
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses: { "202": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentResponse" } } } } }

  /control/v1/deployments/{deployment_id}/revisions:
    get:
      operationId: listDeploymentRevisions
      tags: [deployments]
      responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentRevisionListResponse" } } } } }

  /control/v1/deployments/{deployment_id}/health:
    get:
      operationId: getDeploymentHealth
      tags: [deployments]
      responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentHealthResponse" } } } } }

  /control/v1/deployments/{deployment_id}/logs:
    get:
      operationId: tailDeploymentLogs
      tags: [deployments]
      parameters:
        - { in: query, name: since, schema: { type: string, format: date-time } }
        - { in: query, name: filter, schema: { type: string } }
        - { in: query, name: tail, schema: { type: integer, minimum: 1, maximum: 10000, default: 100 } }
      responses:
        "200":
          content:
            application/x-ndjson:
              schema: { type: string }

  /control/v1/deployments/{deployment_id}/impersonation-sessions:
    post:
      operationId: startImpersonationSession
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody: { content: { application/json: { schema: { $ref: "#/components/schemas/StartImpersonationRequest" } } } }
      responses: { "201": { content: { application/json: { schema: { $ref: "#/components/schemas/StartImpersonationResponse" } } } } }

  /control/v1/deployments/{deployment_id}/domains:
    parameters: [ { in: path, name: deployment_id, required: true, schema: { type: string } } ]
    get:  { operationId: listDeploymentDomains, tags: [domains], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentDomainListResponse" } } } } } }
    post:
      operationId: attachDeploymentDomain
      tags: [domains]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      requestBody:
        content:
          application/json:
            schema: { $ref: "#/components/schemas/AttachDomainRequest" }
      responses:
        "201":
          content: { application/json: { schema: { $ref: "#/components/schemas/DeploymentDomainResponse" } } }

  /control/v1/deployments/{deployment_id}/domains/{domain_id}:
    parameters:
      - { in: path, name: deployment_id, required: true, schema: { type: string } }
      - { in: path, name: domain_id,     required: true, schema: { type: string, pattern: "^dom_[0-9A-HJKMNP-TV-Z]{26}$" } }
    delete: { operationId: detachDeploymentDomain, tags: [domains], parameters: [ { $ref: "#/components/parameters/IfMatch" } ], responses: { "204": { description: Detached. } } }

  /control/v1/deployments/{deployment_id}/domains/{domain_id}/verify:
    post:
      operationId: verifyDeploymentDomain
      tags: [domains]
      parameters: [ { $ref: "#/components/parameters/IdempotencyKey" } ]
      responses:
        "200":
          content:
            application/json:
              schema: { $ref: "#/components/schemas/DeploymentDomainResponse" }

  /control/v1/audit-events:
    # Control-plane audit. Same shape as data-plane audit but with control-plane scope.
    get:
      operationId: listControlPlaneAuditEvents
      tags: [deployments]
      parameters: [ { $ref: "#/components/parameters/Limit" }, { $ref: "#/components/parameters/Cursor" } ]
      responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/ControlPlaneAuditEventListResponse" } } } } }

  /control/v1/operators:
    get: { operationId: listOperators, tags: [operators], responses: { "200": { content: { application/json: { schema: { $ref: "#/components/schemas/OperatorListResponse" } } } } } }

components:
  schemas:
    Deployment:
      type: object
      required: [id, project_slug, environment_slug, status, image_version, created_at, etag]
      properties:
        id:               { type: string, pattern: "^dep_[0-9A-HJKMNP-TV-Z]{26}$" }
        project_slug:     { type: string, pattern: "^[a-z][a-z0-9-]*[a-z0-9]$", minLength: 2, maxLength: 32 }
        environment_slug: { type: string, pattern: "^[a-z][a-z0-9-]*[a-z0-9]$", minLength: 2, maxLength: 32 }
        region:           { type: string }
        modules:          { type: array, items: { type: string } }
        image_version:    { type: string }
        data_residency:   { type: string }
        primary_vhost:    { type: string, description: "<env>.<project>.saas.omarss.net" }
        custom_domains:   { type: array, items: { type: string } }
        status:           { type: string, enum: [provisioning, active, upgrading, failed, destroyed, restoring, purged] }
        metadata:         { type: object, additionalProperties: { type: string } }
        last_event_id:    { type: [string, "null"] }
        retain_until:     { type: [string, "null"], format: date-time }
        created_at:       { type: string, format: date-time }
        updated_at:       { type: string, format: date-time }
        etag:             { type: string }

    CreateDeploymentRequest:
      type: object
      required: [project_slug, environment_slug, image_version]
      properties:
        project_slug:     { type: string }
        environment_slug: { type: string }
        region:           { type: string }
        modules:          { type: array, items: { type: string } }
        image_version:    { type: string }
        data_residency:   { type: string }
        metadata:         { type: object, additionalProperties: { type: string } }

    CreateDeploymentResponse:
      type: object
      required: [data, bootstrap_api_key]
      properties:
        data: { $ref: "#/components/schemas/Deployment" }
        bootstrap_api_key:
          type: object
          required: [id, secret, tenant_id]
          properties:
            id:        { type: string }
            secret:    { type: string, x-oapi-codegen-extra-tags: { sensitive: "true" } }
            tenant_id: { type: string }

    UpdateDeploymentRequest:
      type: object
      properties:
        image_version: { type: string }
        metadata:      { type: object, additionalProperties: { type: string } }

    UpgradeDeploymentRequest:
      type: object
      required: [image_version]
      properties:
        image_version: { type: string }
        run_migrations: { type: boolean, default: true }

    RestoreDeploymentRequest:
      type: object
      required: [to_timestamp]
      properties:
        to_timestamp: { type: string, format: date-time }

    StartImpersonationRequest:
      type: object
      required: [target_member_id, reason]
      properties:
        target_member_id: { type: string }
        reason:           { type: string, minLength: 1, maxLength: 256 }
        duration_seconds: { type: integer, minimum: 60, maximum: 900, default: 900 }

    StartImpersonationResponse:
      type: object
      required: [token, expires_at]
      properties:
        token:      { type: string, x-oapi-codegen-extra-tags: { sensitive: "true" } }
        expires_at: { type: string, format: date-time }

    DeploymentDomain:
      type: object
      required: [id, deployment_id, domain, status, verification_method, verification_record, created_at]
      properties:
        id:                  { type: string, pattern: "^dom_[0-9A-HJKMNP-TV-Z]{26}$" }
        deployment_id:       { type: string }
        domain:              { type: string, format: hostname }
        status:              { type: string, enum: [pending, verified, failed, removed] }
        verification_method: { type: string, enum: [dns_txt] }
        verification_record:
          type: object
          required: [record_name, record_type, record_value]
          properties:
            record_name:  { type: string }
            record_type:  { type: string, enum: [TXT] }
            record_value: { type: string }
        verified_at:         { type: [string, "null"], format: date-time }
        last_check_at:       { type: [string, "null"], format: date-time }
        created_at:          { type: string, format: date-time }

    AttachDomainRequest:
      type: object
      required: [domain]
      properties:
        domain: { type: string, format: hostname }

    DeploymentResponse:          { type: object, properties: { data: { $ref: "#/components/schemas/Deployment" } } }
    DeploymentListResponse:      { type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/Deployment" } }, pagination: { $ref: "#/components/schemas/Pagination" } } }
    DeploymentDomainResponse:    { type: object, properties: { data: { $ref: "#/components/schemas/DeploymentDomain" } } }
    DeploymentDomainListResponse:{ type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/DeploymentDomain" } } } }
    DeploymentRevisionListResponse: { type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/DeploymentRevision" } } } }
    DeploymentHealthResponse:       { type: object, properties: { data: { $ref: "#/components/schemas/DeploymentHealth" } } }
    OperatorListResponse:           { type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/Operator" } } } }
    ControlPlaneAuditEventListResponse: { type: object, properties: { data: { type: array, items: { $ref: "#/components/schemas/ControlPlaneAuditEvent" } } } }

    DeploymentRevision:
      type: object
      properties:
        id:            { type: string }
        deployment_id: { type: string }
        image_version: { type: string }
        applied_at:    { type: string, format: date-time }
        is_rolled_back: { type: boolean }

    DeploymentHealth:
      type: object
      properties:
        deployment_id: { type: string }
        overall:       { type: string, enum: [healthy, degraded, unhealthy, unknown] }
        components:
          type: array
          items:
            type: object
            properties:
              name:   { type: string }
              status: { type: string }
              detail: { type: string }
        checked_at:    { type: string, format: date-time }

    Operator:
      type: object
      properties:
        id:       { type: string, pattern: "^op_[0-9A-HJKMNP-TV-Z]{26}$" }
        email:    { type: string, x-oapi-codegen-extra-tags: { pii: "true" } }
        name:     { type: string, x-oapi-codegen-extra-tags: { pii: "true" } }
        is_active: { type: boolean }
        mfa_enabled: { type: boolean }
        ip_allowlist: { type: array, items: { type: string } }

    ControlPlaneAuditEvent:
      type: object
      properties:
        id:            { type: string }
        operator_id:   { type: string }
        action:        { type: string }
        deployment_id: { type: [string, "null"] }
        occurred_at:   { type: string, format: date-time }
        ip_address:    { type: string }
        request_id:    { type: string }
        metadata:      { type: object }
```

### 11.2 Control-plane migrations

`migrations/controlplane/000002_deployments.up.sql`:

```sql
CREATE TABLE deployment (
    id                  text PRIMARY KEY CHECK (id LIKE 'dep_%'),
    project_slug        text NOT NULL CHECK (project_slug ~ '^[a-z][a-z0-9-]*[a-z0-9]$' AND length(project_slug) BETWEEN 2 AND 32),
    environment_slug    text NOT NULL CHECK (environment_slug ~ '^[a-z][a-z0-9-]*[a-z0-9]$'),
    region              text,
    modules             text[] NOT NULL DEFAULT '{}',
    image_version       text NOT NULL,
    data_residency      text,
    primary_vhost       text NOT NULL,
    status              text NOT NULL DEFAULT 'provisioning'
                        CHECK (status IN ('provisioning','active','upgrading','failed','destroyed','restoring','purged')),
    db_name             text NOT NULL,
    db_app_role         text NOT NULL,
    namespace           text NOT NULL,
    bao_kid             text NOT NULL,
    metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_event_id       text,
    retain_until        timestamptz,
    row_seq             bigint NOT NULL DEFAULT 1,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_slug, environment_slug)
);
CREATE TRIGGER deployment_bump_row_seq BEFORE UPDATE ON deployment FOR EACH ROW EXECUTE FUNCTION bump_row_seq();

CREATE TABLE deployment_revision (
    id              text PRIMARY KEY,
    deployment_id   text NOT NULL REFERENCES deployment (id),
    image_version   text NOT NULL,
    applied_at      timestamptz NOT NULL DEFAULT now(),
    is_rolled_back  boolean NOT NULL DEFAULT false,
    applied_by      text NOT NULL
);

CREATE TABLE deployment_domain (
    id                    text PRIMARY KEY CHECK (id LIKE 'dom_%'),
    deployment_id         text NOT NULL REFERENCES deployment (id),
    domain                text NOT NULL,
    status                text NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','verified','failed','removed')),
    verification_method   text NOT NULL DEFAULT 'dns_txt',
    verification_record   jsonb NOT NULL,
    verified_at           timestamptz,
    last_check_at         timestamptz,
    last_check_error      text,
    cert_status           text NOT NULL DEFAULT 'pending',  -- Phase 12a fills in
    created_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (domain) WHERE status <> 'removed'
);

CREATE TABLE control_plane_audit_event (
    id            text PRIMARY KEY,
    operator_id   text NOT NULL,
    action        text NOT NULL,
    deployment_id text,
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    ip_address    text,
    request_id    text,
    metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash     bytea NOT NULL,
    row_hash      bytea NOT NULL,
    chain_sequence bigint NOT NULL UNIQUE
);

-- Operator inventory (extended in Phase 13 with MFA fields).
CREATE TABLE operator (
    id           text PRIMARY KEY CHECK (id LIKE 'op_%'),
    email_hash   bytea NOT NULL UNIQUE,
    email_ciphertext  bytea NOT NULL,
    email_wrapped_dek text  NOT NULL,
    email_nonce       bytea NOT NULL,
    email_kid         text  NOT NULL,
    email_key_version integer NOT NULL,
    is_active    boolean NOT NULL DEFAULT true,
    mfa_enabled  boolean NOT NULL DEFAULT false,    -- Phase 13
    ip_allowlist text[] NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now()
);
```

### 11.3 Module — `internal/controlplane/deployments/`

```text
internal/controlplane/deployments/
  domain.go
  ports.go              # DeploymentRepo, DomainRepo, RevisionRepo, Provisioner (interface), DNSResolver
  service.go            # CRUD + lifecycle (upgrade, rollback, restore, purge); calls Provisioner
  repo_pgx.go
  provisioner_local.go  # Phase 11 local-mode provisioner — creates DB, runs migrations, seeds tenant + API key
  provisioner_iface.go  # Interface declared here; real per-host adapter ships in Phase 12a-e
  domain_service.go     # Attach, verify, detach
  dns_resolver.go       # net.DefaultResolver wrapper
  handler.go
  errors.go
  service_test.go
  provisioner_local_test.go
  domain_test.go
  security_test.go
```

`provisioner_iface.go`:

```go
package deployments

import "context"

// Provisioner is the seam between the control plane and the host. Phase 11
// ships an implementation that only writes to Postgres (local mode); Phases
// 12a-e add adapters that compose the full host-touching sequence.
type Provisioner interface {
    Provision(ctx context.Context, d *Deployment) (BootstrapResult, error)
    Upgrade(ctx context.Context, d *Deployment, newImage string, runMigrations bool) error
    Rollback(ctx context.Context, d *Deployment, previousImage string) error
    Restart(ctx context.Context, d *Deployment) error
    Restore(ctx context.Context, oldDep *Deployment, toTimestamp time.Time) (*Deployment, error)
    Destroy(ctx context.Context, d *Deployment) error      // soft destroy; reclaim later
    Purge(ctx context.Context, d *Deployment) error        // hard delete

    // BYOD
    AttachDomain(ctx context.Context, d *Deployment, dd *DeploymentDomain) error
    VerifyDomain(ctx context.Context, d *Deployment, dd *DeploymentDomain) (bool, error)
    DetachDomain(ctx context.Context, d *Deployment, dd *DeploymentDomain) error
}

type BootstrapResult struct {
    BootstrapTenantID  string
    BootstrapAPIKeyID  string
    BootstrapAPIKeySecret string   // returned once
}
```

`provisioner_local.go`:

```go
package deployments

import (
    "context"
    "fmt"

    "github.com/jackc/pgx/v5/pgxpool"
    "github.com/golang-migrate/migrate/v4"
    _ "github.com/golang-migrate/migrate/v4/database/postgres"
    "github.com/golang-migrate/migrate/v4/source/iofs"

    dpmigrations "github.com/omarss/saas/migrations/dataplane"
    "github.com/omarss/saas/internal/platform/id"
)

type LocalProvisioner struct {
    hostPool *pgxpool.Pool       // connection to host Postgres as superuser-or-equivalent
    appDSN   func(dep *Deployment) string
}

func (p *LocalProvisioner) Provision(ctx context.Context, d *Deployment) (BootstrapResult, error) {
    // 1. CREATE DATABASE (idempotent — check pg_database first; CREATE DB is not transactional).
    var exists bool
    if err := p.hostPool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)`, d.DBName).Scan(&exists); err != nil {
        return BootstrapResult{}, err
    }
    if !exists {
        if _, err := p.hostPool.Exec(ctx, fmt.Sprintf(`CREATE DATABASE %s`, sanitizeDBName(d.DBName))); err != nil {
            return BootstrapResult{}, fmt.Errorf("create db: %w", err)
        }
    }

    // 2. Apply data-plane migrations.
    src, _ := iofs.New(dpmigrations.FS, "dataplane")
    m, err := migrate.NewWithSourceInstance("iofs", src, p.appDSN(d))
    if err != nil { return BootstrapResult{}, fmt.Errorf("migrate new: %w", err) }
    if err := m.Up(); err != nil && err != migrate.ErrNoChange {
        return BootstrapResult{}, fmt.Errorf("migrate up: %w", err)
    }

    // 3. Seed bootstrap tenant + admin user + member + api key.
    //    Uses the data-plane DB connection via the platform pgx pool.
    seed, err := p.seed(ctx, d)
    if err != nil { return BootstrapResult{}, fmt.Errorf("seed bootstrap: %w", err) }

    // Local mode skips: nginx, k3s, OpenBao key creation, certbot. Phases 12a-e
    // add those.
    return seed, nil
}

func (p *LocalProvisioner) seed(ctx context.Context, d *Deployment) (BootstrapResult, error) {
    // Connect to the data-plane DB as the platform; create tenant_bootstrap_<suffix>,
    // user, member, role assignment (tenant_admin), API key.
    // The API key secret is generated here and returned ONCE (caught by the handler).
    // Implementation mirrors Phases 2 + 5 + 7 + 8 + 9 service.Create calls, but
    // bypasses the chi handler stack — local provisioner uses the same repo
    // layer with a synthetic operator principal.
    // ...
    return BootstrapResult{
        BootstrapTenantID:     "tenant_bootstrap_" + d.ID[4:14],   // deterministic
        BootstrapAPIKeyID:     id.New(id.PrefixAPIKey),
        BootstrapAPIKeySecret: "<one-time-secret>",
    }, nil
}

// AttachDomain, VerifyDomain, DetachDomain in local mode just update the
// control-plane DB. Phase 12a wires real nginx + certbot.
func (p *LocalProvisioner) AttachDomain(ctx context.Context, d *Deployment, dd *DeploymentDomain) error {
    dd.VerificationRecord = makeDNSTXTRecord(d.ID, dd.Domain)
    return nil
}

func (p *LocalProvisioner) VerifyDomain(ctx context.Context, d *Deployment, dd *DeploymentDomain) (bool, error) {
    // Local mode: query DNS via net.LookupTXT and check the expected value.
    // Phase 12a additionally configures nginx for the domain and runs certbot.
    txts, err := p.resolver.LookupTXT(ctx, dd.VerificationRecord.RecordName)
    if err != nil { return false, err }
    for _, v := range txts {
        if v == dd.VerificationRecord.RecordValue { return true, nil }
    }
    return false, nil
}
```

### 11.4 Deployment service — orchestration

`service.go`:

```go
func (s *Service) Create(ctx context.Context, req CreateRequest) (Deployment, BootstrapResult, error) {
    // Operator auth assumed (middleware in Phase 13). For Phase 11 we accept any
    // operator-typed principal.
    if err := s.requireOperator(ctx); err != nil { return Deployment{}, BootstrapResult{}, err }

    // Slug uniqueness checked via UNIQUE constraint.
    d := Deployment{
        ID:               id.New(id.PrefixDeployment),
        ProjectSlug:      req.ProjectSlug,
        EnvironmentSlug:  req.EnvironmentSlug,
        Region:           req.Region,
        Modules:          req.Modules,
        ImageVersion:     req.ImageVersion,
        DataResidency:    req.DataResidency,
        PrimaryVhost:     fmt.Sprintf("%s.%s.saas.omarss.net", req.EnvironmentSlug, req.ProjectSlug),
        Status:           "provisioning",
        DBName:           fmt.Sprintf("saas_%s_%s", req.ProjectSlug, req.EnvironmentSlug),
        DBAppRole:        fmt.Sprintf("saas_%s_%s_app", req.ProjectSlug, req.EnvironmentSlug),
        Namespace:        fmt.Sprintf("saas-%s-%s", req.ProjectSlug, req.EnvironmentSlug),
        BaoKid:           id.New(id.PrefixDeployment),    // same as ID in Phase 11; Phase 12d may diverge
        Metadata:         req.Metadata,
        CreatedAt:        time.Now(),
        UpdatedAt:        time.Now(),
    }
    d, err := s.repo.Create(ctx, d)
    if err != nil { return Deployment{}, BootstrapResult{}, err }

    boot, err := s.provisioner.Provision(ctx, &d)
    if err != nil {
        // Mark failed; the destroy reconciler picks it up.
        _ = s.repo.UpdateStatus(ctx, d.ID, "failed")
        return d, BootstrapResult{}, err
    }
    _ = s.repo.UpdateStatus(ctx, d.ID, "active")
    _ = s.events.Publish(ctx, "deployment.provisioned", "", map[string]any{
        "deployment_id": d.ID, "project_slug": d.ProjectSlug, "environment_slug": d.EnvironmentSlug,
    })
    return d, boot, nil
}
```

Similar `Upgrade`, `Rollback`, `Restart`, `Restore`, `Delete`, `Purge` methods. Each emits the relevant `deployment.*` outbox event.

### 11.5 Domain service — BYOD

`domain_service.go`:

```go
func (s *DomainService) Attach(ctx context.Context, deploymentID, domain string) (*DeploymentDomain, error) {
    // Validate domain shape (hostname; not in the platform's own zone).
    if strings.HasSuffix(domain, ".saas.omarss.net") {
        return nil, ErrCustomDomainInPlatformZone
    }
    // Limit (default 5 per Deployment).
    count, _ := s.repo.CountActive(ctx, deploymentID)
    if count >= s.maxPerDeployment { return nil, ErrDomainLimitReached }

    d, err := s.depRepo.Get(ctx, deploymentID)
    if err != nil { return nil, err }
    dd := &DeploymentDomain{
        ID:                id.New(id.PrefixDomain),
        DeploymentID:      deploymentID,
        Domain:            domain,
        Status:            "pending",
        VerificationMethod: "dns_txt",
        VerificationRecord: makeDNSTXTRecord(deploymentID, domain),
        CreatedAt:          time.Now(),
    }
    if err := s.provisioner.AttachDomain(ctx, &d, dd); err != nil { return nil, err }
    return s.repo.Create(ctx, dd)
}

func (s *DomainService) Verify(ctx context.Context, deploymentID, domainID string) (*DeploymentDomain, error) {
    d, _ := s.depRepo.Get(ctx, deploymentID)
    dd, err := s.repo.Get(ctx, deploymentID, domainID); if err != nil { return nil, err }
    ok, err := s.provisioner.VerifyDomain(ctx, &d, dd)
    if err != nil {
        dd.LastCheckError = err.Error()
        _ = s.repo.UpdateCheck(ctx, dd.ID, "failed", time.Now(), dd.LastCheckError)
        return dd, nil
    }
    if ok {
        dd.Status = "verified"; dd.VerifiedAt = ptrTime(time.Now())
    }
    return s.repo.UpdateCheck(ctx, dd.ID, dd.Status, time.Now(), "")
}

func makeDNSTXTRecord(deploymentID, domain string) VerificationRecord {
    // record_name = _saas-verify.<domain>
    // record_value = "saas-verify=<HMAC(domain, deployment_id, secret)>"
    h := hmac.New(sha256.New, []byte(deploymentID))   // a deployment-bound HMAC
    h.Write([]byte(domain))
    token := hex.EncodeToString(h.Sum(nil))
    return VerificationRecord{
        RecordName:  "_saas-verify." + domain,
        RecordType:  "TXT",
        RecordValue: "saas-verify=" + token,
    }
}
```

### 11.6 Local provisioner — bootstrap tenant + API key seed

Reuses the data-plane services via a synthesized operator principal. The seed transaction:

1. Open data-plane pgx pool against the new DB.
2. Create a tenant via `tenancy.Service.Create(slug="bootstrap", name="Bootstrap")`.
3. Create a user via `identity.Service.Create(email="ops+<dep_id>@omarss.net", name="Operator")`.
4. Create a member in the default org via `organizations.Service.AutoMembership(user, org)`.
5. Assign `role_tenant_admin` via `authorization.Service.AssignMemberRole(member, role_tenant_admin)`.
6. Create an API key with `scopes=["*"]` via `apikeys.Service.Create(name="bootstrap")`.
7. Return the API key secret + tenant id + member id.

Step 6's `scopes=["*"]` is special: Phase 9's validator pattern forbids `*` in scopes. The bootstrap path bypasses validation by going through the repo directly. This is the ONE legitimate `*`-scope exception in the platform; tests pin that it can't be set via the public API.

### 11.7 Control-plane main.go wiring

`cmd/controlplane/main.go` already exists (Phase 1). Extend:

```go
func run() error {
    // ... existing setup ...

    // Operator JWT verifier: Phase 11 stub; Phase 13 replaces with operators-realm.
    opVerifier, _ := auth.NewJWTVerifier(ctx, opJWKS, opIssuer, "saas-control")

    // Control-plane Postgres pool (separate DB from data plane; no tenant binding).
    cpPool, _ := pgx.NewPool(ctx, pgx.Options{DSN: os.Getenv("CONTROLPLANE_DATABASE_URL"), SkipTenantBinding: true})

    // Provisioner (local-mode in Phase 11).
    localProv := &deployments.LocalProvisioner{HostPool: cpPool, AppDSN: dpDSNForDeployment}
    depSvc := deployments.NewService(deploymentRepo, localProv, controlPlaneEvents)

    r := chi.NewRouter()
    r.Use(middleware.RequestID, middleware.RealIP, middleware.Logger, middleware.Recoverer)
    r.Use(otelhttp.NewMiddleware("saas-controlplane"))
    r.Use(opVerifier.Middleware)
    spec, _ := controlplaneapi.GetSwagger()
    spec.Servers = nil
    r.Use(oapimw.OapiRequestValidatorWithOptions(spec, &oapimw.Options{Options: openapi3filter.Options{AuthenticationFunc: opAuthFunc}}))
    r.Use(idempotency.Middleware(cpIdempStore))
    controlplaneapi.HandlerFromMux(controlplaneapi.NewStrictHandler(depHandler, nil), r)

    // ...
}
```

### 11.8 saasctl — full deployment surface

```text
saasctl deployment list
saasctl deployment create --project acme --environment prod --image v0.3.1 [--region ksa-riyadh] [--modules identity,tenancy,...]
saasctl deployment get <dep_id>
saasctl deployment upgrade <dep_id> --image v0.4.0 [--no-migrations]
saasctl deployment rollback <dep_id>
saasctl deployment restart <dep_id>
saasctl deployment restore <dep_id> --to-timestamp '2026-05-20T10:00:00Z'
saasctl deployment purge <dep_id>
saasctl deployment delete <dep_id> [--retain-days 30]
saasctl deployment health <dep_id>
saasctl deployment logs <dep_id> [--since ...] [--filter ...] [--tail 100]
saasctl deployment revisions <dep_id>

saasctl domain attach <dep_id> --domain api.acme.com
saasctl domain list <dep_id>
saasctl domain verify <dep_id> --domain-id dom_...
saasctl domain detach <dep_id> --domain-id dom_...
```

`saasctl deployment create` prints the bootstrap API key:

```text
Deployment created: dep_...
Primary vhost:      prod.acme.saas.omarss.net
Bootstrap tenant:   tenant_bootstrap_...
Bootstrap API key:  apik_...
Bootstrap secret:   live_ax9_...

IMPORTANT: copy the bootstrap secret NOW. It will not be shown again.
```

### 11.9 ADR 015 — BYOD

`docs/adr/015-byod-custom-domains.md`:

```markdown
# ADR 015 — Bring-Your-Own-Domain: DNS TXT verification + multi-server_name + per-domain cert

## Status
Accepted (2026-05-24).

## Context
Per scope-change 2026-05-24, each Deployment may attach N custom domains.
The control plane verifies ownership before nginx + certbot are touched.
Two verification approaches:

(1) DNS TXT record at `_saas-verify.<domain>` containing an HMAC-bound token.
(2) HTTP-01 challenge — operator points the domain at the platform first,
    then certbot does the standard ACME http-01 dance.

(2) requires the domain to point at the platform's IP before we can prove
ownership. Many BYOD orgs can't do that in one step (DNS TTL + cert + nginx
must all flip together). (1) decouples ownership proof from cutover.

## Decision
1. Verification: DNS TXT. Record name `_saas-verify.<domain>`; value
   `saas-verify=<HMAC(domain, deployment_id, deployment-bound-secret)>`.
2. Cert issuance (Phase 12a): once verified, certbot HTTP-01 against the
   actual domain (now pointed at the platform). nginx vhost adds the
   custom domain to its `server_name` directive (multi-server_name).
3. Per-Deployment domain limit: 5 (configurable via metadata).
4. Cert is per-domain (one cert per `server_name` entry). ADR 008
   evaluates wildcard vs per-domain — wildcard is for `*.saas.omarss.net`
   only; BYOD always uses per-domain.

## Consequences
+ Operator can verify ownership BEFORE the cutover; no race.
+ Multiple BYOD domains map to one Deployment's data plane (one vhost,
  multiple server_names).
- Certbot's LE rate limit (50 certs/registered-domain/week) doesn't apply
  to BYOD because each custom domain is a different registered domain.
- BYOD customers must understand DNS basics. Documented in the recipe
  (Phase 15).
- The HMAC secret per Deployment must be stable across control-plane
  restarts. Stored in OpenBao KV at `secret/data/<dep_id>/byod_hmac_key`
  (Phase 12d creates).
```

### 11.10 §17.3 matrix — operator-only

Limited matrix because tenant_id is not in scope:

| Test | Assert |
|---|---|
| Deployment list as operator | 200 |
| Deployment list as data-plane user (with data-plane JWT) | 401 (aud mismatch) |
| Create deployment with duplicate slug | 409 |
| Create deployment with malformed slug | 422 |
| Attach BYOD with platform-zone domain | 422 |
| Attach BYOD beyond limit | 422 |
| Verify BYOD without DNS record | 200 with status=failed |
| Verify BYOD with correct DNS record | 200 with status=verified |
| Delete deployment with retain_days=0 | 204 + status=destroyed; retain_until=null |
| Purge before destroy | 422 (can only purge destroyed) |
| Upgrade non-existent deployment | 404 |

### 11.11 Audit emission (control-plane chain)

Every operator action emits a row to `control_plane_audit_event`. The hash chain is the same JCS scheme as Phase 10, with `tenant_id` replaced by `'control-plane'` as the single chain identifier. Implementation reuses `internal/dataplane/audit/jcs.go` (which is moved to `internal/platform/audit/jcs.go` in this phase since both planes use it).

Phase 10 audit subscriber doesn't run in the control plane (different DB); a separate control-plane audit subscriber lives in `internal/controlplane/audit/` and listens to control-plane outbox.

### 11.12 Tests

`provisioner_local_test.go`:

- Provision creates a new DB; second call is no-op (idempotent).
- Provision applies migrations.
- Provision seeds tenant + member + role + API key.
- Provision-with-existing-slug returns DUPLICATE error (caught by service).
- Partial failure (e.g. migrate fails mid-way) leaves status=failed; destroy reconciler can re-run.

`domain_test.go`:

- Attach domain in platform zone rejected.
- Attach over limit rejected.
- Verify with no DNS record returns failed.
- Verify with correct TXT returns verified.
- Re-verify already-verified is idempotent.

`service_test.go`:

- Upgrade flow flips status: active → upgrading → active.
- Rollback flips back; emits rollback event.
- Restore creates a new dep_id; original unchanged.
- Delete with retain_days=30 sets retain_until.
- Purge before destroy returns 422.

### 11.13 Commits

```bash
git add openapi/control-plane.yaml openapi/problems/
git commit -m "add control plane deployments and byod endpoints"

git add migrations/controlplane/000002_deployments.up.sql internal/controlplane/db/queries/deployments.sql
git commit -m "add control plane deployment tables"

git add internal/controlplane/deployments/
git commit -m "implement control plane deployments module"

git add internal/controlplane/audit/ internal/platform/audit/    # JCS promotion
git commit -m "promote jcs to platform and add cp audit"

git add cmd/controlplane/main.go
git commit -m "wire control plane chi router and provisioner"

git add cmd/saasctl/
git commit -m "saasctl full deployment and domain coverage"

git add docs/adr/015-byod-custom-domains.md
git commit -m "add byod adr"
```

---

## Verification checklist

```bash
# 1. Migrations apply (both planes).
$ make migrate
$ psql -c "\d deployment" -c "\d deployment_domain" -c "\d operator" -c "\d control_plane_audit_event"

# 2. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 3. Operator JWT (Phase 11 stub).
$ TOK=$(curl -s -X POST http://localhost:8081/realms/operators/protocol/openid-connect/token \
        -d grant_type=client_credentials -u saas-controlplane:dev-cp-secret | jq -r .access_token)

# 4. Create a deployment.
$ curl -s -X POST http://localhost:8080/control/v1/deployments \
    -H "Authorization: Bearer $TOK" -H "Idempotency-Key: idem_..." -H "Content-Type: application/json" \
    -d '{"project_slug":"acme","environment_slug":"prod","image_version":"v0.3.1"}' | jq
# Expected: 201, deployment data, bootstrap_api_key.secret

# 5. The Postgres database exists.
$ psql -c "SELECT 1 FROM pg_database WHERE datname = 'saas_acme_prod';"
# Expected: 1 row

# 6. Migrations applied to that DB.
$ psql -d saas_acme_prod -c "\dt"
# Expected: tenant, platform_user, member, ... — all data-plane tables

# 7. Bootstrap tenant exists.
$ psql -d saas_acme_prod -c "SELECT id, slug, name FROM tenant;"
# Expected: 1 row, slug='bootstrap'

# 8. Idempotent re-create.
$ curl -X POST http://localhost:8080/control/v1/deployments ... -d '{"project_slug":"acme","environment_slug":"prod","image_version":"v0.3.1"}'
# Expected: 201 with SAME deployment_id (Idempotency-Key replay)

# 9. BYOD attach + verify (DNS will fail in local dev unless you have a test record).
$ curl -X POST http://localhost:8080/control/v1/deployments/<id>/domains ... -d '{"domain":"api.acme.test"}'
$ curl -X POST http://localhost:8080/control/v1/deployments/<id>/domains/<dom_id>/verify ...
# Expected: 200 with status=failed (no DNS record present)

# 10. saasctl coverage.
$ ./bin/saasctl deployment list
$ ./bin/saasctl deployment create --project ace --environment dev --image v0.3.1
$ ./bin/saasctl deployment get dep_...
$ ./bin/saasctl domain attach dep_... --domain api.example.com

# 11. Control-plane audit row emitted.
$ psql -c "SELECT action, deployment_id FROM control_plane_audit_event ORDER BY chain_sequence DESC LIMIT 5;"
# Expected: deployment.provisioned, etc.

# 12. §17.3 matrix.
$ go test -run TestDeployments_AuthZ -v ./internal/controlplane/deployments/...
```

---

## Anti-pattern guards

- **NEVER** write to `/etc/nginx/...`, `kubectl apply`, `sudo certbot`, or any non-Postgres host state in this phase. The LocalProvisioner is by design Postgres-only; Phase 12a-e adds the other adapters with CHECKPOINTs in between.
- **NEVER** mint a control-plane JWT with data-plane audience. The verifier sets `expectedAudience = "saas-control"`; bypassing is a security incident.
- **NEVER** look up `deployment_id` from a request body. It's always in the URL path.
- **NEVER** allow `project_slug` or `environment_slug` to contain `/` or upper-case. The CHECK enforces; the pattern in OpenAPI enforces.
- **NEVER** allow a BYOD domain to be a subdomain of `*.saas.omarss.net`. The attach endpoint rejects.
- **NEVER** issue real certs from this phase. Phase 12a does that, AFTER CHECKPOINT 4 review.
- **NEVER** allow the local-mode provisioner code path to reach prod. The provisioner is selected at startup via env `SAAS_PROVISIONER=local|real`; prod must use `real` (Phase 12e configures).
- **NEVER** seed a bootstrap API key with `scopes=["*"]` via the public API. The bypass is repo-level only and exercised solely by the LocalProvisioner.

---

## Open questions

1. **HMAC secret for BYOD verification token.** Default: per-Deployment, generated at provision time, stored in OpenBao KV at `secret/data/<dep_id>/byod_hmac_key`. Phase 11 uses an in-memory placeholder; Phase 12d creates the KV entry. Confirm.
2. **Domain verification re-check cadence.** Default: only on `POST /verify`. Alternative: a daily ticker re-checks unverified domains. Out of MVP; flag for v1.
3. **Operator email storage.** Phase 11 introduces an `operator` table with envelope-encrypted email + HMAC lookup. Phase 13 adds MFA fields. Confirm shape.
4. **Bootstrap admin email.** Default: `ops+<dep_id>@omarss.net`. Configurable per deployment via metadata. Confirm.
5. **Modules array — what does it mean?** §8.0 lists `modules: ["identity","tenancy","organizations","authorization","apikeys","audit"]`. In MVP the data-plane binary ships ALL modules; the array is metadata for future per-module-enable. Default: store the array but always boot all modules.

---

## Phase 11 — Definition of done

- [ ] OpenAPI updated; `make openapi-check` green
- [ ] Migrations applied; `deployment`, `deployment_revision`, `deployment_domain`, `operator`, `control_plane_audit_event` exist
- [ ] `internal/controlplane/deployments/` complete with handler, service, repos, local provisioner, domain service, tests
- [ ] `LocalProvisioner` implements the full `Provisioner` interface (Provision/Upgrade/Rollback/Restart/Restore/Destroy/Purge + AttachDomain/VerifyDomain/DetachDomain) — Postgres-only, no host writes
- [ ] BYOD: attach + verify + detach functional in local mode; DNS TXT record returned by attach; verify polls actual DNS
- [ ] Control-plane main.go wires operator JWT verifier (stub realm) + chi router + idempotency + control-plane audit subscriber
- [ ] `saasctl deployment` + `saasctl domain` subtrees complete and tested
- [ ] §17.4 provisioning happy-path test (local-mode) passes
- [ ] §17.3 control-plane authorization matrix passes
- [ ] Bootstrap API key returned ONCE via the create response; not retrievable via subsequent reads
- [ ] Control-plane audit chain works (Phase 10 JCS reused)
- [ ] ADR 015 committed
- [ ] All Phase 2-10 tests still green
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 4 — sudoers + certbot + nginx layout + k3s templates approved

> CHECKPOINT 4 gates Phase 12a starting. Phase 11 ships ZERO host writes; Phase 12 sub-phases will write to /etc/nginx, k3s API, host Postgres, OpenBao. This checkpoint forces the user to review the templates that those phases will use.

### What was done (Phase 11)
- openapi/control-plane.yaml: all /control/v1/deployments/* + /domains/* + /audit-events + /operators endpoints
- migrations/controlplane/000002_deployments.up.sql
- internal/controlplane/deployments/{domain,ports,service,repo_pgx,provisioner_local,provisioner_iface,domain_service,handler,errors}.go
- internal/controlplane/audit/ + internal/platform/audit/jcs.go (promoted)
- cmd/controlplane/main.go: wired router, provisioner, audit subscriber
- cmd/saasctl: 11 deployment subcommands + 4 domain subcommands
- docs/adr/015-byod-custom-domains.md

### What to verify BEFORE proceeding to Phase 12a
The user must review the following files and approve:

```bash
# 1. The sudoers stub that Phase 12a will install (lives in deploy/nginx/saas-controlplane.sudoers).
$ cat deploy/nginx/saas-controlplane.sudoers
# Expected (verbatim from 01-foundations.md §10):
# Cmnd_Alias SAAS_NGINX = /usr/sbin/nginx -t, /usr/sbin/nginx -s reload, /usr/bin/systemctl reload nginx
# Cmnd_Alias SAAS_CERTBOT = /usr/bin/certbot --nginx -d *.saas.omarss.net --non-interactive --agree-tos -m *
# saas ALL=(root) NOPASSWD: SAAS_NGINX, SAAS_CERTBOT

# 2. The nginx vhost template Phase 12a will render.
$ cat deploy/nginx/vhost.conf.tmpl
# Expected: pre-certbot listen 80 block, server_name {{ .PrimaryVhost }} {{ range .CustomDomains }} {{ . }} {{ end }};
# proxy_pass http://127.0.0.1:{{ .NodePort }}; include /etc/nginx/snippets/saas-security-headers.conf;

# 3. The k3s manifest base + overlay template Phase 12b will use.
$ ls deploy/k3s/base/ deploy/k3s/overlays/template/
# Expected: namespace.yaml, deployment.yaml, service.yaml, networkpolicy-default-deny.yaml,
# networkpolicy-allow-ingress.yaml, networkpolicy-allow-egress.yaml, kustomization.yaml
$ cat deploy/k3s/base/networkpolicy-default-deny.yaml
# Expected: ingress + egress denied by default

# 4. The Postgres bootstrap script Phase 12c will use.
$ cat deploy/postgres/per-deployment.sh
# Expected: CREATE DATABASE; CREATE ROLE; GRANT CONNECT; ALTER ROLE SET search_path; FORCE RLS

# 5. The OpenBao per-deployment policy template Phase 12d will upload.
$ cat deploy/openbao/policies/deployment.hcl.tmpl

# 6. The control-plane → host trust assumptions documented.
$ cat docs/runbooks/control-plane-host-trust.md
# Expected: documents that the saas user can sudo nginx + certbot; control plane runs as that user;
# the k3s ServiceAccount it uses; the OpenBao AppRole creds path.
```

The user MUST approve each of the six items above before Phase 12a starts.

### What approval means
By proceeding past CHECKPOINT 4, you accept:
- Phase 12a will install the sudoers file at `/etc/sudoers.d/saas-controlplane` (mode 0440, validated with visudo -cf).
- Phase 12a will write per-vhost files under `/etc/nginx/sites-available/saas-*.conf` and reload nginx.
- Phase 12a will run certbot for `*.saas.omarss.net` subdomains (HTTP-01) and BYOD custom domains (HTTP-01) without operator intervention.
- Phase 12b will create per-Deployment k3s namespaces with default-deny NetworkPolicy. Cross-namespace traffic between deployments will be physically blocked.
- Phase 12c will create per-Deployment Postgres databases + roles with FORCE RLS, on the host Postgres cluster.
- Phase 12d will create per-Deployment OpenBao transit keys + KV paths + policies + audit hooks.
- Phase 12e will wire the §6.2 13-step provisioning sequence end-to-end with a destroy reconciler.
- Each of these phases ends in its own CHECKPOINT (5, 6, 7, 8, 9) so you can inspect the first real artifact before any subsequent provision.

### Rollback if rejected
```bash
# Phase 11 wrote no host state. Reverting the commits removes the control-plane API surface
# and migrations; the data plane keeps working as-is.
git revert <hashes for the 7 phase-11 commits>
psql -c "DROP DATABASE saas_acme_prod;"    # any local-mode databases created during testing
psql -c "DROP TABLE deployment, deployment_revision, deployment_domain, operator, control_plane_audit_event;"
```

---

End of Phase 11. Next: `13a-host-nginx.md`.
