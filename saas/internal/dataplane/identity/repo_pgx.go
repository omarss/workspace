package identity

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
	"github.com/omarss/saas/internal/platform/crypto"
	"github.com/omarss/saas/internal/platform/crypto/envelope"
)

// resourceUser is the canonical resource_type label used in AAD binding
// for every row in this module. See ADR 004 / 017 §AAD binding. Hard-coded
// rather than derived so a refactor cannot silently change the binding and
// invalidate every persisted envelope.
const resourceUser = "user"

// PgxRepository is the pgx-backed Repository implementation. It owns the
// sqlc Queries plus the envelope encryptor/decryptor + the deployment id
// used for kid binding (CONVENTIONS.md §10.1).
//
// CRITICAL invariants (Phase 5 plan §5.4):
//
//   - Every Create / Update runs crypto.EncryptPIIFieldsStrict BEFORE binding
//     sqlc parameters. Strict mode refuses silent envelope drop on a missing
//     sibling field — a schema bug surfaces as a 5xx, never a plaintext write.
//   - Every Get / List verifies env.KID == r.deploymentID BEFORE calling
//     Decrypt. Calling Decrypt with a foreign kid would let OpenBao decrypt
//     under the wrong transit key in a misconfigured cluster.
//   - The pool's AfterAcquire hook is expected to SET LOCAL
//     app.current_tenant_id = $tenant on every connection (defense layer 3).
//     Without that hook, RLS silently returns empty result sets.
type PgxRepository struct {
	q            *db.Queries
	enc          crypto.Encryptor
	dec          crypto.Decryptor
	deploymentID string
	now          func() time.Time
}

// NewPgxRepository constructs the repository.
func NewPgxRepository(q *db.Queries, enc crypto.Encryptor, dec crypto.Decryptor, deploymentID string) *PgxRepository {
	return &PgxRepository{
		q:            q,
		enc:          enc,
		dec:          dec,
		deploymentID: deploymentID,
		now:          time.Now,
	}
}

// WithClock overrides the clock used for state TTL comparisons. Tests only.
func (r *PgxRepository) WithClock(now func() time.Time) *PgxRepository {
	r.now = now
	return r
}

// Create persists a User row. Runs strict-mode encryption first; the walker
// clears the plaintext fields on u after wrapping so no caller can re-read
// them from the in-memory struct.
//
// Returns ErrEmailTaken on the per-tenant UNIQUE collision.
func (r *PgxRepository) Create(ctx context.Context, u User) (User, error) {
	// Strict envelope walker: refuses to proceed if any pii-tagged field on
	// User lacks an <Field>Envelope sibling. Adding a new PII column requires
	// adding the sibling in domain.go or this call fails closed.
	//
	// AAD binds the ciphertext to (deployment_id, "user", u.ID, field_name)
	// so a row stolen from a sibling user in the same deployment fails the
	// AEAD verify on decrypt. See ADR 004 / 017 §AAD binding.
	if err := crypto.EncryptPIIFieldsStrict(ctx, r.enc, r.deploymentID, resourceUser, u.ID, &u); err != nil {
		return User{}, err
	}
	metaJSON, err := marshalUserMetadata(u.Metadata)
	if err != nil {
		return User{}, err
	}
	params := db.CreatePlatformUserParams{
		ID:              u.ID,
		TenantID:        u.TenantID,
		EmailLookupHash: u.EmailLookupHash,
		EmailCiphertext: u.EmailEnvelope.Ciphertext,
		EmailWrappedDek: u.EmailEnvelope.WrappedDEK,
		EmailNonce:      u.EmailEnvelope.Nonce,
		EmailKid:        u.EmailEnvelope.KID,
		EmailKeyVersion: keyVersionToInt32(u.EmailEnvelope.KeyVersion),
		EmailVerified:   u.EmailVerified,
		KeycloakUserID:  u.KeycloakUserID,
		Status:          string(u.Status),
		Metadata:        metaJSON,
	}
	if !u.NameEnvelope.IsZero() {
		params.NameCiphertext = u.NameEnvelope.Ciphertext
		wrapped := u.NameEnvelope.WrappedDEK
		params.NameWrappedDek = &wrapped
		params.NameNonce = u.NameEnvelope.Nonce
		kid := u.NameEnvelope.KID
		params.NameKid = &kid
		ver := keyVersionToInt32(u.NameEnvelope.KeyVersion)
		params.NameKeyVersion = &ver
	}
	if !u.PhoneEnvelope.IsZero() {
		params.PhoneCiphertext = u.PhoneEnvelope.Ciphertext
		wrapped := u.PhoneEnvelope.WrappedDEK
		params.PhoneWrappedDek = &wrapped
		params.PhoneNonce = u.PhoneEnvelope.Nonce
		kid := u.PhoneEnvelope.KID
		params.PhoneKid = &kid
		ver := keyVersionToInt32(u.PhoneEnvelope.KeyVersion)
		params.PhoneKeyVersion = &ver
	}
	row, err := r.q.CreatePlatformUser(ctx, params)
	if err != nil {
		if isUniqueViolation(err) {
			return User{}, ErrEmailTaken
		}
		return User{}, err
	}
	return r.hydrate(ctx, row)
}

