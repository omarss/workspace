package organizations

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

// Canonical resource_type labels for AAD binding. Hard-coded so a
// refactor cannot silently change the binding and invalidate every
// persisted envelope (CONVENTIONS.md §10.1).
const (
	resourceOrganization = "organization"
	resourceMember       = "member"
	resourceInvitation   = "invitation"
)

// PgxOrganizationRepo is the pgx-backed OrganizationRepo. Organization
// metadata + slug + name are plaintext; no envelope walker invocation.
type PgxOrganizationRepo struct {
	q *db.Queries
}

// NewPgxOrganizationRepo wires the org repo over sqlc Queries.
func NewPgxOrganizationRepo(q *db.Queries) *PgxOrganizationRepo {
	return &PgxOrganizationRepo{q: q}
}

// Create persists a new organization.
func (r *PgxOrganizationRepo) Create(ctx context.Context, o Organization) (Organization, error) {
	metaJSON, err := marshalStringMap(o.Metadata)
	if err != nil {
		return Organization{}, err
	}
	row, err := r.q.CreateOrganization(ctx, db.CreateOrganizationParams{
		ID:       o.ID,
		TenantID: o.TenantID,
		Slug:     o.Slug,
		Name:     o.Name,
		Status:   string(o.Status),
		Metadata: metaJSON,
	})
	if err != nil {
		if isUniqueViolation(err) {
			return Organization{}, ErrSlugTaken
		}
		return Organization{}, err
	}
	return mapOrganization(row)
}

// Get returns the organization row for orgID scoped to tenantID. Cross-
// tenant rows surface as ErrNotFound to avoid existence-leak attacks.
func (r *PgxOrganizationRepo) Get(ctx context.Context, tenantID, orgID string) (Organization, error) {
	row, err := r.q.GetOrganization(ctx, orgID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Organization{}, ErrNotFound
		}
		return Organization{}, err
	}
	if row.TenantID != tenantID {
		return Organization{}, ErrNotFound
	}
	return mapOrganization(row)
}

// GetBySlug returns the organization in tenantID with the given slug.
func (r *PgxOrganizationRepo) GetBySlug(ctx context.Context, tenantID, slug string) (Organization, error) {
	row, err := r.q.GetOrganizationBySlug(ctx, db.GetOrganizationBySlugParams{
		TenantID: tenantID,
		Slug:     slug,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Organization{}, ErrNotFound
		}
		return Organization{}, err
	}
	return mapOrganization(row)
}

// List paginates organizations for tenantID.
func (r *PgxOrganizationRepo) List(ctx context.Context, tenantID string, limit int, cur *OrgListCursor) ([]Organization, bool, error) {
	params := db.ListOrganizationsByTenantParams{
		TenantID: tenantID,
		RowLimit: clampLimit(limit + 1),
	}
	if cur != nil {
		params.CursorCreatedAt = pgtype.Timestamptz{Time: cur.CreatedAt, Valid: true}
		cid := cur.ID
		params.CursorID = &cid
	}
	rows, err := r.q.ListOrganizationsByTenant(ctx, params)
	if err != nil {
		return nil, false, err
	}
	hasMore := len(rows) > limit
	if hasMore {
		rows = rows[:limit]
	}
	out := make([]Organization, 0, len(rows))
	for _, row := range rows {
		o, err := mapOrganization(row)
		if err != nil {
			return nil, false, err
		}
		out = append(out, o)
	}
	return out, hasMore, nil
}

