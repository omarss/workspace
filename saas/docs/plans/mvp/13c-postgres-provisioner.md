# Phase 12c — Per-Deployment Postgres Provisioner (DB + Role + RLS + Migrations)

> **Goal**: Implement the real `PostgresAdapter` for the composite Provisioner. For each Deployment: create database `saas_<project>_<env>`, app role `saas_<project>_<env>_app` with a generated random password stored in OpenBao KV, GRANT CONNECT + USAGE, set `ALTER ROLE ... SET search_path = app, public`, run golang-migrate against the new DB, ensure every tenant-bound table has FORCE ROW LEVEL SECURITY, and revoke UPDATE/DELETE on `audit_event` from the role. Stop at CHECKPOINT 7 where the user verifies `\d` + `psql -l` + role grants on the first real per-Deployment DB.
>
> **Why now**: Phase 12b created the k3s workload — but the workload's `DATAPLANE_DATABASE_URL` env var still points at the dev host's `saas` superuser DB. Phase 12c replaces this with a per-Deployment DB + least-priv role. Phase 12d (OpenBao) and Phase 12e (full sequence) follow. Without per-Deployment Postgres, layer 4 of tenant isolation collapses (multiple Deployments sharing one DB defeats RLS at the physical layer).
>
> **What this phase does NOT do**: No dynamic role generation via OpenBao's database secrets engine (deferred per §18.7 — opt-in for compliance customers). No backups (Phase 12e wires WAL archiving). No restore from PITR (Phase 12e). No purge — soft destroy keeps the DB around until purge.
>
> **Maps to AGENTS.md**: §4.1 (Postgres), §6.1 (per-Deployment DB), §6.2 steps 4-6 (database + role + migrations + seed), §6.4 (destroy), §18.1 layer 3 (RLS) + layer 4 (physical), §18.7 (database secrets engine opt-in). `01-foundations.md` §4 (sqlc + pgx + golang-migrate).
>
> **Estimated subagent sessions**: 2 (one for adapter + role management; one for migration runner + RLS enforcement + tests).

---

## Pre-flight

