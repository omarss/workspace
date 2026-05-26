// Package impersonation mints and verifies operator-impersonation
// JWTs. Phase 13.
//
// The token is signed by the platform (not Keycloak): Keycloak issues
// the upstream OPERATOR token from the operators realm; the control
// plane then mints a SEPARATE short-lived (≤15 min) data-plane JWT
// here, signed with a per-process HS256 / RS256 key. The data-plane
// auth middleware accepts these tokens alongside Keycloak-issued
// data-plane tokens because both share the `aud=saas-data-<dep_id>`
// audience and a documented issuer (`saas-controlplane`).
//
// Why not Keycloak token-exchange: gocloak v14 has spotty support for
// the RFC 8693 grant, and Keycloak's exchange UX requires per-target-
// realm policy plumbing that we'd have to maintain at every
// Deployment. Self-signed is cleaner and the trust anchor is the
// control-plane's already-trusted boot configuration.
//
// Trust model:
//   - The control-plane configures the data-plane verifier with the
//     impersonation issuer's public key (or shared HS256 secret) at
//     boot via SAAS_IMPERSONATION_PUBKEY / SAAS_IMPERSONATION_SECRET.
//   - Each Deployment optionally rotates its impersonation key
//     (Phase 14+ feature). For MVP a single per-platform key is fine
//     — the audience binding makes a key compromise narrow to the
//     one Deployment.
//   - The data-plane middleware MUST verify `aud == saas-data-<dep_id>`
//     before accepting; mixing with the per-Deployment audience makes
//     cross-Deployment impersonation impossible.
//
// AGENTS.md §18.4 (operator auth model) and the plan §13.6 / §13.7.
//
//nolint:revive,gosec // package documented; HS256 secret reads are
// constrained to controlplane boot via env vars (foundations §5).

package impersonation

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

// Issuer is the fixed `iss` claim emitted by the platform on every
// impersonation token. Acceptors compare with constant-time equality
// before reading any claim — see Verify.
const Issuer = "saas-controlplane"

// AudiencePrefix is the per-Deployment audience prefix; the full value
// is `saas-data-<deployment_id>` so a token minted for dep_A cannot be
// replayed against dep_B's data plane.
const AudiencePrefix = "saas-data-"

// MaxDuration is the AGENTS.md §18.4 hard ceiling. Tokens minted with
// a duration > 15 min are silently clamped — the API contract says
// the field is bounded.
const MaxDuration = 15 * time.Minute

// MinDuration prevents 0-second tokens; matches the OpenAPI minimum.
const MinDuration = time.Minute

// MintInput aggregates the values needed to build an impersonation
// token. All fields are required except TargetMemberID (operators
// occasionally impersonate at tenant level when no specific member
// applies — incident-response scenario).
type MintInput struct {
	DeploymentID   string        // dep_<ulid>
	OperatorID     string        // op_<ulid>
	OperatorEmail  string        // surfaced in audit
	TenantID       string        // tenant_<ulid> the operator is acting as
	TargetMemberID string        // member_<ulid>; optional
	Reason         string        // free text; redactor-safe
	Duration       time.Duration // clamped to [MinDuration, MaxDuration]
	SessionID      string        // impses_<ulid>; pre-computed by caller for atomic insert
	Now            time.Time     // injected for tests; zero -> time.Now()
}

// Result holds the signed JWT + the metadata the handler needs to
// persist and surface.
type Result struct {
	Token     string
	SessionID string
	IssuedAt  time.Time
	ExpiresAt time.Time
}

// Minter mints platform-signed impersonation tokens. One per process.
// The signing material is held by the struct so callers can pass it
// through DI; never read env vars directly here.
type Minter struct {
	secret []byte
	// nowFn is the clock; zero => time.Now. Hot-path branch is
	// avoided by callers always supplying a valid value.
	nowFn func() time.Time
}

// NewMinter constructs a Minter with the supplied HS256 secret. Returns
// an error if the secret is shorter than 32 bytes — HS256 with a weak
// key defeats the whole point of signing.
func NewMinter(secret []byte) (*Minter, error) {
	if len(secret) < 32 {
		return nil, fmt.Errorf("impersonation: signing secret must be >=32 bytes (got %d)", len(secret))
	}
	return &Minter{secret: secret, nowFn: time.Now}, nil
}