// Update applies the patch under optimistic concurrency.
func (r *PgxOrganizationRepo) Update(ctx context.Context, tenantID, orgID string, expectedSeq int64, patch OrgPatch) (Organization, error) {
	// Confirm tenant ownership before any UPDATE; cross-tenant rows
	// resolve to ErrNotFound (not ErrETagMismatch) to hide existence.
	if existing, err := r.q.GetOrganization(ctx, orgID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Organization{}, ErrNotFound
		}
		return Organization{}, err
	} else if existing.TenantID != tenantID {
		return Organization{}, ErrNotFound
	}
	params := db.UpdateOrganizationParams{
		ID:     orgID,
		RowSeq: expectedSeq,
	}
	if patch.Name != nil {
		params.Name = patch.Name
	}
	if patch.Status != nil {
		s := string(*patch.Status)
		params.Status = &s
	}
	if patch.PatchMetadata {
		metaJSON, err := marshalStringMap(patch.Metadata)
		if err != nil {
			return Organization{}, err
		}
		params.Metadata = metaJSON
	}
	row, err := r.q.UpdateOrganization(ctx, params)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			if _, gerr := r.q.GetOrganization(ctx, orgID); gerr == nil {
				return Organization{}, ErrETagMismatch
			}
			return Organization{}, ErrNotFound
		}
		return Organization{}, err
	}
	return mapOrganization(row)
}

// SoftDelete flips status to "deleted" + stamps deleted_at.
func (r *PgxOrganizationRepo) SoftDelete(ctx context.Context, tenantID, orgID string, expectedSeq int64) (Organization, error) {
	if existing, err := r.q.GetOrganization(ctx, orgID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Organization{}, ErrNotFound
		}
		return Organization{}, err
	} else if existing.TenantID != tenantID {
		return Organization{}, ErrNotFound
	}
	row, err := r.q.SoftDeleteOrganization(ctx, db.SoftDeleteOrganizationParams{
		ID:     orgID,
		RowSeq: expectedSeq,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			if _, gerr := r.q.GetOrganization(ctx, orgID); gerr == nil {
				return Organization{}, ErrETagMismatch
			}
			return Organization{}, ErrNotFound
		}
		return Organization{}, err
	}
	return mapOrganization(row)
}

// ---------------------------------------------------------------------------
// Members
// ---------------------------------------------------------------------------

// PgxMemberRepo is the pgx-backed MemberRepo.
type PgxMemberRepo struct {
	q *db.Queries
}

// NewPgxMemberRepo wires the member repo over sqlc Queries.
func NewPgxMemberRepo(q *db.Queries) *PgxMemberRepo { return &PgxMemberRepo{q: q} }

// Create persists a new member.
func (r *PgxMemberRepo) Create(ctx context.Context, m Member) (Member, error) {
	metaJSON, err := marshalStringMap(m.Metadata)
	if err != nil {
		return Member{}, err
	}
	row, err := r.q.CreateMember(ctx, db.CreateMemberParams{
		ID:             m.ID,
		TenantID:       m.TenantID,
		OrganizationID: m.OrganizationID,
		UserID:         m.UserID,
		RoleID:         m.RoleID,
		Status:         string(m.Status),
		Metadata:       metaJSON,
	})
	if err != nil {
		if isUniqueViolation(err) {
			return Member{}, ErrMemberExists
		}
		return Member{}, err
	}
	return mapMember(row), nil
}

// Get returns the member row for memberID scoped to tenantID.
func (r *PgxMemberRepo) Get(ctx context.Context, tenantID, memberID string) (Member, error) {
	row, err := r.q.GetMember(ctx, memberID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Member{}, ErrNotFound
		}
		return Member{}, err
	}
	if row.TenantID != tenantID {
		return Member{}, ErrNotFound
	}
	return mapMember(row), nil
}

// GetByUser returns the active member row for (organizationID, userID).
func (r *PgxMemberRepo) GetByUser(ctx context.Context, organizationID, userID string) (Member, error) {
	row, err := r.q.GetMemberByUser(ctx, db.GetMemberByUserParams{
		OrganizationID: organizationID,
		UserID:         userID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Member{}, ErrNotFound
		}
		return Member{}, err
	}
	return mapMember(row), nil
}

