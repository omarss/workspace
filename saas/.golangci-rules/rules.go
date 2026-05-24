// Package gorules holds the go-ruleguard rules enforced by gocritic's
// ruleguard checker (see .golangci.yml). The forbidigo linter cannot match
// call expressions with literal arguments — it forbids identifiers — so the
// banned-header-and-secret patterns from AGENTS.md §18.1 / §18.7 live here.
//
// Rules use the ruleguard DSL (github.com/quasilyte/go-ruleguard). The
// matcher `$h.Get("X-Tenant-Id")` matches any expression `e.Get("X-Tenant-Id")`
// regardless of receiver type, which is precisely the foot-gun we want to ban.
//
// Build tag `ruleguard` keeps this file out of regular Go compilation so the
// import of the ruleguard DSL package doesn't add a runtime dependency to the
// platform binaries — gocritic loads it via its own runtime.
//
//go:build ruleguard

package gorules

import "github.com/quasilyte/go-ruleguard/dsl"

// bannedTenantHeader forbids reads of the X-Tenant-Id header at any call
// site. Layer 1 of the eight-layer tenant isolation invariant (AGENTS.md
// §18.1): tenant identity comes from the verified JWT/API key principal, not
// from a client-controllable header.
func bannedTenantHeader(m dsl.Matcher) {
	m.Match(`$h.Get("X-Tenant-Id")`).
		Report(`X-Tenant-Id is rejected by design. Use auth.TenantFromContext (layer 1 of the eight-layer tenant isolation invariant).`)
}

// bannedActingTenantHeader forbids reads of X-Acting-Tenant-Id outside the
// auth middleware that mints operator-impersonation principals. The header
// requires the tenants.impersonate scope; raw reads bypass the scope check.
func bannedActingTenantHeader(m dsl.Matcher) {
	m.Match(`$h.Get("X-Acting-Tenant-Id")`).
		Report(`X-Acting-Tenant-Id requires the tenants.impersonate scope. Route through auth.ActingTenantFromContext, never via header reads at call sites.`)
}

// bannedMockTenantHeader forbids reads of X-Mock-Tenant-Id outside
// internal/platform/auth/middleware_mock.go (the one sanctioned reader). The
// exclusion lives in .golangci.yml; this rule fires everywhere else.
func bannedMockTenantHeader(m dsl.Matcher) {
	m.Match(`$h.Get("X-Mock-Tenant-Id")`).
		Report(`X-Mock-Tenant-Id may only be read inside internal/platform/auth/middleware_mock.go.`)
}

// bannedOpenBaoTokenEnv forbids os.Getenv("OPENBAO_TOKEN") at any call site.
// OpenBao tokens flow through the bao api/v2 client (AppRole / OIDC), never
// through env at call sites. The bootstrap path may use a one-shot
// VAULT_TOKEN env var, which is a different key.
func bannedOpenBaoTokenEnv(m dsl.Matcher) {
	m.Match(`os.Getenv("OPENBAO_TOKEN")`).
		Report(`OpenBao tokens never come from env at call sites. Use the bao api/v2 client (AppRole or short-lived OIDC); see foundations §5.`)
}