1. AGENTS.md §4.1, §6.1, §6.2, §6.4, §18.1, §18.7.
2. `01-foundations.md` §4 (sqlc + pgx + golang-migrate).
3. CHECKPOINT 6 approved.
4. Confirm host Postgres has a `postgres` superuser-equivalent that the control-plane process can use (read from `CONTROLPLANE_DATABASE_URL` for control-plane state; create a separate connection string for the provisioner's superuser ops loaded from OpenBao KV at `secret/data/platform/postgres_admin`).
5. Confirm the dev host's Postgres allows `CREATE DATABASE` (peer or md5 auth; not just `local trust`).

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| DB naming | `saas_<project_slug>_<environment_slug>` (lowercase, underscored) | Hash-based (refused — operator-unfriendly) |
| Role naming | `saas_<project_slug>_<environment_slug>_app` | Per-version role (refused — connection churn) |
| Role password | 32-byte URL-safe random; stored in OpenBao KV at `secret/data/<dep_id>/postgres/app_password` | Static (refused — leaks); OpenBao dynamic secrets engine (deferred) |
| Schema | `app` (set as default `search_path = app, public` on the role) | `public` (refused — pollutes; harder to scope grants) |
| RLS enforcement | `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` (so even table owner is subject to policy) per tenant-bound table; CHECK via the migration | Optional (refused — defense in depth) |
| Audit grants | `GRANT SELECT, INSERT ON audit_event TO <role>; REVOKE UPDATE, DELETE FROM <role>` | INSERT-only via trigger function (refused — slower; same effect) |
| Idempotency | `IF NOT EXISTS` for CREATE TABLE; SELECT pg_database before CREATE DATABASE (no IF NOT EXISTS for that); INSERT … ON CONFLICT for seed | Drop+recreate (refused — destructive) |
| Connection strategy | Two pools: an "admin" pool to the platform's `postgres` DB for provisioning ops; a per-Deployment "app" pool reused only after the role exists | One mega-pool with role-switching (refused — error-prone) |
| Migration source | `embed.FS` from `migrations/dataplane/*.up.sql` (same as Phase 1's migrate runner) | External CLI (refused — extra dep) |
| RLS test enforcement | At provision time, run a smoke query that asserts `current_setting('row_security') = 'on'` and that a `SET LOCAL app.current_tenant_id = 'x'` change actually filters rows | Skip (refused — quiet regressions) |

If the user disagrees, stop.

---

## Tasks

### 12c.1 Adapter — `internal/controlplane/provision/postgres/`

```text
internal/controlplane/provision/postgres/
  adapter.go        # PostgresAdapter
  database.go       # CREATE DATABASE idempotent
  role.go           # CREATE ROLE + password generation
  grants.go         # schema + table grants + REVOKE update/delete on audit_event
  migrate.go        # golang-migrate runner against the new DB
  seed.go           # bootstrap tenant + member + role + API key (moved from Phase 11 LocalProvisioner)
  destroy.go        # DROP DATABASE + DROP ROLE on purge
  adapter_test.go
  rls_test.go       # RLS smoke against a real DB
```

`adapter.go`:

```go
package postgres

import (
    "context"
    "fmt"

    "github.com/jackc/pgx/v5/pgxpool"

    "github.com/omarss/saas/internal/platform/crypto/envelope"
)

type Adapter struct {
    Admin  *pgxpool.Pool           // pool to the platform's superuser DB
    Bao    *envelope.Client        // for KV password storage
}

func New(adminPool *pgxpool.Pool, bao *envelope.Client) *Adapter {
    return &Adapter{Admin: adminPool, Bao: bao}
}

// Provision is steps 4-6 of §6.2.
func (a *Adapter) Provision(ctx context.Context, dep *Deployment) error {
    if err := a.ensureDatabase(ctx, dep.DBName); err != nil { return err }
    pwd, err := a.ensureRole(ctx, dep)
    if err != nil { return err }
    if err := a.grantToRole(ctx, dep); err != nil { return err }
    if err := a.applyMigrations(ctx, dep, pwd); err != nil { return err }
    if err := a.enforceRLSAndAuditGrants(ctx, dep, pwd); err != nil { return err }
    return a.smokeRLS(ctx, dep, pwd)
}

// Destroy drops the DB + role on purge (NOT on destroy — that retains).
func (a *Adapter) Destroy(ctx context.Context, dep *Deployment) error {
    return nil  // soft destroy: keep DB; only mark in DB
}

func (a *Adapter) Purge(ctx context.Context, dep *Deployment) error {
    if _, err := a.Admin.Exec(ctx, fmt.Sprintf(`DROP DATABASE IF EXISTS %s`, sanitize(dep.DBName))); err != nil {
        return err
    }
    if _, err := a.Admin.Exec(ctx, fmt.Sprintf(`DROP ROLE IF EXISTS %s`, sanitize(dep.DBAppRole))); err != nil {
        return err
    }
    return a.Bao.KVDelete(ctx, dep.ID, "postgres/app_password")
}
```

### 12c.2 Database creation

`database.go`:

```go
func (a *Adapter) ensureDatabase(ctx context.Context, name string) error {
    var exists bool
    if err := a.Admin.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)`, name).Scan(&exists); err != nil {
        return fmt.Errorf("check db: %w", err)
    }
    if exists { return nil }
    // CREATE DATABASE is not allowed inside a transaction; must use a fresh conn.
    conn, err := a.Admin.Acquire(ctx); if err != nil { return err }
    defer conn.Release()
    _, err = conn.Conn().Exec(ctx, fmt.Sprintf(`CREATE DATABASE %s ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0`, sanitize(name)))
    return err
}

