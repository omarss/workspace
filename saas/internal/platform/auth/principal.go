// Package auth — Principal is the verified caller, populated by auth
// middleware (mock in Phase 2/3, JWT-verified in Phase 5). Higher layers
// read tenant, actor, scopes only through the helpers in this file —
// header reads are physically banned by the §18.1 invariant.
package auth

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
)

// ActorType enumerates the principal kinds. Mirrors AGENTS.md §8.6 audit fields.
type ActorType string

// The set of allowed actor types. Operator impersonation is its own kind so
// audit rows can distinguish a direct operator action from a tenant-scoped
// one performed on the operator's behalf.
const (
	ActorUser                  ActorType = "user"
	ActorAPIKey                ActorType = "api_key"
	ActorOperator              ActorType = "operator"
	ActorOperatorImpersonation ActorType = "operator_impersonation"
	ActorSystem                ActorType = "system"
)

// Principal is the verified caller. Populated by auth middleware; never
// constructed by handler code.
type Principal struct {
	ActorType ActorType
	ActorID   string // user_<ulid>, apik_<ulid>, op_<ulid>, etc.
	TenantID  string // empty for operator without impersonation
	Scopes    []string
	IPAddress string
	UserAgent string
	RequestID string

	// Phase 13 — operator MFA + step-up auth fields.
	//
	// AMR (Authentication Methods References, RFC 8176) is the set of
	// methods used at the upstream IdP (e.g. {pwd, otp, hwk}). The
	// step-up middleware reads HasStrongAMR to decide whether the
	// caller has cleared the MFA bar; the audit subscriber carries
	// the array into operator_audit_event.metadata.
	//
	// ACR (Authentication Context Class Reference, RFC 6711 / OIDC
	// core) is the level-of-assurance string. Per the operators-realm
	// `acr.loa.map`, "gold" == MFA-fresh, "silver" == password-only.
	// Step-up checks acr == "gold" AND AuthTime within 5 min.
	//
	// AuthTime is the seconds-since-epoch of the upstream password /
	// MFA event (OIDC standard `auth_time` claim). Time.IsZero() means
	// the token did not carry it — verifiers must refuse step-up in
	// that case rather than treat it as "now".
	//
	// Additional impersonation fields are populated when the data-plane
	// verifier sees `actor_type=operator_impersonation`:
	//   - ImpersonationSessionID is the impses_<ulid> from the
	//     control-plane impersonation_session row used to revoke.
	//   - ImpersonatedTenantID equals TenantID for impersonation tokens
	//     but is also surfaced explicitly so audit rows can distinguish
	//     "the operator was acting AS this tenant" from "this tenant
	//     called itself".
	AMR                     []string
	ACR                     string
	AuthTime                time.Time
	ImpersonationSessionID  string
	ImpersonatedTenantID    string
	ImpersonationReason     string
	ImpersonationActorEmail string
}

// HasScope reports whether the principal carries the given OAuth-style scope.
// Linear scan is fine — scope lists are short (< 20).
func (p Principal) HasScope(s string) bool {
	for _, sc := range p.Scopes {
		if sc == s {
			return true
		}
	}
	return false
}

// strongAMRMethods enumerates the AMR values that count as "phishing-resistant
// MFA" for step-up purposes. Conservative — we accept any IdP-asserted MFA
// signal (OTP, hardware key, software key, generic mfa). The set follows
// RFC 8176 vocabulary; tighten to webauthn-only via a Phase 14+ ADR if needed.
//
// Defined as a package-level variable so test code (and future config) can
// override it; the production codepath only reads from this slice.
var strongAMRMethods = map[string]struct{}{
	"otp":      {},
	"hwk":      {},
	"swk":      {},
	"mfa":      {},
	"webauthn": {},
	"hwa":      {},
	"fpt":      {},
}

// HasStrongAMR reports whether the principal's AMR slice contains at least
// one MFA-class method. Used by the step-up middleware to refuse destructive
// operations performed under a password-only token.
func (p Principal) HasStrongAMR() bool {
	for _, m := range p.AMR {
		if _, ok := strongAMRMethods[m]; ok {
			return true
		}
	}
	return false
}

