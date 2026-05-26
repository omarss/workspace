// HostProvisioner — Phase 12e composite provisioner. Composes the four
// host adapters (nginx + k3s + postgres + openbao) into the AGENTS.md
// §6.2 13-step sequence + the §6.3 upgrade / rollback / restart and
// §6.6 restore / §18.6 purge / §18.7 freeze-keys lifecycle flows.
//
// The implementation delegates 99% of the work to
// `internal/controlplane/provision/sequence` — that package owns the
// orchestrator, ledger, destroy reconciler, and all the lifecycle
// closures. HostProvisioner is the seam where the Phase 11 Provisioner
// interface meets the §6.2 sequence; it exists so the deployments
// service does not have to know about sequence.Sequence directly.
//
// Selection: `cmd/controlplane/main.go` chooses HostProvisioner when
// `SAAS_HOST_PROVISIONER=true`. Default off for safety; LocalProvisioner
// (Phase 11) remains the easy-to-run path for `make dev` and tests.
package deployments

import (
	"context"
	"time"
)

// HostProvisionerSeq is the narrow interface HostProvisioner needs from
// the sequence orchestrator. Declared here (not as the concrete
// sequence.Sequence) so the deployments package does not import the
// sequence package directly — that would create an import cycle
// (sequence imports deployments for the Deployment + BootstrapResult
// types).
//
// The concrete sequence.Sequence + its lifecycle methods satisfy this
// interface via a thin shim wired in cmd/controlplane/main.go.
type HostProvisionerSeq interface {
	// Run executes the §6.2 13-step provisioning sequence. On success
	// the BootstrapResult is captured in the seed step's BootstrapStore;
	// HostProvisioner retrieves it via BootstrapStore.Get below.
	Run(ctx context.Context, d *Deployment) error

	// Upgrade runs §6.3: forward migrations + image patch + rollout +
	// healthz.
	Upgrade(ctx context.Context, d *Deployment, newImage string, runMigrations bool) error

	// Rollback runs §6.3 rollback: image flip only.
	Rollback(ctx context.Context, d *Deployment, previousImage string) error

	// Restart re-applies the same k3s manifest to bounce pods.
	Restart(ctx context.Context, d *Deployment) error

	// Restore runs §6.6: PITR into a NEW deployment_id. MVP returns
	// ErrRestoreNotImplemented; full implementation lands in a later
	// phase under provision/backup/.
	Restore(ctx context.Context, oldDep *Deployment, toTimestamp time.Time) (*Deployment, error)

	// Destroy flips status='destroying'; the reconciler picks it up
	// within `Period` (default 30 s).
	Destroy(ctx context.Context, d *Deployment) error

	// Purge runs §18.6 physical-delete. Audit row emitted BEFORE the
	// data disappears.
	Purge(ctx context.Context, d *Deployment) error

	// FreezeKeys runs §18.7: disable transit key + status='suspended'
	// + emit deployment.keys_frozen.
	FreezeKeys(ctx context.Context, d *Deployment, reason string) error

	// BootstrapFor returns the one-time BootstrapResult captured by
	// the seed step, then removes it from the store.
	BootstrapFor(deploymentID string) (BootstrapResult, bool)
}

// HostProvisioner satisfies the Provisioner interface by delegating
// every method to a HostProvisionerSeq. Construct via
// NewHostProvisioner; the seq value is the sequence.Sequence wrapped
// in the shim shipped from cmd/controlplane.
type HostProvisioner struct {
	seq      HostProvisionerSeq
	resolver DNSResolver

	// byodHMACKey is used by AttachDomain / VerifyDomain. Phase 12e
	// continues to use the Phase 11 in-process key; the per-Deployment
	// KV-stored key is a Phase 13+ hardening.
	byodHMACKey []byte
}

// HostProvisionerOptions wires HostProvisioner. Seq is required; the
// rest are optional with sensible defaults.
type HostProvisionerOptions struct {
	Seq         HostProvisionerSeq
	Resolver    DNSResolver
	BYODHMACKey []byte
}