// List paginates members for an organization.
func (r *PgxMemberRepo) List(ctx context.Context, tenantID, orgID string, limit int, cur *MemberListCursor) ([]Member, bool, error) {
	params := db.ListMembersByOrganizationParams{
		OrganizationID: orgID,
		RowLimit:       clampLimit(limit + 1),
	}
	if cur != nil {
		params.CursorJoinedAt = pgtype.Timestamptz{Time: cur.JoinedAt, Valid: true}
		cid := cur.ID
		params.CursorID = &cid
	}
	rows, err := r.q.ListMembersByOrganization(ctx, params)
	if err != nil {
		return nil, false, err
	}
	hasMore := len(rows) > limit
	if hasMore {
		rows = rows[:limit]
	}
	out := make([]Member, 0, len(rows))
	for _, row := range rows {
		if row.TenantID != tenantID {
			// Defense in depth — RLS already filters but the check
			// guards against a misconfigured pool.
			continue
		}
		out = append(out, mapMember(row))
	}
	return out, hasMore, nil
}

// UpdateRole patches the role_id column under optimistic concurrency.
func (r *PgxMemberRepo) UpdateRole(ctx context.Context, tenantID, memberID string, expectedSeq int64, roleID *string) (Member, error) {
	existing, err := r.q.GetMember(ctx, memberID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Member{}, ErrNotFound
		}
		return Member{}, err
	}
	if existing.TenantID != tenantID {
		return Member{}, ErrNotFound
	}
	row, err := r.q.UpdateMemberRole(ctx, db.UpdateMemberRoleParams{
		ID:     memberID,
		RowSeq: expectedSeq,
		RoleID: roleID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			if _, gerr := r.q.GetMember(ctx, memberID); gerr == nil {
				return Member{}, ErrETagMismatch
			}
			return Member{}, ErrNotFound
		}
		return Member{}, err
	}
	return mapMember(row), nil
}

// Remove soft-removes a member.
func (r *PgxMemberRepo) Remove(ctx context.Context, tenantID, memberID string, expectedSeq int64) (Member, error) {
	existing, err := r.q.GetMember(ctx, memberID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Member{}, ErrNotFound
		}
		return Member{}, err
	}
	if existing.TenantID != tenantID {
		return Member{}, ErrNotFound
	}
	row, err := r.q.RemoveMember(ctx, db.RemoveMemberParams{
		ID:     memberID,
		RowSeq: expectedSeq,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			if _, gerr := r.q.GetMember(ctx, memberID); gerr == nil {
				return Member{}, ErrETagMismatch
			}
			return Member{}, ErrNotFound
		}
		return Member{}, err
	}
	return mapMember(row), nil
}

// CountActive counts active members in an organization.
func (r *PgxMemberRepo) CountActive(ctx context.Context, organizationID string) (int64, error) {
	return r.q.CountActiveMembersByOrganization(ctx, organizationID)
}

// ---------------------------------------------------------------------------
// Invitations
// ---------------------------------------------------------------------------

// PgxInvitationRepo is the pgx-backed InvitationRepo. Owns the envelope
// walker for the invitee_email column.
type PgxInvitationRepo struct {
	q            *db.Queries
	enc          crypto.Encryptor
	dec          crypto.Decryptor
	deploymentID string
}

// NewPgxInvitationRepo wires the invitation repo.
func NewPgxInvitationRepo(q *db.Queries, enc crypto.Encryptor, dec crypto.Decryptor, deploymentID string) *PgxInvitationRepo {
	return &PgxInvitationRepo{q: q, enc: enc, dec: dec, deploymentID: deploymentID}
}

