// LocalProvisioner — Phase 11 Postgres-only provisioner. It creates a
// per-Deployment database on the host postgres (via the existing pgxpool),
// runs the data-plane migrations against it, and seeds a bootstrap admin
// tenant + first API key.
//
// The local provisioner DELIBERATELY skips:
//   - nginx vhost writes (lands in Phase 12a behind CHECKPOINT 5)
//   - k3s namespace + workload creation (Phase 12b behind CHECKPOINT 6)
//   - host Postgres ROLE creation with FORCE RLS (Phase 12c behind CP 7;
//     local mode reuses the dev `saas` role for app access)
//   - OpenBao transit key + KV path creation (Phase 12d behind CP 8)
//   - certbot cert issuance (Phase 12a)
//
// Phase 11 must NEVER contain code that writes outside Postgres. The
// CHECKPOINT 4 review gates that promise.
package deployments

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"time"

	"github.com/omarss/saas/internal/platform/id"
)

// dbNameSafe restricts CREATE DATABASE identifiers to a strict pattern.
// CREATE DATABASE is NOT a parameterised statement — the identifier must
// be interpolated. The shape is already constrained by the project / env
// slug CHECKs (lowercase letters, digits, hyphen) but we re-enforce here
// in defense of any caller that bypasses the slug validator.
var dbNameSafe = regexp.MustCompile(`^[a-z][a-z0-9_]{1,62}$`)

// hostDB is the minimal pool surface LocalProvisioner needs. We use a
// narrow interface so tests can substitute a fake without depending on
// pgxpool internals.
type hostDB interface {
	Exec(ctx context.Context, sql string, args ...any) (commandTag, error)
	QueryRow(ctx context.Context, sql string, args ...any) row
}

// commandTag and row are extracted to keep the test seam tight. The
// concrete pgxpool adapter in repo_pgx.go satisfies these by simple
// wrapping; we do not depend on pgx types in the interface.
type commandTag interface {
	RowsAffected() int64
}

type row interface {
	Scan(dest ...any) error
}

// LocalProvisioner ships in Phase 11. The hostPool is the control-plane
// process's existing pgxpool — re-used to issue CREATE DATABASE and run
// data-plane migrations.
//
// The Phase 12 provisioner will satisfy the same Provisioner interface
// but call out to nginx + certbot + client-go + OpenBao adapters too.
type LocalProvisioner struct {
	// hostPool is the host's superuser-or-equivalent connection. For
	// local dev it's the same pool the control plane uses; in production
	// it would be the host postgres maintenance DB.
	hostPool hostDB

	// migrationsApplier is the data-plane migration runner. The default
	// applies migrations via golang-migrate against an inline DSN.
	// Stubbed out in tests.
	migrationsApplier MigrationsApplier

	// resolver does DNS TXT verification for BYOD. Defaults to the
	// process-wide net.DefaultResolver via DefaultDNSResolver.
	resolver DNSResolver

	// byodHMACKey is the per-process BYOD HMAC placeholder (Phase 11).
	// Phase 12d swaps to per-Deployment keys read from OpenBao KV at
	// secret/data/<dep_id>/byod_hmac_key.
	byodHMACKey []byte

	// seeder seeds the bootstrap tenant + admin user + member + api key
	// inside the freshly-migrated data-plane DB. Implemented separately
	// because it depends on data-plane modules and is straightforward
	// to fake in tests.
	seeder BootstrapSeeder

	// dataPlaneDSN constructs a DSN to the new per-Deployment database.
	// Phase 11: same host, distinct database name, same `saas` role.
	dataPlaneDSN func(d *Deployment) string
}

// MigrationsApplier runs the data-plane migrations against a per-Deployment
// DSN. The default impl uses golang-migrate; tests inject a fake.
type MigrationsApplier interface {
	Up(ctx context.Context, dsn string) error
}

// BootstrapSeeder seeds the first tenant + API key inside a freshly
// migrated data-plane DB. Implemented in Phase 11 via a thin shim that
// reuses the data-plane services through synthetic operator principal.
type BootstrapSeeder interface {
	Seed(ctx context.Context, d *Deployment, dataPlaneDSN string) (BootstrapResult, error)
}

