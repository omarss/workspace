package apikeys

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// PgxRepository is the pgx-backed Repository implementation for the
// api_key table. Hand-rolled SQL (not sqlc-generated) because the
// envelope-columns + array-typed fields would otherwise duplicate the
// boilerplate from notifications/repo_pgx.go without buying much; the
// shape stays small enough to audit inline.
//
// The pool's PrepareConn hook binds app.current_tenant_id on every
// acquired connection (internal/platform/pgxpool) so the RLS policy in
// migrations/dataplane/000007_api_keys.up.sql automatically scopes
// every query to the caller's tenant. The repository never sets the
// GUC itself; it trusts the platform tenancy layer.
type PgxRepository struct {
	pool *pgxpool.Pool
}

// NewPgxRepository constructs a Repository over pool.
func NewPgxRepository(pool *pgxpool.Pool) *PgxRepository {
	return &PgxRepository{pool: pool}
}

// Create inserts a new api_key row in one statement.
func (r *PgxRepository) Create(ctx context.Context, k APIKey) (APIKey, error) {
	const stmt = `
INSERT INTO api_key (
    id, tenant_id, environment_id, name, prefix,
    argon_phc,
    prefix_lookup_hash,
    prefix_lookup_ciphertext, prefix_lookup_wrapped_dek, prefix_lookup_nonce,
    prefix_lookup_kid, prefix_lookup_key_version,
    scopes, status, rate_limit_per_minute, ip_allowlist,
    created_by, expires_at
)
VALUES (
    $1,$2,NULLIF($3,''),$4,$5,
    $6,
    $7,
    $8,$9,$10,
    $11,$12,
    $13,$14,$15,$16,
    $17,$18
)
RETURNING row_seq, created_at, updated_at;
`
	row := r.pool.QueryRow(
		ctx, stmt,
		k.ID, k.TenantID, k.EnvironmentID, k.Name, k.Prefix,
		k.ArgonPHC,
		k.PrefixLookupHash,
		k.PrefixLookupEnvelope.Ciphertext, k.PrefixLookupEnvelope.WrappedDEK, k.PrefixLookupEnvelope.Nonce,
		k.PrefixLookupEnvelope.KID, k.PrefixLookupEnvelope.KeyVersion,
		k.Scopes, string(k.Status), k.RateLimitPerMinute, k.IPAllowlist,
		k.CreatedBy, k.ExpiresAt,
	)
	var seq int64
	var created, updated time.Time
	if err := row.Scan(&seq, &created, &updated); err != nil {
		return APIKey{}, fmt.Errorf("apikeys: create: %w", err)
	}
	k.RowSeq = seq
	k.CreatedAt = created
	k.UpdatedAt = updated
	return k, nil
}

// Get fetches a single row by id under the RLS policy.
func (r *PgxRepository) Get(ctx context.Context, tenantID, apiKeyID string) (APIKey, error) {
	row, err := r.scanOne(ctx, `SELECT `+apiKeyCols+` FROM api_key WHERE id = $1 AND tenant_id = $2`, apiKeyID, tenantID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return APIKey{}, ErrNotFound
		}
		return APIKey{}, fmt.Errorf("apikeys: get: %w", err)
	}
	return row, nil
}

// List returns up to limit rows for tenantID newest-first.
func (r *PgxRepository) List(ctx context.Context, tenantID string, limit int) ([]APIKey, bool, error) {
	const stmt = `SELECT ` + apiKeyCols + `
FROM api_key
WHERE tenant_id = $1
ORDER BY created_at DESC
LIMIT $2`
	rows, err := r.pool.Query(ctx, stmt, tenantID, limit+1)
	if err != nil {
		return nil, false, fmt.Errorf("apikeys: list: %w", err)
	}
	defer rows.Close()
	out := make([]APIKey, 0, limit)
	for rows.Next() {
		k, scanErr := r.scanRow(rows)
		if scanErr != nil {
			return nil, false, fmt.Errorf("apikeys: list scan: %w", scanErr)
		}
		out = append(out, k)
	}
	if err := rows.Err(); err != nil {
		return nil, false, err
	}
	hasMore := len(out) > limit
	if hasMore {
		out = out[:limit]
	}
	return out, hasMore, nil
}

