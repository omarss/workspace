package apikeys

import (
	"bytes"
	"context"
	"sort"
	"sync"
	"time"
)

// MemoryRepository is the in-memory Repository implementation used by
// the unit + security tests. Production wiring uses the pgx repo (see
// repo_pgx.go) — this file keeps the test surface independent of a
// running Postgres so `go test ./...` stays seconds-fast.
//
// Concurrent access is protected by a single mutex; under test load
// (single goroutine driving the service) contention is negligible.
type MemoryRepository struct {
	mu   sync.Mutex
	rows map[string]APIKey
}

// NewMemoryRepository constructs an empty in-memory repo.
func NewMemoryRepository() *MemoryRepository {
	return &MemoryRepository{rows: map[string]APIKey{}}
}

// Create persists a new row. Returns the row with row_seq set to 1.
func (r *MemoryRepository) Create(_ context.Context, k APIKey) (APIKey, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, exists := r.rows[k.ID]; exists {
		return APIKey{}, ErrInvalidInput
	}
	k.RowSeq = 1
	r.rows[k.ID] = k
	return k, nil
}

// Get fetches by tenant + id. ErrNotFound when the row is in a
// different tenant (no existence leak across tenants).
func (r *MemoryRepository) Get(_ context.Context, tenantID, apiKeyID string) (APIKey, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	k, ok := r.rows[apiKeyID]
	if !ok || k.TenantID != tenantID {
		return APIKey{}, ErrNotFound
	}
	return k, nil
}

// List returns up to limit rows newest first.
func (r *MemoryRepository) List(_ context.Context, tenantID string, limit int) ([]APIKey, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]APIKey, 0, len(r.rows))
	for _, k := range r.rows {
		if k.TenantID == tenantID {
			out = append(out, k)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt.After(out[j].CreatedAt) })
	hasMore := len(out) > limit
	if hasMore {
		out = out[:limit]
	}
	return out, hasMore, nil
}

// Update applies the patch under an ETag check.
func (r *MemoryRepository) Update(_ context.Context, tenantID, apiKeyID string, expectedSeq int64, patch UpdatePatch) (APIKey, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	k, ok := r.rows[apiKeyID]
	if !ok || k.TenantID != tenantID {
		return APIKey{}, ErrNotFound
	}
	if expectedSeq != 0 && k.RowSeq != expectedSeq {
		return APIKey{}, ErrETagMismatch
	}
	if patch.Name != nil {
		k.Name = *patch.Name
	}
	if patch.Scopes != nil {
		k.Scopes = append([]string(nil), (*patch.Scopes)...)
	}
	if patch.RateLimitPerMinute != nil {
		v := *patch.RateLimitPerMinute
		k.RateLimitPerMinute = &v
	}
	if patch.IPAllowlist != nil {
		k.IPAllowlist = append([]string(nil), (*patch.IPAllowlist)...)
	}
	if patch.ExpiresAt != nil {
		t := *patch.ExpiresAt
		k.ExpiresAt = &t
	}
	k.RowSeq++
	k.UpdatedAt = time.Now().UTC()
	r.rows[apiKeyID] = k
	return k, nil
}

// Revoke marks the row revoked. Idempotent.
func (r *MemoryRepository) Revoke(_ context.Context, tenantID, apiKeyID string) (APIKey, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	k, ok := r.rows[apiKeyID]
	if !ok || k.TenantID != tenantID {
		return APIKey{}, ErrNotFound
	}
	if k.Status == StatusRevoked {
		return k, nil
	}
	now := time.Now().UTC()
	k.Status = StatusRevoked
	k.RevokedAt = &now
	k.UpdatedAt = now
	k.RowSeq++
	r.rows[apiKeyID] = k
	return k, nil
}

// Rotate atomically promotes the predecessor PHC + applies the new
// hash / envelope / prefix.
func (r *MemoryRepository) Rotate(_ context.Context, tenantID, apiKeyID string, newPHC, newPrefix string, newHash []byte, newEnv LookupEnvelope, predecessorExpiresAt time.Time) (APIKey, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	k, ok := r.rows[apiKeyID]
	if !ok || k.TenantID != tenantID {
		return APIKey{}, ErrNotFound
	}
	if k.Status != StatusActive {
		return APIKey{}, ErrNotRotatable
	}
	expires := predecessorExpiresAt
	prevPHC := k.ArgonPHC

	k.PredecessorArgonPHC = prevPHC
	k.PredecessorExpiresAt = &expires
	k.ArgonPHC = newPHC
	k.Prefix = newPrefix
	k.PrefixLookupHash = append([]byte(nil), newHash...)
	k.PrefixLookupEnvelope = newEnv
	now := time.Now().UTC()
	k.RotatedAt = &now
	k.UpdatedAt = now
	k.RowSeq++
	r.rows[apiKeyID] = k
	return k, nil
}

// LookupByPrefixHash returns active rows whose prefix_lookup_hash
// matches hash byte-for-byte.
func (r *MemoryRepository) LookupByPrefixHash(_ context.Context, hash []byte) ([]APIKey, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	var out []APIKey
	for _, k := range r.rows {
		if k.Status != StatusActive {
			continue
		}
		if bytes.Equal(k.PrefixLookupHash, hash) {
			out = append(out, k)
		}
	}
	return out, nil
}

// BulkUpdateLastUsed coalesces a batch of (id, timestamp) into the
// stored rows. Rows missing from the buffer (already deleted) are
// silently ignored.
func (r *MemoryRepository) BulkUpdateLastUsed(_ context.Context, batch map[string]time.Time) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	for id, t := range batch {
		if k, ok := r.rows[id]; ok {
			ts := t
			k.LastUsedAt = &ts
			r.rows[id] = k
		}
	}
	return nil
}

// SweepExpiredPredecessors clears expired predecessor PHCs.
func (r *MemoryRepository) SweepExpiredPredecessors(_ context.Context, now time.Time) (int, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	n := 0
	for id, k := range r.rows {
		if k.PredecessorExpiresAt == nil {
			continue
		}
		if now.After(*k.PredecessorExpiresAt) {
			k.PredecessorArgonPHC = ""
			k.PredecessorExpiresAt = nil
			r.rows[id] = k
			n++
		}
	}
	return n, nil
}

// ForceStatus is a test-only helper that flips the status without
// going through the service. Used to exercise the revoked / expired
// branches of the verifier.
func (r *MemoryRepository) ForceStatus(apiKeyID string, status Status) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if k, ok := r.rows[apiKeyID]; ok {
		k.Status = status
		r.rows[apiKeyID] = k
	}
}

// ForceExpiresAt is a test-only helper that pins the row's expires_at.
func (r *MemoryRepository) ForceExpiresAt(apiKeyID string, t time.Time) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if k, ok := r.rows[apiKeyID]; ok {
		k.ExpiresAt = &t
		r.rows[apiKeyID] = k
	}
}

// ForcePredecessorExpiry test-only helper to push the predecessor
// expiry into the past (simulating post-grace state).
func (r *MemoryRepository) ForcePredecessorExpiry(apiKeyID string, t time.Time) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if k, ok := r.rows[apiKeyID]; ok {
		k.PredecessorExpiresAt = &t
		r.rows[apiKeyID] = k
	}
}
