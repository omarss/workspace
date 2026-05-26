// Phase 13 — impersonation minter + verifier tests.
//
// Covers the §17.3 matrix rows that don't require a real Postgres:
//   - happy path (mint -> verify -> field round-trip)
//   - duration clamping at the 15-min ceiling
//   - audience binding (token minted for dep_A refused at dep_B)
//   - expired-token rejection
//   - tampered-payload rejection
//   - reason length / required-field validation
// Integration-build-tag tests in test/ exercise the audit-row writeback
// path.

package impersonation_test

import (
	"strings"
	"testing"
	"time"

	"github.com/omarss/saas/internal/controlplane/impersonation"
	"github.com/omarss/saas/internal/platform/auth"
)

func newMinter(t *testing.T) *impersonation.Minter {
	t.Helper()
	m, err := impersonation.NewMinter([]byte(strings.Repeat("a", 32)))
	if err != nil {
		t.Fatalf("NewMinter: %v", err)
	}
	return m
}

func validInput() impersonation.MintInput {
	return impersonation.MintInput{
		DeploymentID:   "dep_01HXTEST",
		OperatorID:     "op_01HXTEST",
		OperatorEmail:  "ops@example.com",
		TenantID:       "tenant_01HXTEST",
		TargetMemberID: "member_01HXTEST",
		Reason:         "incident #42",
		Duration:       5 * time.Minute,
		SessionID:      "impses_01HXTEST",
	}
}

func TestImpersonationMintVerifyRoundTrip(t *testing.T) {
	m := newMinter(t)
	in := validInput()
	res, err := m.Mint(in)
	if err != nil {
		t.Fatalf("Mint: %v", err)
	}
	if res.Token == "" {
		t.Fatal("empty token")
	}
	if got, want := strings.Count(res.Token, "."), 2; got != want {
		t.Errorf("compact JWT should have 2 dots, got %d", got)
	}
	v, err := impersonation.NewVerifier([]byte(strings.Repeat("a", 32)), in.DeploymentID)
	if err != nil {
		t.Fatalf("NewVerifier: %v", err)
	}
	r, err := v.Verify(res.Token)
	if err != nil {
		t.Fatalf("Verify: %v", err)
	}
	if r.OperatorID != in.OperatorID {
		t.Errorf("OperatorID=%q want %q", r.OperatorID, in.OperatorID)
	}
	if r.TenantID != in.TenantID {
		t.Errorf("TenantID=%q want %q", r.TenantID, in.TenantID)
	}
	if r.ImpersonationSessionID != in.SessionID {
		t.Errorf("SessionID=%q want %q", r.ImpersonationSessionID, in.SessionID)
	}
	if r.Reason != in.Reason {
		t.Errorf("Reason=%q want %q", r.Reason, in.Reason)
	}
}

func TestImpersonationDurationClampedToMax(t *testing.T) {
	m := newMinter(t)
	in := validInput()
	in.Duration = 30 * time.Minute // > 15 min ceiling
	res, err := m.Mint(in)
	if err != nil {
		t.Fatalf("Mint: %v", err)
	}
	got := res.ExpiresAt.Sub(res.IssuedAt)
	if got > impersonation.MaxDuration+time.Second {
		t.Errorf("ExpiresAt-IssuedAt=%v should be clamped to %v", got, impersonation.MaxDuration)
	}
}

func TestImpersonationAudienceBinding(t *testing.T) {
	m := newMinter(t)
	in := validInput()
	in.DeploymentID = "dep_alpha"
	res, err := m.Mint(in)
	if err != nil {
		t.Fatalf("Mint: %v", err)
	}
	// Verify against the wrong Deployment audience: must refuse.
	v, err := impersonation.NewVerifier([]byte(strings.Repeat("a", 32)), "dep_beta")
	if err != nil {
		t.Fatalf("NewVerifier: %v", err)
	}
	if _, err := v.Verify(res.Token); err == nil {
		t.Fatal("expected aud mismatch, got nil")
	}
}

func TestImpersonationExpiredTokenRejected(t *testing.T) {
	m := newMinter(t)
	in := validInput()
	// Mint at t=now-1h with a 5-min duration -> already expired.
	in.Now = time.Now().Add(-time.Hour).UTC()
	res, err := m.Mint(in)
	if err != nil {
		t.Fatalf("Mint: %v", err)
	}
	v, err := impersonation.NewVerifier([]byte(strings.Repeat("a", 32)), in.DeploymentID)
	if err != nil {
		t.Fatalf("NewVerifier: %v", err)
	}
	if _, err := v.Verify(res.Token); err == nil {
		t.Fatal("expected expiry error, got nil")
	}
}

func TestImpersonationTamperedPayloadRejected(t *testing.T) {
	m := newMinter(t)
	in := validInput()
	res, err := m.Mint(in)
	if err != nil {
		t.Fatalf("Mint: %v", err)
	}
	// Flip a byte inside the payload segment.
	parts := strings.Split(res.Token, ".")
	if len(parts) != 3 {
		t.Fatalf("compact JWT shape")
	}
	tampered := parts[0] + "." + parts[1][:5] + "AAAA" + parts[1][9:] + "." + parts[2]
	v, _ := impersonation.NewVerifier([]byte(strings.Repeat("a", 32)), in.DeploymentID)
	if _, err := v.Verify(tampered); err == nil {
		t.Fatal("expected bad signature, got nil")
	}
}

func TestImpersonationActorTypeIsImpersonation(t *testing.T) {
	m := newMinter(t)
	in := validInput()
	res, err := m.Mint(in)
	if err != nil {
		t.Fatalf("Mint: %v", err)
	}
	// Sanity-check that the payload encoded the impersonation actor type
	// (verifier rejects anything else, so this protects against a
	// regression that switched the claim to ActorOperator).
	v, _ := impersonation.NewVerifier([]byte(strings.Repeat("a", 32)), in.DeploymentID)
	if _, err := v.Verify(res.Token); err != nil {
		t.Fatalf("Verify: %v", err)
	}
	// Cross-check the principal kind constant we encoded under.
	if auth.ActorOperatorImpersonation != "operator_impersonation" {
		t.Errorf("actor type constant drift: %q", auth.ActorOperatorImpersonation)
	}
}

func TestImpersonationRequiredFields(t *testing.T) {
	m := newMinter(t)
	bad := []impersonation.MintInput{
		{}, // all empty
		{DeploymentID: "dep_x"},
		{DeploymentID: "dep_x", OperatorID: "op_x"},
		{DeploymentID: "dep_x", OperatorID: "op_x", OperatorEmail: "o@x"},
		{DeploymentID: "dep_x", OperatorID: "op_x", OperatorEmail: "o@x", TenantID: "t_x"},
		{DeploymentID: "dep_x", OperatorID: "op_x", OperatorEmail: "o@x", TenantID: "t_x", Reason: strings.Repeat("z", 257)},
	}
	for i, in := range bad {
		if _, err := m.Mint(in); err == nil {
			t.Errorf("case %d: expected validation error, got nil", i)
		}
	}
}

func TestImpersonationShortSecretRefused(t *testing.T) {
	if _, err := impersonation.NewMinter([]byte("too short")); err == nil {
		t.Fatal("expected weak-secret error")
	}
	if _, err := impersonation.NewVerifier([]byte("too short"), "dep_x"); err == nil {
		t.Fatal("expected weak-secret error")
	}
}