// Create persists a new invitation. Runs the strict-mode walker on the
// invitee_email field; AAD binds to (deployment, "invitation", inv.ID,
// "InviteeEmail") so a ciphertext stolen from one invitation cannot be
// pasted into another invitation's row.
func (r *PgxInvitationRepo) Create(ctx context.Context, inv Invitation) (Invitation, error) {
	if err := crypto.EncryptPIIFieldsStrict(ctx, r.enc, r.deploymentID, resourceInvitation, inv.ID, &inv); err != nil {
		return Invitation{}, err
	}
	params := db.CreateInvitationParams{
		ID:                     inv.ID,
		TenantID:               inv.TenantID,
		OrganizationID:         inv.OrganizationID,
		InviteeEmailLookupHash: inv.InviteeEmailHash,
		InviteeEmailCiphertext: inv.InviteeEmailEnvelope.Ciphertext,
		InviteeEmailWrappedDek: inv.InviteeEmailEnvelope.WrappedDEK,
		InviteeEmailNonce:      inv.InviteeEmailEnvelope.Nonce,
		InviteeEmailKid:        inv.InviteeEmailEnvelope.KID,
		InviteeEmailKeyVersion: keyVersionToInt32(inv.InviteeEmailEnvelope.KeyVersion),
		TokenHash:              inv.TokenHash,
		TokenPrefix:            inv.TokenPrefix,
		InvitedByUserID:        inv.InvitedByUserID,
		ProposedRoleID:         inv.ProposedRoleID,
		Status:                 string(inv.Status),
		ExpiresAt:              pgtype.Timestamptz{Time: inv.ExpiresAt, Valid: true},
	}
	row, err := r.q.CreateInvitation(ctx, params)
	if err != nil {
		if isUniqueViolation(err) {
			return Invitation{}, ErrPendingInvitationExists
		}
		return Invitation{}, err
	}
	return r.hydrateInvitation(ctx, row)
}

// Get returns the invitation row for invitationID scoped to tenantID.
func (r *PgxInvitationRepo) Get(ctx context.Context, tenantID, invitationID string) (Invitation, error) {
	row, err := r.q.GetInvitation(ctx, invitationID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Invitation{}, ErrNotFound
		}
		return Invitation{}, err
	}
	if row.TenantID != tenantID {
		return Invitation{}, ErrNotFound
	}
	return r.hydrateInvitation(ctx, row)
}

// GetByTokenHash performs the constant-time hash equality lookup. The
// accept flow has no tenant context yet — see the documented exception
// in service.AcceptInvitation.
func (r *PgxInvitationRepo) GetByTokenHash(ctx context.Context, tokenHash []byte) (Invitation, error) {
	row, err := r.q.GetInvitationByTokenHash(ctx, tokenHash)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Invitation{}, ErrNotFound
		}
		return Invitation{}, err
	}
	return r.hydrateInvitation(ctx, row)
}

// GetPendingByEmailHash returns the pending invitation matching
// (organization_id, invitee_email_lookup_hash) — or ErrNotFound.
func (r *PgxInvitationRepo) GetPendingByEmailHash(ctx context.Context, organizationID string, emailHash []byte) (Invitation, error) {
	// sqlc does not generate this exact filter shape, so iterate over the
	// org's invitations. In practice an org has few simultaneous pending
	// invitations; the dedicated UNIQUE index still backs the race.
	rows, err := r.q.ListInvitationsByOrganization(ctx, db.ListInvitationsByOrganizationParams{
		OrganizationID: organizationID,
		RowLimit:       200,
	})
	if err != nil {
		return Invitation{}, err
	}
	for _, row := range rows {
		if row.Status == string(InvitationStatusPending) &&
			len(row.InviteeEmailLookupHash) == len(emailHash) {
			eq := true
			for i := range row.InviteeEmailLookupHash {
				if row.InviteeEmailLookupHash[i] != emailHash[i] {
					eq = false
					break
				}
			}
			if eq {
				return r.hydrateInvitation(ctx, row)
			}
		}
	}
	return Invitation{}, ErrNotFound
}

