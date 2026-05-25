package notifications

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

// resourceChannel / resourceNotification are the canonical resource_type
// labels used in AAD binding for rows in this module. See ADR 004 / 017
// §AAD binding. Hard-coded rather than derived so a refactor cannot
// silently change the binding and invalidate persisted envelopes.
const (
	resourceChannel      = "channel"
	resourceNotification = "notification"
)

// PgxRepository is the pgx-backed Repository implementation.
//
// CRITICAL invariants (mirrors identity Phase 5):
//
//   - Every channel Create / RotateSecrets runs crypto.EncryptPIIFieldsStrict
//     BEFORE binding sqlc parameters. Strict mode fails closed when the
//     Secrets/SecretsEnvelope sibling is missing — a schema bug surfaces as
//     a 5xx, never a plaintext write.
//   - Every channel Get / List verifies env.KID == r.deploymentID BEFORE
//     calling Decrypt. Layer 5 of the eight-layer tenant invariant.
//   - The Notification payload runs the same walker; ToUserID is treated as
//     a non-PII platform id (it is the platform's own ULID).
type PgxRepository struct {
	q            *db.Queries
	enc          crypto.Encryptor
	dec          crypto.Decryptor
	deploymentID string
}

// NewPgxRepository wires the repo.
func NewPgxRepository(q *db.Queries, enc crypto.Encryptor, dec crypto.Decryptor, deploymentID string) *PgxRepository {
	return &PgxRepository{q: q, enc: enc, dec: dec, deploymentID: deploymentID}
}

// ---------------------------------------------------------------------------
// Channels
// ---------------------------------------------------------------------------

// CreateChannel runs the strict envelope walker on the Secrets payload, then
// inserts the row. For the in_app provider the empty plaintext skips the
// walker — no encryption needed when there's nothing to encrypt.
func (r *PgxRepository) CreateChannel(ctx context.Context, c Channel) (Channel, error) {
	// AAD binds to (deployment, "channel", channelID, field) so a Secrets
	// ciphertext from one channel cannot be pasted into another channel's
	// row inside the same deployment — the cross-resource swap attack.
	if err := crypto.EncryptPIIFieldsStrict(ctx, r.enc, r.deploymentID, resourceChannel, c.ID, &c); err != nil {
		return Channel{}, err
	}
	configJSON, err := marshalStringMap(c.Config)
	if err != nil {
		return Channel{}, err
	}
	params := db.CreateNotificationChannelParams{
		ID:           c.ID,
		TenantID:     c.TenantID,
		Provider:     string(c.Provider),
		Name:         c.Name,
		Config:       configJSON,
		IsDefaultFor: c.IsDefaultFor,
		Status:       string(c.Status),
	}
	if !c.SecretsEnvelope.IsZero() {
		params.SecretsCiphertext = c.SecretsEnvelope.Ciphertext
		wrapped := c.SecretsEnvelope.WrappedDEK
		params.SecretsWrappedDek = &wrapped
		params.SecretsNonce = c.SecretsEnvelope.Nonce
		kid := c.SecretsEnvelope.KID
		params.SecretsKid = &kid
		ver := keyVersionToInt32(c.SecretsEnvelope.KeyVersion)
		params.SecretsKeyVersion = &ver
	}
	row, err := r.q.CreateNotificationChannel(ctx, params)
	if err != nil {
		if isUniqueViolation(err) {
			return Channel{}, ErrNameTaken
		}
		return Channel{}, err
	}
	return r.hydrateChannel(ctx, row)
}

// GetChannel returns the channel row matching channelID, scoped to tenant.
func (r *PgxRepository) GetChannel(ctx context.Context, tenantID, channelID string) (Channel, error) {
	row, err := r.q.GetNotificationChannel(ctx, channelID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Channel{}, ErrNotFound
		}
		return Channel{}, err
	}
	if row.TenantID != tenantID {
		return Channel{}, ErrNotFound
	}
	return r.hydrateChannel(ctx, row)
}

// GetChannelByName is a convenience used by the worker default-channel lookup.
func (r *PgxRepository) GetChannelByName(ctx context.Context, tenantID, name string) (Channel, error) {
	row, err := r.q.GetNotificationChannelByName(ctx, db.GetNotificationChannelByNameParams{
		TenantID: tenantID,
		Name:     name,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Channel{}, ErrNotFound
		}
		return Channel{}, err
	}
	return r.hydrateChannel(ctx, row)
}

