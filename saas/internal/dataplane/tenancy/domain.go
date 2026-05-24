// Package tenancy is the Phase 2 vertical slice: tenant CRUD with RLS,
// idempotent writes, ETag-guarded mutation, and outbox-emitted events.
// Hexagonal layout (AGENTS.md section 3.6):
//
//	handler.go        HTTP boundary (oapi-codegen StrictServerInterface)
//	service.go        application orchestration
//	ports.go          Repository + EventPublisher interfaces
//	repo_pgx.go       pgx-backed Repository implementation
//	domain.go         Tenant struct + Status enum
//	errors.go         sentinel errors translated to HTTP problems
//
// All subsequent modules (organizations, identity, api-keys, ...) follow the
// same shape — this directory is the template that Phase 3 promotes into
// CONVENTIONS.md.
package tenancy

import (
	"time"

	"github.com/omarss/saas/internal/platform/etag"
)

// Status mirrors the OpenAPI Tenant.status enum.
type Status string

// Allowed tenant lifecycle states. "deleted" is the soft-delete terminal state.
const (
	StatusActive    Status = "active"
	StatusSuspended Status = "suspended"
	StatusDeleted   Status = "deleted"
)

// Valid reports whether s is one of the platform's allowed states.
func (s Status) Valid() bool {
	switch s {
	case StatusActive, StatusSuspended, StatusDeleted:
		return true
	}
	return false
}

// Tenant is the in-memory representation passed between handler, service,
// repository, and outbox. Persistence types live in internal/dataplane/db/sqlc.
type Tenant struct {
	ID                    string
	Slug                  string
	Name                  string
	Status                Status
	DefaultOrganizationID *string
	Metadata              map[string]string
	RowSeq                int64
	CreatedAt             time.Time
	UpdatedAt             time.Time
	DeletedAt             *time.Time
}

// ETag returns the platform's Weak ETag for this tenant (W/"v<row_seq>").
func (t Tenant) ETag() string { return etag.Format(t.RowSeq) }

// UpdatePatch carries optional fields for a PATCH /v1/tenants/{id}. A nil
// pointer means "do not change this column"; sqlc COALESCE leaves the column
// alone in that case.
type UpdatePatch struct {
	Name     *string
	Status   *Status
	Metadata map[string]string
	// PatchMetadata distinguishes "client sent an explicit empty metadata
	// object" from "client omitted metadata entirely" — JSON-PATCH doesn't
	// help us here, so we carry the bool alongside.
	PatchMetadata bool
}