// Get returns the row matching userID, scoped to tenantID. Verifies the kid
// on every envelope column before issuing any Decrypt call.
func (r *PgxRepository) Get(ctx context.Context, tenantID, userID string) (User, error) {
	row, err := r.q.GetPlatformUser(ctx, userID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return User{}, ErrNotFound
		}
		return User{}, err
	}
	// Cross-tenant rows must look like ErrNotFound at this layer (defense in
	// depth with RLS — the service is also doing AssertTenant).
	if row.TenantID != tenantID {
		return User{}, ErrNotFound
	}
	return r.hydrate(ctx, row)
}

// GetByEmailHash performs the HMAC-equality lookup. Cross-tenant rows return
// ErrNotFound (same fail-closed shape as Get).
func (r *PgxRepository) GetByEmailHash(ctx context.Context, tenantID string, emailHash []byte) (User, error) {
	row, err := r.q.GetPlatformUserByEmailHash(ctx, db.GetPlatformUserByEmailHashParams{
		TenantID:        tenantID,
		EmailLookupHash: emailHash,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return User{}, ErrNotFound
		}
		return User{}, err
	}
	return r.hydrate(ctx, row)
}

// List paginates users for tenantID. Decrypts every row's PII on the way out.
func (r *PgxRepository) List(ctx context.Context, tenantID string, limit int, cur *ListCursor, emailHash []byte) ([]User, bool, error) {
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	// emailHash filter: if supplied, fall back to the by-hash lookup (single
	// row at most). The HMAC equality is the cheapest predicate available.
	if len(emailHash) > 0 {
		u, err := r.GetByEmailHash(ctx, tenantID, emailHash)
		if err != nil {
			if errors.Is(err, ErrNotFound) {
				return nil, false, nil
			}
			return nil, false, err
		}
		return []User{u}, false, nil
	}
	params := db.ListPlatformUsersParams{
		TenantID: tenantID,
		RowLimit: int32(limit + 1),
	}
	if cur != nil {
		params.CursorCreatedAt = pgtype.Timestamptz{Time: cur.CreatedAt, Valid: true}
		cursorID := cur.ID
		params.CursorID = &cursorID
	}
	rows, err := r.q.ListPlatformUsers(ctx, params)
	if err != nil {
		return nil, false, err
	}
	hasMore := len(rows) > limit
	if hasMore {
		rows = rows[:limit]
	}
	out := make([]User, 0, len(rows))
	for _, row := range rows {
		u, err := r.hydrate(ctx, row)
		if err != nil {
			return nil, false, err
		}
		out = append(out, u)
	}
	return out, hasMore, nil
}

