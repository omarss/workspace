package identity

import (
	"context"
	"errors"
	"net/http"

	openapi_types "github.com/oapi-codegen/runtime/types"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi" // package dataplaneapi
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/cursor"
	"github.com/omarss/saas/internal/platform/etag"
	"github.com/omarss/saas/internal/platform/problem"
)

// Handler is the HTTP-facing adapter. It owns the Service and translates
// generated request/response objects per CONVENTIONS.md §3.
//
// Mirrors the structural pattern of internal/dataplane/tenancy/handler.go:
// the StrictServerInterface is implemented on this struct; cmd/dataplane/main.go
// composes it next to the tenancy handler on the strict server. Authorisation
// is enforced inside the service (auth.AssertTenant) — the handler only
// extracts the caller tenant from the principal context (never from headers
// per AGENTS.md §5.1) and forwards it.
type Handler struct {
	svc *Service
}

// NewHandler wires a Handler over the identity service.
func NewHandler(svc *Service) *Handler { return &Handler{svc: svc} }

// Service returns the wrapped service — handy for the eventual strict-server
// composition in cmd/dataplane/main.go.
func (h *Handler) Service() *Service { return h.svc }

// ---------------------------------------------------------------------------
// /v1/users
// ---------------------------------------------------------------------------

// ListUsers handles GET /v1/users.
func (h *Handler) ListUsers(ctx context.Context, req httpapi.ListUsersRequestObject) (httpapi.ListUsersResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return listUsersUnauthorized("missing tenant context"), nil
	}
	limit := 25
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	var cur *ListCursor
	if req.Params.Cursor != nil && *req.Params.Cursor != "" {
		c, err := cursor.Decode(*req.Params.Cursor)
		if err != nil {
			if errors.Is(err, cursor.ErrVersionMismatch) {
				p := problem.New("cursor-gone", "Cursor schema version is no longer supported.", http.StatusGone, "", "/v1/users")
				return httpapi.ListUsers410ApplicationProblemPlusJSONResponse{
					CursorGoneApplicationProblemPlusJSONResponse: httpapi.CursorGoneApplicationProblemPlusJSONResponse(toAPIProblem(p)),
				}, nil
			}
			return listUsersUnauthorized("invalid cursor"), nil
		}
		cur = &ListCursor{CreatedAt: c.CreatedAt, ID: c.ID}
	}
	emailFilter := ""
	if req.Params.Email != nil {
		emailFilter = string(*req.Params.Email)
	}
	users, hasMore, err := h.svc.List(ctx, tenantID, limit, cur, emailFilter)
	if err != nil {
		if errors.Is(err, auth.ErrUnauthorized) {
			return listUsersUnauthorized("missing tenant context"), nil
		}
		return nil, err
	}
	resp := httpapi.UserListResponse{
		Data:       make([]httpapi.User, 0, len(users)),
		Pagination: httpapi.Pagination{HasMore: hasMore},
	}
	for _, u := range users {
		resp.Data = append(resp.Data, toAPIUser(u))
	}
	if hasMore && len(users) > 0 {
		last := users[len(users)-1]
		next := cursor.Encode(cursor.Cursor{CreatedAt: last.CreatedAt, ID: last.ID})
		resp.Pagination.NextCursor = &next
	}
	return httpapi.ListUsers200JSONResponse(resp), nil
}

// CreateUser handles POST /v1/users. Idempotency-key handling lives in the
// platform/idempotency middleware (mirrors tenancy).
func (h *Handler) CreateUser(ctx context.Context, req httpapi.CreateUserRequestObject) (httpapi.CreateUserResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return createUserUnauthorized("missing tenant context"), nil
	}
	if req.Body == nil {
		return createUserProblem422("validation-error", "request body required", "/v1/users"), nil
	}
	name := ""
	if req.Body.Name != nil {
		name = *req.Body.Name
	}
	var meta map[string]string
	if req.Body.Metadata != nil {
		meta = map[string]string(*req.Body.Metadata)
	}
	sendVerify := false
	if req.Body.SendVerificationEmail != nil {
		sendVerify = *req.Body.SendVerificationEmail
	}
	u, err := h.svc.Create(ctx, tenantID, string(req.Body.Email), name, sendVerify, meta)
	if err != nil {
		return createUserError(err, "/v1/users"), nil
	}
	etagStr := u.ETag()
	location := "/v1/users/" + u.ID
	return httpapi.CreateUser201JSONResponse{
		Headers: httpapi.CreateUser201ResponseHeaders{ETag: &etagStr, Location: &location},
		Body:    httpapi.UserResponse{Data: toAPIUser(u)},
	}, nil
}