func sanitize(name string) string {
    // Validate against a strict allowlist: lowercase letters, digits, underscore, length ≤ 63.
    // Panic if invalid — this is internal naming, not user input.
    for _, r := range name {
        if !(r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '_') {
            panic("postgres: invalid identifier: " + name)
        }
    }
    if len(name) > 63 { panic("postgres: identifier too long") }
    return name
}
```

### 12c.3 Role creation + password

`role.go`:

```go
import (
    "crypto/rand"
    "encoding/base64"
)

func (a *Adapter) ensureRole(ctx context.Context, dep *Deployment) (password string, err error) {
    // Check OpenBao KV first; reuse existing password on re-provision.
    if data, err := a.Bao.KVGet(ctx, dep.ID, "postgres/app_password"); err == nil {
        if p, ok := data["password"].(string); ok && p != "" { return p, nil }
    }

    raw := make([]byte, 24)
    if _, err := rand.Read(raw); err != nil { return "", err }
    password = base64.RawURLEncoding.EncodeToString(raw)

    // CREATE ROLE is idempotent via DO block.
    sql := fmt.Sprintf(`
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) THEN
                CREATE ROLE %s NOINHERIT LOGIN PASSWORD %s;
            ELSE
                ALTER ROLE %s WITH LOGIN PASSWORD %s;
            END IF;
        END$$;`,
        quoteLiteral(dep.DBAppRole), sanitize(dep.DBAppRole), quoteLiteral(password),
        sanitize(dep.DBAppRole), quoteLiteral(password))
    if _, err := a.Admin.Exec(ctx, sql); err != nil { return "", err }

    // Persist to OpenBao KV for the data-plane process to read at boot.
    if err := a.Bao.KVPut(ctx, dep.ID, "postgres/app_password", map[string]any{"password": password}); err != nil {
        return "", err
    }
    return password, nil
}
```

### 12c.4 Grants

`grants.go`:

```go
func (a *Adapter) grantToRole(ctx context.Context, dep *Deployment) error {
    // Connect to the new DB as superuser to grant; need a fresh pool.
    pool, err := pgxpool.New(ctx, a.adminDSNForDB(dep.DBName))
    if err != nil { return err }
    defer pool.Close()

    stmts := []string{
        fmt.Sprintf(`CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION %s`, sanitize(dep.DBAppRole)),
        fmt.Sprintf(`GRANT CONNECT ON DATABASE %s TO %s`, sanitize(dep.DBName), sanitize(dep.DBAppRole)),
        fmt.Sprintf(`GRANT USAGE ON SCHEMA app TO %s`, sanitize(dep.DBAppRole)),
        fmt.Sprintf(`ALTER ROLE %s SET search_path = app, public`, sanitize(dep.DBAppRole)),
        // Default privileges: future tables/sequences auto-grant to the role.
        fmt.Sprintf(`ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %s`, sanitize(dep.DBAppRole)),
        fmt.Sprintf(`ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO %s`, sanitize(dep.DBAppRole)),
    }
    for _, s := range stmts {
        if _, err := pool.Exec(ctx, s); err != nil { return fmt.Errorf("grant: %w", err) }
    }
    return nil
}
```

### 12c.5 Migrations

`migrate.go`:

```go
func (a *Adapter) applyMigrations(ctx context.Context, dep *Deployment, pwd string) error {
    dsn := a.appDSN(dep, pwd) + "&x-migrations-table=schema_migrations_dataplane&search_path=app,public"
    src, err := iofs.New(dataplanemigrations.FS, "dataplane")
    if err != nil { return err }
    m, err := migrate.NewWithSourceInstance("iofs", src, dsn)
    if err != nil { return err }
    defer m.Close()
    err = m.Up()
    if err != nil && err != migrate.ErrNoChange { return err }
    return nil
}
```

The migrations are applied as the **app role** (not superuser). This means CREATE TABLE etc. is owned by the role; the schema namespace is `app`. This is critical because:

1. The role's `FORCE ROW LEVEL SECURITY` is bypassable by the table owner unless explicitly forced — and `FORCE` makes even the owner subject to RLS.
2. Phase 10's `REVOKE UPDATE, DELETE ON audit_event FROM PUBLIC` runs as superuser at the migration tail — see §12c.6.

### 12c.6 RLS enforcement + audit grants tail

`grants.go` continues with the post-migration tail:

```go
func (a *Adapter) enforceRLSAndAuditGrants(ctx context.Context, dep *Deployment, pwd string) error {
    pool, err := pgxpool.New(ctx, a.adminDSNForDB(dep.DBName))
    if err != nil { return err }
    defer pool.Close()

    // For every tenant-bound table, FORCE RLS. The migration sets ENABLE RLS;
    // we double-tighten with FORCE here so even the table owner is subject.
    tables := []string{
        "tenant", "platform_user", "identity_provider_mapping", "social_login_state",
        "notification_channel", "notification_workflow", "notification",
        "organization", "member", "invitation",
        "role", "member_role", "casbin_rule",
        "api_key", "audit_event",
    }
    for _, t := range tables {
        // The table may not exist if the deployment's modules array excluded the feature.
        // Skip silently in that case.
        if _, err := pool.Exec(ctx, fmt.Sprintf(`ALTER TABLE IF EXISTS %s FORCE ROW LEVEL SECURITY`, t)); err != nil {
            return fmt.Errorf("force rls %s: %w", t, err)
        }
    }

    // Append-only on audit_event for the app role.
    _, err = pool.Exec(ctx, fmt.Sprintf(`REVOKE UPDATE, DELETE ON audit_event FROM %s`, sanitize(dep.DBAppRole)))
    if err != nil { return err }
    _, err = pool.Exec(ctx, fmt.Sprintf(`REVOKE TRUNCATE ON audit_event FROM %s`, sanitize(dep.DBAppRole)))
    if err != nil { return err }
    // The same for casbin_rule — wildcard policy attempts must hit DB CHECK, not bypass via UPDATE.
    return nil
}
```

### 12c.7 Smoke test for RLS

`smoke.go`:

```go
func (a *Adapter) smokeRLS(ctx context.Context, dep *Deployment, pwd string) error {
    pool, err := pgxpool.New(ctx, a.appDSN(dep, pwd))
    if err != nil { return err }
    defer pool.Close()

    // Insert two rows under different tenant_ids; with GUC set, only one is visible.
    conn, _ := pool.Acquire(ctx); defer conn.Release()
    if _, err := conn.Exec(ctx, `INSERT INTO tenant (id, slug, name) VALUES ('tenant_smokea', 'smokea', 'Smoke A') ON CONFLICT DO NOTHING`); err != nil { return err }
    if _, err := conn.Exec(ctx, `INSERT INTO tenant (id, slug, name) VALUES ('tenant_smokeb', 'smokeb', 'Smoke B') ON CONFLICT DO NOTHING`); err != nil { return err }

    var n int
    _, _ = conn.Exec(ctx, `SET LOCAL app.current_tenant_id = 'tenant_smokea'`)
    if err := conn.QueryRow(ctx, `SELECT count(*) FROM tenant`).Scan(&n); err != nil { return err }
    if n != 1 { return fmt.Errorf("RLS smoke failed: expected 1 row with GUC=smokea, got %d", n) }

    _, _ = conn.Exec(ctx, `RESET app.current_tenant_id`)
    // Without GUC, RLS returns zero rows (current_setting returns empty).
    if err := conn.QueryRow(ctx, `SELECT count(*) FROM tenant`).Scan(&n); err != nil { return err }
    if n != 0 { return fmt.Errorf("RLS smoke failed: expected 0 rows with no GUC, got %d", n) }

    // Cleanup.
    _, _ = conn.Exec(ctx, `SET LOCAL app.current_tenant_id = 'tenant_smokea'`)
    _, _ = conn.Exec(ctx, `DELETE FROM tenant WHERE slug IN ('smokea','smokeb')`)
    return nil
}
```

Failure halts provisioning + flips status='failed'. RLS smoke is the layer-3 invariant test in production code path, not just in CI.

### 12c.8 Audit grant test

`audit_grants_test.go`:

```go
func TestPostgresAdapter_AuditAppendOnly(t *testing.T) {
    // Provision a test deployment.
    dep := provision(t)
    pool, _ := pgxpool.New(ctx, a.appDSN(dep, password))
    defer pool.Close()
    _, err := pool.Exec(ctx, `UPDATE audit_event SET action = 'tamper' WHERE id IS NOT NULL`)
    require.Error(t, err)
    require.Contains(t, err.Error(), "permission denied")

    _, err = pool.Exec(ctx, `DELETE FROM audit_event`)
    require.Error(t, err)
    require.Contains(t, err.Error(), "permission denied")
}
```

### 12c.9 Composite Provisioner wiring

```go
type CompositeProvisioner struct {
    Local    *LocalProvisioner   // deprecated; will go away in Phase 12e once Postgres adapter fully replaces it
    Postgres *postgres.Adapter
    K3s      *k3s.Adapter
    Nginx    *nginx.Adapter
}

