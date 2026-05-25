package authorization

import (
	"context"
	"errors"
	"net/http"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/etag"
	"github.com/omarss/saas/internal/platform/problem"
)

// Handler is the HTTP-facing adapter for the authorization module. It
// implements the relevant subset of the generated StrictServerInterface
// — cmd/dataplane composes this handler alongside the other modules
// (CONVENTIONS.md §3). All handlers source tenant context from the
// principal (auth.TenantFromContext) — never from a header or path.
type Handler struct {
	svc *Service
}

// NewHandler wires a Handler over the authorization service.
func NewHandler(svc *Service) *Handler { return &Handler{svc: svc} }

// Service returns the wrapped service. Used by sibling modules that
// need to enforce authorization before their own state transitions
// (Phase 8 §8.11 retrofits Phase 7 handlers).
func (h *Handler) Service() *Service { return h.svc }

const (
	pathRoles           = "/v1/roles"
	pathTenantRoles     = "/v1/tenants/{tenant_id}/roles"
	pathPermissions     = "/v1/permissions"
	pathMemberRoles     = "/v1/members/{member_id}/roles"
	pathCheck           = "/v1/authorization/check"
	pathBatchCheck      = "/v1/authorization/batch-check"
	defaultRoleListSize = 25
)

// ---------------------------------------------------------------------------
// Roles
// ---------------------------------------------------------------------------

// ListRoles handles GET /v1/tenants/{tenant_id}/roles.
func (h *Handler) ListRoles(ctx context.Context, req httpapi.ListRolesRequestObject) (httpapi.ListRolesResponseObject, error) {
	limit := defaultRoleListSize
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	roles, err := h.svc.ListRoles(ctx, req.TenantId, limit)
	if err != nil {
		return h.listRolesError(err), nil
	}
	out := httpapi.RoleListResponse{
		Data:       make([]httpapi.Role, 0, len(roles)),
		Pagination: httpapi.Pagination{HasMore: false},
	}
	for _, r := range roles {
		out.Data = append(out.Data, toAPIRole(r))
	}
	return httpapi.ListRoles200JSONResponse(out), nil
}

// CreateRole handles POST /v1/tenants/{tenant_id}/roles.
func (h *Handler) CreateRole(ctx context.Context, req httpapi.CreateRoleRequestObject) (httpapi.CreateRoleResponseObject, error) {
	if req.Body == nil {
		return h.createRoleProblem422("request body required"), nil
	}
	in := CreateRoleInput{Name: req.Body.Name}
	if req.Body.Description != nil {
		in.Description = *req.Body.Description
	}
	if req.Body.Permissions != nil {
		in.Permissions = *req.Body.Permissions
	}
	if req.Body.Metadata != nil {
		in.Metadata = *req.Body.Metadata
	}
	role, err := h.svc.CreateRole(ctx, req.TenantId, in)
	if err != nil {
		return h.createRoleError(err), nil
	}
	tag := role.ETag()
	loc := "/v1/roles/" + role.ID
	return httpapi.CreateRole201JSONResponse{
		Headers: httpapi.CreateRole201ResponseHeaders{ETag: &tag, Location: &loc},
		Body:    httpapi.RoleResponse{Data: toAPIRole(role)},
	}, nil
}

// GetRole handles GET /v1/roles/{role_id}.
func (h *Handler) GetRole(ctx context.Context, req httpapi.GetRoleRequestObject) (httpapi.GetRoleResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return h.getRoleUnauthorized(), nil
	}
	role, err := h.svc.GetRole(ctx, tenantID, req.RoleId)
	if err != nil {
		return h.getRoleError(err), nil
	}
	return httpapi.GetRole200JSONResponse(httpapi.RoleResponse{Data: toAPIRole(role)}), nil
}

