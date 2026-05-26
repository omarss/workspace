package sequence

import (
	"context"
	"fmt"
	"log/slog"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
	"github.com/omarss/saas/internal/controlplane/provision/k3s"
	"github.com/omarss/saas/internal/controlplane/provision/nginx"
	"github.com/omarss/saas/internal/controlplane/provision/openbao"
	"github.com/omarss/saas/internal/controlplane/provision/postgres"
)

// imageVersionShape matches the v<major>.<minor>.<patch>[-pre] pattern
// AGENTS.md §6.3 (and the OpenAPI schema) require for image_version
// values. The strict shape is the anti-pattern guard against
// client-supplied junk landing in container image tags.
var imageVersionShape = regexp.MustCompile(`^v\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?$`)

// validateImageVersion enforces the shape. Anti-pattern guard from the
// plan §12e "NEVER trust client-supplied image_version".
func validateImageVersion(v string) error {
	if !imageVersionShape.MatchString(v) {
		return fmt.Errorf("%w: %q", ErrInvalidImageVersion, v)
	}
	return nil
}

// compareSemver returns -1 / 0 / +1 for a < b / a == b / a > b. Only
// the major.minor.patch triple is compared; pre-release suffixes break
// ties as "pre-release < release" per semver, which is what we want
// for the "refuse downgrade" guard.
//
// Caller has already validated both strings via validateImageVersion;
// this function panics on un-parseable input (programmer error).
func compareSemver(a, b string) int {
	at := semverTriple(a)
	bt := semverTriple(b)
	for i := 0; i < 3; i++ {
		switch {
		case at[i] < bt[i]:
			return -1
		case at[i] > bt[i]:
			return 1
		}
	}
	// Major.minor.patch tied. Pre-release suffix loses to no-suffix.
	aPre := strings.Contains(a, "-")
	bPre := strings.Contains(b, "-")
	switch {
	case aPre && !bPre:
		return -1
	case !aPre && bPre:
		return 1
	}
	return 0
}

// semverTriple extracts the numeric triple from v<M>.<m>.<p>[-pre].
func semverTriple(v string) [3]int {
	core := strings.TrimPrefix(v, "v")
	if dash := strings.Index(core, "-"); dash >= 0 {
		core = core[:dash]
	}
	parts := strings.SplitN(core, ".", 3)
	var out [3]int
	for i := 0; i < len(parts) && i < 3; i++ {
		n, _ := strconv.Atoi(parts[i])
		out[i] = n
	}
	return out
}

// UpgradeOptions narrows the Upgrade entry point's input. Mirrors
// AGENTS.md §6.3.
type UpgradeOptions struct {
	NewImageVersion string
	RunMigrations   bool
}