func (c *CompositeProvisioner) Provision(ctx context.Context, d *Deployment) (BootstrapResult, error) {
    // Order per §6.2 — Phase 12e re-orders into the formal 13-step sequence.
    if err := c.Postgres.Provision(ctx, d); err != nil { return BootstrapResult{}, fmt.Errorf("postgres: %w", err) }
    if err := c.K3s.Provision(ctx, d);      err != nil { return BootstrapResult{}, fmt.Errorf("k3s: %w", err) }
    boot, err := c.seedBootstrap(ctx, d);   if err != nil { return boot, fmt.Errorf("seed: %w", err) }
    if err := c.Nginx.ApplyVhost(ctx, vhostInput(d));          err != nil { return boot, fmt.Errorf("nginx: %w", err) }
    if err := c.Nginx.IssueCertificate(ctx, d.ID, d.PrimaryVhost, d.CustomDomains); err != nil { return boot, fmt.Errorf("certbot: %w", err) }
    if err := c.waitForPublicHealth(ctx, d); err != nil { return boot, fmt.Errorf("health: %w", err) }
    return boot, nil
}
```

`seedBootstrap` is the function previously inside LocalProvisioner; it now connects to the new per-Deployment DB via the app role + password from OpenBao KV.

### 12c.10 Data-plane image reads DB password from OpenBao

The data-plane binary reads `BAO_ADDR` + its in-cluster SA token → logs in via Kubernetes auth → reads `secret/data/<deployment_id>/postgres/app_password` → builds its own DATAPLANE_DATABASE_URL at startup.

Update `cmd/dataplane/main.go`:

```go
data, err := encClient.KVGet(ctx, deploymentID, "postgres/app_password")
if err != nil { return fmt.Errorf("kv read pg password: %w", err) }
password := data["password"].(string)
dsn := fmt.Sprintf("postgres://%s:%s@%s:5432/%s?sslmode=verify-full&search_path=app,public",
    appRoleName, password, hostExternal, dbName)
