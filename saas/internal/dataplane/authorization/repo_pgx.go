package authorization

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
)

// PgxRoleRepo is the pgx-backed RoleRepo. Role rows are plaintext; no
// envelope walker invocation is required.
type PgxRoleRepo struct {
	q *db.Queries
}

// NewPgxRoleRepo wires the role repo over sqlc Queries.
func NewPgxRoleRepo(q *db.Queries) *PgxRoleRepo {
	return &PgxRoleRepo{q: q}
}

// Create persists a new role.
func (r *PgxRoleRepo) Create(ctx context.Context, role Role) (Role, error) {
	meta, err := marshalStringMap(role.Metadata)
	if err != nil {
		return Role{}, err
	}
	row, err := r.q.CreateRole(ctx, db.CreateRoleParams{
		ID:          role.ID,
		TenantID:    role.TenantID,
		Name:        role.Name,
		Description: ptrIfNotEmpty(role.Description),
		IsSystem:    role.IsSystem,
		Metadata:    meta,
	})
	if err != nil {
		if isUniqueViolation(err) {
			return Role{}, ErrInvalidRoleName
		}
		return Role{}, err
	}
	return mapRole(row), nil
}

// Get returns the role row. Returns ErrRoleNotFound when the row is
// absent or belongs to a different tenant.
func (r *PgxRoleRepo) Get(ctx context.Context, tenantID, roleID string) (Role, error) {
	row, err := r.q.GetRole(ctx, roleID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Role{}, ErrRoleNotFound
		}
		return Role{}, err
	}
	if row.TenantID != tenantID {
		return Role{}, ErrRoleNotFound
	}
	return mapRole(row), nil
}

// List returns up to `limit` roles for tenantID.
func (r *PgxRoleRepo) List(ctx context.Context, tenantID string, limit int) ([]Role, error) {
	rows, err := r.q.ListRolesByTenant(ctx, db.ListRolesByTenantParams{
		TenantID: tenantID,
		RowLimit: clampLimit(limit),
	})
	if err != nil {
		return nil, err
	}
	out := make([]Role, 0, len(rows))
	for _, row := range rows {
		out = append(out, mapRole(row))
	}
	return out, nil
}

// Update applies the patch under optimistic concurrency.
func (r *PgxRoleRepo) Update(ctx context.Context, tenantID, roleID string, expectedSeq int64, patch RolePatch) (Role, error) {
	existing, err := r.Get(ctx, tenantID, roleID)
	if err != nil {
		return Role{}, err
	}
	if existing.RowSeq != expectedSeq {
		return Role{}, ErrETagMismatch
	}
	var meta []byte
	if patch.Metadata != nil {
		meta, err = marshalStringMap(patch.Metadata)
		if err != nil {
			return Role{}, err
		}
	}
	row, err := r.q.UpdateRole(ctx, db.UpdateRoleParams{
		ID:          roleID,
		RowSeq:      expectedSeq,
		Name:        patch.Name,
		Description: patch.Description,
		Metadata:    meta,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Role{}, ErrETagMismatch
		}
		return Role{}, err
	}
	return mapRole(row), nil
}

// SoftDelete marks the role deleted_at.
func (r *PgxRoleRepo) SoftDelete(ctx context.Context, tenantID, roleID string, expectedSeq int64) (Role, error) {
	existing, err := r.Get(ctx, tenantID, roleID)
	if err != nil {
		return Role{}, err
	}
	if existing.RowSeq != expectedSeq {
		return Role{}, ErrETagMismatch
	}
	row, err := r.q.SoftDeleteRole(ctx, db.SoftDeleteRoleParams{
		ID:     roleID,
		RowSeq: expectedSeq,
	})
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Role{}, ErrETagMismatch
		}
		return Role{}, err
	}
	return mapRole(row), nil
}

// PgxPermissionRepo is the pgx-backed PermissionRepo.
type PgxPermissionRepo struct {
	q *db.Queries
}

// NewPgxPermissionRepo wires the permission repo over sqlc Queries.
func NewPgxPermissionRepo(q *db.Queries) *PgxPermissionRepo {
	return &PgxPermissionRepo{q: q}
}

// List returns the full permission catalogue. The catalogue is small
// (~25 rows in MVP) so no pagination is needed.
func (r *PgxPermissionRepo) List(ctx context.Context) ([]Permission, error) {
	rows, err := r.q.ListPermissions(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]Permission, 0, len(rows))
	for _, row := range rows {
		out = append(out, mapPermission(row))
	}
	return out, nil
}