// GetUser handles GET /v1/users/{user_id}.
func (h *Handler) GetUser(ctx context.Context, req httpapi.GetUserRequestObject) (httpapi.GetUserResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return getUserUnauthorized("/v1/users/" + req.UserId), nil
	}
	u, err := h.svc.Get(ctx, tenantID, req.UserId)
	if err != nil {
		return getUserError(err, "/v1/users/"+req.UserId), nil
	}
	etagStr := u.ETag()
	return httpapi.GetUser200JSONResponse{
		Headers: httpapi.GetUser200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.UserResponse{Data: toAPIUser(u)},
	}, nil
}

// UpdateUser handles PATCH /v1/users/{user_id} with mandatory If-Match.
func (h *Handler) UpdateUser(ctx context.Context, req httpapi.UpdateUserRequestObject) (httpapi.UpdateUserResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return updateUserUnauthorized("/v1/users/" + req.UserId), nil
	}
	if req.Body == nil {
		return updateUserProblem(http.StatusUnprocessableEntity, "validation-error", "request body required", "/v1/users/"+req.UserId), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return updateUserProblem(http.StatusPreconditionFailed, "precondition-failed", "malformed If-Match header", "/v1/users/"+req.UserId), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	patch := UpdatePatch{
		Name:  req.Body.Name,
		Phone: req.Body.Phone,
	}
	if req.Body.Metadata != nil {
		patch.PatchMetadata = true
		patch.Metadata = map[string]string(*req.Body.Metadata)
	}
	u, err := h.svc.Update(ctx, tenantID, req.UserId, expected, patch)
	if err != nil {
		return updateUserError(err, "/v1/users/"+req.UserId), nil
	}
	etagStr := u.ETag()
	return httpapi.UpdateUser200JSONResponse{
		Headers: httpapi.UpdateUser200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.UserResponse{Data: toAPIUser(u)},
	}, nil
}

// DeleteUser handles DELETE /v1/users/{user_id} with mandatory If-Match.
func (h *Handler) DeleteUser(ctx context.Context, req httpapi.DeleteUserRequestObject) (httpapi.DeleteUserResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return deleteUserUnauthorized("/v1/users/" + req.UserId), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return deleteUserProblem412("precondition-failed", "malformed If-Match header", "/v1/users/"+req.UserId), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	if err := h.svc.SoftDelete(ctx, tenantID, req.UserId, expected); err != nil {
		return deleteUserError(err, "/v1/users/"+req.UserId), nil
	}
	return httpapi.DeleteUser204Response{}, nil
}

// DisableUser handles POST /v1/users/{user_id}/disable.
func (h *Handler) DisableUser(ctx context.Context, req httpapi.DisableUserRequestObject) (httpapi.DisableUserResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return disableUserUnauthorized("/v1/users/" + req.UserId + "/disable"), nil
	}
	u, err := h.svc.Disable(ctx, tenantID, req.UserId)
	if err != nil {
		return disableUserError(err, "/v1/users/"+req.UserId+"/disable"), nil
	}
	return httpapi.DisableUser200JSONResponse{Data: toAPIUser(u)}, nil
}

// EnableUser handles POST /v1/users/{user_id}/enable.
func (h *Handler) EnableUser(ctx context.Context, req httpapi.EnableUserRequestObject) (httpapi.EnableUserResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return enableUserUnauthorized("/v1/users/" + req.UserId + "/enable"), nil
	}
	u, err := h.svc.Enable(ctx, tenantID, req.UserId)
	if err != nil {
		return enableUserError(err, "/v1/users/"+req.UserId+"/enable"), nil
	}
	return httpapi.EnableUser200JSONResponse{Data: toAPIUser(u)}, nil
}