// UpdateRole handles PATCH /v1/roles/{role_id}.
func (h *Handler) UpdateRole(ctx context.Context, req httpapi.UpdateRoleRequestObject) (httpapi.UpdateRoleResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return h.updateRoleUnauthorized(), nil
	}
	if req.Body == nil {
		return h.updateRoleProblem422("request body required"), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return h.updateRoleProblem412("malformed If-Match header"), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	patch := RolePatch{}
	if req.Body.Name != nil {
		n := *req.Body.Name
		patch.Name = &n
	}
	if req.Body.Description != nil {
		d := *req.Body.Description
		patch.Description = &d
	}
	if req.Body.Metadata != nil {
		patch.Metadata = *req.Body.Metadata
	}
	if req.Body.Permissions != nil {
		patch.PatchPerms = true
		patch.Permissions = *req.Body.Permissions
	}
	updated, err := h.svc.UpdateRole(ctx, tenantID, req.RoleId, expected, patch)
	if err != nil {
		return h.updateRoleError(err), nil
	}
	tag := updated.ETag()
	return httpapi.UpdateRole200JSONResponse{
		Headers: httpapi.UpdateRole200ResponseHeaders{ETag: &tag},
		Body:    httpapi.RoleResponse{Data: toAPIRole(updated)},
	}, nil
}

// DeleteRole handles DELETE /v1/roles/{role_id}.
func (h *Handler) DeleteRole(ctx context.Context, req httpapi.DeleteRoleRequestObject) (httpapi.DeleteRoleResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return h.deleteRoleUnauthorized(), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return h.deleteRoleProblem412("malformed If-Match header"), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	if err := h.svc.DeleteRole(ctx, tenantID, req.RoleId, expected); err != nil {
		return h.deleteRoleError(err), nil
	}
	return httpapi.DeleteRole204Response{}, nil
}

// ---------------------------------------------------------------------------
// Permissions
// ---------------------------------------------------------------------------

// ListPermissions handles GET /v1/permissions.
func (h *Handler) ListPermissions(ctx context.Context, _ httpapi.ListPermissionsRequestObject) (httpapi.ListPermissionsResponseObject, error) {
	perms, err := h.svc.ListPermissions(ctx)
	if err != nil {
		return h.listPermissionsError(err), nil
	}
	out := httpapi.PermissionListResponse{Data: make([]httpapi.Permission, 0, len(perms))}
	for _, p := range perms {
		out.Data = append(out.Data, toAPIPermission(p))
	}
	return httpapi.ListPermissions200JSONResponse(out), nil
}

// ---------------------------------------------------------------------------
// Member-role assignments
// ---------------------------------------------------------------------------

// ListMemberRoles handles GET /v1/members/{member_id}/roles.
func (h *Handler) ListMemberRoles(ctx context.Context, req httpapi.ListMemberRolesRequestObject) (httpapi.ListMemberRolesResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return h.listMemberRolesUnauthorized(), nil
	}
	mrs, err := h.svc.ListMemberRoles(ctx, tenantID, req.MemberId)
	if err != nil {
		return h.listMemberRolesError(err), nil
	}
	out := httpapi.MemberRoleListResponse{Data: make([]httpapi.MemberRoleAssignment, 0, len(mrs))}
	for _, mr := range mrs {
		out.Data = append(out.Data, toAPIMemberRole(mr))
	}
	return httpapi.ListMemberRoles200JSONResponse(out), nil
}

// AssignMemberRole handles POST /v1/members/{member_id}/roles.
func (h *Handler) AssignMemberRole(ctx context.Context, req httpapi.AssignMemberRoleRequestObject) (httpapi.AssignMemberRoleResponseObject, error) {
	if req.Body == nil {
		return h.assignMemberRoleProblem422("request body required"), nil
	}
	mr, err := h.svc.AssignMemberRole(ctx, req.Body.TenantId, req.MemberId, req.Body.RoleId)
	if err != nil {
		return h.assignMemberRoleError(err), nil
	}
	return httpapi.AssignMemberRole200JSONResponse(httpapi.MemberRoleResponse{Data: toAPIMemberRole(mr)}), nil
}

// UnassignMemberRole handles DELETE /v1/members/{member_id}/roles/{role_id}.
func (h *Handler) UnassignMemberRole(ctx context.Context, req httpapi.UnassignMemberRoleRequestObject) (httpapi.UnassignMemberRoleResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return h.unassignMemberRoleUnauthorized(), nil
	}
	if err := h.svc.UnassignMemberRole(ctx, tenantID, req.MemberId, req.RoleId); err != nil {
		return h.unassignMemberRoleError(err), nil
	}
	return httpapi.UnassignMemberRole204Response{}, nil
}