// ListChannels returns up to limit channels in tenantID.
func (r *PgxRepository) ListChannels(ctx context.Context, tenantID string, limit int) ([]Channel, error) {
	rows, err := r.q.ListNotificationChannels(ctx, db.ListNotificationChannelsParams{
		TenantID: tenantID,
		RowLimit: clampLimit(limit),
	})
	if err != nil {
		return nil, err
	}
	out := make([]Channel, 0, len(rows))
	for _, row := range rows {
		ch, err := r.hydrateChannel(ctx, row)
		if err != nil {
			return nil, err
		}
		out = append(out, ch)
	}
	return out, nil
}

// UpdateChannel applies the meta-only patch under optimistic concurrency.
func (r *PgxRepository) UpdateChannel(ctx context.Context, tenantID, channelID string, expectedSeq int64, patch ChannelPatch) (Channel, error) {
	// Confirm row exists + belongs to tenant so cross-tenant 404 fires
	// before the UPDATE.
	if existing, err := r.q.GetNotificationChannel(ctx, channelID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Channel{}, ErrNotFound
		}
		return Channel{}, err
	} else if existing.TenantID != tenantID {
		return Channel{}, ErrNotFound
	}
	params := db.UpdateNotificationChannelMetaParams{
		ID:     channelID,
		RowSeq: expectedSeq,
	}
	if patch.Name != nil {
		name := *patch.Name
		params.Name = &name
	}
	if patch.Status != nil {
		status := string(*patch.Status)
		params.Status = &status
	}
	if patch.PatchDefaults {
		// nil slice → no change via COALESCE; empty slice → clears defaults.
		if patch.IsDefaultFor == nil {
			patch.IsDefaultFor = []string{}
		}
		params.IsDefaultFor = patch.IsDefaultFor
	}
	if patch.PatchConfig {
		configJSON, err := marshalStringMap(patch.Config)
		if err != nil {
			return Channel{}, err
		}
		params.Config = configJSON
	}
	row, err := r.q.UpdateNotificationChannelMeta(ctx, params)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			// Distinguish stale ETag from concurrent delete.
			if _, gerr := r.q.GetNotificationChannel(ctx, channelID); gerr == nil {
				return Channel{}, ErrETagMismatch
			}
			return Channel{}, ErrNotFound
		}
		return Channel{}, err
	}
	if row.TenantID != tenantID {
		return Channel{}, ErrNotFound
	}
	return r.hydrateChannel(ctx, row)
}

// DeleteChannel soft-deletes under optimistic concurrency.
func (r *PgxRepository) DeleteChannel(ctx context.Context, tenantID, channelID string, expectedSeq int64) error {
	existing, err := r.q.GetNotificationChannel(ctx, channelID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		return err
	}
	if existing.TenantID != tenantID {
		return ErrNotFound
	}
	affected, err := r.q.SoftDeleteNotificationChannel(ctx, db.SoftDeleteNotificationChannelParams{
		ID:     channelID,
		RowSeq: expectedSeq,
	})
	if err != nil {
		return err
	}
	if affected == 0 {
		return ErrETagMismatch
	}
	return nil
}

// RotateChannelSecrets is the only Repository path that accepts new
// credentials. Runs the strict walker on a transient Channel-shaped struct
// so the sibling envelope assertion fires for rotations too.
func (r *PgxRepository) RotateChannelSecrets(ctx context.Context, tenantID, channelID string, newPlaintext string) (Channel, error) {
	// Confirm tenant ownership before any encrypt round-trip.
	existing, err := r.q.GetNotificationChannel(ctx, channelID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Channel{}, ErrNotFound
		}
		return Channel{}, err
	}
	if existing.TenantID != tenantID {
		return Channel{}, ErrNotFound
	}
	wrapper := struct {
		Secrets         string `pii:"true" sensitive:"true"`
		SecretsEnvelope crypto.Envelope
	}{
		Secrets: newPlaintext,
	}
	if err := crypto.EncryptPIIFieldsStrict(ctx, r.enc, r.deploymentID, resourceChannel, channelID, &wrapper); err != nil {
		return Channel{}, err
	}
	params := db.RotateNotificationChannelSecretsParams{
		ID:                channelID,
		SecretsCiphertext: wrapper.SecretsEnvelope.Ciphertext,
	}
	if !wrapper.SecretsEnvelope.IsZero() {
		wrapped := wrapper.SecretsEnvelope.WrappedDEK
		params.SecretsWrappedDek = &wrapped
		params.SecretsNonce = wrapper.SecretsEnvelope.Nonce
		kid := wrapper.SecretsEnvelope.KID
		params.SecretsKid = &kid
		ver := keyVersionToInt32(wrapper.SecretsEnvelope.KeyVersion)
		params.SecretsKeyVersion = &ver
	}
	row, err := r.q.RotateNotificationChannelSecrets(ctx, params)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Channel{}, ErrNotFound
		}
		return Channel{}, err
	}
	return r.hydrateChannel(ctx, row)
}