// Update applies the patch under optimistic concurrency. Runs strict-mode
// encryption on the patch struct so a missing sibling on the dynamic Name /
// Phone columns also fails closed.
func (r *PgxRepository) Update(ctx context.Context, tenantID, userID string, expectedSeq int64, patch UpdatePatch) (User, error) {
	// Read the row first so the cross-tenant 404 fires before the UPDATE.
	if _, err := r.q.GetPlatformUser(ctx, userID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return User{}, ErrNotFound
		}
		return User{}, err
	}
	// Strict walker covers UpdatePatch — both Name and Phone declare envelope
	// siblings. Empty *string fields are skipped by the walker because their
	// underlying value is "" — the walker only encrypts non-empty plaintext.
	// AAD binds to userID so a patch payload cannot be replayed against a
	// different user's row.
	if err := crypto.EncryptPIIFieldsStrict(ctx, r.enc, r.deploymentID, resourceUser, userID, &patch); err != nil {
		return User{}, err
	}
	params := db.UpdatePlatformUserParams{
		ID:     userID,
		RowSeq: expectedSeq,
	}
	if !patch.NameEnvelope.IsZero() {
		params.NameCiphertext = patch.NameEnvelope.Ciphertext
		wrapped := patch.NameEnvelope.WrappedDEK
		params.NameWrappedDek = &wrapped
		params.NameNonce = patch.NameEnvelope.Nonce
		kid := patch.NameEnvelope.KID
		params.NameKid = &kid
		ver := keyVersionToInt32(patch.NameEnvelope.KeyVersion)
		params.NameKeyVersion = &ver
	}
	if !patch.PhoneEnvelope.IsZero() {
		params.PhoneCiphertext = patch.PhoneEnvelope.Ciphertext
		wrapped := patch.PhoneEnvelope.WrappedDEK
		params.PhoneWrappedDek = &wrapped
		params.PhoneNonce = patch.PhoneEnvelope.Nonce
		kid := patch.PhoneEnvelope.KID
		params.PhoneKid = &kid
		ver := keyVersionToInt32(patch.PhoneEnvelope.KeyVersion)
		params.PhoneKeyVersion = &ver
	}
	if patch.PatchMetadata {
		metaJSON, err := marshalUserMetadata(patch.Metadata)
		if err != nil {
			return User{}, err
		}
		params.Metadata = metaJSON
	}
	row, err := r.q.UpdatePlatformUser(ctx, params)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// Distinguish ETag mismatch (row exists, row_seq stale) from a
			// concurrent delete (row gone).
			if _, gerr := r.q.GetPlatformUser(ctx, userID); gerr == nil {
				return User{}, ErrETagMismatch
			}
			return User{}, ErrNotFound
		}
		return User{}, err
	}
	if row.TenantID != tenantID {
		return User{}, ErrNotFound
	}
	return r.hydrate(ctx, row)
}

// SetStatus flips status without re-encrypting PII.
func (r *PgxRepository) SetStatus(ctx context.Context, tenantID, userID string, status Status) (User, error) {
	row, err := r.q.SetPlatformUserStatus(ctx, db.SetPlatformUserStatusParams{
		ID:     userID,
		Status: string(status),
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return User{}, ErrNotFound
		}
		return User{}, err
	}
	if row.TenantID != tenantID {
		return User{}, ErrNotFound
	}
	return r.hydrate(ctx, row)
}

// SetEmailVerified flips the email_verified flag.
func (r *PgxRepository) SetEmailVerified(ctx context.Context, tenantID, userID string, verified bool) (User, error) {
	row, err := r.q.SetPlatformUserEmailVerified(ctx, db.SetPlatformUserEmailVerifiedParams{
		ID:            userID,
		EmailVerified: verified,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return User{}, ErrNotFound
		}
		return User{}, err
	}
	if row.TenantID != tenantID {
		return User{}, ErrNotFound
	}
	return r.hydrate(ctx, row)
}

// SoftDelete marks the row deleted under optimistic concurrency.
func (r *PgxRepository) SoftDelete(ctx context.Context, tenantID, userID string, expectedSeq int64) (User, error) {
	// Confirm the row exists + belongs to tenantID before the UPDATE so we
	// can distinguish ErrNotFound vs ErrETagMismatch in the post-error branch.
	existing, err := r.q.GetPlatformUser(ctx, userID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return User{}, ErrNotFound
		}
		return User{}, err
	}
	if existing.TenantID != tenantID {
		return User{}, ErrNotFound
	}
	row, err := r.q.SoftDeletePlatformUser(ctx, db.SoftDeletePlatformUserParams{
		ID:     userID,
		RowSeq: expectedSeq,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return User{}, ErrETagMismatch
		}
		return User{}, err
	}
	return r.hydrate(ctx, row)
}

