package apikeys

import (
	"context"
	"errors"

	"github.com/omarss/saas/internal/dataplane/authorization"
	httpapi "github.com/omarss/saas/internal/dataplane/httpapi"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/etag"
	"github.com/omarss/saas/internal/platform/problem"
)

// strict_handler.go bridges between the oapi-codegen-generated strict
// request / response shapes (httpapi package) and the apikeys.Handler's
// internal logic. The strict server is the single source of truth for
// request validation (path/header/body parsing) so we satisfy the
// generated StrictServerInterface here instead of routing via raw chi.
//
// The chi.Mount entry point in handler.go is retained for tests +
// callers that need direct router-level wiring; production via
// cmd/dataplane goes through the strict server.

// ListAPIKeys handles GET /v1/tenants/{tenant_id}/api-keys.
func (h *Handler) ListAPIKeys(ctx context.Context, req httpapi.ListAPIKeysRequestObject) (httpapi.ListAPIKeysResponseObject, error) {
	limit := 25
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	keys, _, err := h.svc.List(ctx, req.TenantId, limit)
	if err != nil {
		return listProblem(err, "/v1/tenants/"+req.TenantId+"/api-keys"), nil
	}
	out := httpapi.APIKeyListResponse{
		Data:       make([]httpapi.APIKey, 0, len(keys)),
		Pagination: httpapi.Pagination{HasMore: false},
	}
	for _, k := range keys {
		out.Data = append(out.Data, toAPIKey(k))
	}
	return httpapi.ListAPIKeys200JSONResponse(out), nil
}

// CreateAPIKey handles POST /v1/tenants/{tenant_id}/api-keys with the
// Phase 8 RBAC retrofit gate.
func (h *Handler) CreateAPIKey(ctx context.Context, req httpapi.CreateAPIKeyRequestObject) (httpapi.CreateAPIKeyResponseObject, error) {
	instance := "/v1/tenants/" + req.TenantId + "/api-keys"
	if req.Body == nil {
		return createProblem422(instance, "request body required"), nil
	}
	if err := h.enforceWriteCtx(ctx, req.TenantId); err != nil {
		return createProblem403(instance), nil //nolint:nilerr // surfaces as 403 problem response
	}
	in := CreateInput{
		Name:               req.Body.Name,
		Scopes:             req.Body.Scopes,
		ExpiresAt:          req.Body.ExpiresAt,
		RateLimitPerMinute: req.Body.RateLimitPerMinute,
		Environment:        EnvironmentLive,
	}
	if req.Body.EnvironmentId != nil {
		in.EnvironmentID = *req.Body.EnvironmentId
	}
	if req.Body.IpAllowlist != nil {
		in.IPAllowlist = *req.Body.IpAllowlist
	}
	res, err := h.svc.Create(ctx, req.TenantId, in)
	if err != nil {
		return createError(err, instance), nil
	}
	tag := res.APIKey.ETag()
	loc := "/v1/api-keys/" + res.APIKey.ID
	return httpapi.CreateAPIKey201JSONResponse{
		Headers: httpapi.CreateAPIKey201ResponseHeaders{ETag: &tag, Location: &loc},
		Body: httpapi.CreateAPIKeyResponse{
			Data:   toAPIKey(res.APIKey),
			Secret: res.Plaintext,
		},
	}, nil
}

// GetAPIKey handles GET /v1/api-keys/{api_key_id}. The tenant comes
// from the auth context (the URL has no tenant segment).
func (h *Handler) GetAPIKey(ctx context.Context, req httpapi.GetAPIKeyRequestObject) (httpapi.GetAPIKeyResponseObject, error) {
	instance := "/v1/api-keys/" + req.ApiKeyId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return getProblem401(instance), nil
	}
	k, err := h.svc.Get(ctx, tenantID, req.ApiKeyId)
	if err != nil {
		return getError(err, instance), nil
	}
	tag := k.ETag()
	return httpapi.GetAPIKey200JSONResponse{
		Headers: httpapi.GetAPIKey200ResponseHeaders{ETag: &tag},
		Body:    httpapi.APIKeyResponse{Data: toAPIKey(k)},
	}, nil
}

// UpdateAPIKey handles PATCH /v1/api-keys/{api_key_id}.
func (h *Handler) UpdateAPIKey(ctx context.Context, req httpapi.UpdateAPIKeyRequestObject) (httpapi.UpdateAPIKeyResponseObject, error) {
	instance := "/v1/api-keys/" + req.ApiKeyId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return updateProblem401(instance), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return updateProblem412(instance, "malformed If-Match header"), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	if req.Body == nil {
		return updateProblem422(instance, "request body required"), nil
	}
	patch := UpdatePatch{
		Name:               req.Body.Name,
		RateLimitPerMinute: req.Body.RateLimitPerMinute,
		ExpiresAt:          req.Body.ExpiresAt,
	}
	if req.Body.Scopes != nil {
		s := append([]string(nil), *req.Body.Scopes...)
		patch.Scopes = &s
	}
	if req.Body.IpAllowlist != nil {
		ip := append([]string(nil), *req.Body.IpAllowlist...)
		patch.IPAllowlist = &ip
	}
	k, err := h.svc.Update(ctx, tenantID, req.ApiKeyId, expected, patch)
	if err != nil {
		return updateError(err, instance), nil
	}
	tag := k.ETag()
	return httpapi.UpdateAPIKey200JSONResponse{
		Headers: httpapi.UpdateAPIKey200ResponseHeaders{ETag: &tag},
		Body:    httpapi.APIKeyResponse{Data: toAPIKey(k)},
	}, nil
}