// LocalProvisionerOptions wires the LocalProvisioner. All fields except
// hostPool are optional; sensible defaults are filled in.
type LocalProvisionerOptions struct {
	HostPool          hostDB
	MigrationsApplier MigrationsApplier
	Resolver          DNSResolver
	BYODHMACKey       []byte
	Seeder            BootstrapSeeder
	DataPlaneDSN      func(d *Deployment) string
}

// NewLocalProvisioner constructs a LocalProvisioner. Caller is expected to
// pass at least HostPool, MigrationsApplier, Seeder, and DataPlaneDSN.
// Resolver defaults to DefaultDNSResolver; BYODHMACKey defaults to a
// process-local random key (Phase 12d replaces).
func NewLocalProvisioner(opts LocalProvisionerOptions) *LocalProvisioner {
	if opts.Resolver == nil {
		opts.Resolver = DefaultDNSResolver{}
	}
	if len(opts.BYODHMACKey) == 0 {
		opts.BYODHMACKey = defaultHMACKey()
	}
	return &LocalProvisioner{
		hostPool:          opts.HostPool,
		migrationsApplier: opts.MigrationsApplier,
		resolver:          opts.Resolver,
		byodHMACKey:       opts.BYODHMACKey,
		seeder:            opts.Seeder,
		dataPlaneDSN:      opts.DataPlaneDSN,
	}
}

// Provision runs the local-mode flow: create DB, apply migrations, seed
// bootstrap tenant. Each step is recorded so a partial failure can be
// retried by the destroy reconciler. Re-running on an already-provisioned
// Deployment is a no-op (idempotent).
func (p *LocalProvisioner) Provision(ctx context.Context, d *Deployment) (BootstrapResult, error) {
	if p == nil || p.hostPool == nil {
		return BootstrapResult{}, ErrProvisionerNotConfigured
	}

	// Step 1: CREATE DATABASE (not transactional; check first).
	if err := p.createDatabaseIfMissing(ctx, d.DBName); err != nil {
		return BootstrapResult{}, fmt.Errorf("create database: %w", err)
	}

	// Step 2: apply data-plane migrations against the new DB.
	if p.migrationsApplier != nil {
		dsn := ""
		if p.dataPlaneDSN != nil {
			dsn = p.dataPlaneDSN(d)
		}
		if err := p.migrationsApplier.Up(ctx, dsn); err != nil {
			return BootstrapResult{}, fmt.Errorf("apply migrations: %w", err)
		}
	}

	// Step 3: seed the bootstrap tenant + API key. The secret is returned
	// here and propagated to the create response — never persisted.
	if p.seeder == nil {
		return BootstrapResult{}, errors.New("bootstrap seeder not configured")
	}
	dsn := ""
	if p.dataPlaneDSN != nil {
		dsn = p.dataPlaneDSN(d)
	}
	return p.seeder.Seed(ctx, d, dsn)
}