// Update applies a patch under an ETag (row_seq) check.
func (r *PgxRepository) Update(ctx context.Context, tenantID, apiKeyID string, expectedSeq int64, patch UpdatePatch) (APIKey, error) {
	// Build a dynamic UPDATE: nil-pointer fields are left unchanged.
	parts := []string{}
	args := []any{}
	idx := 1
	pushNum := func(col string, val any) {
		parts = append(parts, fmt.Sprintf("%s = $%d", col, idx))
		args = append(args, val)
		idx++
	}
	if patch.Name != nil {
		pushNum("name", *patch.Name)
	}
	if patch.Scopes != nil {
		pushNum("scopes", *patch.Scopes)
	}
	if patch.RateLimitPerMinute != nil {
		pushNum("rate_limit_per_minute", *patch.RateLimitPerMinute)
	}
	if patch.IPAllowlist != nil {
		pushNum("ip_allowlist", *patch.IPAllowlist)
	}
	if patch.ExpiresAt != nil {
		pushNum("expires_at", *patch.ExpiresAt)
	}
	if len(parts) == 0 {
		// No-op update; return the current row.
		return r.Get(ctx, tenantID, apiKeyID)
	}
	parts = append(parts, "updated_at = now()")
	// row_seq is bumped by the trigger.
	parts = append(parts, "row_seq = row_seq + 1")
	args = append(args, apiKeyID, tenantID)
	whereID := idx
	whereTen := idx + 1
	args = append(args, expectedSeq)
	whereSeq := idx + 2
	stmt := fmt.Sprintf(`UPDATE api_key SET %s WHERE id = $%d AND tenant_id = $%d AND ($%d = 0 OR row_seq = $%d) RETURNING %s`,
		strings.Join(parts, ", "), whereID, whereTen, whereSeq, whereSeq, apiKeyCols)
	row, err := r.scanOne(ctx, stmt, args...)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// Either the row doesn't exist OR the row_seq mismatched. Re-fetch to disambiguate.
			if _, getErr := r.Get(ctx, tenantID, apiKeyID); getErr != nil {
				return APIKey{}, getErr
			}
			return APIKey{}, ErrETagMismatch
		}
		return APIKey{}, fmt.Errorf("apikeys: update: %w", err)
	}
	return row, nil
}

// Revoke marks the row revoked.
func (r *PgxRepository) Revoke(ctx context.Context, tenantID, apiKeyID string) (APIKey, error) {
	const stmt = `UPDATE api_key
SET status = 'revoked', revoked_at = now(), updated_at = now(), row_seq = row_seq + 1
WHERE id = $1 AND tenant_id = $2
RETURNING ` + apiKeyCols
	row, err := r.scanOne(ctx, stmt, apiKeyID, tenantID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return APIKey{}, ErrNotFound
		}
		return APIKey{}, fmt.Errorf("apikeys: revoke: %w", err)
	}
	return row, nil
}

// Rotate writes the new PHC + envelope columns, demoting the previous
// PHC into the predecessor columns.
func (r *PgxRepository) Rotate(ctx context.Context, tenantID, apiKeyID string, newPHC, newPrefix string, newHash []byte, newEnv LookupEnvelope, predecessorExpiresAt time.Time) (APIKey, error) {
	const stmt = `UPDATE api_key
SET predecessor_argon_phc = argon_phc,
    predecessor_expires_at = $3,
    argon_phc = $4,
    prefix = $5,
    prefix_lookup_hash = $6,
    prefix_lookup_ciphertext = $7,
    prefix_lookup_wrapped_dek = $8,
    prefix_lookup_nonce = $9,
    prefix_lookup_kid = $10,
    prefix_lookup_key_version = $11,
    rotated_at = now(),
    updated_at = now(),
    row_seq = row_seq + 1
WHERE id = $1 AND tenant_id = $2 AND status = 'active'
RETURNING ` + apiKeyCols
	row, err := r.scanOne(
		ctx, stmt,
		apiKeyID, tenantID, predecessorExpiresAt,
		newPHC, newPrefix, newHash,
		newEnv.Ciphertext, newEnv.WrappedDEK, newEnv.Nonce, newEnv.KID, newEnv.KeyVersion,
	)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// Either no row, or status != active. Re-fetch to give
			// callers the precise sentinel.
			existing, getErr := r.Get(ctx, tenantID, apiKeyID)
			if getErr != nil {
				return APIKey{}, getErr
			}
			if existing.Status != StatusActive {
				return APIKey{}, ErrNotRotatable
			}
			return APIKey{}, ErrNotFound
		}
		return APIKey{}, fmt.Errorf("apikeys: rotate: %w", err)
	}
	return row, nil
}

// LookupByPrefixHash returns active rows whose prefix_lookup_hash
// matches hash. The unique-ish index on prefix_lookup_hash keeps the
// candidate set small.
func (r *PgxRepository) LookupByPrefixHash(ctx context.Context, hash []byte) ([]APIKey, error) {
	const stmt = `SELECT ` + apiKeyCols + `
FROM api_key
WHERE prefix_lookup_hash = $1 AND status = 'active'`
	rows, err := r.pool.Query(ctx, stmt, hash)
	if err != nil {
		return nil, fmt.Errorf("apikeys: lookup: %w", err)
	}
	defer rows.Close()
	var out []APIKey
	for rows.Next() {
		k, scanErr := r.scanRow(rows)
		if scanErr != nil {
			return nil, scanErr
		}
		out = append(out, k)
	}
	return out, rows.Err()
}