// Mint builds the token. The caller pre-computes SessionID so the
// session row insert + token sign are atomic from the handler's POV
// (insert first, then sign; if signing fails the row is rolled back).
func (m *Minter) Mint(in MintInput) (Result, error) {
	if err := validateInput(in); err != nil {
		return Result{}, err
	}
	now := in.Now
	if now.IsZero() {
		now = m.nowFn()
	}
	dur := clamp(in.Duration, MinDuration, MaxDuration)
	exp := now.Add(dur)
	claims := map[string]any{
		"iss":                      Issuer,
		"aud":                      AudiencePrefix + in.DeploymentID,
		"sub":                      in.OperatorID,
		"actor_type":               string(auth.ActorOperatorImpersonation),
		"actor_id":                 in.OperatorID,
		"actor_email":              in.OperatorEmail,
		"tenant_id":                in.TenantID,
		"impersonation_session_id": in.SessionID,
		"reason":                   in.Reason,
		"iat":                      now.Unix(),
		"exp":                      exp.Unix(),
		"nbf":                      now.Unix() - 1, // tolerate 1s clock skew
	}
	if in.TargetMemberID != "" {
		claims["target_member_id"] = in.TargetMemberID
	}
	tok, err := signHS256(m.secret, claims)
	if err != nil {
		return Result{}, fmt.Errorf("impersonation: sign: %w", err)
	}
	return Result{
		Token:     tok,
		SessionID: in.SessionID,
		IssuedAt:  now.UTC(),
		ExpiresAt: exp.UTC(),
	}, nil
}

// NewSessionID is a convenience for callers that don't have an id helper
// inline; uses the platform-wide impses_ prefix.
func NewSessionID() string {
	return id.New("impses")
}

func validateInput(in MintInput) error {
	switch {
	case in.DeploymentID == "":
		return errors.New("impersonation: DeploymentID is required")
	case in.OperatorID == "":
		return errors.New("impersonation: OperatorID is required")
	case in.OperatorEmail == "":
		return errors.New("impersonation: OperatorEmail is required for audit")
	case in.TenantID == "":
		return errors.New("impersonation: TenantID is required")
	case in.Reason == "":
		return errors.New("impersonation: Reason is required")
	case len(in.Reason) > 256:
		return errors.New("impersonation: Reason exceeds 256 chars")
	case in.SessionID == "":
		return errors.New("impersonation: SessionID is required")
	}
	return nil
}

func clamp(d, lo, hi time.Duration) time.Duration {
	if d < lo {
		return lo
	}
	if d > hi {
		return hi
	}
	return d
}

// signHS256 produces a compact-form JWT. We hand-roll instead of
// pulling in github.com/golang-jwt/jwt because jwx v3 (already a
// platform dep) supports signing but its API for this narrow case is
// fiddly, and the surface is small enough to audit inline.
func signHS256(secret []byte, claims map[string]any) (string, error) {
	header := map[string]string{"alg": "HS256", "typ": "JWT"}
	hb, err := json.Marshal(header)
	if err != nil {
		return "", err
	}
	pb, err := json.Marshal(claims)
	if err != nil {
		return "", err
	}
	headerB64 := base64.RawURLEncoding.EncodeToString(hb)
	payloadB64 := base64.RawURLEncoding.EncodeToString(pb)
	signing := headerB64 + "." + payloadB64
	mac := hmac.New(sha256.New, secret)
	mac.Write([]byte(signing))
	sig := mac.Sum(nil)
	return signing + "." + base64.RawURLEncoding.EncodeToString(sig), nil
}

// Verifier checks the signature + standard claims and extracts the
// impersonation fields. The data-plane middleware constructs one of
// these at boot and reuses it for every request.
type Verifier struct {
	secret           []byte
	expectedAudience string // "saas-data-<dep_id>"
	nowFn            func() time.Time
}

// NewVerifier binds the verifier to a Deployment's expected audience.
// Each data-plane process serves exactly one Deployment so the
// audience is fixed at boot.
func NewVerifier(secret []byte, deploymentID string) (*Verifier, error) {
	if len(secret) < 32 {
		return nil, fmt.Errorf("impersonation: verifier secret must be >=32 bytes")
	}
	if deploymentID == "" {
		return nil, fmt.Errorf("impersonation: deploymentID is required")
	}
	return &Verifier{
		secret:           secret,
		expectedAudience: AudiencePrefix + deploymentID,
		nowFn:            time.Now,
	}, nil
}

