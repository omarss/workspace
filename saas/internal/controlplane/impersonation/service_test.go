// Phase 13 — impersonation service tests.
//
// The service composes the minter, the session repo, and the outbox
// publisher. Tests use a memory-backed repo + publisher to keep the
// suite Postgres-free; integration tests in test/integration cover
// the DB trigger surface.

package impersonation_test

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgtype"

	"github.com/omarss/saas/internal/controlplane/impersonation"
	db "github.com/omarss/saas/internal/controlplane/db/sqlc"
)

type memRepo struct {
	mu       sync.Mutex
	sessions map[string]db.ImpersonationSession
	insErr   error
}

func newMemRepo() *memRepo {
	return &memRepo{sessions: map[string]db.ImpersonationSession{}}
}

func (m *memRepo) InsertImpersonationSession(_ context.Context, arg db.InsertImpersonationSessionParams) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.insErr != nil {
		return m.insErr
	}
	m.sessions[arg.ID] = db.ImpersonationSession{
		ID:              arg.ID,
		DeploymentID:    arg.DeploymentID,
		OperatorID:      arg.OperatorID,
		OperatorEmail:   arg.OperatorEmail,
		TargetMemberID:  arg.TargetMemberID,
		TargetTenantID:  arg.TargetTenantID,
		Reason:          arg.Reason,
		DurationSeconds: arg.DurationSeconds,
		IssuedAt:        arg.IssuedAt,
		ExpiresAt:       arg.ExpiresAt,
	}
	return nil
}

func (m *memRepo) GetImpersonationSession(_ context.Context, id string) (db.ImpersonationSession, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	row, ok := m.sessions[id]
	if !ok {
		return db.ImpersonationSession{}, errors.New("not found")
	}
	return row, nil
}

func (m *memRepo) IsImpersonationSessionActive(_ context.Context, id string) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	row, ok := m.sessions[id]
	if !ok {
		return false, nil
	}
	if row.EndedAt.Valid {
		return false, nil
	}
	if row.ExpiresAt.Valid && time.Now().After(row.ExpiresAt.Time) {
		return false, nil
	}
	return true, nil
}

func (m *memRepo) EndImpersonationSession(_ context.Context, arg db.EndImpersonationSessionParams) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	row, ok := m.sessions[arg.ID]
	if !ok {
		return errors.New("not found")
	}
	row.EndedAt = pgtype.Timestamptz{Time: time.Now(), Valid: true}
	row.EndedReason = arg.EndedReason
	m.sessions[arg.ID] = row
	return nil
}

type memPub struct {
	mu    sync.Mutex
	calls []pubCall
	err   error
}

type pubCall struct {
	Type     string
	TenantID string
	Payload  map[string]any
}

func (p *memPub) Publish(_ context.Context, eventType, tenantID string, payload map[string]any) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.err != nil {
		return p.err
	}
	p.calls = append(p.calls, pubCall{Type: eventType, TenantID: tenantID, Payload: payload})
	return nil
}

func newSvc(t *testing.T, repo *memRepo, pub *memPub) *impersonation.Service {
	t.Helper()
	m, _ := impersonation.NewMinter([]byte(strings.Repeat("a", 32)))
	svc, err := impersonation.NewService(m, repo, pub)
	if err != nil {
		t.Fatalf("NewService: %v", err)
	}
	return svc
}

func TestServiceStartSessionPersistsAndAudits(t *testing.T) {
	repo := newMemRepo()
	pub := &memPub{}
	svc := newSvc(t, repo, pub)
	res, err := svc.StartSession(context.Background(), impersonation.StartSessionInput{
		DeploymentID:    "dep_01HXTEST",
		OperatorID:      "op_01HXTEST",
		OperatorEmail:   "ops@example.com",
		TargetTenantID:  "tenant_01HXTEST",
		Reason:          "incident #1",
		DurationSeconds: 300,
	})
	if err != nil {
		t.Fatalf("StartSession: %v", err)
	}
	if res.Token == "" || !strings.HasPrefix(res.SessionID, "impses_") {
		t.Errorf("unexpected result: token-empty=%v session=%q", res.Token == "", res.SessionID)
	}
	if len(repo.sessions) != 1 {
		t.Errorf("expected 1 session, got %d", len(repo.sessions))
	}
	if len(pub.calls) != 1 || pub.calls[0].Type != "operator.impersonation_started" {
		t.Errorf("expected impersonation_started, got %+v", pub.calls)
	}
}