// List paginates invitations for an organization in tenantID.
func (r *PgxInvitationRepo) List(ctx context.Context, tenantID, organizationID string, limit int) ([]Invitation, error) {
	rows, err := r.q.ListInvitationsByOrganization(ctx, db.ListInvitationsByOrganizationParams{
		OrganizationID: organizationID,
		RowLimit:       clampLimit(limit),
	})
	if err != nil {
		return nil, err
	}
	out := make([]Invitation, 0, len(rows))
	for _, row := range rows {
		if row.TenantID != tenantID {
			continue
		}
		inv, err := r.hydrateInvitation(ctx, row)
		if err != nil {
			return nil, err
		}
		out = append(out, inv)
	}
	return out, nil
}

// MarkAccepted flips status='accepted' + stamps accepted_at +
// accepted_by_user_id. The status='pending' guard prevents replay.
func (r *PgxInvitationRepo) MarkAccepted(ctx context.Context, invitationID, acceptedByUserID string) (Invitation, error) {
	row, err := r.q.MarkInvitationAccepted(ctx, db.MarkInvitationAcceptedParams{
		ID:               invitationID,
		AcceptedByUserID: &acceptedByUserID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Invitation{}, ErrInvitationConsumed
		}
		return Invitation{}, err
	}
	return r.hydrateInvitation(ctx, row)
}

// MarkRevoked flips status='revoked'.
func (r *PgxInvitationRepo) MarkRevoked(ctx context.Context, tenantID, invitationID string, expectedSeq int64, revokedByUserID string) (Invitation, error) {
	existing, err := r.q.GetInvitation(ctx, invitationID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Invitation{}, ErrNotFound
		}
		return Invitation{}, err
	}
	if existing.TenantID != tenantID {
		return Invitation{}, ErrNotFound
	}
	row, err := r.q.MarkInvitationRevoked(ctx, db.MarkInvitationRevokedParams{
		ID:              invitationID,
		RowSeq:          expectedSeq,
		RevokedByUserID: &revokedByUserID,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			if existing.Status != string(InvitationStatusPending) {
				return Invitation{}, ErrInvitationConsumed
			}
			return Invitation{}, ErrETagMismatch
		}
		return Invitation{}, err
	}
	return r.hydrateInvitation(ctx, row)
}

