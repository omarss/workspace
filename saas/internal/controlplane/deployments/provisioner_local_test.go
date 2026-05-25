package deployments_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
)

// fakeRow + fakeTag + fakeHostDB stub out the hostDB interface so the
// provisioner can be exercised without a real Postgres.
type fakeRow struct {
	exists bool
	err    error
}

func (f fakeRow) Scan(dest ...any) error {
	if f.err != nil {
		return f.err
	}
	if p, ok := dest[0].(*bool); ok {
		*p = f.exists
	}
	return nil
}

type fakeTag struct{}

func (fakeTag) RowsAffected() int64 { return 1 }

type fakeHostDB struct {
	existing  bool
	createErr error
	createSQL string
	scanErr   error
}

func (f *fakeHostDB) Exec(_ context.Context, sql string, _ ...any) (deployments.CommandTagForTest, error) {
	f.createSQL = sql
	return fakeTag{}, f.createErr
}

func (f *fakeHostDB) QueryRow(_ context.Context, _ string, _ ...any) deployments.RowForTest {
	return fakeRow{exists: f.existing, err: f.scanErr}
}

// fakeApplier records the DSN it was asked to migrate.
type fakeApplier struct {
	called bool
	err    error
}

func (a *fakeApplier) Up(_ context.Context, _ string) error {
	a.called = true
	return a.err
}

// fakeSeeder returns a canned BootstrapResult.
type fakeSeeder struct {
	res deployments.BootstrapResult
	err error
}

func (s *fakeSeeder) Seed(_ context.Context, d *deployments.Deployment, _ string) (deployments.BootstrapResult, error) {
	if s.err != nil {
		return deployments.BootstrapResult{}, s.err
	}
	if s.res.BootstrapTenantID == "" {
		s.res.BootstrapTenantID = "tenant_bootstrap_" + d.ID[4:14]
	}
	return s.res, nil
}

// fakeResolver returns pre-seeded TXT records for the lookup.
type fakeResolver struct {
	txts map[string][]string
	err  error
}

func (f fakeResolver) LookupTXT(_ context.Context, name string) ([]string, error) {
	if f.err != nil {
		return nil, f.err
	}
	return f.txts[name], nil
}

func newProvisioner(t *testing.T, db deployments.HostDBForTest, applier deployments.MigrationsApplier, seeder deployments.BootstrapSeeder, resolver deployments.DNSResolver) *deployments.LocalProvisioner {
	t.Helper()
	return deployments.NewLocalProvisioner(deployments.LocalProvisionerOptions{
		HostPool:          db,
		MigrationsApplier: applier,
		Seeder:            seeder,
		Resolver:          resolver,
		DataPlaneDSN:      func(d *deployments.Deployment) string { return "postgres://localhost/" + d.DBName },
	})
}

func TestLocalProvisioner_CreatesDb(t *testing.T) {
	db := &fakeHostDB{existing: false}
	applier := &fakeApplier{}
	seeder := &fakeSeeder{}
	p := newProvisioner(t, db, applier, seeder, fakeResolver{})

	dep := &deployments.Deployment{
		ID:              "dep_01H0000000000000000000000",
		ProjectSlug:     "acme",
		EnvironmentSlug: "prod",
		DBName:          "saas_acme_prod",
		ImageVersion:    "v0.3.1",
	}
	res, err := p.Provision(context.Background(), dep)
	if err != nil {
		t.Fatalf("Provision: %v", err)
	}
	if res.BootstrapTenantID == "" {
		t.Errorf("expected BootstrapTenantID populated")
	}
	if !applier.called {
		t.Errorf("expected migrations applier to be called")
	}
}

func TestLocalProvisioner_IdempotentOnExistingDb(t *testing.T) {
	db := &fakeHostDB{existing: true}
	p := newProvisioner(t, db, &fakeApplier{}, &fakeSeeder{}, fakeResolver{})
	dep := &deployments.Deployment{
		ID:              "dep_01H0000000000000000000000",
		ProjectSlug:     "acme",
		EnvironmentSlug: "prod",
		DBName:          "saas_acme_prod",
	}
	if _, err := p.Provision(context.Background(), dep); err != nil {
		t.Fatalf("Provision: %v", err)
	}
	if db.createSQL != "" {
		t.Errorf("expected no CREATE DATABASE on existing DB; got %q", db.createSQL)
	}
}