func TestServiceStartSessionRejectsBadInput(t *testing.T) {
	repo := newMemRepo()
	pub := &memPub{}
	svc := newSvc(t, repo, pub)
	bad := []impersonation.StartSessionInput{
		{}, // empty
		{DeploymentID: "dep_x"},
		{DeploymentID: "dep_x", OperatorID: "op_x"},
		{DeploymentID: "dep_x", OperatorID: "op_x", OperatorEmail: "ops@example.com"},
		{DeploymentID: "dep_x", OperatorID: "op_x", OperatorEmail: "ops@example.com", TargetTenantID: "t"},
		{DeploymentID: "bad-prefix", OperatorID: "op_x", OperatorEmail: "ops@example.com", TargetTenantID: "t", Reason: "r"},
		{DeploymentID: "dep_x", OperatorID: "bad-prefix", OperatorEmail: "ops@example.com", TargetTenantID: "t", Reason: "r"},
	}
	for i, in := range bad {
		if _, err := svc.StartSession(context.Background(), in); err == nil {
			t.Errorf("case %d: expected error, got nil (in=%+v)", i, in)
		}
	}
}

func TestServiceEndSessionRevokesAndAudits(t *testing.T) {
	repo := newMemRepo()
	pub := &memPub{}
	svc := newSvc(t, repo, pub)
	res, err := svc.StartSession(context.Background(), impersonation.StartSessionInput{
		DeploymentID:   "dep_01HXTEST",
		OperatorID:     "op_01HXTEST",
		OperatorEmail:  "ops@example.com",
		TargetTenantID: "tenant_01HXTEST",
		Reason:         "incident #2",
		DurationSeconds: 300,
	})
	if err != nil {
		t.Fatalf("StartSession: %v", err)
	}
	if err := svc.EndSession(context.Background(), res.SessionID, "operator_request", "op_01HXTEST"); err != nil {
		t.Fatalf("EndSession: %v", err)
	}
	// Verify revocation: SessionStatus should be inactive.
	active, _ := svc.SessionStatus(context.Background(), res.SessionID)
	if active {
		t.Errorf("expected inactive after EndSession")
	}
	// One started + one ended.
	if got := len(pub.calls); got != 2 {
		t.Fatalf("expected 2 audit events, got %d", got)
	}
	if pub.calls[1].Type != "operator.impersonation_ended" {
		t.Errorf("expected impersonation_ended second, got %q", pub.calls[1].Type)
	}
}

func TestServiceEndSessionRejectsNonOriginatingOperator(t *testing.T) {
	repo := newMemRepo()
	pub := &memPub{}
	svc := newSvc(t, repo, pub)
	res, err := svc.StartSession(context.Background(), impersonation.StartSessionInput{
		DeploymentID:    "dep_01HXTEST",
		OperatorID:      "op_alpha",
		OperatorEmail:   "alpha@example.com",
		TargetTenantID:  "tenant_01HXTEST",
		Reason:          "incident",
		DurationSeconds: 300,
	})
	if err != nil {
		t.Fatalf("StartSession: %v", err)
	}
	if err := svc.EndSession(context.Background(), res.SessionID, "operator_request", "op_beta"); err == nil {
		t.Error("expected refusal when a different operator tries to end the session")
	}
}

func TestServiceSessionStatusInactiveAfterEnd(t *testing.T) {
	repo := newMemRepo()
	pub := &memPub{}
	svc := newSvc(t, repo, pub)
	res, _ := svc.StartSession(context.Background(), impersonation.StartSessionInput{
		DeploymentID:    "dep_x",
		OperatorID:      "op_x",
		OperatorEmail:   "o@x",
		TargetTenantID:  "tenant_x",
		Reason:          "r",
		DurationSeconds: 300,
	})
	active, _ := svc.SessionStatus(context.Background(), res.SessionID)
	if !active {
		t.Fatal("session should be active immediately after start")
	}
	_ = svc.EndSession(context.Background(), res.SessionID, "operator_request", "op_x")
	active, _ = svc.SessionStatus(context.Background(), res.SessionID)
	if active {
		t.Error("session should be inactive after EndSession")
	}
}