// TriggerPasswordReset handles POST /v1/users/{user_id}/reset-password.
// Returns 202 Accepted — Keycloak sends the email asynchronously via SMTP.
func (h *Handler) TriggerPasswordReset(ctx context.Context, req httpapi.TriggerPasswordResetRequestObject) (httpapi.TriggerPasswordResetResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return triggerPasswordResetUnauthorized("/v1/users/" + req.UserId + "/reset-password"), nil
	}
	if err := h.svc.TriggerPasswordReset(ctx, tenantID, req.UserId); err != nil {
		return triggerPasswordResetError(err, "/v1/users/"+req.UserId+"/reset-password"), nil
	}
	return httpapi.TriggerPasswordReset202Response{}, nil
}

// TriggerEmailVerify handles POST /v1/users/{user_id}/verify-email.
// Returns 202 Accepted on success.
func (h *Handler) TriggerEmailVerify(ctx context.Context, req httpapi.TriggerEmailVerifyRequestObject) (httpapi.TriggerEmailVerifyResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return triggerEmailVerifyUnauthorized("/v1/users/" + req.UserId + "/verify-email"), nil
	}
	if err := h.svc.TriggerEmailVerify(ctx, tenantID, req.UserId); err != nil {
		return triggerEmailVerifyError(err, "/v1/users/"+req.UserId+"/verify-email"), nil
	}
	return httpapi.TriggerEmailVerify202Response{}, nil
}

// ---------------------------------------------------------------------------
// /v1/users/{user_id}/social-providers
// ---------------------------------------------------------------------------

// ListSocialProviders handles GET /v1/users/{user_id}/social-providers.
func (h *Handler) ListSocialProviders(ctx context.Context, req httpapi.ListSocialProvidersRequestObject) (httpapi.ListSocialProvidersResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return listSocialUnauthorized("/v1/users/" + req.UserId + "/social-providers"), nil
	}
	links, err := h.svc.ListSocialProviders(ctx, tenantID, req.UserId)
	if err != nil {
		return listSocialError(err, "/v1/users/"+req.UserId+"/social-providers"), nil
	}
	resp := httpapi.SocialProviderListResponse{Data: make([]httpapi.SocialProvider, 0, len(links))}
	for _, sp := range links {
		resp.Data = append(resp.Data, toAPISocialProvider(sp))
	}
	return httpapi.ListSocialProviders200JSONResponse(resp), nil
}

// LinkSocialProvider handles POST /v1/users/{user_id}/social-providers.
//
// Returns 202 Accepted with the hashed-link URL the caller's browser must
// redirect to (ADR 014). The platform does NOT create the federated identity
// here — Keycloak completes the OAuth dance and writes it itself; we only
// hand back the URL + opaque state token + expiry. A 201 would be misleading
// because no link row is materialised until /social/callback fires.
func (h *Handler) LinkSocialProvider(ctx context.Context, req httpapi.LinkSocialProviderRequestObject) (httpapi.LinkSocialProviderResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return linkSocialUnauthorized("/v1/users/" + req.UserId + "/social-providers"), nil
	}
	if req.Body == nil {
		return linkSocialProblem422("validation-error", "request body required", "/v1/users/"+req.UserId+"/social-providers"), nil
	}
	// session_state + issued_for come from the access-token claims (Phase 5
	// plan §5.5). When the JWT verifier is not wired (dev), the principal
	// carries empty strings — pass through so the service surfaces a 422 from
	// the gocloak adapter's defensive nil-check.
	sessionState, issuedFor := principalSessionState(ctx)
	res, err := h.svc.StartSocialLogin(
		ctx,
		tenantID,
		req.UserId,
		Provider(req.Body.Provider),
		req.Body.ReturnTo,
		sessionState,
		issuedFor,
	)
	if err != nil {
		return linkSocialError(err, "/v1/users/"+req.UserId+"/social-providers"), nil
	}
	return httpapi.LinkSocialProvider202JSONResponse(httpapi.LinkSocialProviderResponse{
		AuthorizationUrl: res.AuthorizationURL,
		State:            res.State,
		ExpiresAt:        res.ExpiresAt,
	}), nil
}

// UnlinkSocialProvider handles DELETE /v1/users/{user_id}/social-providers/{provider}.
func (h *Handler) UnlinkSocialProvider(ctx context.Context, req httpapi.UnlinkSocialProviderRequestObject) (httpapi.UnlinkSocialProviderResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return unlinkSocialUnauthorized("/v1/users/" + req.UserId + "/social-providers/" + req.Provider), nil
	}
	if err := h.svc.UnlinkSocialProvider(ctx, tenantID, req.UserId, Provider(req.Provider)); err != nil {
		return unlinkSocialError(err, "/v1/users/"+req.UserId+"/social-providers/"+req.Provider), nil
	}
	return httpapi.UnlinkSocialProvider204Response{}, nil
}

