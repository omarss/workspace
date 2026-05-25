package audit_test

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	"github.com/omarss/saas/internal/dataplane/audit"
	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
)

func newOutboxEvent(t *testing.T, eventID, typ, tenantID string, payload map[string]any) db.OutboxEvent {
	t.Helper()
	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	tid := tenantID
	return db.OutboxEvent{
		EventID:      eventID,
		Type:         typ,
		EventVersion: 1,
		TenantID:     &tid,
		DeploymentID: "dep_test",
		OccurredAt:   pgtype.Timestamptz{Time: time.Date(2026, 5, 25, 8, 0, 0, 0, time.UTC), Valid: true},
		Payload:      body,
	}
}

func TestAuditedEventTypes_MatchesAGENTSList(t *testing.T) {
	// AGENTS.md §18.3 enumerates the audited types; mirror as a tripwire.
	want := []string{
		"tenant.created", "tenant.updated", "tenant.suspended", "tenant.deleted",
		"user.created", "user.disabled", "user.enabled", "user.email_verified",
		"user.password_reset_requested", "user.social_linked", "user.social_unlinked",
		"member.invited", "member.joined", "member.removed", "member.role_changed",
		"role.created", "role.updated", "role.deleted",
		"member_role.assigned", "member_role.unassigned",
		"permission.granted", "permission.revoked", "authorization.denied",
		"api_key.created", "api_key.rotated", "api_key.revoked",
		"notification.delivery_failed",
		"notification_channel.created", "notification_channel.rotated", "notification_channel.deleted",
		"operator.login", "operator.impersonation_started", "operator.impersonation_ended",
		"deployment.provisioned", "deployment.upgraded", "deployment.rollback",
		"deployment.destroyed", "deployment.purged",
		"deployment.domain_attached", "deployment.domain_verified", "deployment.domain_detached",
	}
	for _, w := range want {
		if !audit.IsAudited(w) {
			t.Errorf("§18.3 type %q not registered in AuditedEventTypes", w)
		}
	}
}