pool, _ := pgx.NewPool(ctx, pgx.Options{DSN: dsn})
```

This means the manifest's `dataplane-db` Secret (from Phase 12b) is replaced: in Phase 12c we DO NOT put the password into a k8s Secret. The pod has no env var with the password; it reads from OpenBao via its SA. This is layer 5 + layer 3 belt-and-braces.

Phase 12b's deployment.yaml must be updated to remove the `valueFrom: secretKeyRef: dataplane-db` env and instead inject `BAO_ADDR` + use the SA token.

### 12c.11 Tests

`adapter_test.go`:

- Provision twice — second is no-op.
- Concurrent Provision of two different deployments — no role/db collision.
- Provision when DB exists but role missing — creates role, applies grants.
- Provision when role exists but password rotated externally — re-stores in KV.
- DROP DATABASE while a connection is open — error reported; operator runbook notes to disconnect first.

`rls_test.go`:

- Smoke from §12c.7 — pass/fail.
- Cross-tenant SELECT with GUC mismatch — 0 rows.
- Audit UPDATE/DELETE — permission denied.

### 12c.12 Commits

```bash
git add internal/controlplane/provision/postgres/
git commit -m "implement per deployment postgres provisioner"

git add cmd/controlplane/main.go internal/controlplane/deployments/
git commit -m "wire postgres adapter into composite provisioner"