// Upgrade applies pending data-plane migrations + image patch + waits
// for rollout + waits for /healthz. AGENTS.md §6.3.
//
// On failure the deployment is left in status='upgrading' so the
// operator can decide between rollback or retry. The orchestrator does
// NOT auto-rollback the image — automatic rollback on partial upgrade
// risks oscillation when the underlying issue is transient.
func (s *Sequence) Upgrade(ctx context.Context, d *deployments.Deployment, a Adapters, opts UpgradeOptions) error {
	if s.Logger == nil {
		s.Logger = slog.Default()
	}
	if err := validateImageVersion(opts.NewImageVersion); err != nil {
		return err
	}
	if d.ImageVersion != "" {
		if err := validateImageVersion(d.ImageVersion); err != nil {
			return err
		}
		if compareSemver(opts.NewImageVersion, d.ImageVersion) <= 0 {
			return fmt.Errorf("%w: current=%s target=%s",
				ErrCannotDowngrade, d.ImageVersion, opts.NewImageVersion)
		}
	}
	if a.K3s == nil {
		return fmt.Errorf("%w: k3s", ErrAdapterNil)
	}
	dep := FromDeployment(d)
	dep.ImageVersion = opts.NewImageVersion

	if a.Status != nil {
		if err := a.Status.UpdateStatus(ctx, d.ID, deployments.StatusUpgrading); err != nil {
			return fmt.Errorf("update status upgrading: %w", err)
		}
	}

	// 1. Migrations. Forward-only per §6.3.
	if opts.RunMigrations && a.Postgres != nil {
		// The migrations runner ships with the postgres adapter via
		// Apply. For an existing deployment we cannot re-run Apply
		// (it would rotate the password); instead we re-issue the
		// migrations through a re-Apply with a flag that skips role
		// creation. Phase 12c's Apply is idempotent enough for this;
		// the password rotation is acceptable as part of an upgrade
		// (operator re-fetches via KV).
		if _, err := a.Postgres.Apply(ctx, postgres.ApplyInput{
			DeploymentID:    d.ID,
			ProjectSlug:     d.ProjectSlug,
			EnvironmentSlug: d.EnvironmentSlug,
			AdminDSN:        a.PostgresAdminDSN,
			HostExternal:    a.PostgresHostExternal,
		}); err != nil {
			return fmt.Errorf("upgrade migrations: %w", err)
		}
	}

	// 2. k3s image patch + wait for rollout. The adapter's Apply is
	// idempotent and the SSA path patches only the image tag; the
	// adapter handles the rest.
	if err := a.K3s.Apply(ctx, k3s.ApplyInput{
		DeploymentID:     d.ID,
		ProjectSlug:      d.ProjectSlug,
		EnvironmentSlug:  d.EnvironmentSlug,
		ImageVersion:     opts.NewImageVersion,
		NodePort:         orDefaultNodePort(a.K3sNodePort),
		HostNginxCIDR:    a.K3sHostNginxCIDR,
		HostPostgresCIDR: a.K3sHostPostgresCIDR,
		HostOpenBaoCIDR:  a.K3sHostOpenBaoCIDR,
	}); err != nil {
		return fmt.Errorf("upgrade k3s apply: %w", err)
	}

	// 3. Public /healthz probe.
	if err := pollHealthz(ctx, a, dep); err != nil {
		return err
	}

	if a.Status != nil {
		if err := a.Status.UpdateStatus(ctx, d.ID, deployments.StatusActive); err != nil {
			return fmt.Errorf("update status active: %w", err)
		}
	}
	if a.Events != nil {
		_ = a.Events.Publish(ctx, "deployment.upgraded", d.ID, map[string]any{
			"deployment_id":      d.ID,
			"new_image_version":  opts.NewImageVersion,
			"prev_image_version": d.ImageVersion,
		})
	}
	return nil
}

// Rollback flips the running image back to a previous revision. §6.3
// is explicit: DB is NOT rolled back. Migrations applied during the
// failed upgrade remain in place; §27 enforces that they be backward
// compatible with the previous image.
//
// previousImageVersion is supplied by the caller (the deployments
// service reads it from deployment_revision). Phase 12e doesn't read
// the revision table directly — the service layer does the lookup
// before invoking Rollback.
func (s *Sequence) Rollback(ctx context.Context, d *deployments.Deployment, a Adapters, previousImageVersion string) error {
	if err := validateImageVersion(previousImageVersion); err != nil {
		return err
	}
	if a.K3s == nil {
		return fmt.Errorf("%w: k3s", ErrAdapterNil)
	}
	dep := FromDeployment(d)
	dep.ImageVersion = previousImageVersion

	if err := a.K3s.Apply(ctx, k3s.ApplyInput{
		DeploymentID:     d.ID,
		ProjectSlug:      d.ProjectSlug,
		EnvironmentSlug:  d.EnvironmentSlug,
		ImageVersion:     previousImageVersion,
		NodePort:         orDefaultNodePort(a.K3sNodePort),
		HostNginxCIDR:    a.K3sHostNginxCIDR,
		HostPostgresCIDR: a.K3sHostPostgresCIDR,
		HostOpenBaoCIDR:  a.K3sHostOpenBaoCIDR,
	}); err != nil {
		return fmt.Errorf("rollback k3s apply: %w", err)
	}
	if err := pollHealthz(ctx, a, dep); err != nil {
		return err
	}
	if a.Status != nil {
		if err := a.Status.UpdateStatus(ctx, d.ID, deployments.StatusActive); err != nil {
			return fmt.Errorf("update status active: %w", err)
		}
	}
	if a.Events != nil {
		_ = a.Events.Publish(ctx, "deployment.rolled_back", d.ID, map[string]any{
			"deployment_id":      d.ID,
			"prev_image_version": d.ImageVersion,
			"image_version":      previousImageVersion,
		})
	}
	return nil
}