// DeleteAPIKey handles DELETE /v1/api-keys/{api_key_id} — alias for
// the soft-revoke verb.
func (h *Handler) DeleteAPIKey(ctx context.Context, req httpapi.DeleteAPIKeyRequestObject) (httpapi.DeleteAPIKeyResponseObject, error) {
	instance := "/v1/api-keys/" + req.ApiKeyId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return deleteProblem401(instance), nil
	}
	if _, err := h.svc.Revoke(ctx, tenantID, req.ApiKeyId); err != nil {
		return deleteError(err, instance), nil
	}
	return httpapi.DeleteAPIKey204Response{}, nil
}

// RotateAPIKey handles POST /v1/api-keys/{api_key_id}/rotate. RBAC
// retrofit gate runs before the rotation; grace period default is
// applied when the body or grace_period_seconds field is omitted.
func (h *Handler) RotateAPIKey(ctx context.Context, req httpapi.RotateAPIKeyRequestObject) (httpapi.RotateAPIKeyResponseObject, error) {
	instance := "/v1/api-keys/" + req.ApiKeyId + "/rotate"
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return rotateProblem401(instance), nil
	}
	if err := h.enforceWriteCtx(ctx, tenantID); err != nil {
		return rotateProblem403(instance), nil //nolint:nilerr // surfaces as 403 problem response
	}
	grace := GracePeriodDefault
	if req.Body != nil && req.Body.GracePeriodSeconds != nil {
		grace = *req.Body.GracePeriodSeconds
	}
	res, err := h.svc.Rotate(ctx, tenantID, req.ApiKeyId, grace)
	if err != nil {
		return rotateError(err, instance), nil
	}
	tag := res.APIKey.ETag()
	return httpapi.RotateAPIKey200JSONResponse{
		Headers: httpapi.RotateAPIKey200ResponseHeaders{ETag: &tag},
		Body: httpapi.RotateAPIKeyResponse{
			Data:                 toAPIKey(res.APIKey),
			Secret:               res.Plaintext,
			PredecessorExpiresAt: res.PredecessorExpiresAt,
		},
	}, nil
}

// RevokeAPIKey handles POST /v1/api-keys/{api_key_id}/revoke.
func (h *Handler) RevokeAPIKey(ctx context.Context, req httpapi.RevokeAPIKeyRequestObject) (httpapi.RevokeAPIKeyResponseObject, error) {
	instance := "/v1/api-keys/" + req.ApiKeyId + "/revoke"
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return revokeProblem401(instance), nil
	}
	k, err := h.svc.Revoke(ctx, tenantID, req.ApiKeyId)
	if err != nil {
		return revokeError(err, instance), nil
	}
	return httpapi.RevokeAPIKey200JSONResponse(httpapi.APIKeyResponse{Data: toAPIKey(k)}), nil
}

// ---------------------------------------------------------------------
// mappers + error translators
// ---------------------------------------------------------------------

// enforceWriteCtx is the Phase 8 retrofit gate. Mirrors
// h.enforceWrite from handler.go but takes a context directly so the
// strict-server methods (which already have ctx in scope) don't have
// to fabricate an http.Request.
func (h *Handler) enforceWriteCtx(ctx context.Context, tenantID string) error {
	p, _ := auth.PrincipalFromContext(ctx)
	return authorization.EnforceDestructive(ctx, h.checker, p.ActorID, tenantID, "apikey.write")
}

func toAPIKey(k APIKey) httpapi.APIKey {
	out := httpapi.APIKey{
		Id:        k.ID,
		Object:    httpapi.APIKeyObjectApiKey,
		TenantId:  k.TenantID,
		Name:      k.Name,
		Prefix:    k.Prefix,
		Scopes:    append([]string(nil), k.Scopes...),
		Status:    httpapi.APIKeyStatus(k.Status),
		CreatedBy: k.CreatedBy,
		CreatedAt: k.CreatedAt,
		UpdatedAt: k.UpdatedAt,
		Etag:      k.ETag(),
	}
	if k.EnvironmentID != "" {
		v := k.EnvironmentID
		out.EnvironmentId = &v
	}
	if k.RateLimitPerMinute != nil {
		v := *k.RateLimitPerMinute
		out.RateLimitPerMinute = &v
	}
	if len(k.IPAllowlist) > 0 {
		ip := append([]string(nil), k.IPAllowlist...)
		out.IpAllowlist = &ip
	}
	if k.ExpiresAt != nil {
		t := *k.ExpiresAt
		out.ExpiresAt = &t
	}
	if k.LastUsedAt != nil {
		t := *k.LastUsedAt
		out.LastUsedAt = &t
	}
	if k.RevokedAt != nil {
		t := *k.RevokedAt
		out.RevokedAt = &t
	}
	if k.RotatedAt != nil {
		t := *k.RotatedAt
		out.RotatedAt = &t
	}
	if k.PredecessorExpiresAt != nil {
		t := *k.PredecessorExpiresAt
		out.PredecessorExpiresAt = &t
	}
	return out
}

