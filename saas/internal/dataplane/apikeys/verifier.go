package apikeys

import (
	"context"
	"crypto/subtle"
	"errors"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
)

// Verifier authenticates a presented bearer against the api_key table.
// Composed by middleware.go and the cmd/dataplane wiring. The service
// owns the verifier so it can reuse the same indexer + repo without
// the auth chain needing to import the persistence layer.
type Verifier struct {
	svc     *Service
	buffer  *UsageBuffer
	limiter *RateLimiter
}

// NewVerifier wires the auth-time verifier. usage may be nil (no
// last_used_at batching — used by tests). limiter may be nil (no rate
// limiting — also used by tests).
func NewVerifier(svc *Service, usage *UsageBuffer, limiter *RateLimiter) *Verifier {
	return &Verifier{svc: svc, buffer: usage, limiter: limiter}
}

// VerifyResult is the structured outcome of a verifier call.
// Principal is populated on success. The status fields steer the
// middleware response.
type VerifyResult struct {
	Principal     auth.Principal
	RateLimitInfo *RateLimitInfo
	APIKey        APIKey
}

// RateLimitInfo carries the headers the middleware echoes when the
// limiter trips. Surfaced separately so the caller can decide whether
// to emit RateLimit-* headers on success too (yes, when the bucket has
// remaining capacity).
type RateLimitInfo struct {
	Limit      int
	Remaining  int
	RetryAfter int // seconds
}

// Verify authenticates bearer against the api_key table and the
// envelope-encrypted prefix index. The flow is:
//
// Parse the bearer into (env, prefix, full secret); HMAC the prefix
// into a bucket and SELECT candidate rows. For each candidate decrypt
// the envelope (kid-verified) and constant-time-compare against the
// HMAC bucket — defence in depth. Then argon-verify the full bearer;
// during grace, fall through to the predecessor PHC. Finally check
// status / expiry / ip allowlist / rate limit, construct the
// principal, and record usage.
//
// remoteAddr is the request RemoteAddr (host:port or just host); IP
// allowlist matching extracts the host portion.
//
// Errors returned to the caller:
//
//	auth.ErrUnauthorized — bearer shape / no candidate / argon mismatch / revoked / expired
//	auth.ErrIPNotAllowed — bearer valid but source IP outside allowlist
//	auth.ErrKeyRevoked   — bearer matches a revoked row
//	auth.ErrKeyExpired   — bearer matches an expired row or a rotated row past grace
func (v *Verifier) Verify(ctx context.Context, bearer, remoteAddr string) (VerifyResult, error) {
	_, visiblePrefix, _, err := ParseBearer(bearer)
	if err != nil {
		return VerifyResult{}, auth.ErrUnauthorized
	}

	hash, err := v.svc.indexer.IndexHash(ctx, visiblePrefix)
	if err != nil {
		return VerifyResult{}, auth.ErrUnauthorized
	}

	candidates, err := v.svc.repo.LookupByPrefixHash(ctx, hash)
	if err != nil {
		return VerifyResult{}, auth.ErrUnauthorized
	}
	if len(candidates) == 0 {
		return VerifyResult{}, auth.ErrUnauthorized
	}

	now := v.svc.now()
	var matched *APIKey
	for i := range candidates {
		c := candidates[i]
		// Constant-time compare the HMAC bucket of the candidate row
		// against the one we just computed. Defence in depth — a
		// hash collision would still need to satisfy the envelope
		// + argon checks below.
		if subtle.ConstantTimeCompare(c.PrefixLookupHash, hash) != 1 {
			continue
		}
		// Envelope verify (kid-bound). Skipped when the envelope is
		// zero (no-encryptor dev mode); production wiring always
		// supplies a real envelope so this branch is dev-only.
		if !c.PrefixLookupEnvelope.IsZero() {
			ok, derr := v.svc.indexer.VerifyEnvelope(ctx, c.ID, c.PrefixLookupEnvelope, hash)
			if derr != nil || !ok {
				continue
			}
		}
		// argon verify against the current PHC.
		if ok, _ := VerifySecret(bearer, c.ArgonPHC); ok {
			matched = &c
			break
		}
		// During grace, fall through to the predecessor PHC.
		if c.InGrace(now) {
			if ok, _ := VerifySecret(bearer, c.PredecessorArgonPHC); ok {
				matched = &c
				break
			}
		}
	}
	if matched == nil {
		return VerifyResult{}, auth.ErrUnauthorized
	}

	// State checks. Order matters — revoked > expired > IP > rate
	// limit so the surfaced error matches the §17.3 matrix.
	if matched.IsRevoked() {
		return VerifyResult{}, auth.ErrKeyRevoked
	}
	if matched.IsExpired(now) {
		return VerifyResult{}, auth.ErrKeyExpired
	}
	if !IPAllowed(remoteAddr, matched.IPAllowlist) {
		return VerifyResult{}, auth.ErrIPNotAllowed
	}

	// Rate limit. Limiter nil = no enforcement (tests).
	var rlInfo *RateLimitInfo
	if v.limiter != nil {
		allowed, info := v.limiter.Allow(matched.ID, matched.RateLimitPerMinute)
		rlInfo = &info
		if !allowed {
			return VerifyResult{RateLimitInfo: rlInfo}, errRateLimited
		}
	}

	// Record usage (fire-and-forget — no error path on a buffer
	// write).
	if v.buffer != nil {
		v.buffer.Record(matched.ID, now)
	}

	principal := auth.Principal{
		ActorType: auth.ActorAPIKey,
		ActorID:   matched.ID,
		TenantID:  matched.TenantID,
		Scopes:    matched.Scopes,
		IPAddress: remoteAddr,
	}
	return VerifyResult{Principal: principal, RateLimitInfo: rlInfo, APIKey: *matched}, nil
}

// errRateLimited is the internal sentinel the verifier raises to
// signal a 429 path. The middleware translates it to a Problem; the
// surface is private so callers can't confuse it with the auth.ErrXxx
// pre-existing ones.
var errRateLimited = errors.New("apikeys: rate limited")

// IsRateLimited reports whether err is the verifier's rate-limit
// signal.
func IsRateLimited(err error) bool { return errors.Is(err, errRateLimited) }

// HasBearerPrefix reports whether the supplied Authorization header
// value looks like an API key bearer (live_ or test_). Used by the
// middleware to short-circuit non-API-key paths (JWT etc.) without a
// failed DB lookup.
func HasBearerPrefix(authHeader string) bool {
	const bearer = "Bearer "
	if !strings.HasPrefix(authHeader, bearer) {
		return false
	}
	token := authHeader[len(bearer):]
	return strings.HasPrefix(token, string(EnvironmentLive)+"_") ||
		strings.HasPrefix(token, string(EnvironmentTest)+"_")
}

// ExtractBearer returns the raw bearer token from an Authorization
// header value, or "" if absent / malformed.
func ExtractBearer(authHeader string) string {
	const bearer = "Bearer "
	if !strings.HasPrefix(authHeader, bearer) {
		return ""
	}
	return strings.TrimSpace(authHeader[len(bearer):])
}

// VerifyTimeout is the recommended context timeout for an auth call.
// Exposed so the middleware wiring can derive a child context without
// the apikeys package owning the timeout decision.
const VerifyTimeout = 2 * time.Second
