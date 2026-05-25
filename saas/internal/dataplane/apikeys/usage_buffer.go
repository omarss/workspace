package apikeys

import (
	"context"
	"sync"
	"time"
)

// UsageBuffer coalesces last_used_at writes so the api_key table is
// not hot-rowed under load. Records are kept in an in-memory map
// (latest timestamp wins) and flushed every flushInterval via a single
// bulk UPDATE.
//
// Trade-off: under high contention the persisted last_used_at can lag
// the real timestamp by up to flushInterval seconds. ADR 008 documents
// this — operators should not rely on last_used_at for sub-minute
// freshness; the audit log is the source of truth for that.
type UsageBuffer struct {
	repo          Repository
	flushInterval time.Duration

	mu   sync.Mutex
	seen map[string]time.Time
}

// DefaultFlushInterval matches AGENTS.md §8.5 — 30 s between flushes.
const DefaultFlushInterval = 30 * time.Second

// NewUsageBuffer constructs a buffer backed by repo with a flushInterval
// tick. Pass 0 to use DefaultFlushInterval.
func NewUsageBuffer(repo Repository, flushInterval time.Duration) *UsageBuffer {
	if flushInterval == 0 {
		flushInterval = DefaultFlushInterval
	}
	return &UsageBuffer{
		repo:          repo,
		flushInterval: flushInterval,
		seen:          map[string]time.Time{},
	}
}

// Record stores the latest seen timestamp for apiKeyID. Subsequent
// records within the flush window overwrite the previous timestamp
// (last-write-wins) so a per-request UPDATE collapses into one row
// touch per flush cycle.
func (b *UsageBuffer) Record(apiKeyID string, t time.Time) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if existing, ok := b.seen[apiKeyID]; ok && !t.After(existing) {
		return
	}
	b.seen[apiKeyID] = t
}

// Snapshot returns a copy of the current buffer + resets it to empty.
// Exposed so tests can drive the flush deterministically without
// waiting for the goroutine.
func (b *UsageBuffer) Snapshot() map[string]time.Time {
	b.mu.Lock()
	defer b.mu.Unlock()
	if len(b.seen) == 0 {
		return nil
	}
	out := make(map[string]time.Time, len(b.seen))
	for k, v := range b.seen {
		out[k] = v
	}
	b.seen = map[string]time.Time{}
	return out
}

// Flush issues a BulkUpdateLastUsed against the repository with the
// current buffer contents and clears the buffer. Safe to call from any
// goroutine; the repo write happens outside the buffer lock.
func (b *UsageBuffer) Flush(ctx context.Context) error {
	snap := b.Snapshot()
	if len(snap) == 0 {
		return nil
	}
	if b.repo == nil {
		// No repo wired (test). Drop on the floor.
		return nil
	}
	return b.repo.BulkUpdateLastUsed(ctx, snap)
}

// Run drives the flush ticker until ctx is cancelled. On context
// cancel, performs one final flush so the last 30 s of usage is not
// dropped on graceful shutdown.
func (b *UsageBuffer) Run(ctx context.Context) error {
	t := time.NewTicker(b.flushInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			// One final flush on shutdown. Use a short detached
			// context so the SQL update has a chance to complete
			// even though the parent is cancelled.
			shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			_ = b.Flush(shutdownCtx)
			cancel()
			return ctx.Err()
		case <-t.C:
			_ = b.Flush(ctx)
		}
	}
}
