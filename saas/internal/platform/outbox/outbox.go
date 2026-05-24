// Package outbox is the in-process dispatcher for outbox_event rows.
// ADR 009: MVP uses a single goroutine polling every 250 ms; NATS / asynq
// promotion is deferred to v1.
//
// The publisher abstraction lets us swap a stdout logger for a real outgoing
// HTTP/NATS publisher later without touching the dispatcher loop. Phase 2 ships
// the logger publisher only (real webhook delivery is post-MVP).
package outbox

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"time"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
)

// Publisher is the side-effect that the dispatcher calls per event. The Phase 2
// implementation is LoggerPublisher; Phase 6+ may wire HTTP/NATS.
type Publisher interface {
	Publish(ctx context.Context, e db.OutboxEvent) error
}

// Dispatcher polls outbox_event for unpublished rows and forwards them to the
// Publisher. It owns its own Queries handle so it can be wired into the
// dataplane binary alongside the request-serving Queries.
type Dispatcher struct {
	q        *db.Queries
	publish  Publisher
	interval time.Duration
	batch    int32
	log      *slog.Logger
}

// New constructs a Dispatcher with sensible defaults (250 ms tick, batch 100).
// Callers may override via WithInterval / WithBatch in future phases.
func New(q *db.Queries, pub Publisher) *Dispatcher {
	return &Dispatcher{
		q:        q,
		publish:  pub,
		interval: 250 * time.Millisecond,
		batch:    100,
		log:      slog.Default(),
	}
}

// Run blocks until ctx is canceled. It tolerates per-event failures (logs
// them and increments delivery_attempts) but does NOT stop the loop on
// transient errors.
func (d *Dispatcher) Run(ctx context.Context) error {
	t := time.NewTicker(d.interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
			if err := d.tick(ctx); err != nil && !errors.Is(err, context.Canceled) {
				d.log.Error("outbox dispatcher tick", "err", err)
			}
		}
	}
}

func (d *Dispatcher) tick(ctx context.Context) error {
	events, err := d.q.ListUnpublishedOutbox(ctx, d.batch)
	if err != nil {
		return err
	}
	for _, e := range events {
		if err := d.publish.Publish(ctx, e); err != nil {
			msg := err.Error()
			_ = d.q.MarkOutboxFailed(ctx, db.MarkOutboxFailedParams{ID: e.ID, LastError: &msg})
			continue
		}
		_ = d.q.MarkOutboxPublished(ctx, e.ID)
	}
	return nil
}

// LoggerPublisher writes each event as a JSON line via slog. Phase 2 only.
type LoggerPublisher struct {
	log *slog.Logger
}

// NewLoggerPublisher returns a Publisher that records each event via slog.
func NewLoggerPublisher(log *slog.Logger) *LoggerPublisher {
	if log == nil {
		log = slog.Default()
	}
	return &LoggerPublisher{log: log}
}

// Publish renders the event as a structured log record.
func (p *LoggerPublisher) Publish(_ context.Context, e db.OutboxEvent) error {
	var payload any
	_ = json.Unmarshal(e.Payload, &payload)
	tenant := ""
	if e.TenantID != nil {
		tenant = *e.TenantID
	}
	p.log.Info(
		"outbox publish",
		"event_id", e.EventID,
		"type", e.Type,
		"tenant_id", tenant,
		"deployment_id", e.DeploymentID,
		"payload", payload,
	)
	return nil
}