// LinkSocialProvider inserts (or refreshes) a mapping row.
func (r *PgxRepository) LinkSocialProvider(ctx context.Context, tenantID, userID string, provider Provider, externalSubject string) error {
	return r.q.LinkIdentityProvider(ctx, db.LinkIdentityProviderParams{
		PlatformUserID:  userID,
		TenantID:        tenantID,
		Provider:        string(provider),
		ExternalSubject: externalSubject,
	})
}

// UnlinkSocialProvider removes the mapping row.
func (r *PgxRepository) UnlinkSocialProvider(ctx context.Context, _, userID string, provider Provider) error {
	_, err := r.q.UnlinkIdentityProvider(ctx, db.UnlinkIdentityProviderParams{
		PlatformUserID: userID,
		Provider:       string(provider),
	})
	return err
}

// ListSocialProviders returns mapping rows for a user.
func (r *PgxRepository) ListSocialProviders(ctx context.Context, tenantID, userID string) ([]SocialProvider, error) {
	rows, err := r.q.ListIdentityProviders(ctx, db.ListIdentityProvidersParams{
		PlatformUserID: userID,
		TenantID:       tenantID,
	})
	if err != nil {
		return nil, err
	}
	out := make([]SocialProvider, 0, len(rows))
	for _, row := range rows {
		out = append(out, SocialProvider{
			Provider:        Provider(row.Provider),
			ExternalSubject: row.ExternalSubject,
			LinkedAt:        row.LinkedAt.Time.UTC(),
		})
	}
	return out, nil
}

// InsertSocialLoginState persists the 5-minute state row.
func (r *PgxRepository) InsertSocialLoginState(ctx context.Context, state SocialLoginState) error {
	return r.q.InsertSocialLoginState(ctx, db.InsertSocialLoginStateParams{
		State:          state.State,
		TenantID:       state.TenantID,
		PlatformUserID: state.PlatformUserID,
		Provider:       string(state.Provider),
		ReturnTo:       state.ReturnTo,
		Nonce:          state.Nonce,
		ExpiresAt:      pgtype.Timestamptz{Time: state.ExpiresAt, Valid: true},
	})
}

// ConsumeSocialLoginState atomically marks the state consumed. Returns
// ErrNotFound for unknown / expired / already-used states. The service
// re-reads to distinguish ErrStateExpired vs ErrStateAlreadyUsed when needed.
func (r *PgxRepository) ConsumeSocialLoginState(ctx context.Context, stateToken string) (SocialLoginState, error) {
	row, err := r.q.ConsumeSocialLoginState(ctx, stateToken)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return SocialLoginState{}, ErrNotFound
		}
		return SocialLoginState{}, err
	}
	out := SocialLoginState{
		State:          row.State,
		TenantID:       row.TenantID,
		PlatformUserID: row.PlatformUserID,
		Provider:       Provider(row.Provider),
		ReturnTo:       row.ReturnTo,
		Nonce:          row.Nonce,
		CreatedAt:      row.CreatedAt.Time.UTC(),
		ExpiresAt:      row.ExpiresAt.Time.UTC(),
	}
	if row.ConsumedAt.Valid {
		t := row.ConsumedAt.Time.UTC()
		out.ConsumedAt = &t
	}
	return out, nil
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