// ---------------------------------------------------------------------------
// Check / BatchCheck
// ---------------------------------------------------------------------------

// CheckAuthorization handles POST /v1/authorization/check.
func (h *Handler) CheckAuthorization(ctx context.Context, req httpapi.CheckAuthorizationRequestObject) (httpapi.CheckAuthorizationResponseObject, error) {
	if req.Body == nil {
		return h.checkProblem422("request body required"), nil
	}
	resp, err := h.svc.Check(ctx, req.Body.TenantId, req.Body.MemberId, req.Body.Permission)
	if err != nil {
		return h.checkError(err), nil
	}
	return httpapi.CheckAuthorization200JSONResponse(httpapi.CheckAuthorizationResponse{
		Data: toAPICheckResult(resp),
	}), nil
}

// BatchCheckAuthorization handles POST /v1/authorization/batch-check.
func (h *Handler) BatchCheckAuthorization(ctx context.Context, req httpapi.BatchCheckAuthorizationRequestObject) (httpapi.BatchCheckAuthorizationResponseObject, error) {
	if req.Body == nil {
		return h.batchCheckProblem422("request body required"), nil
	}
	if len(req.Body.Checks) > MaxBatchCheckSize {
		return h.batchCheckProblem422("batch size exceeds 100"), nil
	}
	entries := make([]CheckBatchEntry, 0, len(req.Body.Checks))
	for _, c := range req.Body.Checks {
		entries = append(entries, CheckBatchEntry{
			TenantID:   c.TenantId,
			MemberID:   c.MemberId,
			Permission: c.Permission,
		})
	}
	results, err := h.svc.BatchCheck(ctx, entries)
	if err != nil {
		return h.batchCheckError(err), nil
	}
	out := httpapi.BatchCheckAuthorizationResponse{Data: make([]httpapi.CheckAuthorizationResponseData, len(results))}
	for i, r := range results {
		out.Data[i] = toAPICheckResult(r)
	}
	return httpapi.BatchCheckAuthorization200JSONResponse(out), nil
}

// ---------------------------------------------------------------------------
// mapping helpers
// ---------------------------------------------------------------------------

func toAPIRole(r Role) httpapi.Role {
	out := httpapi.Role{
		Id:        r.ID,
		Object:    httpapi.RoleObjectRole,
		TenantId:  r.TenantID,
		Name:      r.Name,
		IsSystem:  r.IsSystem,
		CreatedAt: r.CreatedAt,
		UpdatedAt: r.UpdatedAt,
		Etag:      r.ETag(),
	}
	if r.Description != "" {
		d := r.Description
		out.Description = &d
	}
	if len(r.Permissions) > 0 {
		p := r.Permissions
		out.Permissions = &p
	}
	if len(r.Metadata) > 0 {
		meta := httpapi.Metadata(r.Metadata)
		out.Metadata = &meta
	}
	return out
}

func toAPIPermission(p Permission) httpapi.Permission {
	sys := p.IsSystem
	return httpapi.Permission{
		Id:           p.ID,
		ResourceType: p.ResourceType,
		Action:       p.Action,
		Description:  p.Description,
		Module:       p.Module,
		IsSystem:     &sys,
	}
}

func toAPIMemberRole(mr MemberRole) httpapi.MemberRoleAssignment {
	return httpapi.MemberRoleAssignment{
		MemberId:   mr.MemberID,
		RoleId:     mr.RoleID,
		TenantId:   mr.TenantID,
		AssignedAt: mr.AssignedAt,
		AssignedBy: mr.AssignedBy,
	}
}

func toAPICheckResult(r CheckResponse) httpapi.CheckAuthorizationResponseData {
	out := httpapi.CheckAuthorizationResponseData{Allowed: r.Allowed}
	if r.ViaRole != "" {
		v := r.ViaRole
		out.ViaRole = &v
	}
	return out
}

