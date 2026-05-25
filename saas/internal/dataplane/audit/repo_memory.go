package audit

import (
	"context"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/omarss/saas/internal/platform/id"
)

// MemoryRepository is an in-process Repository for unit tests and the
// MVP-stage local dev path where the data plane runs without OpenBao /
// Postgres for fast iteration. The chain bookkeeping is identical to the
// pgx implementation — every test that exercises the chain via this repo
// is faithful to production behaviour.
type MemoryRepository struct {
	mu      sync.Mutex
	events  []Event              // append-only; ordered by insert
	bySrcID map[string]int       // source_event_id → events index, for idempotency
	chains  map[string][]int     // tenant_id → ordered indices into events
	now     func() time.Time
}

// NewMemoryRepository constructs an empty in-memory repo.
func NewMemoryRepository() *MemoryRepository {
	return &MemoryRepository{
		bySrcID: make(map[string]int),
		chains:  make(map[string][]int),
		now:     time.Now,
	}
}

// SetClock overrides the wall clock; tests use a frozen clock to keep
// occurred_at deterministic across runs.
func (r *MemoryRepository) SetClock(now func() time.Time) {
	r.mu.Lock()
	r.now = now
	r.mu.Unlock()
}

// TamperRowHash mutates the stored row_hash for an event identified by
// id, bypassing every append-only guard. ONLY for use by the verifier's
// integration test. Real production code never has a path to mutate an
// audit row — calling this from non-test code is a defect.
func (r *MemoryRepository) TamperRowHash(eventID string, replacement []byte) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	for i := range r.events {
		if r.events[i].ID == eventID {
			r.events[i].RowHash = append(r.events[i].RowHash[:0:0], replacement...)
			return true
		}
	}
	return false
}

// TamperPrevHash mutates the stored prev_hash for an event identified by
// id, bypassing every append-only guard. ONLY for use by the verifier's
// integration test.
func (r *MemoryRepository) TamperPrevHash(eventID string, replacement []byte) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	for i := range r.events {
		if r.events[i].ID == eventID {
			r.events[i].PrevHash = append(r.events[i].PrevHash[:0:0], replacement...)
			return true
		}
	}
	return false
}

// Append implements Repository. The lock is held across the lookup +
// compute + INSERT so two concurrent appends on the same tenant produce
// a deterministic chain — equivalent to the pgx implementation's
// SERIALIZABLE-with-FOR-UPDATE pattern.
func (r *MemoryRepository) Append(_ context.Context, in NewEventInput) (Event, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if err := validateNewEvent(in); err != nil {
		return Event{}, err
	}
	// Idempotency: the same source_event_id never produces two rows.
	if in.SourceEventID != "" {
		if idx, ok := r.bySrcID[in.SourceEventID]; ok {
			return r.events[idx], nil
		}
	}
	chain := r.chains[in.TenantID]
	var prev []byte
	var seq int64 = 1
	if len(chain) == 0 {
		prev = Genesis(in.TenantID)
	} else {
		head := r.events[chain[len(chain)-1]]
		prev = head.RowHash
		seq = head.ChainSequence + 1
	}
	ev := Event{
		ID:            id.New(id.PrefixAudit),
		TenantID:      in.TenantID,
		ActorType:     in.ActorType,
		ActorID:       in.ActorID,
		Action:        in.Action,
		ResourceType:  in.ResourceType,
		ResourceID:    in.ResourceID,
		OccurredAt:    occurredAtOrNow(in.OccurredAt, r.now),
		IPAddress:     in.IPAddress,
		UserAgent:     in.UserAgent,
		RequestID:     in.RequestID,
		Metadata:      copyMetadata(in.Metadata),
		SourceEventID: in.SourceEventID,
		PrevHash:      prev,
		ChainSequence: seq,
	}
	rh, err := ComputeRowHash(prev, ev.CanonicalBody())
	if err != nil {
		return Event{}, err
	}
	ev.RowHash = rh
	r.events = append(r.events, ev)
	idx := len(r.events) - 1
	r.chains[in.TenantID] = append(chain, idx)
	if in.SourceEventID != "" {
		r.bySrcID[in.SourceEventID] = idx
	}
	return ev, nil
}