// FormatActor returns the "<actor_type>:<actor_id>" string used in audit
// metadata and structured log fields.
func (p Principal) FormatActor() string {
	return fmt.Sprintf("%s:%s", p.ActorType, p.ActorID)
}

type principalKey struct{}

// WithPrincipal returns a child context carrying p. Only auth middleware
// should call this; handlers read via PrincipalFromContext.
func WithPrincipal(ctx context.Context, p Principal) context.Context {
	return context.WithValue(ctx, principalKey{}, p)
}

// PrincipalFromContext returns the verified principal, if any.
func PrincipalFromContext(ctx context.Context) (Principal, bool) {
	v, ok := ctx.Value(principalKey{}).(Principal)
	return v, ok
}

// Additional sentinel errors for richer principal-aware checks. The Phase 2
// trio (ErrUnauthorized, ErrCrossTenant) lives in tenant.go.
var (
	// ErrMissingScope — principal authenticated but lacks the OAuth scope
	// required to call the endpoint.
	ErrMissingScope = errors.New("auth: missing scope")
	// ErrDisabled — principal exists but is disabled (e.g. user.disabled,
	// api_key.revoked).
	ErrDisabled = errors.New("auth: principal disabled")
	// ErrIPNotAllowed — principal is API-key-bound to an IP allowlist that
	// rejects this request's source address.
	ErrIPNotAllowed = errors.New("auth: ip not allowlisted")
	// ErrKeyRevoked — API key was revoked. Distinct from ErrDisabled so the
	// audit row carries the precise reason.
	ErrKeyRevoked = errors.New("auth: api key revoked")
	// ErrKeyExpired — API key TTL elapsed.
	ErrKeyExpired = errors.New("auth: api key expired")
	// ErrStepUpRequired — caller's token lacks fresh MFA (Phase 13). The
	// operator must re-authenticate (kc_acr=gold OR max_age=0) and retry.
	ErrStepUpRequired = errors.New("auth: step-up authentication required")
	// ErrImpersonationSessionRevoked — operator-impersonation token's
	// backing impersonation_session row has been ended_at != null, even
	// though the JWT itself has not yet hit exp.
	ErrImpersonationSessionRevoked = errors.New("auth: impersonation session revoked")
)

// RequireScope returns ErrMissingScope when the principal lacks the named
// scope, ErrUnauthorized when no principal is in context.
func RequireScope(ctx context.Context, scope string) error {
	p, ok := PrincipalFromContext(ctx)
	if !ok {
		return ErrUnauthorized
	}
	if !p.HasScope(scope) {
		return ErrMissingScope
	}
	return nil
}

// ActingTenantFromContext returns the effective tenant the caller is acting
// on. Equals TenantFromContext for normal callers; equals the impersonation
// target when an operator carries the tenants.impersonate scope AND the
// middleware honoured X-Acting-Tenant-Id. Handlers must use this reader for
// X-Acting-Tenant-Id-aware paths; everything else uses TenantFromContext.
func ActingTenantFromContext(ctx context.Context) (string, bool) {
	if act, ok := ctx.Value(actingTenantKey{}).(string); ok && act != "" {
		return act, true
	}
	return TenantFromContext(ctx)
}

type actingTenantKey struct{}

// WithActingTenant is only called by auth middleware after the scope check.
// Never call from handler code — pass the value through the principal.
func WithActingTenant(ctx context.Context, tenantID string) context.Context {
	return context.WithValue(ctx, actingTenantKey{}, tenantID)
}

// ParseScopes splits a space- or comma-separated scope claim into a slice.
// JWT issuers use both delimiters in the wild; we accept either.
func ParseScopes(claim string) []string {
	fields := strings.FieldsFunc(claim, func(r rune) bool { return r == ' ' || r == ',' })
	out := make([]string, 0, len(fields))
	for _, s := range fields {
		if s = strings.TrimSpace(s); s != "" {
			out = append(out, s)
		}
	}
	return out
}