func toAPIProblem(p problem.Problem) httpapi.Problem {
	out := httpapi.Problem{
		Type:   p.Type,
		Title:  p.Title,
		Status: p.Status,
	}
	if p.Detail != "" {
		out.Detail = &p.Detail
	}
	if p.Instance != "" {
		out.Instance = &p.Instance
	}
	if p.RequestID != "" {
		out.RequestId = &p.RequestID
	}
	return out
}

// ---------------------------------------------------------------------------
// error translation
// ---------------------------------------------------------------------------

// --- ListRoles -------------------------------------------------------------

func (h *Handler) listRolesUnauthorized() httpapi.ListRoles401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathTenantRoles)
	return httpapi.ListRoles401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) listRolesForbidden() httpapi.ListRoles403ApplicationProblemPlusJSONResponse {
	p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathTenantRoles)
	return httpapi.ListRoles403ApplicationProblemPlusJSONResponse{
		ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) listRolesError(err error) httpapi.ListRolesResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return h.listRolesUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		return h.listRolesForbidden()
	default:
		return h.listRolesUnauthorized()
	}
}

// --- CreateRole ------------------------------------------------------------

func (h *Handler) createRoleUnauthorized() httpapi.CreateRole401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathTenantRoles)
	return httpapi.CreateRole401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) createRoleForbidden() httpapi.CreateRole403ApplicationProblemPlusJSONResponse {
	p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathTenantRoles)
	return httpapi.CreateRole403ApplicationProblemPlusJSONResponse{
		ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) createRoleProblem422(detail string) httpapi.CreateRole422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, pathTenantRoles)
	return httpapi.CreateRole422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) createRoleError(err error) httpapi.CreateRoleResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return h.createRoleUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		return h.createRoleForbidden()
	case errors.Is(err, ErrPermissionNotFound):
		return h.createRoleProblem422("unknown permission id")
	case errors.Is(err, ErrInvalidRoleName), errors.Is(err, ErrWildcardDomain):
		return h.createRoleProblem422(err.Error())
	default:
		return h.createRoleProblem422("create failed")
	}
}

// --- GetRole ---------------------------------------------------------------

func (h *Handler) getRoleUnauthorized() httpapi.GetRole401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathRoles)
	return httpapi.GetRole401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) getRoleError(err error) httpapi.GetRoleResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return h.getRoleUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathRoles)
		return httpapi.GetRole403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Role not found.", http.StatusNotFound, "", pathRoles)
		return httpapi.GetRole404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

// --- UpdateRole ------------------------------------------------------------

func (h *Handler) updateRoleUnauthorized() httpapi.UpdateRole401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathRoles)
	return httpapi.UpdateRole401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) updateRoleProblem412(detail string) httpapi.UpdateRole412ApplicationProblemPlusJSONResponse {
	p := problem.New("precondition-failed", "Precondition failed.", http.StatusPreconditionFailed, detail, pathRoles)
	return httpapi.UpdateRole412ApplicationProblemPlusJSONResponse{
		PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) updateRoleProblem422(detail string) httpapi.UpdateRole422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, pathRoles)
	return httpapi.UpdateRole422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) updateRoleError(err error) httpapi.UpdateRoleResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return h.updateRoleUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathRoles)
		return httpapi.UpdateRole403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return h.updateRoleProblem412("etag mismatch")
	case errors.Is(err, ErrRoleNotFound):
		p := problem.New("not-found", "Role not found.", http.StatusNotFound, "", pathRoles)
		return httpapi.UpdateRole404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrPermissionNotFound):
		return h.updateRoleProblem422("unknown permission id")
	default:
		return h.updateRoleProblem422("update failed")
	}
}

// --- DeleteRole ------------------------------------------------------------

