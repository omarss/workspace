package deployments_test

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
)

// fakeSeq records the calls + returns canned results.
type fakeSeq struct {
	runErr      error
	bootstrap   deployments.BootstrapResult
	bootstrapOK bool
	calls       []string
}

func (f *fakeSeq) Run(_ context.Context, d *deployments.Deployment) error {
	f.calls = append(f.calls, "Run:"+d.ID)
	return f.runErr
}

func (f *fakeSeq) Upgrade(_ context.Context, d *deployments.Deployment, newImage string, _ bool) error {
	f.calls = append(f.calls, "Upgrade:"+d.ID+":"+newImage)
	return nil
}

func (f *fakeSeq) Rollback(_ context.Context, d *deployments.Deployment, prev string) error {
	f.calls = append(f.calls, "Rollback:"+d.ID+":"+prev)
	return nil
}

func (f *fakeSeq) Restart(_ context.Context, d *deployments.Deployment) error {
	f.calls = append(f.calls, "Restart:"+d.ID)
	return nil
}

func (f *fakeSeq) Restore(_ context.Context, d *deployments.Deployment, _ time.Time) (*deployments.Deployment, error) {
	f.calls = append(f.calls, "Restore:"+d.ID)
	return d, nil
}

func (f *fakeSeq) Destroy(_ context.Context, d *deployments.Deployment) error {
	f.calls = append(f.calls, "Destroy:"+d.ID)
	return nil
}

func (f *fakeSeq) Purge(_ context.Context, d *deployments.Deployment) error {
	f.calls = append(f.calls, "Purge:"+d.ID)
	return nil
}

func (f *fakeSeq) FreezeKeys(_ context.Context, d *deployments.Deployment, reason string) error {
	f.calls = append(f.calls, "FreezeKeys:"+d.ID+":"+reason)
	return nil
}

func (f *fakeSeq) BootstrapFor(_ string) (deployments.BootstrapResult, bool) {
	return f.bootstrap, f.bootstrapOK
}

func TestHostProvisioner_DelegatesProvision(t *testing.T) {
	seq := &fakeSeq{
		bootstrap:   deployments.BootstrapResult{BootstrapTenantID: "tenant_X"},
		bootstrapOK: true,
	}
	p, err := deployments.NewHostProvisioner(deployments.HostProvisionerOptions{Seq: seq})
	if err != nil {
		t.Fatalf("NewHostProvisioner: %v", err)
	}
	res, err := p.Provision(context.Background(), &deployments.Deployment{ID: "dep_X"})
	if err != nil {
		t.Fatalf("Provision: %v", err)
	}
	if res.BootstrapTenantID != "tenant_X" {
		t.Errorf("unexpected bootstrap: %+v", res)
	}
	if len(seq.calls) != 1 || seq.calls[0] != "Run:dep_X" {
		t.Errorf("calls: %v", seq.calls)
	}
}

func TestHostProvisioner_NilSeqRejected(t *testing.T) {
	_, err := deployments.NewHostProvisioner(deployments.HostProvisionerOptions{})
	if !errors.Is(err, deployments.ErrProvisionerNotConfigured) {
		t.Errorf("want ErrProvisionerNotConfigured; got %v", err)
	}
}

func TestHostProvisioner_AttachDomain_PopulatesRecord(t *testing.T) {
	seq := &fakeSeq{}
	p, _ := deployments.NewHostProvisioner(deployments.HostProvisionerOptions{
		Seq:         seq,
		BYODHMACKey: []byte("k"),
	})
	dd := &deployments.DeploymentDomain{Domain: "api.acme.com"}
	if err := p.AttachDomain(context.Background(), &deployments.Deployment{ID: "dep_X"}, dd); err != nil {
		t.Fatalf("AttachDomain: %v", err)
	}
	if dd.VerificationRecord.RecordName != "_saas-verify.api.acme.com" {
		t.Errorf("unexpected record name: %s", dd.VerificationRecord.RecordName)
	}
}

func TestHostProvisioner_LifecycleDelegations(t *testing.T) {
	seq := &fakeSeq{}
	p, _ := deployments.NewHostProvisioner(deployments.HostProvisionerOptions{Seq: seq})
	ctx := context.Background()
	d := &deployments.Deployment{ID: "dep_X"}
	_ = p.Upgrade(ctx, d, "v0.4.0", true)
	_ = p.Rollback(ctx, d, "v0.3.0")
	_ = p.Restart(ctx, d)
	_, _ = p.Restore(ctx, d, time.Now())
	_ = p.Destroy(ctx, d)
	_ = p.Purge(ctx, d)
	_ = p.FreezeKeys(ctx, d, "test")
	if len(seq.calls) != 7 {
		t.Errorf("want 7 calls; got %d: %v", len(seq.calls), seq.calls)
	}
}
