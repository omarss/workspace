package nginx

import (
	"context"
	"fmt"
	"strings"
)

// IssueCert implements Adapter. The flow is:
//
//  1. Validate input (re-checked even though Apply has already done it —
//     the caller may invoke IssueCert separately for re-issuance after
//     a BYOD attach).
//  2. Build argv: --nginx + repeated `-d <domain>` for primary + BYOD +
//     --cert-name <deployment_id> so renewals are tracked per-Deployment.
//  3. Shell out via the Runner.
//  4. Classify common failure modes (rate-limit, ACME unreachable) and
//     return a typed error.
//
// certbot's `--nginx` plugin edits the vhost in place to add the 443
// server block. The Apply step above has already installed the
// pre-certbot vhost; this method extends it with TLS.
//
// IMPORTANT (workspace_personal/CLAUDE.md gotcha #1): never run
// `make -C ../homelab apply-nginx` after this — it overwrites the
// 443 block certbot injected. The Phase 12a adapter manages its own
// per-Deployment vhost files; the homelab's bulk apply is for the
// homelab's own (non-saas) vhosts.
func (a *HostAdapter) IssueCert(ctx context.Context, in ApplyInput) error {
	if err := in.Validate(); err != nil {
		return err
	}
	if in.OpsEmail == "" {
		return fmt.Errorf("%w: ops_email empty (required by certbot --non-interactive)", ErrInvalidInput)
	}

	args := []string{
		"--nginx",
		"--non-interactive",
		"--agree-tos",
		"-m", in.OpsEmail,
		"--cert-name", in.DeploymentID,
		"--keep-until-expiring", // re-runs reuse existing cert if SAN list matches + not yet renewable
		"-d", in.PrimaryDomain,
	}
	for _, d := range in.CustomDomains {
		args = append(args, "-d", d)
	}

	err := a.Runner.Run(ctx, a.CertbotBin, args...)
	if err == nil {
		return nil
	}

	// Classify the failure for the caller. We do not parse certbot's
	// exit code — it returns 1 for most failures; the discriminator is
	// the stderr text the Runner has wrapped into the error message.
	msg := err.Error()
	switch {
	case containsAny(msg, "too many certificates", "rateLimited", "rate limit"):
		return fmt.Errorf("%w: %w", ErrRateLimited, err)
	case containsAny(msg, "connection refused", "Timeout during connect", "Fetching http", "unauthorized"):
		// HTTP-01 challenge couldn't be served. Either port 80 is blocked
		// (geofence allows :80 globally — should not be us) or DNS does
		// not resolve to the host's external IP.
		return fmt.Errorf("%w: %w", ErrACMEUnreachable, err)
	default:
		return fmt.Errorf("%w: %w", ErrCertbotFailed, err)
	}
}

// containsAny is a case-insensitive substring contains for any of the
// needles. We avoid regexp here because certbot's error surface is
// stable enough for plain matches and we don't want the dependency.
func containsAny(haystack string, needles ...string) bool {
	hay := strings.ToLower(haystack)
	for _, n := range needles {
		if strings.Contains(hay, strings.ToLower(n)) {
			return true
		}
	}
	return false
}

// Ensure compile-time conformance.
var _ Adapter = (*HostAdapter)(nil)
