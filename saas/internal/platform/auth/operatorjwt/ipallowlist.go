// Phase 13 — operator IP allowlist enforcement.
//
// AGENTS.md §18.4 lists "IP allowlist: configurable per operator" as a
// hard requirement. The allowlist is a list of CIDR strings on the
// operator row (migration 000003); an empty list means "no restriction"
// — convenient for the bootstrap operator that has to tighten its own
// allowlist before locking down the rest. Once non-empty the middleware
// refuses requests whose source IP is not in any listed CIDR with
// 403 + ip-not-allowlisted (RFC 9457).
//
// Source IP detection: prefers chi/middleware's RequestID-style read of
// `X-Real-IP` (set by the homelab nginx, which strips any spoofed
// header from the client before forwarding). If the header is absent
// the middleware falls back to r.RemoteAddr — only meaningful in tests
// or when the binary is somehow exposed directly. The header read is
// gated on a TrustedProxies CIDR list passed at construction time so
// the spoofing CVE that retired chi's RealIP can't bite us.

package operatorjwt

import (
	"context"
	"net"
	"net/http"
	"strings"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/problem"
)

// OperatorLookup is the minimal interface the IP-allowlist middleware
// needs from the operator repository. Keeping the surface tiny lets
// tests pass a map-backed fake; the production wiring binds it to the
// sqlc-generated GetOperatorByKeycloakUserID / GetOperatorByID.
type OperatorLookup interface {
	GetOperatorIPAllowlist(ctx context.Context, operatorID string) ([]string, error)
}

// IPAllowlistOptions configures the middleware.
//
// TrustedProxies is the list of CIDRs whose `X-Real-IP` header the
// middleware will honour. Empty means trust nothing — the middleware
// always reads r.RemoteAddr. The homelab production CIDR is set in
// cmd/controlplane to the nginx reverse-proxy address.
type IPAllowlistOptions struct {
	TrustedProxies []string
}

// IPAllowlistMiddleware returns an http.Handler-shaped middleware that
// looks up the principal's operator row and enforces its ip_allowlist.
// Non-operator principals (or absent principals) pass through — this
// middleware only gates operator paths.
func IPAllowlistMiddleware(lookup OperatorLookup, opts IPAllowlistOptions) func(http.Handler) http.Handler {
	trusted := mustParseCIDRs(opts.TrustedProxies)
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			p, ok := auth.PrincipalFromContext(r.Context())
			if !ok || p.ActorType != auth.ActorOperator || p.ActorID == "" {
				next.ServeHTTP(w, r)
				return
			}
			allow, err := lookup.GetOperatorIPAllowlist(r.Context(), p.ActorID)
			if err != nil {
				// A repo lookup failure is a server problem, not the
				// caller's. We log via the structured logger above the
				// middleware and refuse with 401 — "unable to verify
				// identity" — rather than 500, so probing the endpoint
				// can't surface backend errors.
				writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized,
					"operator lookup failed", "")
				return
			}
			if len(allow) == 0 {
				next.ServeHTTP(w, r)
				return
			}
			ip := extractClientIP(r, trusted)
			if ip == nil {
				writeProblem(w, r, http.StatusForbidden, problem.TypeIPNotAllowed,
					"source IP could not be determined", "")
				return
			}
			if !cidrAllowed(ip, allow) {
				writeProblem(w, r, http.StatusForbidden, problem.TypeIPNotAllowed,
					"source IP outside operator allowlist", "")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// cidrAllowed reports whether ip falls within at least one of the CIDR
// strings in allow. Bad CIDRs in the list are skipped — the operator
// repo validates them at write time so this is belt-and-braces.
func cidrAllowed(ip net.IP, allow []string) bool {
	for _, cidr := range allow {
		_, n, err := net.ParseCIDR(cidr)
		if err != nil {
			continue
		}
		if n.Contains(ip) {
			return true
		}
	}
	return false
}

// extractClientIP returns the request's source IP. When the immediate
// RemoteAddr matches one of the trusted-proxy CIDRs AND `X-Real-IP` is
// set, the header is honoured; otherwise the RemoteAddr ip:port is
// stripped to its IP component. Returns nil on malformed input.
func extractClientIP(r *http.Request, trusted []*net.IPNet) net.IP {
	remote := r.RemoteAddr
	if h, _, err := net.SplitHostPort(remote); err == nil {
		remote = h
	}
	remoteIP := net.ParseIP(remote)
	if remoteIP != nil && isTrusted(remoteIP, trusted) {
		if hdr := strings.TrimSpace(r.Header.Get("X-Real-IP")); hdr != "" {
			if parsed := net.ParseIP(hdr); parsed != nil {
				return parsed
			}
		}
	}
	return remoteIP
}

func isTrusted(ip net.IP, trusted []*net.IPNet) bool {
	for _, n := range trusted {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}

func mustParseCIDRs(in []string) []*net.IPNet {
	out := make([]*net.IPNet, 0, len(in))
	for _, c := range in {
		_, n, err := net.ParseCIDR(c)
		if err == nil {
			out = append(out, n)
		}
	}
	return out
}