// Get implements Repository.
func (r *MemoryRepository) Get(_ context.Context, tenantID, eventID string) (Event, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, e := range r.events {
		if e.TenantID == tenantID && e.ID == eventID {
			return e, nil
		}
	}
	return Event{}, ErrNotFound
}

// List implements Repository.
func (r *MemoryRepository) List(_ context.Context, filter ListFilter) ([]Event, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	limit := filter.Limit
	if limit <= 0 {
		limit = 25
	}
	candidates := make([]Event, 0, len(r.events))
	for _, e := range r.events {
		if filter.TenantID != "" && e.TenantID != filter.TenantID {
			continue
		}
		if filter.Action != "" && e.Action != filter.Action {
			continue
		}
		if filter.ResourceType != "" && e.ResourceType != filter.ResourceType {
			continue
		}
		if filter.ResourceID != "" && e.ResourceID != filter.ResourceID {
			continue
		}
		if filter.ActorID != "" && e.ActorID != filter.ActorID {
			continue
		}
		if !filter.OccurredFrom.IsZero() && e.OccurredAt.Before(filter.OccurredFrom) {
			continue
		}
		if !filter.OccurredTo.IsZero() && e.OccurredAt.After(filter.OccurredTo) {
			continue
		}
		candidates = append(candidates, e)
	}
	// occurred_at DESC, tie-breaker chain_sequence DESC for stable order.
	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].OccurredAt.Equal(candidates[j].OccurredAt) {
			return candidates[i].ChainSequence > candidates[j].ChainSequence
		}
		return candidates[i].OccurredAt.After(candidates[j].OccurredAt)
	})
	hasMore := len(candidates) > limit
	if hasMore {
		candidates = candidates[:limit]
	}
	return candidates, hasMore, nil
}

// StreamForVerify implements Repository. Yields rows in chain order so
// the verifier can walk every tenant's chain start-to-finish in a single
// pass.
func (r *MemoryRepository) StreamForVerify(_ context.Context, tenantFilter string, fn func(Event) error) error {
	r.mu.Lock()
	// Snapshot indices into a tenant-ordered list while holding the lock,
	// then release before invoking fn so callbacks may re-enter the repo.
	type ordered struct {
		tenantID string
		idx      int
	}
	all := make([]ordered, 0, len(r.events))
	tenants := make([]string, 0, len(r.chains))
	for t := range r.chains {
		if tenantFilter != "" && t != tenantFilter {
			continue
		}
		tenants = append(tenants, t)
	}
	sort.Strings(tenants)
	for _, t := range tenants {
		for _, i := range r.chains[t] {
			all = append(all, ordered{tenantID: t, idx: i})
		}
	}
	snapshot := make([]Event, len(all))
	for i, o := range all {
		snapshot[i] = r.events[o.idx]
	}
	r.mu.Unlock()
	for _, e := range snapshot {
		if err := fn(e); err != nil {
			return err
		}
	}
	return nil
}

// validateNewEvent enforces the minimum-field policy at the repository
// boundary so callers (subscribers) cannot poison the chain with empty
// rows. Each failure returns ErrInvalidInput with a wrapping detail.
func validateNewEvent(in NewEventInput) error {
	missing := []string{}
	if strings.TrimSpace(in.TenantID) == "" {
		missing = append(missing, "tenant_id")
	}
	if strings.TrimSpace(in.ActorID) == "" {
		missing = append(missing, "actor_id")
	}
	if strings.TrimSpace(string(in.ActorType)) == "" {
		missing = append(missing, "actor_type")
	}
	if strings.TrimSpace(in.Action) == "" {
		missing = append(missing, "action")
	}
	if strings.TrimSpace(in.ResourceType) == "" {
		missing = append(missing, "resource_type")
	}
	if len(missing) > 0 {
		return ErrInvalidInput
	}
	return nil
}

func occurredAtOrNow(t time.Time, now func() time.Time) time.Time {
	if t.IsZero() {
		return now().UTC()
	}
	return t.UTC()
}

func copyMetadata(m map[string]any) map[string]any {
	if m == nil {
		return map[string]any{}
	}
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}