// BulkUpdateLastUsed issues a single UPDATE ... FROM VALUES.
func (r *PgxRepository) BulkUpdateLastUsed(ctx context.Context, batch map[string]time.Time) error {
	if len(batch) == 0 {
		return nil
	}
	// Build the VALUES list. Capped at 1000 per ADR 008.
	const cap = 1000
	if len(batch) > cap {
		// Drop the excess on the floor — the next tick will pick
		// them up. Logging is the middleware's responsibility.
		i := 0
		trimmed := make(map[string]time.Time, cap)
		for k, v := range batch {
			if i >= cap {
				break
			}
			trimmed[k] = v
			i++
		}
		batch = trimmed
	}
	args := make([]any, 0, 2*len(batch))
	placeholders := make([]string, 0, len(batch))
	idx := 1
	for id, t := range batch {
		placeholders = append(placeholders, fmt.Sprintf("($%d::text, $%d::timestamptz)", idx, idx+1))
		args = append(args, id, t)
		idx += 2
	}
	stmt := `UPDATE api_key
SET last_used_at = data.t
FROM (VALUES ` + strings.Join(placeholders, ",") + `) AS data(id, t)
WHERE api_key.id = data.id`
	_, err := r.pool.Exec(ctx, stmt, args...)
	return err
}

// SweepExpiredPredecessors clears predecessor columns for rows whose
// predecessor_expires_at has elapsed.
func (r *PgxRepository) SweepExpiredPredecessors(ctx context.Context, now time.Time) (int, error) {
	const stmt = `UPDATE api_key
SET predecessor_argon_phc = NULL,
    predecessor_expires_at = NULL
WHERE predecessor_expires_at IS NOT NULL AND predecessor_expires_at < $1`
	tag, err := r.pool.Exec(ctx, stmt, now)
	if err != nil {
		return 0, err
	}
	return int(tag.RowsAffected()), nil
}

// ---------------------------------------------------------------------
// scan helpers
// ---------------------------------------------------------------------

// apiKeyCols is the canonical column ordering used by every scanRow
// site. Kept in one place so a future ALTER TABLE only requires one
// edit. The gosec G101 finding is a false positive — these are SQL
// column names, not credentials. The "prefix_lookup_*" tokens come
// from the migration in 000007_api_keys.up.sql.
//
//nolint:gosec // G101: SQL column list, not credentials.
const apiKeyCols = `id, tenant_id, COALESCE(environment_id,'') AS environment_id, name, prefix,
    argon_phc,
    COALESCE(predecessor_argon_phc,'') AS predecessor_argon_phc, predecessor_expires_at,
    prefix_lookup_hash,
    prefix_lookup_ciphertext, prefix_lookup_wrapped_dek, prefix_lookup_nonce, prefix_lookup_kid, prefix_lookup_key_version,
    scopes, status, rate_limit_per_minute, ip_allowlist,
    created_by, created_at, updated_at, expires_at, last_used_at, revoked_at, rotated_at, row_seq`

func (r *PgxRepository) scanOne(ctx context.Context, stmt string, args ...any) (APIKey, error) {
	row := r.pool.QueryRow(ctx, stmt, args...)
	return scanFromRow(row)
}

func (r *PgxRepository) scanRow(rows pgx.Rows) (APIKey, error) {
	return scanFromRow(rows)
}

// rowScanner is satisfied by both pgx.Row and pgx.Rows for scan reuse.
type rowScanner interface {
	Scan(dest ...any) error
}

func scanFromRow(rs rowScanner) (APIKey, error) {
	var k APIKey
	var envID, predPHC, status string
	var preExpires, expires, lastUsed, revoked, rotated *time.Time
	var rateLimit *int
	err := rs.Scan(
		&k.ID, &k.TenantID, &envID, &k.Name, &k.Prefix,
		&k.ArgonPHC,
		&predPHC, &preExpires,
		&k.PrefixLookupHash,
		&k.PrefixLookupEnvelope.Ciphertext, &k.PrefixLookupEnvelope.WrappedDEK, &k.PrefixLookupEnvelope.Nonce, &k.PrefixLookupEnvelope.KID, &k.PrefixLookupEnvelope.KeyVersion,
		&k.Scopes, &status, &rateLimit, &k.IPAllowlist,
		&k.CreatedBy, &k.CreatedAt, &k.UpdatedAt, &expires, &lastUsed, &revoked, &rotated, &k.RowSeq,
	)
	if err != nil {
		return APIKey{}, err
	}
	k.EnvironmentID = envID
	k.PredecessorArgonPHC = predPHC
	k.PredecessorExpiresAt = preExpires
	k.Status = Status(status)
	k.RateLimitPerMinute = rateLimit
	k.ExpiresAt = expires
	k.LastUsedAt = lastUsed
	k.RevokedAt = revoked
	k.RotatedAt = rotated
	return k, nil
}