// SetChannelNovuIntegrationID is called by the worker after Novu confirms
// the integration. The platform stores the returned id for subsequent
// integration updates.
func (r *PgxRepository) SetChannelNovuIntegrationID(ctx context.Context, channelID, novuIntegrationID string) error {
	v := novuIntegrationID
	return r.q.SetNotificationChannelNovuIntegration(ctx, db.SetNotificationChannelNovuIntegrationParams{
		ID:                channelID,
		NovuIntegrationID: &v,
	})
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

// RegisterWorkflow inserts a name → novu_workflow_id mapping.
func (r *PgxRepository) RegisterWorkflow(ctx context.Context, w Workflow) (Workflow, error) {
	params := db.RegisterNotificationWorkflowParams{
		ID:             w.ID,
		TenantID:       w.TenantID,
		Name:           w.Name,
		NovuWorkflowID: w.NovuWorkflowID,
	}
	if w.Description != "" {
		desc := w.Description
		params.Description = &desc
	}
	row, err := r.q.RegisterNotificationWorkflow(ctx, params)
	if err != nil {
		if isUniqueViolation(err) {
			return Workflow{}, ErrNameTaken
		}
		return Workflow{}, err
	}
	return workflowFromRow(row), nil
}

// GetWorkflowByName returns the workflow with the given name.
func (r *PgxRepository) GetWorkflowByName(ctx context.Context, tenantID, name string) (Workflow, error) {
	row, err := r.q.GetNotificationWorkflowByName(ctx, db.GetNotificationWorkflowByNameParams{
		TenantID: tenantID,
		Name:     name,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Workflow{}, ErrNotFound
		}
		return Workflow{}, err
	}
	return workflowFromRow(row), nil
}

// UpdateWorkflow applies a partial update to (novu_workflow_id, description).
// Cross-tenant rows are 404 (the UPDATE filters on tenant_id directly so
// the row simply does not match).
func (r *PgxRepository) UpdateWorkflow(ctx context.Context, tenantID, workflowID string, patch WorkflowPatch) (Workflow, error) {
	params := db.UpdateNotificationWorkflowParams{
		ID:       workflowID,
		TenantID: tenantID,
	}
	if patch.NovuWorkflowID != nil {
		v := *patch.NovuWorkflowID
		params.NovuWorkflowID = &v
	}
	if patch.Description != nil {
		v := *patch.Description
		params.Description = &v
	}
	row, err := r.q.UpdateNotificationWorkflow(ctx, params)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Workflow{}, ErrNotFound
		}
		return Workflow{}, err
	}
	return workflowFromRow(row), nil
}

// ListWorkflows enumerates workflows in a tenant.
func (r *PgxRepository) ListWorkflows(ctx context.Context, tenantID string) ([]Workflow, error) {
	rows, err := r.q.ListNotificationWorkflows(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	out := make([]Workflow, 0, len(rows))
	for _, row := range rows {
		out = append(out, workflowFromRow(row))
	}
	return out, nil
}

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

// CreateNotification persists a queued notification. Runs the strict walker
// over Payload before binding params so a payload always lands envelope-
// encrypted with a valid kid.
func (r *PgxRepository) CreateNotification(ctx context.Context, n Notification) (Notification, error) {
	if err := crypto.EncryptPIIFieldsStrict(ctx, r.enc, r.deploymentID, resourceNotification, n.ID, &n); err != nil {
		return Notification{}, err
	}
	if n.PayloadEnvelope.IsZero() {
		// Empty payload would skip the walker (string == "" branch). We
		// still need the kid binding, so encrypt a literal "{}".
		envFields := struct {
			Payload         string `pii:"true" sensitive:"true"`
			PayloadEnvelope crypto.Envelope
		}{Payload: "{}"}
		if err := crypto.EncryptPIIFieldsStrict(ctx, r.enc, r.deploymentID, resourceNotification, n.ID, &envFields); err != nil {
			return Notification{}, err
		}
		n.PayloadEnvelope = envFields.PayloadEnvelope
	}
	params := db.CreateNotificationParams{
		ID:                n.ID,
		TenantID:          n.TenantID,
		WorkflowName:      n.WorkflowName,
		ToUserID:          n.ToUserID,
		PayloadCiphertext: n.PayloadEnvelope.Ciphertext,
		PayloadWrappedDek: n.PayloadEnvelope.WrappedDEK,
		PayloadNonce:      n.PayloadEnvelope.Nonce,
		PayloadKid:        n.PayloadEnvelope.KID,
		PayloadKeyVersion: keyVersionToInt32(n.PayloadEnvelope.KeyVersion),
		Status:            string(n.Status),
	}
	row, err := r.q.CreateNotification(ctx, params)
	if err != nil {
		return Notification{}, err
	}
	return notificationFromRowNoDecrypt(row), nil
}

// GetNotification fetches a notification row + decrypts the payload.
func (r *PgxRepository) GetNotification(ctx context.Context, tenantID, notificationID string) (Notification, error) {
	row, err := r.q.GetNotification(ctx, notificationID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Notification{}, ErrNotFound
		}
		return Notification{}, err
	}
	if row.TenantID != tenantID {
		return Notification{}, ErrNotFound
	}
	return r.hydrateNotification(ctx, row)
}