// VerifyResult is the parsed-and-validated payload. The middleware
// uses this to construct an auth.Principal with
// ActorType=ActorOperatorImpersonation.
type VerifyResult struct {
	OperatorID             string
	OperatorEmail          string
	TenantID               string
	TargetMemberID         string
	ImpersonationSessionID string
	Reason                 string
	ExpiresAt              time.Time
}

// Verify parses raw, checks signature + iss + aud + exp + nbf, and
// returns the decoded fields. Errors are non-specific so a verifier
// loop can't be used as an oracle for which check failed.
func (v *Verifier) Verify(raw string) (VerifyResult, error) {
	parts := strings.Split(raw, ".")
	if len(parts) != 3 {
		return VerifyResult{}, errors.New("impersonation: malformed token")
	}
	headerJSON, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return VerifyResult{}, errors.New("impersonation: header decode")
	}
	payloadJSON, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return VerifyResult{}, errors.New("impersonation: payload decode")
	}
	sig, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		return VerifyResult{}, errors.New("impersonation: signature decode")
	}
	var hdr struct {
		Alg string `json:"alg"`
		Typ string `json:"typ"`
	}
	if err := json.Unmarshal(headerJSON, &hdr); err != nil {
		return VerifyResult{}, errors.New("impersonation: header parse")
	}
	if hdr.Alg != "HS256" {
		return VerifyResult{}, errors.New("impersonation: unsupported alg")
	}
	mac := hmac.New(sha256.New, v.secret)
	mac.Write([]byte(parts[0] + "." + parts[1]))
	if !hmac.Equal(sig, mac.Sum(nil)) {
		return VerifyResult{}, errors.New("impersonation: bad signature")
	}
	var c struct {
		Iss                    string `json:"iss"`
		Aud                    any    `json:"aud"`
		ActorType              string `json:"actor_type"`
		ActorID                string `json:"actor_id"`
		ActorEmail             string `json:"actor_email"`
		TenantID               string `json:"tenant_id"`
		TargetMemberID         string `json:"target_member_id,omitempty"`
		ImpersonationSessionID string `json:"impersonation_session_id"`
		Reason                 string `json:"reason"`
		Iat                    int64  `json:"iat"`
		Exp                    int64  `json:"exp"`
		Nbf                    int64  `json:"nbf"`
	}
	if err := json.Unmarshal(payloadJSON, &c); err != nil {
		return VerifyResult{}, errors.New("impersonation: payload parse")
	}
	if c.Iss != Issuer {
		return VerifyResult{}, errors.New("impersonation: bad iss")
	}
	if !audienceMatches(c.Aud, v.expectedAudience) {
		return VerifyResult{}, errors.New("impersonation: bad aud")
	}
	if c.ActorType != string(auth.ActorOperatorImpersonation) {
		return VerifyResult{}, errors.New("impersonation: actor_type mismatch")
	}
	now := v.nowFn().Unix()
	if c.Exp <= now {
		return VerifyResult{}, errors.New("impersonation: token expired")
	}
	if c.Nbf > now {
		return VerifyResult{}, errors.New("impersonation: token not yet valid")
	}
	if c.ImpersonationSessionID == "" {
		return VerifyResult{}, errors.New("impersonation: missing session id")
	}
	return VerifyResult{
		OperatorID:             c.ActorID,
		OperatorEmail:          c.ActorEmail,
		TenantID:               c.TenantID,
		TargetMemberID:         c.TargetMemberID,
		ImpersonationSessionID: c.ImpersonationSessionID,
		Reason:                 c.Reason,
		ExpiresAt:              time.Unix(c.Exp, 0).UTC(),
	}, nil
}

// audienceMatches accepts either a single string or a single-element
// array — JWT spec allows both shapes. The string is constant-time
// compared to defeat timing-based audience-enumeration attacks.
func audienceMatches(claim any, expected string) bool {
	switch v := claim.(type) {
	case string:
		return constantTimeEq(v, expected)
	case []any:
		for _, e := range v {
			if s, ok := e.(string); ok && constantTimeEq(s, expected) {
				return true
			}
		}
	}
	return false
}

func constantTimeEq(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	var diff byte
	for i := range a {
		diff |= a[i] ^ b[i]
	}
	return diff == 0
}
