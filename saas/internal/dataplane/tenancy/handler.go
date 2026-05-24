package tenancy

import (
	"context"
	"errors"
	"net/http"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi" // package dataplaneapi
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/cursor"
	"github.com/omarss/saas/internal/platform/etag"
	"github.com/omarss/saas/internal/platform/problem"
)

// Handler implements the oapi-codegen StrictServerInterface entries for
// /v1/tenants. The interface includes /healthz; Phase 2 keeps healthz outside
// this struct because it has no tenancy concerns, and the data-plane main()
// composes the two via embedding (see cmd/dataplane/main.go).
type Handler struct {
	svc *Service
}

// NewHandler wires a Handler over the tenancy service.
func NewHandler(svc *Service) *Handler { return &Handler{svc: svc} }

// ListTenants returns the caller's tenant. Cross-tenant listing is reserved
// for operator impersonation (Phase 13).
func (h *Handler) ListTenants(ctx context.Context, req httpapi.ListTenantsRequestObject) (httpapi.ListTenantsResponseObject, error) {
	limit := 25
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	var cur *ListCursor
	if req.Params.Cursor != nil && *req.Params.Cursor != "" {
		c, err := cursor.Decode(*req.Params.Cursor)
		if err != nil {
			if errors.Is(err, cursor.ErrVersionMismatch) {
				p := problem.New("cursor-gone", "Cursor schema version is no longer supported.", http.StatusGone, "", "/v1/tenants")
				return httpapi.ListTenants410ApplicationProblemPlusJSONResponse{
					CursorGoneApplicationProblemPlusJSONResponse: httpapi.CursorGoneApplicationProblemPlusJSONResponse(toAPIProblem(p)),
				}, nil
			}
			// Bad cursor is an authentication-agnostic validation failure;
			// surface as 401-style problem until the spec gains a 422 here.
			return unauthorizedList("invalid cursor", "/v1/tenants"), nil
		}
		cur = &ListCursor{CreatedAt: c.CreatedAt, ID: c.ID}
	}
	tenants, hasMore, err := h.svc.List(ctx, limit, cur)
	if err != nil {
		if errors.Is(err, auth.ErrUnauthorized) {
			return unauthorizedList("missing tenant context", "/v1/tenants"), nil
		}
		return nil, err
	}
	resp := httpapi.TenantListResponse{
		Data:       make([]httpapi.Tenant, 0, len(tenants)),
		Pagination: httpapi.Pagination{HasMore: hasMore},
	}
	for _, t := range tenants {
		resp.Data = append(resp.Data, toAPITenant(t))
	}
	if hasMore && len(tenants) > 0 {
		last := tenants[len(tenants)-1]
		next := cursor.Encode(cursor.Cursor{CreatedAt: last.CreatedAt, ID: last.ID})
		resp.Pagination.NextCursor = &next
	}
	return httpapi.ListTenants200JSONResponse(resp), nil
}

// CreateTenant handles POST /v1/tenants. Idempotency is handled by the
// idempotency middleware; this method is invoked only when the key is fresh.
func (h *Handler) CreateTenant(ctx context.Context, req httpapi.CreateTenantRequestObject) (httpapi.CreateTenantResponseObject, error) {
	if req.Body == nil {
		return createTenantProblem(http.StatusUnprocessableEntity, "validation-error", "request body required", "/v1/tenants"), nil
	}
	var meta map[string]string
	if req.Body.Metadata != nil {
		meta = map[string]string(*req.Body.Metadata)
	}
	t, err := h.svc.Create(ctx, req.Body.Slug, req.Body.Name, meta)
	if err != nil {
		return createTenantError(err, "/v1/tenants"), nil
	}
	etagStr := t.ETag()
	location := "/v1/tenants/" + t.ID
	return httpapi.CreateTenant201JSONResponse{
		Headers: httpapi.CreateTenant201ResponseHeaders{ETag: &etagStr, Location: &location},
		Body:    httpapi.TenantResponse{Data: toAPITenant(t)},
	}, nil
}

// GetTenant handles GET /v1/tenants/{tenant_id}.
func (h *Handler) GetTenant(ctx context.Context, req httpapi.GetTenantRequestObject) (httpapi.GetTenantResponseObject, error) {
	t, err := h.svc.Get(ctx, req.TenantId)
	if err != nil {
		return getTenantError(err, "/v1/tenants/"+req.TenantId), nil
	}
	etagStr := t.ETag()
	return httpapi.GetTenant200JSONResponse{
		Headers: httpapi.GetTenant200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.TenantResponse{Data: toAPITenant(t)},
	}, nil
}