func TestLocalProvisioner_RejectsUnsafeDbName(t *testing.T) {
	db := &fakeHostDB{existing: false}
	p := newProvisioner(t, db, &fakeApplier{}, &fakeSeeder{}, fakeResolver{})
	dep := &deployments.Deployment{
		ID:              "dep_01H0000000000000000000000",
		ProjectSlug:     "acme",
		EnvironmentSlug: "prod",
		DBName:          `"; DROP DATABASE saas; --`,
	}
	_, err := p.Provision(context.Background(), dep)
	if err == nil {
		t.Fatalf("expected error for unsafe db name")
	}
}

func TestLocalProvisioner_VerifyDomain_Match(t *testing.T) {
	db := &fakeHostDB{existing: true}
	hmacKey := []byte("test-key")
	rec := deployments.MakeVerificationRecord("dep_X", "api.example.com", hmacKey)
	resolver := fakeResolver{txts: map[string][]string{rec.RecordName: {rec.RecordValue}}}
	p := deployments.NewLocalProvisioner(deployments.LocalProvisionerOptions{
		HostPool: db, Resolver: resolver, BYODHMACKey: hmacKey,
	})
	dd := &deployments.DeploymentDomain{Domain: "api.example.com", VerificationRecord: rec}
	ok, err := p.VerifyDomain(context.Background(), &deployments.Deployment{ID: "dep_X"}, dd)
	if err != nil || !ok {
		t.Fatalf("expected verified; ok=%v err=%v", ok, err)
	}
}

func TestLocalProvisioner_VerifyDomain_NoRecord(t *testing.T) {
	db := &fakeHostDB{existing: true}
	p := deployments.NewLocalProvisioner(deployments.LocalProvisionerOptions{
		HostPool: db, Resolver: fakeResolver{}, BYODHMACKey: []byte("k"),
	})
	rec := deployments.MakeVerificationRecord("dep_X", "api.example.com", []byte("k"))
	dd := &deployments.DeploymentDomain{Domain: "api.example.com", VerificationRecord: rec}
	ok, err := p.VerifyDomain(context.Background(), &deployments.Deployment{ID: "dep_X"}, dd)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if ok {
		t.Fatalf("expected not verified")
	}
}

func TestLocalProvisioner_VerifyDomain_ResolverError(t *testing.T) {
	db := &fakeHostDB{existing: true}
	p := deployments.NewLocalProvisioner(deployments.LocalProvisionerOptions{
		HostPool: db, Resolver: fakeResolver{err: errors.New("dns down")},
	})
	rec := deployments.MakeVerificationRecord("dep_X", "api.example.com", []byte("k"))
	dd := &deployments.DeploymentDomain{Domain: "api.example.com", VerificationRecord: rec}
	if _, err := p.VerifyDomain(context.Background(), &deployments.Deployment{ID: "dep_X"}, dd); err == nil {
		t.Fatalf("expected resolver error to bubble up")
	}
}

func TestLocalProvisioner_AttachDomain_PopulatesRecord(t *testing.T) {
	p := deployments.NewLocalProvisioner(deployments.LocalProvisionerOptions{
		HostPool: &fakeHostDB{existing: true}, BYODHMACKey: []byte("k"),
	})
	dd := &deployments.DeploymentDomain{Domain: "api.acme.com"}
	if err := p.AttachDomain(context.Background(), &deployments.Deployment{ID: "dep_X"}, dd); err != nil {
		t.Fatalf("AttachDomain: %v", err)
	}
	if dd.VerificationRecord.RecordName != "_saas-verify.api.acme.com" {
		t.Errorf("unexpected record name: %s", dd.VerificationRecord.RecordName)
	}
	if dd.VerificationRecord.RecordType != "TXT" {
		t.Errorf("expected TXT record")
	}
}

func TestMakeVerificationRecord_Deterministic(t *testing.T) {
	a := deployments.MakeVerificationRecord("dep_X", "api.acme.com", []byte("k"))
	b := deployments.MakeVerificationRecord("dep_X", "api.acme.com", []byte("k"))
	if a.RecordValue != b.RecordValue {
		t.Errorf("expected deterministic token")
	}
	c := deployments.MakeVerificationRecord("dep_X", "api.acme.com", []byte("different"))
	if c.RecordValue == a.RecordValue {
		t.Errorf("different keys must yield different tokens")
	}
}

func TestCompareVerificationValue(t *testing.T) {
	if !deployments.CompareVerificationValue("abc", "abc") {
		t.Errorf("equal values should compare equal")
	}
	if deployments.CompareVerificationValue("abc", "abd") {
		t.Errorf("differing values should compare unequal")
	}
}

// ensure exported tests compile against the public surface (compile-time
// link of fakes to the package-level interface aliases below).
var _ = time.Now
