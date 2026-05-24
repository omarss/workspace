package idempotency

import (
	"context"
	"errors"
	"log/slog"
	"time"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
)

// DefaultCleanupInterval is the production tick rate for the expiry sweeper.
// ADR 010: 24 h TTL on idempotency_record means a 15-minute sweep is far
// faster than the TTL but slow enough that the DELETE is cheap.
const DefaultCleanupInterval = 15 * time.Minute

// Cleaner removes expired idempotency_record rows on a ticker. One goroutine
// per data-plane process; multiple replicas are safe because the DELETE is
// idempotent (Postgres handles the locking).
type Cleaner struct {
	q        *db.Queries
	interval time.Duration
	log      *slog.Logger
}

// NewCleaner builds a Cleaner. interval=0 falls back to DefaultCleanupInterval.
func NewCleaner(q *db.Queries, interval time.Duration, log *slog.Logger) *Cleaner {
	if interval == 0 {
		interval = DefaultCleanupInterval
	}
	if log == nil {
		log = slog.Default()
	}
	return &Cleaner{q: q, interval: interval, log: log}
}

// Run blocks until ctx is canceled, running ExpireIdempotencyRecords every
// `interval`. Per-tick failures are logged but never stop the loop —
// transient DB errors are expected and the next tick retries.
func (c *Cleaner) Run(ctx context.Context) error {
	t := time.NewTicker(c.interval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
			if err := c.q.ExpireIdempotencyRecords(ctx); err != nil && !errors.Is(err, context.Canceled) {
				c.log.Warn("idempotency cleanup tick failed", "err", err)
			} else {
				c.log.Debug("idempotency cleanup tick")
			}
		}
	}
}