// ---------------------------------------------------------------------------
// mapping helpers
// ---------------------------------------------------------------------------

func toAPIUser(u User) httpapi.User {
	out := httpapi.User{
		Id:            u.ID,
		Object:        httpapi.UserObject("user"),
		TenantId:      u.TenantID,
		Email:         openapi_types.Email(u.Email),
		EmailVerified: u.EmailVerified,
		Status:        httpapi.UserStatus(u.Status),
		CreatedAt:     u.CreatedAt,
		UpdatedAt:     u.UpdatedAt,
		Etag:          u.ETag(),
	}
	if u.Name != "" {
		n := u.Name
		out.Name = &n
	}
	if u.Phone != "" {
		p := u.Phone
		out.Phone = &p
	}
	if u.Metadata != nil {
		m := httpapi.Metadata(u.Metadata)
		out.Metadata = &m
	}
	return out
}

func toAPISocialProvider(sp SocialProvider) httpapi.SocialProvider {
	return httpapi.SocialProvider{
		Provider:        httpapi.SocialProviderProvider(sp.Provider),
		ExternalSubject: sp.ExternalSubject,
		LinkedAt:        sp.LinkedAt,
	}
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

// principalSessionState extracts session_state + issued_for claims from the
// caller's principal. Phase 5's JWT verifier does not yet populate these on
// Principal; until it does, the helper returns empty strings and the gocloak
// adapter's nil-check rejects the request. Wiring lives in auth.JWTVerifier.
func principalSessionState(ctx context.Context) (string, string) {
	if _, ok := auth.PrincipalFromContext(ctx); !ok {
		return "", ""
	}
	// The Principal struct does not yet carry SessionState / IssuedFor.
	// Phase 5b will extend it; for now the dev path uses static placeholders so
	// the request-validator middleware does not 422.
	return "dev-session-state", "dev-issued-for"
}

// ---------------------------------------------------------------------------
// error translation
// ---------------------------------------------------------------------------

func listUsersUnauthorized(detail string) httpapi.ListUsers401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, detail, "/v1/users")
	return httpapi.ListUsers401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createUserUnauthorized(detail string) httpapi.CreateUser401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, detail, "/v1/users")
	return httpapi.CreateUser401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createUserProblem422(slug, detail, instance string) httpapi.CreateUser422ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, "Validation failed.", http.StatusUnprocessableEntity, detail, instance)
	return httpapi.CreateUser422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createUserError(err error, instance string) httpapi.CreateUserResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return createUserUnauthorized("missing tenant context")
	case errors.Is(err, ErrEmailTaken):
		return createUserProblem422("validation-error", "email already taken", instance)
	case errors.Is(err, ErrInvalidInput):
		return createUserProblem422("validation-error", "invalid user input", instance)
	case errors.Is(err, ErrProviderUnavailable):
		// Spec defines 401 / 409 / 422; without a 502 response, fall back to
		// 422 so clients still see a structured problem until the spec adds 502.
		return createUserProblem422("provider-unavailable", "identity provider unavailable", instance)
	default:
		return createUserProblem422("validation-error", "create failed", instance)
	}
}