// NewHostProvisioner constructs the composite provisioner. Returns
// ErrProvisionerNotConfigured if Seq is nil — calling Provision on a
// nil-Seq provisioner would crash; surface the misconfiguration at
// construction time.
func NewHostProvisioner(opts HostProvisionerOptions) (*HostProvisioner, error) {
	if opts.Seq == nil {
		return nil, ErrProvisionerNotConfigured
	}
	resolver := opts.Resolver
	if resolver == nil {
		resolver = DefaultDNSResolver{}
	}
	key := opts.BYODHMACKey
	if len(key) == 0 {
		key = defaultHMACKey()
	}
	return &HostProvisioner{
		seq:         opts.Seq,
		resolver:    resolver,
		byodHMACKey: key,
	}, nil
}

// Provision delegates to Sequence.Run + extracts the BootstrapResult
// from the seed step's BootstrapStore.
func (p *HostProvisioner) Provision(ctx context.Context, d *Deployment) (BootstrapResult, error) {
	if err := p.seq.Run(ctx, d); err != nil {
		return BootstrapResult{}, err
	}
	res, _ := p.seq.BootstrapFor(d.ID)
	return res, nil
}

// Upgrade delegates to Sequence.Upgrade.
func (p *HostProvisioner) Upgrade(ctx context.Context, d *Deployment, newImage string, runMigrations bool) error {
	return p.seq.Upgrade(ctx, d, newImage, runMigrations)
}

// Rollback delegates to Sequence.Rollback.
func (p *HostProvisioner) Rollback(ctx context.Context, d *Deployment, previousImage string) error {
	return p.seq.Rollback(ctx, d, previousImage)
}

// Restart delegates to Sequence.Restart.
func (p *HostProvisioner) Restart(ctx context.Context, d *Deployment) error {
	return p.seq.Restart(ctx, d)
}

// Restore delegates to Sequence.Restore.
func (p *HostProvisioner) Restore(ctx context.Context, oldDep *Deployment, toTimestamp time.Time) (*Deployment, error) {
	return p.seq.Restore(ctx, oldDep, toTimestamp)
}

// Destroy delegates to Sequence.Destroy — flips status='destroying'
// and lets the reconciler do the work.
func (p *HostProvisioner) Destroy(ctx context.Context, d *Deployment) error {
	return p.seq.Destroy(ctx, d)
}

// Purge delegates to Sequence.Purge.
func (p *HostProvisioner) Purge(ctx context.Context, d *Deployment) error {
	return p.seq.Purge(ctx, d)
}

// FreezeKeys delegates to Sequence.FreezeKeys.
func (p *HostProvisioner) FreezeKeys(ctx context.Context, d *Deployment, reason string) error {
	return p.seq.FreezeKeys(ctx, d, reason)
}

// AttachDomain — same shape as LocalProvisioner. Phase 12a's adapter
// rewrites the vhost on next reconcile; the HostProvisioner could
// also reach into nginx directly here, but for MVP we keep the
// AttachDomain handler tight: it populates the verification record
// only; the nginx vhost is updated when the next deployment.upgraded
// or deployment.provisioned event triggers a re-render.
func (p *HostProvisioner) AttachDomain(_ context.Context, d *Deployment, dd *DeploymentDomain) error {
	rec := MakeVerificationRecord(d.ID, dd.Domain, p.byodHMACKey)
	dd.VerificationRecord = rec
	dd.VerificationMethod = "dns_txt"
	dd.VerificationToken = rec.RecordValue
	return nil
}

// VerifyDomain runs the DNS TXT challenge. Identical to LocalProvisioner.
func (p *HostProvisioner) VerifyDomain(ctx context.Context, _ *Deployment, dd *DeploymentDomain) (bool, error) {
	if p.resolver == nil {
		return false, ErrProvisionerNotConfigured
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

// DetachDomain — Phase 12e MVP: noop. The nginx vhost re-render
// happens on the next upgrade / restart; the cert SAN list shrinks
// when certbot is re-run by Apply. Hardening (immediate vhost
// re-render + cert re-issue) is a Phase 13+ item.
func (p *HostProvisioner) DetachDomain(_ context.Context, _ *Deployment, _ *DeploymentDomain) error {
	return nil
}

// Compile-time assertion that HostProvisioner satisfies Provisioner.
var _ Provisioner = (*HostProvisioner)(nil)