// ListNotifications paginates notifications by (queued_at, id).
func (r *PgxRepository) ListNotifications(ctx context.Context, tenantID string, limit int, cur *ListCursor) ([]Notification, bool, error) {
	params := db.ListNotificationsParams{
		TenantID: tenantID,
		RowLimit: clampLimit(limit + 1),
	}
	if cur != nil {
		params.CursorQueuedAt = pgtype.Timestamptz{Time: cur.QueuedAt, Valid: true}
		cursorID := cur.ID
		params.CursorID = &cursorID
	}
	rows, err := r.q.ListNotifications(ctx, params)
	if err != nil {
		return nil, false, err
	}
	hasMore := len(rows) > limit
	if hasMore {
		rows = rows[:limit]
	}
	out := make([]Notification, 0, len(rows))
	for _, row := range rows {
		n, err := r.hydrateNotification(ctx, row)
		if err != nil {
			return nil, false, err
		}
		out = append(out, n)
	}
	return out, hasMore, nil
}

// UpdateNotificationStatus is called by the worker once Novu reports back.
func (r *PgxRepository) UpdateNotificationStatus(ctx context.Context, notificationID string, status NotificationStatus, failureReason *string, novuTransactionID *string) (Notification, error) {
	row, err := r.q.UpdateNotificationStatus(ctx, db.UpdateNotificationStatusParams{
		ID:                notificationID,
		Status:            string(status),
		FailureReason:     failureReason,
		NovuTransactionID: novuTransactionID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Notification{}, ErrNotFound
		}
		return Notification{}, err
	}
	return notificationFromRowNoDecrypt(row), nil
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

// hydrateChannel decrypts the Secrets envelope when present and returns the
// domain Channel. kid verification fires BEFORE any decrypt call.
func (r *PgxRepository) hydrateChannel(ctx context.Context, row db.NotificationChannel) (Channel, error) {
	config := map[string]string{}
	if len(row.Config) > 0 {
		if err := json.Unmarshal(row.Config, &config); err != nil {
			return Channel{}, err
		}
	}
	out := Channel{
		ID:                row.ID,
		TenantID:          row.TenantID,
		Provider:          ChannelProvider(row.Provider),
		Name:              row.Name,
		Config:            config,
		Status:            ChannelStatus(row.Status),
		IsDefaultFor:      append([]string{}, row.IsDefaultFor...),
		NovuIntegrationID: row.NovuIntegrationID,
		RowSeq:            row.RowSeq,
		CreatedAt:         row.CreatedAt.Time.UTC(),
		UpdatedAt:         row.UpdatedAt.Time.UTC(),
	}
	if row.LastRotatedAt.Valid {
		t := row.LastRotatedAt.Time.UTC()
		out.LastRotatedAt = &t
	}
	if row.DeletedAt.Valid {
		t := row.DeletedAt.Time.UTC()
		out.DeletedAt = &t
	}
	if row.SecretsWrappedDek != nil && *row.SecretsWrappedDek != "" && row.SecretsKid != nil {
		if *row.SecretsKid != r.deploymentID {
			return Channel{}, envelope.ErrKidMismatch
		}
		env := crypto.Envelope{
			Ciphertext: row.SecretsCiphertext,
			WrappedDEK: *row.SecretsWrappedDek,
			Nonce:      row.SecretsNonce,
			KID:        *row.SecretsKid,
		}
		if row.SecretsKeyVersion != nil {
			env.KeyVersion = int(*row.SecretsKeyVersion)
		}
		plain, err := r.dec.DecryptField(ctx, env, r.deploymentID, crypto.FieldAAD(r.deploymentID, resourceChannel, row.ID, "Secrets"))
		if err != nil {
			return Channel{}, err
		}
		out.Secrets = string(plain)
		out.SecretsEnvelope = env
	}
	return out, nil
}

// hydrateNotification decrypts the payload and returns the domain
// Notification. Decrypt verifies kid bound to deploymentID.
func (r *PgxRepository) hydrateNotification(ctx context.Context, row db.Notification) (Notification, error) {
	if row.PayloadKid != r.deploymentID {
		return Notification{}, envelope.ErrKidMismatch
	}
	env := crypto.Envelope{
		Ciphertext: row.PayloadCiphertext,
		WrappedDEK: row.PayloadWrappedDek,
		Nonce:      row.PayloadNonce,
		KID:        row.PayloadKid,
		KeyVersion: int(row.PayloadKeyVersion),
	}
	plain, err := r.dec.DecryptField(ctx, env, r.deploymentID, crypto.FieldAAD(r.deploymentID, resourceNotification, row.ID, "Payload"))
	if err != nil {
		return Notification{}, err
	}
	n := Notification{
		ID:                row.ID,
		TenantID:          row.TenantID,
		WorkflowName:      row.WorkflowName,
		ToUserID:          row.ToUserID,
		Status:            NotificationStatus(row.Status),
		Payload:           string(plain),
		PayloadEnvelope:   env,
		NovuTransactionID: row.NovuTransactionID,
		QueuedAt:          row.QueuedAt.Time.UTC(),
		FailureReason:     row.FailureReason,
		RowSeq:            row.RowSeq,
	}
	if row.SentAt.Valid {
		t := row.SentAt.Time.UTC()
		n.SentAt = &t
	}
	if row.DeliveredAt.Valid {
		t := row.DeliveredAt.Time.UTC()
		n.DeliveredAt = &t
	}
	if row.FailedAt.Valid {
		t := row.FailedAt.Time.UTC()
		n.FailedAt = &t
	}
	return n, nil
}

// notificationFromRowNoDecrypt returns the row without decrypting the
// payload. Used on write paths where the caller already cleared the
// plaintext via the walker.
func notificationFromRowNoDecrypt(row db.Notification) Notification {
	n := Notification{
		ID:                row.ID,
		TenantID:          row.TenantID,
		WorkflowName:      row.WorkflowName,
		ToUserID:          row.ToUserID,
		Status:            NotificationStatus(row.Status),
		NovuTransactionID: row.NovuTransactionID,
		QueuedAt:          row.QueuedAt.Time.UTC(),
		FailureReason:     row.FailureReason,
		RowSeq:            row.RowSeq,
	}
	if row.SentAt.Valid {
		t := row.SentAt.Time.UTC()
		n.SentAt = &t
	}
	if row.DeliveredAt.Valid {
		t := row.DeliveredAt.Time.UTC()
		n.DeliveredAt = &t
	}
	if row.FailedAt.Valid {
		t := row.FailedAt.Time.UTC()
		n.FailedAt = &t
	}
	return n
}

func workflowFromRow(row db.NotificationWorkflow) Workflow {
	out := Workflow{
		ID:             row.ID,
		TenantID:       row.TenantID,
		Name:           row.Name,
		NovuWorkflowID: row.NovuWorkflowID,
		CreatedAt:      row.CreatedAt.Time.UTC(),
	}
	if row.Description != nil {
		out.Description = *row.Description
	}
	return out
}

// marshalStringMap serialises a map[string]string for the JSONB config
// column. nil maps marshal to {} so the column never carries SQL NULL.
func marshalStringMap(m map[string]string) ([]byte, error) {
	if m == nil {
		m = map[string]string{}
	}
	return json.Marshal(m)
}

// keyVersionToInt32 narrows safely; mirrors identity.repo_pgx.
func keyVersionToInt32(v int) int32 {
	if v < 0 {
		return 0
	}
	if v > 0x7FFFFFFF {
		return 0x7FFFFFFF
	}
	return int32(v)
}

// clampLimit narrows a positive limit safely into int32. List endpoints
// declare max 200 in the OpenAPI spec, but defensive clamping keeps the
// gosec G115 lint happy and protects against accidental overflow if a
// future caller forgets the validation.
func clampLimit(v int) int32 {
	if v < 1 {
		return 1
	}
	if v > 0x7FFFFFFF {
		return 0x7FFFFFFF
	}
	return int32(v)
}

// isUniqueViolation mirrors tenancy / identity detector.
func isUniqueViolation(err error) bool {
	if err == nil {
		return false
	}
	return strings.Contains(err.Error(), "23505") ||
		strings.Contains(strings.ToLower(err.Error()), "duplicate key")
}

// _ keeps the time import warm — used through pgtype/Now interactions.
var _ = time.Now