// hydrate converts a sqlc row into the domain User, decrypting every PII
// column. The kid verification is implicit in r.dec.DecryptField — it returns
// envelope.ErrKidMismatch when env.KID != r.deploymentID, so a row whose kid
// disagrees with this deployment refuses to surface a plaintext value.
func (r *PgxRepository) hydrate(ctx context.Context, row db.PlatformUser) (User, error) {
	meta := map[string]string{}
	if len(row.Metadata) > 0 {
		if err := json.Unmarshal(row.Metadata, &meta); err != nil {
			return User{}, err
		}
	}
	var deletedAt *time.Time
	if row.DeletedAt.Valid {
		t := row.DeletedAt.Time.UTC()
		deletedAt = &t
	}

	u := User{
		ID:              row.ID,
		TenantID:        row.TenantID,
		KeycloakUserID:  row.KeycloakUserID,
		Status:          Status(row.Status),
		EmailVerified:   row.EmailVerified,
		EmailLookupHash: row.EmailLookupHash,
		Metadata:        meta,
		RowSeq:          row.RowSeq,
		CreatedAt:       row.CreatedAt.Time.UTC(),
		UpdatedAt:       row.UpdatedAt.Time.UTC(),
		DeletedAt:       deletedAt,
	}

	// Email: NOT NULL — every row carries an envelope. Pre-check the kid
	// EXPLICITLY here so the kid mismatch surfaces without going through
	// envelope.Client (lets us return ErrKidMismatch even when the bao
	// client is nil — defense-in-depth for the test path).
	if row.EmailKid != r.deploymentID {
		return User{}, envelope.ErrKidMismatch
	}
	emailEnv := crypto.Envelope{
		Ciphertext: row.EmailCiphertext,
		WrappedDEK: row.EmailWrappedDek,
		Nonce:      row.EmailNonce,
		KID:        row.EmailKid,
		KeyVersion: int(row.EmailKeyVersion),
	}
	emailPlain, err := r.dec.DecryptField(ctx, emailEnv, r.deploymentID, crypto.FieldAAD(r.deploymentID, resourceUser, row.ID, "Email"))
	if err != nil {
		return User{}, err
	}
	u.Email = string(emailPlain)
	u.EmailEnvelope = emailEnv

	// Name + Phone: nullable. Skip the kid check when the envelope is absent.
	if row.NameWrappedDek != nil && *row.NameWrappedDek != "" && row.NameKid != nil {
		if *row.NameKid != r.deploymentID {
			return User{}, envelope.ErrKidMismatch
		}
		nameEnv := crypto.Envelope{
			Ciphertext: row.NameCiphertext,
			WrappedDEK: *row.NameWrappedDek,
			Nonce:      row.NameNonce,
			KID:        *row.NameKid,
		}
		if row.NameKeyVersion != nil {
			nameEnv.KeyVersion = int(*row.NameKeyVersion)
		}
		namePlain, err := r.dec.DecryptField(ctx, nameEnv, r.deploymentID, crypto.FieldAAD(r.deploymentID, resourceUser, row.ID, "Name"))
		if err != nil {
			return User{}, err
		}
		u.Name = string(namePlain)
		u.NameEnvelope = nameEnv
	}

	if row.PhoneWrappedDek != nil && *row.PhoneWrappedDek != "" && row.PhoneKid != nil {
		if *row.PhoneKid != r.deploymentID {
			return User{}, envelope.ErrKidMismatch
		}
		phoneEnv := crypto.Envelope{
			Ciphertext: row.PhoneCiphertext,
			WrappedDEK: *row.PhoneWrappedDek,
			Nonce:      row.PhoneNonce,
			KID:        *row.PhoneKid,
		}
		if row.PhoneKeyVersion != nil {
			phoneEnv.KeyVersion = int(*row.PhoneKeyVersion)
		}
		phonePlain, err := r.dec.DecryptField(ctx, phoneEnv, r.deploymentID, crypto.FieldAAD(r.deploymentID, resourceUser, row.ID, "Phone"))
		if err != nil {
			return User{}, err
		}
		u.Phone = string(phonePlain)
		u.PhoneEnvelope = phoneEnv
	}

	return u, nil
}

func marshalUserMetadata(m map[string]string) ([]byte, error) {
	if m == nil {
		m = map[string]string{}
	}
	return json.Marshal(m)
}

// keyVersionToInt32 narrows a transit key version safely. KeyVersion comes
// from OpenBao's "vault:v<N>:..." token; in practice it stays within int32
// for the lifetime of the deployment (rotation is annual, not millisecond).
// We cap at math.MaxInt32 defensively so a runaway parse cannot overflow.
func keyVersionToInt32(v int) int32 {
	if v < 0 {
		return 0
	}
	if v > 0x7FFFFFFF {
		return 0x7FFFFFFF
	}
	return int32(v)
}

// isUniqueViolation mirrors the tenancy detector — see tenancy/repo_pgx.go.
func isUniqueViolation(err error) bool {
	if err == nil {
		return false
	}
	return strings.Contains(err.Error(), "23505") ||
		strings.Contains(strings.ToLower(err.Error()), "duplicate key")
}