git add cmd/dataplane/main.go deploy/k3s/base/deployment.yaml
git commit -m "read db password from openbao kv"
```

---

## Verification checklist

```bash
# 1. Build + lint + tests.
$ make build && make lint && make test && make test-int

# 2. Provision a real deployment.
$ ./bin/saasctl deployment create --project pgtest --environment dev --image v0.3.1

# 3. DB exists.
$ psql -l | grep saas_pgtest_dev
$ psql -c "\d saas_pgtest_dev.app.*" -d saas_pgtest_dev | head -20

# 4. Role exists + perms.
$ psql -c "\du saas_pgtest_dev_app"
$ psql -c "SELECT rolname, rolsuper, rolcreatedb, rolcanlogin FROM pg_roles WHERE rolname='saas_pgtest_dev_app';"
# Expected: rolsuper=f, rolcreatedb=f, rolcanlogin=t

# 5. RLS forced.
$ psql -d saas_pgtest_dev -c "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN ('tenant','platform_user','audit_event') AND relkind='r';"
# Expected: f, t, t  (or t, t depending; FORCE = t is the critical flag)

# 6. App role has no UPDATE/DELETE on audit_event.
$ PG=postgres://saas_pgtest_dev_app:$(bao kv get -field=password secret/dep_pgtest_dev/postgres)@localhost/saas_pgtest_dev
$ psql "$PG" -c "UPDATE audit_event SET action='x' WHERE 1=1;"
# Expected: ERROR: permission denied for table audit_event

# 7. RLS smoke from inside the data-plane pod.
$ kubectl -n saas-pgtest-dev exec deploy/data-plane -- env | grep DATAPLANE_DATABASE_URL
# Expected: the env is NOT set (password loaded from OpenBao at boot).

$ kubectl -n saas-pgtest-dev logs deploy/data-plane | grep "rls smoke"
# Expected: smoke pass log line at startup

# 8. /healthz via real public URL.
$ curl -I https://dev.pgtest.saas.omarss.net/healthz
# Expected: 200 OK

# 9. Two deployments don't see each other's data.
$ ./bin/saasctl deployment create --project pgtest2 --environment dev --image v0.3.1
$ psql "postgres://saas_pgtest_dev_app:...@/saas_pgtest_dev" -c "SELECT count(*) FROM tenant;"
$ psql "postgres://saas_pgtest2_dev_app:...@/saas_pgtest2_dev" -c "SELECT count(*) FROM tenant;"
# Expected: both 1 (each has its own bootstrap tenant)