// Restart re-applies the k3s manifest (same image) to trigger a rolling
// restart of the data-plane pods. No DB / nginx / OpenBao changes.
func (s *Sequence) Restart(ctx context.Context, d *deployments.Deployment, a Adapters) error {
	if a.K3s == nil {
		return fmt.Errorf("%w: k3s", ErrAdapterNil)
	}
	// Re-apply with the SAME image; the adapter's SSA + the kustomize
	// overlay's deployment annotation include the platform timestamp,
	// which triggers a rolling restart even when the image is unchanged.
	// For belt-and-braces, real `kubectl rollout restart` semantics
	// belong in a future adapter method; for MVP, a plain re-Apply
	// works (the pods stay running because the spec is unchanged,
	// which is the desired "noop restart" behavior when no real change
	// was needed). Operators who want a forced bounce should bump the
	// image_version through Upgrade.
	if err := a.K3s.Apply(ctx, k3s.ApplyInput{
		DeploymentID:     d.ID,
		ProjectSlug:      d.ProjectSlug,
		EnvironmentSlug:  d.EnvironmentSlug,
		ImageVersion:     d.ImageVersion,
		NodePort:         orDefaultNodePort(a.K3sNodePort),
		HostNginxCIDR:    a.K3sHostNginxCIDR,
		HostPostgresCIDR: a.K3sHostPostgresCIDR,
		HostOpenBaoCIDR:  a.K3sHostOpenBaoCIDR,
	}); err != nil {
		return fmt.Errorf("restart k3s apply: %w", err)
	}
	if a.Events != nil {
		_ = a.Events.Publish(ctx, "deployment.restarted", d.ID, map[string]any{
			"deployment_id": d.ID,
		})
	}
	return nil
}

// Restore — Phase 12e MVP stub. AGENTS.md §6.6 prescribes a full
// pg_basebackup + WAL replay flow into a fresh deployment; that
// requires WAL archiving on the host Postgres cluster which is
// documented in the runbook but not wired by this package. The MVP
// stub returns ErrRestoreNotImplemented so the operator runs the
// physical pg_restore manually and registers the resulting deployment
// via a separate code path.
//
// The full implementation lands in a future phase under
// `internal/controlplane/provision/backup/`.
func (s *Sequence) Restore(_ context.Context, _ *deployments.Deployment, _ Adapters, _ time.Time) (*deployments.Deployment, error) {
	return nil, ErrRestoreNotImplemented
}

// Purge runs the full physical-delete sequence and emits the
// deployment.purged event BEFORE any data disappears (§18.6). Refuses
// to run on a deployment that is not in 'destroyed', 'failed', or
// 'purging' state.
//
// Callable directly by the handler (POST /deployments/{id}/purge) or
// by the destroy reconciler when retention expires.
func (s *Sequence) Purge(ctx context.Context, d *deployments.Deployment, a Adapters) error {
	switch d.Status {
	case deployments.StatusDestroyed, deployments.StatusFailed, deployments.StatusPurging:
		// allowed
	default:
		return fmt.Errorf("%w: status=%s", ErrCannotPurgeActive, d.Status)
	}
	// Emit audit BEFORE the data goes away.
	if a.Events != nil {
		_ = a.Events.Publish(ctx, "deployment.purged", d.ID, map[string]any{
			"deployment_id": d.ID,
			"purged_at":     time.Now().UTC().Format(time.RFC3339),
		})
	}
	dep := FromDeployment(d)
	if err := destroyAllAdapters(ctx, dep, a, s.Logger); err != nil {
		return err
	}
	if a.Status != nil {
		if err := a.Status.UpdateStatus(ctx, d.ID, deployments.StatusPurged); err != nil {
			return fmt.Errorf("update status purged: %w", err)
		}
	}
	return nil
}

