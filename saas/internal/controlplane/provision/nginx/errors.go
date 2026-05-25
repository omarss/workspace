// Package nginx is the control-plane's host nginx adapter. It renders the
// pre-certbot vhost template from deploy/nginx/vhost.conf.tmpl, installs it
// at /etc/nginx/sites-available/saas-<dep_id>.conf, symlinks it into
// sites-enabled/, validates with `nginx -t`, reloads via `sudo nginx -s
// reload`, then optionally invokes certbot to issue the TLS cert.
//
// Phase 12a ships the adapter in isolation: it is NOT wired into the
// LocalProvisioner from Phase 11. Phase 12e composes the full §6.2
// 13-step provisioning sequence with this adapter alongside the k3s,
// Postgres, and OpenBao adapters. The only callers in Phase 12a are:
//
//   - The integration tests in this package.
//   - The `saasctl debug nginx apply <dep_id>` CP-5 verification command
//     (build-tagged `!prod`).
//
// See docs/plans/mvp/13a-host-nginx.md and docs/runbooks/
// control-plane-host-trust.md for the operator-facing contract.
package nginx

import "errors"

// Sentinel errors. The control plane translates these to outbox events and
// (in Phase 12e) to deployment_provision_step.status transitions.
var (
	// ErrSetupNotComplete indicates the operator setup script has not been
	// run on this host yet: sudoers, the shared snippet, or the saas user
	// is missing. The adapter refuses to write any vhost file before setup
	// completes — partial state is worse than no state.
	ErrSetupNotComplete = errors.New("nginx adapter: host setup not complete")

	// ErrConfigTestFailed wraps a non-zero exit from `nginx -t`. The
	// adapter rolls back the new file before returning this so the host's
	// existing nginx config remains valid.
	ErrConfigTestFailed = errors.New("nginx adapter: nginx -t failed")

	// ErrReloadFailed wraps a non-zero exit from `nginx -s reload`. By
	// the time we hit this the new vhost has already passed `-t`, so the
	// adapter does NOT roll back — the file is valid and a subsequent
	// reload (manual or scheduled) will pick it up.
	ErrReloadFailed = errors.New("nginx adapter: nginx -s reload failed")

	// ErrCertbotFailed wraps a non-zero exit from certbot. The adapter
	// returns this without rolling back the vhost — the listener is
	// already up on :80 and can serve ACME challenges; the operator can
	// re-run cert issuance separately.
	ErrCertbotFailed = errors.New("nginx adapter: certbot failed")

	// ErrACMEUnreachable signals that certbot's HTTP-01 challenge failed
	// because the LE servers could not reach :80 on the host. Usually a
	// DNS misconfiguration on the operator's side.
	ErrACMEUnreachable = errors.New("nginx adapter: ACME challenge unreachable")

	// ErrRateLimited signals certbot detected a Let's Encrypt rate-limit
	// response. The caller (Phase 12e) records the failure and lets the
	// destroy reconciler retry after the documented LE quota window.
	ErrRateLimited = errors.New("nginx adapter: certbot rate-limited")

	// ErrWildcardDomain blocks the adapter from passing wildcard SANs to
	// certbot. The MVP uses per-domain HTTP-01 (ADR 008); wildcards
	// require DNS-01 which is not yet wired.
	ErrWildcardDomain = errors.New("nginx adapter: wildcard domains require DNS-01 (deferred to ADR 008 follow-up)")

	// ErrInvalidInput is the generic validation error for ApplyInput /
	// RemoveInput. The caller should treat this as a programming bug.
	ErrInvalidInput = errors.New("nginx adapter: invalid input")
)