# 10. Purge drops DB + role + KV.
$ ./bin/saasctl deployment delete dep_... --retain-days 0
$ ./bin/saasctl deployment purge dep_...
$ psql -l | grep saas_pgtest_dev
# Expected: empty
$ bao kv get secret/dep_pgtest_dev/postgres/app_password
# Expected: No value found
```

---

## Anti-pattern guards

- **NEVER** create a role with `SUPERUSER` or `CREATEDB`. The role is application-tier only.
- **NEVER** set the role's password from a string in code without going through the random + OpenBao KV path. Static passwords are the most common forensic finding.
- **NEVER** skip `ALTER ROLE ... SET search_path = app, public`. Without it, the role uses `public` and the migration's `CREATE TABLE` in `app` is invisible.
- **NEVER** apply migrations as superuser. Migration as the app role pins table ownership + cleanly enforces grants downstream.
- **NEVER** skip the `enforceRLSAndAuditGrants` tail. Without FORCE RLS, the table owner (the app role itself in §12c.5) can bypass the policy.
- **NEVER** allow the data-plane pod to read `DATAPLANE_DATABASE_URL` from a k8s Secret. Read via OpenBao KV at boot.
- **NEVER** call `DROP DATABASE` from anywhere except `Purge`. Soft destroy retains; only purge drops.
- **NEVER** allow `sanitize()` to be bypassed. All identifier strings go through it. If a slug somehow contains a non-allowlist char, panic — the producer is buggy.

---

## Open questions

1. **Migration version drift between deployments.** Default: every Deployment is on the same migration set at provision; upgrades run pending migrations (Phase 12e). Multi-image deployments may be on different versions; per §27 the migrations must remain backward-compatible with the previous image for one release. Confirm policy enforced.
2. **WAL archiving config.** Done at the host Postgres cluster level (one-time host setup). The control plane does NOT manage WAL archiving per-Deployment (cluster-wide setting). Document in runbook.
3. **Dynamic database secrets engine.** Deferred per §18.7. When promoted, the data-plane process logs into OpenBao, requests a short-lived role, builds the DSN, refreshes near lease expiry. Out of MVP.
4. **Postgres extensions.** `pgcrypto` is needed for some downstream operations? Default: no — application uses Go crypto. Don't enable extensions globally.

---

## Phase 12c — Definition of done

- [ ] `internal/controlplane/provision/postgres/` complete with adapter, database, role, grants, migrate, seed, destroy + tests
- [ ] DB + role + grants + migrations applied for a real Deployment
- [ ] `FORCE ROW LEVEL SECURITY` on every tenant-bound table; verified by querying pg_class
- [ ] App role lacks UPDATE/DELETE/TRUNCATE on audit_event (DB-tested)
- [ ] DB password generated + stored in OpenBao KV; not in any k8s Secret
- [ ] Data-plane pod reads password from OpenBao at boot
- [ ] RLS smoke test runs at provision time AND at data-plane pod startup
- [ ] Purge drops DB + role + KV path
- [ ] Composite Provisioner uses PostgresAdapter in place of LocalProvisioner's DB step
- [ ] §17.4 partial: DB-only happy + partial-failure + purge tests pass
- [ ] All Phase 2-12b tests still green
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 7 — First real per-Deployment Postgres DB

### What was done
- internal/controlplane/provision/postgres/ adapter + tests
- Per-Deployment DB `saas_<project>_<env>` + role `saas_<project>_<env>_app` + grants
- All tenant-bound tables ENABLE + FORCE RLS
- audit_event UPDATE/DELETE revoked from app role
- DB password stored in OpenBao KV; pod reads at boot
- RLS smoke test in production provisioning path

### What to verify (user runs these)
```bash
$ psql -l | grep saas_
$ psql -c "\du" | grep _app
$ psql -d saas_<p>_<e> -c "SELECT relname, relforcerowsecurity FROM pg_class WHERE relkind='r' ORDER BY relname;"
$ # Audit append-only test:
$ PG=postgres://saas_<p>_<e>_app:$(bao kv get -field=password secret/<dep_id>/postgres/app_password)@/saas_<p>_<e>
$ psql "$PG" -c "UPDATE audit_event SET action='x' WHERE 1=1;"
# Expected: permission denied
$ kubectl -n saas-<p>-<e> logs deploy/data-plane | grep "rls smoke pass"
$ curl -I https://<e>.<p>.saas.omarss.net/healthz
# Expected: 200
```

### What approval means
By proceeding past CHECKPOINT 7, you accept:
- Every Deployment owns its own Postgres DB on the host cluster; cross-DB queries are impossible.
- Every tenant-bound table is RLS-FORCEd; even table owner is subject to the policy.
- Database passwords live only in OpenBao KV; never in k8s Secrets or env files.
- Purge truly drops the DB + role + KV. Recovery from purge requires backup restore.

### Rollback if rejected
```bash
$ ./bin/saasctl deployment purge <dep_id>          # cleans up the test DB
$ git revert <hashes for the 3 phase-12c commits>
# DBs created during testing must be dropped manually if not via purge.
```

---

End of Phase 12c. Next: `13d-openbao-provisioner.md`.