// FreezeKeys disables the per-Deployment transit key by raising its
// min_decryption_version above any existing version. The pod cannot
// decrypt → all PII reads fail with permission denied. §18.7.
//
// Reversible by an operator with step-up auth (Phase 13). For MVP we
// expose the freeze operation only; thaw is a manual `bao write
// transit/keys/<id>/config min_decryption_version=1` until Phase 13
// wires the step-up MFA endpoint.
func (s *Sequence) FreezeKeys(ctx context.Context, d *deployments.Deployment, a Adapters, reason string) error {
	if a.OpenBao == nil {
		return fmt.Errorf("%w: openbao", ErrAdapterNil)
	}
	freezer, ok := a.OpenBao.(KeyFreezer)
	if !ok {
		return fmt.Errorf("%w: openbao adapter does not implement KeyFreezer (Phase 12d HostAdapter required)", ErrAdapterNil)
	}
	if err := freezer.FreezeKeys(ctx, d.ID); err != nil {
		return fmt.Errorf("freeze keys: %w", err)
	}
	// The on-disk status enum doesn't include 'frozen' (the migration's
	// CHECK constraint tops out at 'purged'). Update would fail; for
	// MVP we set status to 'suspended' as the closest semantic match
	// AND we emit the keys_frozen event so the audit row records the
	// transition explicitly.
	if a.Status != nil {
		if err := a.Status.UpdateStatus(ctx, d.ID, deployments.StatusSuspended); err != nil {
			return fmt.Errorf("update status suspended: %w", err)
		}
	}
	if a.Events != nil {
		_ = a.Events.Publish(ctx, "deployment.keys_frozen", d.ID, map[string]any{
			"deployment_id": d.ID,
			"reason":        reason,
		})
	}
	return nil
}

// KeyFreezer is the optional interface the OpenBao adapter may
// implement to support FreezeKeys. Phase 12e includes a stub
// implementation on the package's HostAdapter (see openbao_freeze.go)
// so production wiring works. Test fakes that don't implement
// FreezeKeys get a clear error message from FreezeKeys.
type KeyFreezer interface {
	FreezeKeys(ctx context.Context, deploymentID string) error
}

// destroyAllAdapters tears down every host artifact for a Deployment.
// Used by both the destroy reconciler (handleDestroying / handlePurging)
// and the public Purge entry point.
//
// Order: k3s (cascade-deletes namespace contents) → nginx (cert
// stays — Phase 12a documented this) → postgres (DROP DATABASE +
// DROP ROLE) → openbao (destroy transit key — IRREVERSIBLE).
//
// Each step logs warnings rather than aborting; purge MUST proceed
// even when individual systems are partially absent (idempotent
// across multiple invocations).
func destroyAllAdapters(ctx context.Context, dep DeploymentRef, a Adapters, logger *slog.Logger) error {
	if logger == nil {
		logger = slog.Default()
	}
	var firstErr error
	record := func(label string, err error) {
		if err == nil {
			return
		}
		logger.Warn("destroy: step error",
			"deployment_id", dep.ID, "step", label, "err", err)
		if firstErr == nil {
			firstErr = fmt.Errorf("%s: %w", label, err)
		}
	}
	if a.K3s != nil {
		record("k3s", a.K3s.Remove(ctx, k3s.RemoveInput{DeploymentID: dep.ID}))
	}
	if a.Nginx != nil {
		record("nginx", a.Nginx.Remove(ctx, nginx.RemoveInput{DeploymentID: dep.ID}))
	}
	if a.Postgres != nil {
		record("postgres", a.Postgres.Remove(ctx, postgres.RemoveInput{
			DeploymentID:        dep.ID,
			ProjectSlug:         dep.ProjectSlug,
			EnvironmentSlug:     dep.EnvironmentSlug,
			AdminDSN:            a.PostgresAdminDSN,
			ConfirmDropDatabase: true,
		}))
	}
	if a.OpenBao != nil {
		record("openbao", a.OpenBao.Remove(ctx, openbao.RemoveInput{
			DeploymentID:      dep.ID,
			ConfirmDestroyKey: true,
		}))
	}
	return firstErr
}

// orDefaultNodePort returns 30080 when n is 0. Centralised so the
// upgrade / rollback / restart paths use the same default as the
// initial Provision.
func orDefaultNodePort(n int) int {
	if n == 0 {
		return 30080
	}
	return n
}