func (h *Handler) deleteRoleUnauthorized() httpapi.DeleteRole401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathRoles)
	return httpapi.DeleteRole401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) deleteRoleProblem412(detail string) httpapi.DeleteRole412ApplicationProblemPlusJSONResponse {
	p := problem.New("precondition-failed", "Precondition failed.", http.StatusPreconditionFailed, detail, pathRoles)
	return httpapi.DeleteRole412ApplicationProblemPlusJSONResponse{
		PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) deleteRoleError(err error) httpapi.DeleteRoleResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return h.deleteRoleUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathRoles)
		return httpapi.DeleteRole403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return h.deleteRoleProblem412("etag mismatch")
	case errors.Is(err, ErrSystemRoleImmutable):
		p := problem.New("validation-error", "System role cannot be deleted.", http.StatusUnprocessableEntity, "", pathRoles)
		return httpapi.DeleteRole422ApplicationProblemPlusJSONResponse(toAPIProblem(p))
	case errors.Is(err, ErrRoleNotFound):
		p := problem.New("not-found", "Role not found.", http.StatusNotFound, "", pathRoles)
		return httpapi.DeleteRole404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Role not found.", http.StatusNotFound, "", pathRoles)
		return httpapi.DeleteRole404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

// --- ListPermissions -------------------------------------------------------

func (h *Handler) listPermissionsError(err error) httpapi.ListPermissionsResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathPermissions)
		return httpapi.ListPermissions401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("forbidden", "Caller lacks permission.", http.StatusForbidden, "", pathPermissions)
		return httpapi.ListPermissions403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

// --- Member-role assignments -----------------------------------------------

func (h *Handler) listMemberRolesUnauthorized() httpapi.ListMemberRoles401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathMemberRoles)
	return httpapi.ListMemberRoles401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) listMemberRolesError(err error) httpapi.ListMemberRolesResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return h.listMemberRolesUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, ErrCrossTenantMember):
		p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathMemberRoles)
		return httpapi.ListMemberRoles403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Member not found.", http.StatusNotFound, "", pathMemberRoles)
		return httpapi.ListMemberRoles404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func (h *Handler) assignMemberRoleProblem422(detail string) httpapi.AssignMemberRole422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, pathMemberRoles)
	return httpapi.AssignMemberRole422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) assignMemberRoleError(err error) httpapi.AssignMemberRoleResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathMemberRoles)
		return httpapi.AssignMemberRole401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, ErrCrossTenantMember):
		p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathMemberRoles)
		return httpapi.AssignMemberRole403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrRoleNotFound), errors.Is(err, ErrMemberNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", pathMemberRoles)
		return httpapi.AssignMemberRole404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return h.assignMemberRoleProblem422("assign failed")
	}
}

func (h *Handler) unassignMemberRoleUnauthorized() httpapi.UnassignMemberRole401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathMemberRoles)
	return httpapi.UnassignMemberRole401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) unassignMemberRoleError(err error) httpapi.UnassignMemberRoleResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return h.unassignMemberRoleUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, ErrCrossTenantMember):
		p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathMemberRoles)
		return httpapi.UnassignMemberRole403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Assignment not found.", http.StatusNotFound, "", pathMemberRoles)
		return httpapi.UnassignMemberRole404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

// --- Check / BatchCheck ----------------------------------------------------

func (h *Handler) checkProblem422(detail string) httpapi.CheckAuthorization422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, pathCheck)
	return httpapi.CheckAuthorization422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) checkError(err error) httpapi.CheckAuthorizationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathCheck)
		return httpapi.CheckAuthorization401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, ErrCrossTenantMember):
		p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathCheck)
		return httpapi.CheckAuthorization403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrMalformedPermission):
		return h.checkProblem422("permission must be resource_type.action")
	default:
		return h.checkProblem422("check failed")
	}
}

func (h *Handler) batchCheckProblem422(detail string) httpapi.BatchCheckAuthorization422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, pathBatchCheck)
	return httpapi.BatchCheckAuthorization422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func (h *Handler) batchCheckError(err error) httpapi.BatchCheckAuthorizationResponseObject {
	switch {
	case errors.Is(err, ErrBatchTooLarge):
		return h.batchCheckProblem422("batch size exceeds 100")
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathBatchCheck)
		return httpapi.BatchCheckAuthorization401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("cross-tenant-access-denied", "Cross-tenant access denied.", http.StatusForbidden, "", pathBatchCheck)
		return httpapi.BatchCheckAuthorization403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return h.batchCheckProblem422("batch-check failed")
	}
}
