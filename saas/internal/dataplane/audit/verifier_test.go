package audit_test

import (
	"context"
	"testing"
	"time"

	"github.com/omarss/saas/internal/dataplane/audit"
)

func seedChain(t *testing.T, tenant string, actions ...string) (*audit.MemoryRepository, []audit.Event) {
	t.Helper()
	repo := audit.NewMemoryRepository()
	repo.SetClock(func() time.Time { return time.Date(2026, 5, 25, 0, 0, 0, 0, time.UTC) })
	ctx := withTenant(tenant)
	out := make([]audit.Event, 0, len(actions))
	for i, a := range actions {
		ev, err := repo.Append(ctx, audit.NewEventInput{
			TenantID:      tenant,
			ActorType:     audit.ActorUser,
			ActorID:       "user_a",
			Action:        a,
			ResourceType:  "tenant",
			ResourceID:    tenant,
			SourceEventID: "src_" + tenant + "_" + a,
			Metadata:      map[string]any{"i": i},
		})
		if err != nil {
			t.Fatalf("seed: %v", err)
		}
		out = append(out, ev)
	}
	return repo, out
}

func TestVerifyChain_HappyPath(t *testing.T) {
	repo, _ := seedChain(t, "tenant_a", "tenant.create", "tenant.update", "user.create")
	res, err := audit.VerifyChain(context.Background(), repo, "tenant_a", nil)
	if err != nil {
		t.Fatalf("VerifyChain: %v", err)
	}
	if !res.Verified {
		t.Fatalf("expected verified=true, got %+v", res)
	}
	if res.RowsChecked != 3 {
		t.Errorf("rows_checked = %d want 3", res.RowsChecked)
	}
	if res.FirstMismatchID != nil {
		t.Errorf("expected nil first_mismatch_id, got %q", *res.FirstMismatchID)
	}
}

func TestVerifyChain_MultiTenantAllVerified(t *testing.T) {
	repo, _ := seedChain(t, "tenant_a", "tenant.create", "tenant.update")
	// Seed a second tenant in the same repo.
	ctx := withTenant("tenant_b")
	_, _ = repo.Append(ctx, audit.NewEventInput{
		TenantID: "tenant_b", ActorType: audit.ActorUser, ActorID: "user_b",
		Action: "user.create", ResourceType: "user", ResourceID: "user_b",
		SourceEventID: "src_b_1",
	})
	res, err := audit.VerifyChain(context.Background(), repo, "", nil)
	if err != nil {
		t.Fatalf("VerifyChain: %v", err)
	}
	if !res.Verified {
		t.Fatalf("expected verified=true got %+v", res)
	}
	if res.TenantsChecked != 2 {
		t.Errorf("tenants_checked = %d want 2", res.TenantsChecked)
	}
}

func TestAudit_VerifyChain_DetectsTampering(t *testing.T) {
	repo, events := seedChain(t, "tenant_x", "tenant.create", "tenant.update", "user.create", "role.create")
	target := events[2] // mid-chain row
	tampered := make([]byte, audit.HashSize)
	copy(tampered, target.RowHash)
	tampered[0] ^= 0xff // flip one bit
	if !repo.TamperRowHash(target.ID, tampered) {
		t.Fatalf("tamper failed: target id %s not found", target.ID)
	}
	res, err := audit.VerifyChain(context.Background(), repo, "tenant_x", nil)
	if err != nil {
		t.Fatalf("VerifyChain: %v", err)
	}
	if res.Verified {
		t.Fatalf("expected verified=false after row_hash tampering")
	}
	if res.FirstMismatchID == nil || *res.FirstMismatchID != target.ID {
		t.Fatalf("expected first_mismatch_id = %q, got %v", target.ID,
			derefOrNil(res.FirstMismatchID))
	}
	if res.FirstMismatchSequence == nil || *res.FirstMismatchSequence != target.ChainSequence {
		t.Errorf("expected first_mismatch_sequence = %d, got %v",
			target.ChainSequence, res.FirstMismatchSequence)
	}
	if res.FirstMismatchReason == nil || *res.FirstMismatchReason != audit.ReasonRowHash {
		t.Errorf("expected reason=row_hash, got %v", res.FirstMismatchReason)
	}
}

func TestAudit_VerifyChain_DetectsPrevHashTamper(t *testing.T) {
	repo, events := seedChain(t, "tenant_y", "tenant.create", "tenant.update", "user.create")
	target := events[1]
	corrupt := make([]byte, audit.HashSize) // all zeros — won't match real prev
	if !repo.TamperPrevHash(target.ID, corrupt) {
		t.Fatal("tamper prev_hash failed")
	}
	res, _ := audit.VerifyChain(context.Background(), repo, "tenant_y", nil)
	if res.Verified {
		t.Fatal("expected verified=false")
	}
	if res.FirstMismatchReason == nil || *res.FirstMismatchReason != audit.ReasonPrevHash {
		t.Errorf("expected reason=prev_hash, got %v", res.FirstMismatchReason)
	}
}

func derefOrNil(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}
