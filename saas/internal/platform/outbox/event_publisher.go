package outbox

import (
	"context"
	"encoding/json"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
	"github.com/omarss/saas/internal/platform/id"
)

// PgxEventPublisher implements tenancy.EventPublisher by inserting one row per
// event into outbox_event. Phase 3 promotes this onto a transactional context
// so the insert becomes atomic with the state change. Phase 2 best-effort is
// acceptable because no real consumer subscribes yet.
type PgxEventPublisher struct {
	q            *db.Queries
	deploymentID string
}

// NewPgxEventPublisher wires the publisher over sqlc Queries plus the binary's
// deployment id (passed via env var in cmd/dataplane).
func NewPgxEventPublisher(q *db.Queries, deploymentID string) *PgxEventPublisher {
	return &PgxEventPublisher{q: q, deploymentID: deploymentID}
}

// Publish appends an outbox_event row. tenantID may be empty for cross-tenant
// events (deployment-level audit, etc.).
func (p *PgxEventPublisher) Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	params := db.InsertOutboxEventParams{
		EventID:      id.New(id.PrefixEvent),
		Type:         eventType,
		EventVersion: 1,
		DeploymentID: p.deploymentID,
		Payload:      body,
	}
	if tenantID != "" {
		tid := tenantID
		params.TenantID = &tid
	}
	_, err = p.q.InsertOutboxEvent(ctx, params)
	return err
}