// UpdateTenant handles PATCH /v1/tenants/{tenant_id} with mandatory If-Match.
func (h *Handler) UpdateTenant(ctx context.Context, req httpapi.UpdateTenantRequestObject) (httpapi.UpdateTenantResponseObject, error) {
	if req.Body == nil {
		return updateTenantProblem(http.StatusUnprocessableEntity, "validation-error", "request body required", "/v1/tenants/"+req.TenantId), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return updateTenantProblem(http.StatusPreconditionFailed, "precondition-failed", "malformed If-Match header", "/v1/tenants/"+req.TenantId), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	patch := UpdatePatch{
		Name: req.Body.Name,
	}
	if req.Body.Status != nil {
		s := Status(*req.Body.Status)
		patch.Status = &s
	}
	if req.Body.Metadata != nil {
		patch.PatchMetadata = true
		patch.Metadata = map[string]string(*req.Body.Metadata)
	}
	t, err := h.svc.Update(ctx, req.TenantId, expected, patch)
	if err != nil {
		return updateTenantError(err, "/v1/tenants/"+req.TenantId), nil
	}
	etagStr := t.ETag()
	return httpapi.UpdateTenant200JSONResponse{
		Headers: httpapi.UpdateTenant200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.TenantResponse{Data: toAPITenant(t)},
	}, nil
}

// DeleteTenant handles DELETE /v1/tenants/{tenant_id} with mandatory If-Match.
func (h *Handler) DeleteTenant(ctx context.Context, req httpapi.DeleteTenantRequestObject) (httpapi.DeleteTenantResponseObject, error) {
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return deleteTenantProblem(http.StatusPreconditionFailed, "precondition-failed", "malformed If-Match header", "/v1/tenants/"+req.TenantId), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	if err := h.svc.SoftDelete(ctx, req.TenantId, expected); err != nil {
		return deleteTenantError(err, "/v1/tenants/"+req.TenantId), nil
	}
	return httpapi.DeleteTenant204Response{}, nil
}

// --- mapping helpers ---------------------------------------------------------

func toAPITenant(t Tenant) httpapi.Tenant {
	meta := httpapi.Metadata(t.Metadata)
	out := httpapi.Tenant{
		Id:        t.ID,
		Object:    httpapi.TenantObject("tenant"),
		Slug:      t.Slug,
		Name:      t.Name,
		Status:    httpapi.TenantStatus(t.Status),
		Metadata:  &meta,
		CreatedAt: t.CreatedAt,
		UpdatedAt: t.UpdatedAt,
		Etag:      t.ETag(),
	}
	if t.DefaultOrganizationID != nil {
		out.DefaultOrganizationId = t.DefaultOrganizationID
	}
	if t.DeletedAt != nil {
		out.DeletedAt = t.DeletedAt
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

// --- error → problem translation --------------------------------------------

func unauthorizedList(detail, instance string) httpapi.ListTenants401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, detail, instance)
	return httpapi.ListTenants401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createTenantError(err error, instance string) httpapi.CreateTenantResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "missing tenant context", instance)
		return httpapi.CreateTenant401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrSlugTaken):
		return createTenantProblem(http.StatusUnprocessableEntity, "validation-error", "tenant slug already taken", instance)
	case errors.Is(err, ErrInvalidInput):
		return createTenantProblem(http.StatusUnprocessableEntity, "validation-error", "invalid tenant input", instance)
	default:
		return createTenantProblem(http.StatusUnprocessableEntity, "validation-error", "create failed", instance)
	}
}

// createTenantProblem returns a CreateTenant 422 problem body. The status arg
// is fixed at 422 today, but kept on the signature so future callers can add
// different statuses (e.g. 401 short-circuit) without rewriting the helper.
//
//nolint:unparam // status is intentionally accepted for symmetry with updateTenantProblem
func createTenantProblem(status int, slug, detail, instance string) httpapi.CreateTenant422ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, "Validation failed", status, detail, instance)
	return httpapi.CreateTenant422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func getTenantError(err error, instance string) httpapi.GetTenantResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
		return httpapi.GetTenant401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.GetTenant403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.GetTenant404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("internal", "Unexpected error.", http.StatusNotFound, err.Error(), instance)
		return httpapi.GetTenant404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateTenantError(err error, instance string) httpapi.UpdateTenantResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
		return httpapi.UpdateTenant401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.UpdateTenant403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return updateTenantProblem(http.StatusPreconditionFailed, "precondition-failed", "stale or missing If-Match", instance)
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.UpdateTenant404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidInput):
		return updateTenantProblem(http.StatusUnprocessableEntity, "validation-error", "invalid input", instance)
	default:
		return updateTenantProblem(http.StatusUnprocessableEntity, "validation-error", "update failed", instance)
	}
}

func updateTenantProblem(status int, slug, detail, instance string) httpapi.UpdateTenantResponseObject {
	p := problem.New(slug, statusTitle(status), status, detail, instance)
	switch status {
	case http.StatusPreconditionFailed:
		return httpapi.UpdateTenant412ApplicationProblemPlusJSONResponse{
			PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return httpapi.UpdateTenant422ApplicationProblemPlusJSONResponse{
			IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func deleteTenantError(err error, instance string) httpapi.DeleteTenantResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
		return httpapi.DeleteTenant401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.DeleteTenant403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return deleteTenantProblem(http.StatusPreconditionFailed, "precondition-failed", "stale or missing If-Match", instance)
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.DeleteTenant404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return deleteTenantProblem(http.StatusPreconditionFailed, "precondition-failed", "delete failed", instance)
	}
}

func deleteTenantProblem(status int, slug, detail, instance string) httpapi.DeleteTenant412ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, statusTitle(status), status, detail, instance)
	return httpapi.DeleteTenant412ApplicationProblemPlusJSONResponse{
		PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func statusTitle(status int) string {
	switch status {
	case http.StatusPreconditionFailed:
		return "Precondition failed."
	case http.StatusUnprocessableEntity:
		return "Validation failed."
	default:
		return "Error."
	}
}
