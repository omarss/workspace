package apikeys

import (
	"context"
	"time"
)

// Repository is the persistence port for api_key rows. Per CONVENTIONS.md
// §1 the interface is intentionally narrow — the service composes the
// methods to express each verb. Each method is tenant-bound by its
// first non-ctx argument because the postgres RLS policy refuses queries
// without `app.current_tenant_id` set on the connection.
type Repository interface {
	// Create persists a new row. The service is responsible for argon
	// hashing, prefix wrapping, and ID minting; Create itself does not
	// generate any of those.
	Create(ctx context.Context, k APIKey) (APIKey, error)

	// Get fetches a single row by id within tenant. Returns
	// ErrNotFound when no row exists for that tenant/id pair —
	// including when the row exists in another tenant (the policy
	// fence makes the two cases indistinguishable, by design).
	Get(ctx context.Context, tenantID, apiKeyID string) (APIKey, error)

	// List returns up to `limit` active + revoked rows for the
	// tenant, newest first. The boolean second return reports whether
	// the underlying query saw more rows than were returned.
	List(ctx context.Context, tenantID string, limit int) ([]APIKey, bool, error)

	// Update mutates the row identified by tenantID + apiKeyID,
	// asserting the supplied expectedSeq matches the current row_seq.
	// Returns ErrETagMismatch when the row_seq disagrees.
	Update(ctx context.Context, tenantID, apiKeyID string, expectedSeq int64, patch UpdatePatch) (APIKey, error)

	// Revoke marks the row as revoked. Idempotent — revoking an
	// already-revoked row is a no-op.
	Revoke(ctx context.Context, tenantID, apiKeyID string) (APIKey, error)

	// Rotate atomically writes a new ArgonPHC + envelope columns +
	// prefix, copying the previous PHC into the predecessor columns
	// with the supplied grace expiry. Returns the post-rotate row.
	Rotate(ctx context.Context, tenantID, apiKeyID string, newPHC, newPrefix string, newHash []byte, newEnv LookupEnvelope, predecessorExpiresAt time.Time) (APIKey, error)

	// LookupByPrefixHash returns the (at most a small handful of)
	// active rows whose prefix_lookup_hash matches the supplied
	// HMAC bucket. Used by the auth path.
	LookupByPrefixHash(ctx context.Context, hash []byte) ([]APIKey, error)

	// BulkUpdateLastUsed batches the (api_key_id, last_used_at)
	// tuples buffered by the middleware into a single UPDATE. Errors
	// are logged but do not abort the caller — the buffer is best-
	// effort.
	BulkUpdateLastUsed(ctx context.Context, batch map[string]time.Time) error

	// SweepExpiredPredecessors clears predecessor_argon_phc /
	// predecessor_expires_at for rows whose predecessor_expires_at has
	// elapsed. Idempotent.
	SweepExpiredPredecessors(ctx context.Context, now time.Time) (int, error)
}

// EventPublisher is the outbox port. Mirrors the shape of the platform
// outbox publisher consumed by sibling modules.
type EventPublisher interface {
	Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error
}
