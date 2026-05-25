package deployments

import (
	"context"
	"net"
)

// DefaultDNSResolver wraps net.DefaultResolver. ADR 015 forbids letting
// callers inject an arbitrary resolver — that would let a malicious
// operator spoof a verification by pointing the resolver at a host they
// control. Tests use the in-package fake (deployments_test); production
// uses this.
type DefaultDNSResolver struct{}

// LookupTXT delegates to the process-wide net.DefaultResolver.
func (DefaultDNSResolver) LookupTXT(ctx context.Context, name string) ([]string, error) {
	return net.DefaultResolver.LookupTXT(ctx, name)
}