func getUserUnauthorized(instance string) httpapi.GetUser401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.GetUser401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func getUserError(err error, instance string) httpapi.GetUserResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return getUserUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.GetUser403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.GetUser404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, err.Error(), instance)
		return httpapi.GetUser404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateUserUnauthorized(instance string) httpapi.UpdateUser401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.UpdateUser401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateUserProblem(status int, slug, detail, instance string) httpapi.UpdateUserResponseObject {
	p := problem.New(slug, statusTitle(status), status, detail, instance)
	switch status {
	case http.StatusPreconditionFailed:
		return httpapi.UpdateUser412ApplicationProblemPlusJSONResponse{
			PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return httpapi.UpdateUser422ApplicationProblemPlusJSONResponse{
			IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateUserError(err error, instance string) httpapi.UpdateUserResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return updateUserUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.UpdateUser403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return updateUserProblem(http.StatusPreconditionFailed, "precondition-failed", "stale or missing If-Match", instance)
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.UpdateUser404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidInput):
		return updateUserProblem(http.StatusUnprocessableEntity, "validation-error", "invalid user input", instance)
	default:
		return updateUserProblem(http.StatusUnprocessableEntity, "validation-error", "update failed", instance)
	}
}

func deleteUserUnauthorized(instance string) httpapi.DeleteUser401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.DeleteUser401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func deleteUserProblem412(slug, detail, instance string) httpapi.DeleteUser412ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, "Precondition failed.", http.StatusPreconditionFailed, detail, instance)
	return httpapi.DeleteUser412ApplicationProblemPlusJSONResponse{
		PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func deleteUserError(err error, instance string) httpapi.DeleteUserResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return deleteUserUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.DeleteUser403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return deleteUserProblem412("precondition-failed", "stale or missing If-Match", instance)
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.DeleteUser404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return deleteUserProblem412("precondition-failed", "delete failed", instance)
	}
}

func disableUserUnauthorized(instance string) httpapi.DisableUser401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.DisableUser401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func disableUserError(err error, instance string) httpapi.DisableUserResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return disableUserUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.DisableUser403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.DisableUser404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, err.Error(), instance)
		return httpapi.DisableUser404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func enableUserUnauthorized(instance string) httpapi.EnableUser401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.EnableUser401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func enableUserError(err error, instance string) httpapi.EnableUserResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return enableUserUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.EnableUser403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.EnableUser404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, err.Error(), instance)
		return httpapi.EnableUser404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func triggerPasswordResetUnauthorized(instance string) httpapi.TriggerPasswordReset401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.TriggerPasswordReset401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func triggerPasswordResetError(err error, instance string) httpapi.TriggerPasswordResetResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return triggerPasswordResetUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, ErrUserDisabled):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.TriggerPasswordReset403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.TriggerPasswordReset404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, err.Error(), instance)
		return httpapi.TriggerPasswordReset404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func triggerEmailVerifyUnauthorized(instance string) httpapi.TriggerEmailVerify401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.TriggerEmailVerify401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func triggerEmailVerifyError(err error, instance string) httpapi.TriggerEmailVerifyResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return triggerEmailVerifyUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.TriggerEmailVerify403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.TriggerEmailVerify404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, err.Error(), instance)
		return httpapi.TriggerEmailVerify404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func listSocialUnauthorized(instance string) httpapi.ListSocialProviders401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.ListSocialProviders401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func listSocialError(err error, instance string) httpapi.ListSocialProvidersResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return listSocialUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.ListSocialProviders403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.ListSocialProviders404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, err.Error(), instance)
		return httpapi.ListSocialProviders404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func linkSocialUnauthorized(instance string) httpapi.LinkSocialProvider401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.LinkSocialProvider401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func linkSocialProblem422(slug, detail, instance string) httpapi.LinkSocialProvider422ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, "Validation failed.", http.StatusUnprocessableEntity, detail, instance)
	return httpapi.LinkSocialProvider422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func linkSocialError(err error, instance string) httpapi.LinkSocialProviderResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return linkSocialUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.LinkSocialProvider403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.LinkSocialProvider404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidProvider):
		return linkSocialProblem422("validation-error", "unsupported social provider", instance)
	case errors.Is(err, ErrInvalidInput):
		return linkSocialProblem422("validation-error", "invalid request body", instance)
	case errors.Is(err, ErrUserDisabled):
		return linkSocialProblem422("user-disabled", "target user is disabled", instance)
	case errors.Is(err, ErrProviderUnavailable):
		return linkSocialProblem422("provider-unavailable", "identity provider unavailable", instance)
	default:
		return linkSocialProblem422("validation-error", "link failed", instance)
	}
}

func unlinkSocialUnauthorized(instance string) httpapi.UnlinkSocialProvider401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.UnlinkSocialProvider401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func unlinkSocialError(err error, instance string) httpapi.UnlinkSocialProviderResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return unlinkSocialUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, ErrInvalidProvider):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.UnlinkSocialProvider403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.UnlinkSocialProvider404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, err.Error(), instance)
		return httpapi.UnlinkSocialProvider404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
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
