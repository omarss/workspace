package nginx

import (
	"context"
	"fmt"
	"strings"
)

// Adapter is the host-nginx-side of the deployments.Provisioner. It is a
// narrow interface (just the three lifecycle verbs the nginx layer
// touches) so the Phase 12e composite provisioner can stitch it together
// with the k3s, Postgres, and OpenBao adapters without leaking
// nginx-specific knobs into the wider provisioner contract.
type Adapter interface {
	// Apply renders + installs a vhost for a Deployment. Idempotent:
	// re-applying with the same inputs produces the same file content and
	// is a no-op modulo nginx reload. Atomic: a failed `nginx -t` rolls
	// back the file before the error returns, so the host config stays
	// valid on partial failure.
	Apply(ctx context.Context, in ApplyInput) error

	// IssueCert calls certbot --nginx non-interactively. Safe to retry:
	// certbot caches an unexpired cert with matching SANs and skips the
	// ACME order entirely, so there is no LE rate-limit risk from retry.
	IssueCert(ctx context.Context, in ApplyInput) error

	// Remove deletes the symlink + the underlying vhost file and reloads
	// nginx. Cert deletion is left to the caller (Phase 12e composes the
	// destroy sequence — cert delete runs only after retention expires).
	Remove(ctx context.Context, in RemoveInput) error
}

// ApplyInput is the data the renderer needs to produce one vhost. The
// caller (Phase 12e) constructs this from the Deployment row + the
// verified DeploymentDomain rows; the adapter does NOT read the database.
type ApplyInput struct {
	DeploymentID  string
	PrimaryDomain string
	CustomDomains []string
	NodePort      int
	OpsEmail      string
}

// Validate enforces the Phase 12a input contract.
//
// We intentionally keep the rules tight — every value here ends up
// concatenated into a shell argv for certbot or rendered into nginx
// config, so a sloppy field is a real risk.
func (in ApplyInput) Validate() error {
	if in.DeploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(in.DeploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, in.DeploymentID)
	}
	if in.PrimaryDomain == "" {
		return fmt.Errorf("%w: primary_domain empty", ErrInvalidInput)
	}
	if strings.ContainsAny(in.PrimaryDomain, " \t\n\r\"';") {
		return fmt.Errorf("%w: primary_domain has shell-unsafe characters", ErrInvalidInput)
	}
	if strings.HasPrefix(in.PrimaryDomain, "*.") {
		return fmt.Errorf("%w: primary %q", ErrWildcardDomain, in.PrimaryDomain)
	}
	if in.NodePort < 30000 || in.NodePort > 32767 {
		return fmt.Errorf("%w: node_port %d out of k3s nodeport range 30000-32767", ErrInvalidInput, in.NodePort)
	}
	for _, d := range in.CustomDomains {
		if d == "" {
			return fmt.Errorf("%w: custom domain empty", ErrInvalidInput)
		}
		if strings.HasPrefix(d, "*.") {
			return fmt.Errorf("%w: custom %q", ErrWildcardDomain, d)
		}
		if strings.ContainsAny(d, " \t\n\r\"';") {
			return fmt.Errorf("%w: custom domain %q has shell-unsafe characters", ErrInvalidInput, d)
		}
	}
	return nil
}

// RemoveInput is what Remove takes. We separate it so the caller is forced
// to think about whether cert deletion happens (it does not, at this
// layer — see Adapter.Remove docs).
type RemoveInput struct {
	DeploymentID string
}

// Validate enforces the Phase 12a input contract for RemoveInput. Same
// safety rules as ApplyInput.Validate for the deployment_id field.
func (in RemoveInput) Validate() error {
	if in.DeploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	if !isSafeDeploymentID(in.DeploymentID) {
		return fmt.Errorf("%w: deployment_id %q has unsafe characters", ErrInvalidInput, in.DeploymentID)
	}
	return nil
}

// isSafeDeploymentID restricts deployment IDs to the alphabet the platform
// already enforces (ULID-style with an optional `dep_` prefix). We use
// this value inside file paths, sudoers globs (indirectly, via certbot
// `--cert-name`), and nginx access_log paths.
func isSafeDeploymentID(s string) bool {
	if s == "" || len(s) > 64 {
		return false
	}
	for _, r := range s {
		switch {
		case r >= 'a' && r <= 'z':
		case r >= 'A' && r <= 'Z':
		case r >= '0' && r <= '9':
		case r == '_' || r == '-':
		default:
			return false
		}
	}
	return true
}
