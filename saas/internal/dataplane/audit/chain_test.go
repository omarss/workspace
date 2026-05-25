package audit_test

import (
	"bytes"
	"crypto/sha256"
	"testing"

	"github.com/omarss/saas/internal/dataplane/audit"
)

func TestGenesis_DeterministicPerTenant(t *testing.T) {
	t.Parallel()
	g1 := audit.Genesis("tenant_a")
	g2 := audit.Genesis("tenant_a")
	g3 := audit.Genesis("tenant_b")
	if !bytes.Equal(g1, g2) {
		t.Fatalf("genesis non-deterministic for same tenant")
	}
	if bytes.Equal(g1, g3) {
		t.Fatalf("genesis collided across tenants")
	}
	if len(g1) != audit.HashSize {
		t.Fatalf("genesis length: want %d got %d", audit.HashSize, len(g1))
	}
}

func TestComputeRowHash_StableAcrossKeyOrder(t *testing.T) {
	t.Parallel()
	prev := audit.Genesis("tenant_x")
	a := map[string]any{
		"id":       "audit_01HX",
		"action":   "tenant.create",
		"actor_id": "user_abc",
	}
	b := map[string]any{
		"actor_id": "user_abc",
		"id":       "audit_01HX",
		"action":   "tenant.create",
	}
	ha, err := audit.ComputeRowHash(prev, a)
	if err != nil {
		t.Fatal(err)
	}
	hb, err := audit.ComputeRowHash(prev, b)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(ha, hb) {
		t.Fatalf("row_hash differs by map iteration order")
	}
}

func TestComputeRowHash_DifferentRowsDifferentHashes(t *testing.T) {
	t.Parallel()
	prev := audit.Genesis("t")
	h1, _ := audit.ComputeRowHash(prev, map[string]any{"action": "x"})
	h2, _ := audit.ComputeRowHash(prev, map[string]any{"action": "y"})
	if bytes.Equal(h1, h2) {
		t.Fatalf("expected distinct row_hashes")
	}
}

func TestComputeRowHash_RejectsShortPrev(t *testing.T) {
	t.Parallel()
	_, err := audit.ComputeRowHash([]byte("short"), map[string]any{"a": 1})
	if err == nil {
		t.Fatalf("expected ErrInvalidPrevHash for non-32-byte prev")
	}
}

func TestComputeRowHash_KnownVector(t *testing.T) {
	t.Parallel()
	prev := make([]byte, audit.HashSize) // all-zero prev for the vector
	body := map[string]any{"a": 1, "b": "two"}
	got, err := audit.ComputeRowHash(prev, body)
	if err != nil {
		t.Fatal(err)
	}
	// Hand-computed: sha256(0x00..00 || `{"a":1,"b":"two"}`) — the JCS form
	// alphabetises keys (already sorted) and drops whitespace.
	canonical := []byte(`{"a":1,"b":"two"}`)
	h := sha256.New()
	_, _ = h.Write(prev)
	_, _ = h.Write(canonical)
	want := h.Sum(nil)
	if !bytes.Equal(got, want) {
		t.Fatalf("known vector mismatch:\n want %x\n got  %x", want, got)
	}
}