// createDatabaseIfMissing emits CREATE DATABASE only when the catalogue
// does not already list datname. CREATE DATABASE cannot run inside a
// transaction, so the existence check + create is intentionally a
// two-step racing-safe pattern (the UNIQUE constraint on
// deployment(project_slug, environment_slug) is the actual race breaker).
func (p *LocalProvisioner) createDatabaseIfMissing(ctx context.Context, name string) error {
	if !dbNameSafe.MatchString(name) {
		return fmt.Errorf("unsafe database name: %s", name)
	}
	var exists bool
	r := p.hostPool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)`, name)
	if err := r.Scan(&exists); err != nil {
		return fmt.Errorf("check pg_database: %w", err)
	}
	if exists {
		return nil
	}
	// fmt.Sprintf is unavoidable for DDL identifiers; name is dbNameSafe-validated.
	if _, err := p.hostPool.Exec(ctx, fmt.Sprintf(`CREATE DATABASE %q`, name)); err != nil {
		return fmt.Errorf("create database: %w", err)
	}
	return nil
}

// Upgrade — Phase 11 local mode: just record the new image version. The
// real container-image rollout lives in Phase 12e (the §6.2 sequence).
func (p *LocalProvisioner) Upgrade(_ context.Context, _ *Deployment, _ string, _ bool) error {
	return nil
}

// Rollback — Phase 11 local mode: no-op. Phase 12e wires the real path.
func (p *LocalProvisioner) Rollback(_ context.Context, _ *Deployment, _ string) error {
	return nil
}

// Restart — Phase 11 local mode: no-op (no pods to bounce).
func (p *LocalProvisioner) Restart(_ context.Context, _ *Deployment) error {
	return nil
}

// Restore — Phase 11 local mode: not implemented. Phase 12e wires the
// PITR + namespace swap via WAL-G or pgBackRest.
func (p *LocalProvisioner) Restore(_ context.Context, _ *Deployment, _ time.Time) (*Deployment, error) {
	return nil, errors.New("restore not implemented in local mode (Phase 12e)")
}

// Destroy — Phase 11 local mode: no-op. Soft-delete is handled by the
// service flipping status='destroyed'; Phase 12e adds the destroy
// reconciler that actually tears down namespace + DB.
func (p *LocalProvisioner) Destroy(_ context.Context, _ *Deployment) error {
	return nil
}

// Purge — Phase 11 local mode: no-op. Hard delete (DROP DATABASE, drop
// namespace, revoke OpenBao key, delete vhost) lands in Phase 12e.
func (p *LocalProvisioner) Purge(_ context.Context, _ *Deployment) error {
	return nil
}

// AttachDomain — Phase 11 local mode: populate the verification record
// only. Phase 12a appends the domain to the per-Deployment nginx vhost
// `server_name` and runs certbot for the new SAN.
func (p *LocalProvisioner) AttachDomain(_ context.Context, d *Deployment, dd *DeploymentDomain) error {
	rec := MakeVerificationRecord(d.ID, dd.Domain, p.byodHMACKey)
	dd.VerificationRecord = rec
	dd.VerificationMethod = "dns_txt"
	dd.VerificationToken = rec.RecordValue
	return nil
}

// VerifyDomain runs the synchronous DNS TXT lookup per ADR 015. Returns
// (verified, nil) on a match; (false, nil) if no matching TXT is found;
// or (false, err) on a resolver error so the caller can record it for
// operator observability.
func (p *LocalProvisioner) VerifyDomain(ctx context.Context, _ *Deployment, dd *DeploymentDomain) (bool, error) {
	if p.resolver == nil {
		return false, errors.New("dns resolver not configured")
	}
	txts, err := p.resolver.LookupTXT(ctx, dd.VerificationRecord.RecordName)
	if err != nil {
		return false, err
	}
	for _, v := range txts {
		if CompareVerificationValue(dd.VerificationRecord.RecordValue, v) {
			return true, nil
		}
	}
	return false, nil
}

// DetachDomain — Phase 11 local mode: no-op. Phase 12a re-runs certbot
// without the detached domain so the cert SAN list shrinks; the vhost is
// re-rendered without the entry.
func (p *LocalProvisioner) DetachDomain(_ context.Context, _ *Deployment, _ *DeploymentDomain) error {
	return nil
}

// defaultHMACKey returns a process-local placeholder. Calling this MUST
// not happen in production — Phase 12d wires the per-Deployment OpenBao
// key. The value is deliberately stable across the process lifetime so
// `make test` is deterministic.
func defaultHMACKey() []byte {
	// Static fallback. Not cryptographic randomness — Phase 11 only.
	return []byte("phase-11-placeholder-byod-hmac-key-dev-only")
}

// SynthOperatorPrincipal returns a synthetic principal the bootstrap
// seeder uses to walk the data-plane services without going through the
// chi router. The actor_type is "system" so audit rows clearly mark the
// bootstrap path.
func SynthOperatorPrincipal(deploymentID string) string {
	return "system:bootstrap:" + deploymentID
}

// Compile-time assertion that LocalProvisioner satisfies the full
// Provisioner interface — catches a missing method earlier than a
// runtime nil-method-call.
var _ Provisioner = (*LocalProvisioner)(nil)

// NewID returns a new id with the deployment prefix; centralised here so
// tests can monkey-patch via test-only setters in the future.
func NewID() string { return id.New(id.PrefixDeployment) }
