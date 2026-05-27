package sequence_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
	"github.com/omarss/saas/internal/controlplane/provision/k3s"
	"github.com/omarss/saas/internal/controlplane/provision/nginx"
	"github.com/omarss/saas/internal/controlplane/provision/openbao"
	"github.com/omarss/saas/internal/controlplane/provision/postgres"
	"github.com/omarss/saas/internal/controlplane/provision/sequence"
)

// stubOpenBao satisfies openbao.Adapter with no-op operations.
type stubOpenBao struct {
	freezeCalled bool
}

func (s *stubOpenBao) Apply(_ context.Context, _ openbao.ApplyInput) (openbao.ApplyResult, error) {
	return openbao.ApplyResult{}, nil
}
func (s *stubOpenBao) Remove(_ context.Context, _ openbao.RemoveInput) error { return nil }
func (s *stubOpenBao) VerifyAccess(_ context.Context, _ string) error        { return nil }
func (s *stubOpenBao) FreezeKeys(_ context.Context, _ string) error {
	s.freezeCalled = true
	return nil
}

// stubPostgres satisfies postgres.Adapter.
type stubPostgres struct{}

func (stubPostgres) Apply(_ context.Context, _ postgres.ApplyInput) (postgres.ApplyResult, error) {
	return postgres.ApplyResult{
		DBName:           "saas_acme_prod",
		RoleName:         "saas_acme_prod_app",
		RolePassword:     "test-pw",
		PerDeploymentDSN: "postgres://saas_acme_prod_app:test-pw@localhost:5432/saas_acme_prod", // #nosec G101 -- stub adapter fixture; not a real credential
	}, nil
}
func (stubPostgres) Remove(_ context.Context, _ postgres.RemoveInput) error { return nil }
func (stubPostgres) VerifyRLS(_ context.Context, _ string) error            { return nil }

// stubK3s satisfies k3s.Adapter.
type stubK3s struct{}

func (stubK3s) Apply(_ context.Context, _ k3s.ApplyInput) error   { return nil }
func (stubK3s) Remove(_ context.Context, _ k3s.RemoveInput) error { return nil }
func (stubK3s) WaitReady(_ context.Context, _ string) error       { return nil }

// stubNginx satisfies nginx.Adapter.
type stubNginx struct{}

func (stubNginx) Apply(_ context.Context, _ nginx.ApplyInput) error     { return nil }
func (stubNginx) IssueCert(_ context.Context, _ nginx.ApplyInput) error { return nil }
func (stubNginx) Remove(_ context.Context, _ nginx.RemoveInput) error   { return nil }

func newStubAdapters() (sequence.Adapters, *stubOpenBao) {
	bao := &stubOpenBao{}
	return sequence.Adapters{
		OpenBao:             bao,
		Postgres:            stubPostgres{},
		K3s:                 stubK3s{},
		Nginx:               stubNginx{},
		PostgresAdminDSN:    "postgres://admin@localhost:5432/postgres",
		K3sHostNginxCIDR:    "10.0.0.0/24",
		K3sHostPostgresCIDR: "10.0.0.0/24",
		K3sHostOpenBaoCIDR:  "10.0.0.0/24",
	}, bao
}

func TestSequence_Purge_RefusesActive(t *testing.T) {
	seq := &sequence.Sequence{Ledger: sequence.NewMemoryLedger()}
	adapters, _ := newStubAdapters()
	d := &deployments.Deployment{ID: "dep_X", Status: deployments.StatusActive}
	err := seq.Purge(context.Background(), d, adapters)
	if !errors.Is(err, sequence.ErrCannotPurgeActive) {
		t.Errorf("want ErrCannotPurgeActive; got %v", err)
	}
}

func TestSequence_Purge_AllowsDestroyed(t *testing.T) {
	seq := &sequence.Sequence{Ledger: sequence.NewMemoryLedger()}
	adapters, _ := newStubAdapters()
	d := &deployments.Deployment{ID: "dep_X", Status: deployments.StatusDestroyed}
	if err := seq.Purge(context.Background(), d, adapters); err != nil {
		t.Errorf("Purge on destroyed should succeed; got %v", err)
	}
}

func TestSequence_FreezeKeys_DelegatesToOpenBao(t *testing.T) {
	seq := &sequence.Sequence{Ledger: sequence.NewMemoryLedger()}
	adapters, bao := newStubAdapters()
	d := &deployments.Deployment{ID: "dep_X", Status: deployments.StatusActive}
	if err := seq.FreezeKeys(context.Background(), d, adapters, "test-incident"); err != nil {
		t.Errorf("FreezeKeys: %v", err)
	}
	if !bao.freezeCalled {
		t.Errorf("expected FreezeKeys to call the openbao adapter")
	}
}

func TestSequence_Restore_NotImplemented(t *testing.T) {
	seq := &sequence.Sequence{Ledger: sequence.NewMemoryLedger()}
	adapters, _ := newStubAdapters()
	d := &deployments.Deployment{ID: "dep_X", Status: deployments.StatusActive}
	_, err := seq.Restore(context.Background(), d, adapters, time.Time{})
	if !errors.Is(err, sequence.ErrRestoreNotImplemented) {
		t.Errorf("want ErrRestoreNotImplemented; got %v", err)
	}
}