// ExpireOverdue flips every pending invitation past expires_at into
// 'expired' and returns the (id, tenant_id, organization_id) tuples.
func (r *PgxInvitationRepo) ExpireOverdue(ctx context.Context, now time.Time) ([]ExpiredRow, error) {
	rows, err := r.q.ExpireOverdueInvitations(ctx, pgtype.Timestamptz{Time: now, Valid: true})
	if err != nil {
		return nil, err
	}
	out := make([]ExpiredRow, 0, len(rows))
	for _, row := range rows {
		out = append(out, ExpiredRow{
			InvitationID:   row.ID,
			TenantID:       row.TenantID,
			OrganizationID: row.OrganizationID,
		})
	}
	return out, nil
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

func mapOrganization(row db.Organization) (Organization, error) {
	meta := map[string]string{}
	if len(row.Metadata) > 0 {
		if err := json.Unmarshal(row.Metadata, &meta); err != nil {
			return Organization{}, err
		}
	}
	var deletedAt *time.Time
	if row.DeletedAt.Valid {
		t := row.DeletedAt.Time.UTC()
		deletedAt = &t
	}
	return Organization{
		ID:        row.ID,
		TenantID:  row.TenantID,
		Slug:      row.Slug,
		Name:      row.Name,
		Status:    OrganizationStatus(row.Status),
		Metadata:  meta,
		RowSeq:    row.RowSeq,
		CreatedAt: row.CreatedAt.Time.UTC(),
		UpdatedAt: row.UpdatedAt.Time.UTC(),
		DeletedAt: deletedAt,
	}, nil
}

func mapMember(row db.Member) Member {
	meta := map[string]string{}
	if len(row.Metadata) > 0 {
		_ = json.Unmarshal(row.Metadata, &meta)
	}
	var removedAt *time.Time
	if row.RemovedAt.Valid {
		t := row.RemovedAt.Time.UTC()
		removedAt = &t
	}
	return Member{
		ID:             row.ID,
		TenantID:       row.TenantID,
		OrganizationID: row.OrganizationID,
		UserID:         row.UserID,
		RoleID:         row.RoleID,
		Status:         MemberStatus(row.Status),
		Metadata:       meta,
		RowSeq:         row.RowSeq,
		JoinedAt:       row.JoinedAt.Time.UTC(),
		UpdatedAt:      row.UpdatedAt.Time.UTC(),
		RemovedAt:      removedAt,
	}
}

// hydrateInvitation decrypts the invitee_email envelope and returns the
// domain Invitation. kid verification fires BEFORE any Decrypt call —
// envelope.ErrKidMismatch surfaces directly so callers fail closed.
func (r *PgxInvitationRepo) hydrateInvitation(ctx context.Context, row db.Invitation) (Invitation, error) {
	if row.InviteeEmailKid != r.deploymentID {
		return Invitation{}, envelope.ErrKidMismatch
	}
	env := crypto.Envelope{
		Ciphertext: row.InviteeEmailCiphertext,
		WrappedDEK: row.InviteeEmailWrappedDek,
		Nonce:      row.InviteeEmailNonce,
		KID:        row.InviteeEmailKid,
		KeyVersion: int(row.InviteeEmailKeyVersion),
	}
	plain, err := r.dec.DecryptField(ctx, env, r.deploymentID, crypto.FieldAAD(r.deploymentID, resourceInvitation, row.ID, "InviteeEmail"))
	if err != nil {
		return Invitation{}, err
	}
	inv := Invitation{
		ID:                   row.ID,
		TenantID:             row.TenantID,
		OrganizationID:       row.OrganizationID,
		InviteeEmail:         string(plain),
		InviteeEmailEnvelope: env,
		InviteeEmailHash:     row.InviteeEmailLookupHash,
		TokenHash:            row.TokenHash,
		TokenPrefix:          row.TokenPrefix,
		InvitedByUserID:      row.InvitedByUserID,
		ProposedRoleID:       row.ProposedRoleID,
		Status:               InvitationStatus(row.Status),
		ExpiresAt:            row.ExpiresAt.Time.UTC(),
		AcceptedByUserID:     row.AcceptedByUserID,
		RevokedByUserID:      row.RevokedByUserID,
		RowSeq:               row.RowSeq,
		CreatedAt:            row.CreatedAt.Time.UTC(),
		UpdatedAt:            row.UpdatedAt.Time.UTC(),
	}
	if row.AcceptedAt.Valid {
		t := row.AcceptedAt.Time.UTC()
		inv.AcceptedAt = &t
	}
	if row.RevokedAt.Valid {
		t := row.RevokedAt.Time.UTC()
		inv.RevokedAt = &t
	}
	return inv, nil
}

func marshalStringMap(m map[string]string) ([]byte, error) {
	if m == nil {
		m = map[string]string{}
	}
	return json.Marshal(m)
}

// keyVersionToInt32 mirrors identity / notifications.
func keyVersionToInt32(v int) int32 {
	if v < 0 {
		return 0
	}
	if v > 0x7FFFFFFF {
		return 0x7FFFFFFF
	}
	return int32(v)
}

// clampLimit narrows a positive limit safely into int32.
func clampLimit(v int) int32 {
	if v < 1 {
		return 1
	}
	if v > 0x7FFFFFFF {
		return 0x7FFFFFFF
	}
	return int32(v)
}

// isUniqueViolation mirrors tenancy / identity / notifications detector.
func isUniqueViolation(err error) bool {
	if err == nil {
		return false
	}
	return strings.Contains(err.Error(), "23505") ||
		strings.Contains(strings.ToLower(err.Error()), "duplicate key")
}