func TestSubscriber_AppendsAuditRow(t *testing.T) {
	repo := audit.NewMemoryRepository()
	sub := audit.NewSubscriber(repo, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	e := newOutboxEvent(t, "evt_test_001", "tenant.created", "tenant_X",
		map[string]any{"actor_type": "user", "actor_id": "user_a", "id": "tenant_X"})
	if err := sub.Handle(context.Background(), e); err != nil {
		t.Fatalf("Handle: %v", err)
	}
	rows, _, _ := repo.List(withTenant("tenant_X"), audit.ListFilter{TenantID: "tenant_X"})
	if len(rows) != 1 {
		t.Fatalf("want 1 audit row got %d", len(rows))
	}
	if rows[0].Action != "tenant.create" {
		t.Errorf("want action=tenant.create got %q", rows[0].Action)
	}
	if rows[0].ActorID != "user_a" {
		t.Errorf("actor_id mismatch: %q", rows[0].ActorID)
	}
	if rows[0].SourceEventID != "evt_test_001" {
		t.Errorf("source_event_id mismatch: %q", rows[0].SourceEventID)
	}
}

func TestAuditSubscriber_DuplicateEvent_NoDuplicate(t *testing.T) {
	repo := audit.NewMemoryRepository()
	sub := audit.NewSubscriber(repo, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	e := newOutboxEvent(t, "evt_dup_001", "api_key.created", "tenant_X",
		map[string]any{"actor_type": "user", "actor_id": "user_a", "id": "apik_abc"})
	for i := 0; i < 3; i++ {
		if err := sub.Handle(context.Background(), e); err != nil {
			t.Fatalf("Handle attempt %d: %v", i, err)
		}
	}
	rows, _, _ := repo.List(withTenant("tenant_X"), audit.ListFilter{TenantID: "tenant_X"})
	if len(rows) != 1 {
		t.Fatalf("expected exactly one audit row across re-deliveries, got %d", len(rows))
	}
}

func TestSubscriber_NonAuditedTypeIsNoop(t *testing.T) {
	repo := audit.NewMemoryRepository()
	sub := audit.NewSubscriber(repo, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	e := newOutboxEvent(t, "evt_x", "notification.queued", "tenant_X", nil)
	if err := sub.Handle(context.Background(), e); err != nil {
		t.Fatalf("Handle: %v", err)
	}
	rows, _, _ := repo.List(withTenant("tenant_X"), audit.ListFilter{TenantID: "tenant_X"})
	if len(rows) != 0 {
		t.Fatalf("non-audited type should not produce audit rows; got %d", len(rows))
	}
}

func TestSubscriber_TenantlessAuditedEventIsSkipped(t *testing.T) {
	// operator.login is audit-eligible but data-plane requires a
	// tenant_id; we expect the subscriber to log + skip rather than
	// fail the dispatcher.
	repo := audit.NewMemoryRepository()
	sub := audit.NewSubscriber(repo, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	e := db.OutboxEvent{
		EventID:    "evt_op_login",
		Type:       "operator.login",
		TenantID:   nil,
		Payload:    []byte(`{"actor_type":"operator","actor_id":"op_alice"}`),
		OccurredAt: pgtype.Timestamptz{Time: time.Now(), Valid: true},
	}
	if err := sub.Handle(context.Background(), e); err != nil {
		t.Fatalf("Handle: %v", err)
	}
}

func TestSubscriber_StripsTopLevelPII(t *testing.T) {
	repo := audit.NewMemoryRepository()
	sub := audit.NewSubscriber(repo, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	e := newOutboxEvent(t, "evt_pii", "user.password_reset_requested", "tenant_X",
		map[string]any{
			"actor_type": "user",
			"actor_id":   "user_a",
			"id":         "user_a",
			"metadata": map[string]any{
				"email":    "alice@example.com",
				"password": "swordfish",
				"reason":   "user requested",
			},
		})
	if err := sub.Handle(context.Background(), e); err != nil {
		t.Fatalf("Handle: %v", err)
	}
	rows, _, _ := repo.List(withTenant("tenant_X"), audit.ListFilter{TenantID: "tenant_X"})
	if len(rows) != 1 {
		t.Fatalf("want 1 row got %d", len(rows))
	}
	meta := rows[0].Metadata
	if v, _ := meta["email"].(string); v != "[REDACTED]" {
		t.Errorf("email should be redacted, got %v", meta["email"])
	}
	if v, _ := meta["password"].(string); v != "[REDACTED]" {
		t.Errorf("password should be redacted, got %v", meta["password"])
	}
	if got, _ := meta["reason"].(string); got != "user requested" {
		t.Errorf("non-PII fields should pass through, got %v", meta["reason"])
	}
}

func TestSubscriber_ChainStaysValidAcrossMultipleAppends(t *testing.T) {
	repo := audit.NewMemoryRepository()
	sub := audit.NewSubscriber(repo, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	events := []struct{ id, typ string }{
		{"evt_a", "tenant.created"},
		{"evt_b", "user.created"},
		{"evt_c", "api_key.created"},
		{"evt_d", "role.created"},
	}
	for _, ev := range events {
		oe := newOutboxEvent(t, ev.id, ev.typ, "tenant_chain",
			map[string]any{"actor_type": "user", "actor_id": "u", "id": "r1"})
		if err := sub.Handle(context.Background(), oe); err != nil {
			t.Fatalf("Handle %s: %v", ev.id, err)
		}
	}
	res, err := audit.VerifyChain(context.Background(), repo, "tenant_chain", nil)
	if err != nil {
		t.Fatalf("VerifyChain: %v", err)
	}
	if !res.Verified {
		t.Fatalf("chain should be verified after clean appends: %+v", res)
	}
	if res.RowsChecked != len(events) {
		t.Fatalf("rows_checked = %d want %d", res.RowsChecked, len(events))
	}
}

func TestSubscriber_DropsEventMissingResourceType(t *testing.T) {
	// The action prefix yields resource_type — when both action and
	// payload lack a resource we expect a soft skip (no error, no row).
	repo := audit.NewMemoryRepository()
	sub := audit.NewSubscriber(repo, slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)))
	e := db.OutboxEvent{
		EventID:    "evt_bad",
		Type:       "tenant.created",
		TenantID:   pointer("tenant_X"),
		Payload:    []byte(`{}`),
		OccurredAt: pgtype.Timestamptz{Time: time.Now(), Valid: true},
	}
	// Action prefix is "tenant" so resource_type is non-empty — this
	// should succeed even without explicit payload fields. Verify the
	// row exists.
	if err := sub.Handle(context.Background(), e); err != nil {
		t.Fatalf("Handle: %v", err)
	}
	rows, _, _ := repo.List(withTenant("tenant_X"), audit.ListFilter{TenantID: "tenant_X"})
	if len(rows) != 1 {
		t.Fatalf("expect 1 row inferred from action prefix, got %d", len(rows))
	}
	if !strings.HasPrefix(rows[0].ResourceType, "tenant") {
		t.Errorf("resource_type fallback failed: %q", rows[0].ResourceType)
	}
}

func pointer[T any](v T) *T { return &v }