// Get returns a single permission row by id.
func (r *PgxPermissionRepo) Get(ctx context.Context, id string) (Permission, error) {
	// sqlc has no Get-by-id query for permission; ListPermissions is
	// cheap (single index scan + small catalogue). For MVP we filter
	// in-process. If catalogue growth becomes a concern a sqlc query
	// can be added later without a breaking change here.
	rows, err := r.q.ListPermissions(ctx)
	if err != nil {
		return Permission{}, err
	}
	for _, row := range rows {
		if row.ID == id {
			return mapPermission(row), nil
		}
	}
	return Permission{}, ErrPermissionNotFound
}

// PgxMemberRoleRepo is the pgx-backed MemberRoleRepo.
type PgxMemberRoleRepo struct {
	q *db.Queries
}

// NewPgxMemberRoleRepo wires the member_role repo over sqlc Queries.
func NewPgxMemberRoleRepo(q *db.Queries) *PgxMemberRoleRepo {
	return &PgxMemberRoleRepo{q: q}
}

// Assign upserts the (member, role) assignment.
func (r *PgxMemberRoleRepo) Assign(ctx context.Context, mr MemberRole) (MemberRole, error) {
	row, err := r.q.AssignMemberRole(ctx, db.AssignMemberRoleParams{
		MemberID:   mr.MemberID,
		RoleID:     mr.RoleID,
		TenantID:   mr.TenantID,
		AssignedBy: mr.AssignedBy,
	})
	if err != nil {
		return MemberRole{}, err
	}
	return mapMemberRole(row), nil
}

// Unassign deletes the assignment. Returns true if a row was removed.
func (r *PgxMemberRoleRepo) Unassign(ctx context.Context, memberID, roleID string) (bool, error) {
	n, err := r.q.UnassignMemberRole(ctx, db.UnassignMemberRoleParams{
		MemberID: memberID,
		RoleID:   roleID,
	})
	if err != nil {
		return false, err
	}
	return n > 0, nil
}

// List returns every role assigned to memberID.
func (r *PgxMemberRoleRepo) List(ctx context.Context, memberID string) ([]MemberRole, error) {
	rows, err := r.q.ListMemberRoles(ctx, memberID)
	if err != nil {
		return nil, err
	}
	out := make([]MemberRole, 0, len(rows))
	for _, row := range rows {
		out = append(out, mapMemberRole(row))
	}
	return out, nil
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

func mapRole(row db.Role) Role {
	meta := map[string]string{}
	if len(row.Metadata) > 0 {
		_ = json.Unmarshal(row.Metadata, &meta)
	}
	var deletedAt *time.Time
	if row.DeletedAt.Valid {
		t := row.DeletedAt.Time.UTC()
		deletedAt = &t
	}
	desc := ""
	if row.Description != nil {
		desc = *row.Description
	}
	return Role{
		ID:          row.ID,
		TenantID:    row.TenantID,
		Name:        row.Name,
		Description: desc,
		IsSystem:    row.IsSystem,
		Metadata:    meta,
		RowSeq:      row.RowSeq,
		CreatedAt:   row.CreatedAt.Time.UTC(),
		UpdatedAt:   row.UpdatedAt.Time.UTC(),
		DeletedAt:   deletedAt,
	}
}

func mapPermission(row db.Permission) Permission {
	desc := row.Description
	return Permission{
		ID:           row.ID,
		ResourceType: row.ResourceType,
		Action:       row.Action,
		Description:  desc,
		Module:       row.Module,
		IsSystem:     row.IsSystem,
	}
}

func mapMemberRole(row db.MemberRole) MemberRole {
	return MemberRole{
		MemberID:   row.MemberID,
		RoleID:     row.RoleID,
		TenantID:   row.TenantID,
		AssignedBy: row.AssignedBy,
		AssignedAt: row.AssignedAt.Time.UTC(),
	}
}

func marshalStringMap(m map[string]string) ([]byte, error) {
	if m == nil {
		m = map[string]string{}
	}
	return json.Marshal(m)
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

// ptrIfNotEmpty returns a pointer for non-empty strings, nil otherwise.
// sqlc maps nullable text columns to *string.
func ptrIfNotEmpty(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// isUniqueViolation mirrors the detector used in sibling modules.
func isUniqueViolation(err error) bool {
	if err == nil {
		return false
	}
	return strings.Contains(err.Error(), "23505") ||
		strings.Contains(strings.ToLower(err.Error()), "duplicate key")
}