func toAPIProblem(p problem.Problem) httpapi.Problem {
	out := httpapi.Problem{Type: p.Type, Title: p.Title, Status: p.Status}
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

func listProblem(err error, instance string) httpapi.ListAPIKeysResponseObject {
	if errors.Is(err, auth.ErrUnauthorized) {
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", 401, "", instance)
		return httpapi.ListAPIKeys401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
	p := problem.New("forbidden", "Caller lacks permission for this resource.", 403, "", instance)
	return httpapi.ListAPIKeys403ApplicationProblemPlusJSONResponse{
		ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createProblem403(instance string) httpapi.CreateAPIKey403ApplicationProblemPlusJSONResponse {
	p := problem.New("forbidden", "Caller lacks the required permission.", 403, "apikey.write required", instance)
	return httpapi.CreateAPIKey403ApplicationProblemPlusJSONResponse{
		ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createProblem422(instance, detail string) httpapi.CreateAPIKey422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", 422, detail, instance)
	return httpapi.CreateAPIKey422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createError(err error, instance string) httpapi.CreateAPIKeyResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", 401, "", instance)
		return httpapi.CreateAPIKey401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, auth.ErrCrossTenant):
		return createProblem403(instance)
	case errors.Is(err, authorization.ErrPermissionDenied):
		return createProblem403(instance)
	default:
		return createProblem422(instance, err.Error())
	}
}

func getProblem401(instance string) httpapi.GetAPIKey401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", 401, "", instance)
	return httpapi.GetAPIKey401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func getError(err error, instance string) httpapi.GetAPIKeyResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return getProblem401(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", 403, "", instance)
		return httpapi.GetAPIKey403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "API key not found.", 404, "", instance)
		return httpapi.GetAPIKey404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateProblem401(instance string) httpapi.UpdateAPIKey401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", 401, "", instance)
	return httpapi.UpdateAPIKey401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateProblem412(instance, detail string) httpapi.UpdateAPIKey412ApplicationProblemPlusJSONResponse {
	p := problem.New("precondition-failed", "Precondition failed.", 412, detail, instance)
	return httpapi.UpdateAPIKey412ApplicationProblemPlusJSONResponse{
		PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateProblem422(instance, detail string) httpapi.UpdateAPIKey422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", 422, detail, instance)
	return httpapi.UpdateAPIKey422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateError(err error, instance string) httpapi.UpdateAPIKeyResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return updateProblem401(instance)
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, authorization.ErrPermissionDenied):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", 403, "", instance)
		return httpapi.UpdateAPIKey403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return updateProblem412(instance, "stale or missing If-Match")
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "API key not found.", 404, "", instance)
		return httpapi.UpdateAPIKey404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return updateProblem422(instance, err.Error())
	}
}

func deleteProblem401(instance string) httpapi.DeleteAPIKey401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", 401, "", instance)
	return httpapi.DeleteAPIKey401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func deleteError(err error, instance string) httpapi.DeleteAPIKeyResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return deleteProblem401(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", 403, "", instance)
		return httpapi.DeleteAPIKey403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "API key not found.", 404, "", instance)
		return httpapi.DeleteAPIKey404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func rotateProblem401(instance string) httpapi.RotateAPIKey401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", 401, "", instance)
	return httpapi.RotateAPIKey401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func rotateProblem403(instance string) httpapi.RotateAPIKey403ApplicationProblemPlusJSONResponse {
	p := problem.New("forbidden", "Caller lacks the required permission.", 403, "apikey.write required", instance)
	return httpapi.RotateAPIKey403ApplicationProblemPlusJSONResponse{
		ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func rotateError(err error, instance string) httpapi.RotateAPIKeyResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return rotateProblem401(instance)
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, authorization.ErrPermissionDenied):
		return rotateProblem403(instance)
	case errors.Is(err, ErrGraceOutOfRange), errors.Is(err, ErrNotRotatable):
		p := problem.New("validation-error", "Validation failed.", 422, err.Error(), instance)
		return httpapi.RotateAPIKey422ApplicationProblemPlusJSONResponse{
			IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "API key not found.", 404, "", instance)
		return httpapi.RotateAPIKey404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func revokeProblem401(instance string) httpapi.RevokeAPIKey401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", 401, "", instance)
	return httpapi.RevokeAPIKey401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func revokeError(err error, instance string) httpapi.RevokeAPIKeyResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return revokeProblem401(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", 403, "", instance)
		return httpapi.RevokeAPIKey403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "API key not found.", 404, "", instance)
		return httpapi.RevokeAPIKey404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}
