package apikeys

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/omarss/saas/internal/dataplane/authorization"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/etag"
	"github.com/omarss/saas/internal/platform/problem"
)

// Handler exposes the API-keys endpoints (AGENTS.md §8.5) over chi.
// Phase 9 wires raw chi routes rather than the generated StrictServer
// because regenerating the oapi-codegen surface for a multi-resource
// addition would touch every existing handler's StrictServerInterface
// stub. The OpenAPI spec under openapi/data-plane.yaml still
// documents the contract; SDK generation lifts the schemas without
// requiring the codegen round-trip for handler stubs.
//
// RBAC retrofit: POST /v1/tenants/{tenant_id}/api-keys and
// POST /v1/api-keys/{api_key_id}/rotate route through
// authorization.EnforceDestructive with the `apikey.write` permission
// (CONVENTIONS.md §2 retrofitted-endpoints table).
type Handler struct {
	svc     *Service
	checker authorization.PermissionChecker
}

// NewHandler wires the chi-router-facing handler. checker may be nil
// in tests; production wiring threads in authorization.Service.
func NewHandler(svc *Service, checker authorization.PermissionChecker) *Handler {
	return &Handler{svc: svc, checker: checker}
}

// Mount registers the API-keys routes on r. Idempotency and auth
// middleware are inherited from the parent chain.
func (h *Handler) Mount(r chi.Router) {
	r.Route("/v1/tenants/{tenant_id}/api-keys", func(sub chi.Router) {
		sub.Get("/", h.list)
		sub.Post("/", h.create)
	})
	r.Route("/v1/api-keys/{api_key_id}", func(sub chi.Router) {
		sub.Get("/", h.get)
		sub.Patch("/", h.update)
		sub.Delete("/", h.delete)
		sub.Post("/rotate", h.rotate)
		sub.Post("/revoke", h.revoke)
	})
}

// ---------------------------------------------------------------------
// HTTP payload shapes — mirror the OpenAPI schemas.
//
// We hand-roll these structs rather than pulling them from the codegen
// surface so adding API-keys does NOT regenerate every other module's
// strict-server interface. The OpenAPI spec stays authoritative for
// SDK consumers; these structs are the server-side mirror.
// ---------------------------------------------------------------------

type apiKeyResponse struct {
	ID                   string     `json:"id"`
	Object               string     `json:"object"`
	TenantID             string     `json:"tenant_id"`
	EnvironmentID        string     `json:"environment_id,omitempty"`
	Name                 string     `json:"name"`
	Prefix               string     `json:"prefix"`
	Scopes               []string   `json:"scopes"`
	Status               string     `json:"status"`
	RateLimitPerMinute   *int       `json:"rate_limit_per_minute,omitempty"`
	IPAllowlist          []string   `json:"ip_allowlist,omitempty"`
	CreatedBy            string     `json:"created_by"`
	CreatedAt            time.Time  `json:"created_at"`
	UpdatedAt            time.Time  `json:"updated_at"`
	ExpiresAt            *time.Time `json:"expires_at,omitempty"`
	LastUsedAt           *time.Time `json:"last_used_at,omitempty"`
	RevokedAt            *time.Time `json:"revoked_at,omitempty"`
	RotatedAt            *time.Time `json:"rotated_at,omitempty"`
	PredecessorExpiresAt *time.Time `json:"predecessor_expires_at,omitempty"`
	Etag                 string     `json:"etag"`
}

type createRequest struct {
	Name               string     `json:"name"`
	Scopes             []string   `json:"scopes"`
	EnvironmentID      string     `json:"environment_id"`
	ExpiresAt          *time.Time `json:"expires_at"`
	RateLimitPerMinute *int       `json:"rate_limit_per_minute"`
	IPAllowlist        []string   `json:"ip_allowlist"`
}

type createResponse struct {
	Data   apiKeyResponse `json:"data"`
	Secret string         `json:"secret" pii:"true" sensitive:"true"`
}

type updateRequest struct {
	Name               *string    `json:"name"`
	Scopes             []string   `json:"scopes"`
	HasScopes          bool       `json:"-"`
	RateLimitPerMinute *int       `json:"rate_limit_per_minute"`
	IPAllowlist        []string   `json:"ip_allowlist"`
	HasIPAllowlist     bool       `json:"-"`
	ExpiresAt          *time.Time `json:"expires_at"`
}

// UnmarshalJSON for updateRequest is intentionally hand-rolled so we
// can distinguish absent-field from null-or-empty for Scopes /
// IPAllowlist (set-replace vs leave-unchanged semantics).
func (u *updateRequest) UnmarshalJSON(b []byte) error {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	if v, ok := raw["name"]; ok {
		var s string
		if err := json.Unmarshal(v, &s); err != nil {
			return err
		}
		u.Name = &s
	}
	if v, ok := raw["scopes"]; ok {
		u.HasScopes = true
		if err := json.Unmarshal(v, &u.Scopes); err != nil {
			return err
		}
	}
	if v, ok := raw["rate_limit_per_minute"]; ok {
		var n int
		if err := json.Unmarshal(v, &n); err != nil {
			return err
		}
		u.RateLimitPerMinute = &n
	}
	if v, ok := raw["ip_allowlist"]; ok {
		u.HasIPAllowlist = true
		if err := json.Unmarshal(v, &u.IPAllowlist); err != nil {
			return err
		}
	}
	if v, ok := raw["expires_at"]; ok {
		var t time.Time
		if err := json.Unmarshal(v, &t); err != nil {
			return err
		}
		u.ExpiresAt = &t
	}
	return nil
}

type rotateRequest struct {
	GracePeriodSeconds *int `json:"grace_period_seconds"`
}

type rotateResponse struct {
	Data                 apiKeyResponse `json:"data"`
	Secret               string         `json:"secret" pii:"true" sensitive:"true"`
	PredecessorExpiresAt time.Time      `json:"predecessor_expires_at"`
}

type listResponse struct {
	Data       []apiKeyResponse `json:"data"`
	Pagination struct {
		HasMore bool `json:"has_more"`
	} `json:"pagination"`
}

// ---------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------

func (h *Handler) list(w http.ResponseWriter, r *http.Request) {
	tenantID := chi.URLParam(r, "tenant_id")
	keys, hasMore, err := h.svc.List(r.Context(), tenantID, 25)
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	resp := listResponse{Data: make([]apiKeyResponse, 0, len(keys))}
	resp.Pagination.HasMore = hasMore
	for _, k := range keys {
		resp.Data = append(resp.Data, toResponse(k))
	}
	writeJSON(w, http.StatusOK, resp)
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request) {
	tenantID := chi.URLParam(r, "tenant_id")

	// RBAC retrofit gate (Phase 8 pattern). Runs BEFORE body parse so
	// a forbidden caller can't probe for validation errors.
	if err := h.enforceWrite(r, tenantID); err != nil {
		writeServiceError(w, r, err)
		return
	}

	var req createRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation, "Validation failed.", "request body must be JSON")
		return
	}
	res, err := h.svc.Create(r.Context(), tenantID, CreateInput{
		Name:               req.Name,
		Scopes:             req.Scopes,
		EnvironmentID:      req.EnvironmentID,
		ExpiresAt:          req.ExpiresAt,
		RateLimitPerMinute: req.RateLimitPerMinute,
		IPAllowlist:        req.IPAllowlist,
		Environment:        EnvironmentLive,
	})
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	body := createResponse{Data: toResponse(res.APIKey), Secret: res.Plaintext}
	w.Header().Set("ETag", res.APIKey.ETag())
	w.Header().Set("Location", "/v1/api-keys/"+res.APIKey.ID)
	writeJSON(w, http.StatusCreated, body)
}

func (h *Handler) get(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := auth.TenantFromContext(r.Context())
	if !ok {
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "")
		return
	}
	apiKeyID := chi.URLParam(r, "api_key_id")
	k, err := h.svc.Get(r.Context(), tenantID, apiKeyID)
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	w.Header().Set("ETag", k.ETag())
	writeJSON(w, http.StatusOK, struct {
		Data apiKeyResponse `json:"data"`
	}{Data: toResponse(k)})
}

func (h *Handler) update(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := auth.TenantFromContext(r.Context())
	if !ok {
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "")
		return
	}
	apiKeyID := chi.URLParam(r, "api_key_id")
	expected, parseErr := etag.Parse(r.Header.Get("If-Match"))
	if parseErr != nil {
		writeProblem(w, r, http.StatusPreconditionFailed, problem.TypePreconditionFailed, "Precondition failed.", "malformed If-Match header")
		return
	}
	var req updateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation, "Validation failed.", "request body must be JSON")
		return
	}
	patch := UpdatePatch{Name: req.Name, RateLimitPerMinute: req.RateLimitPerMinute, ExpiresAt: req.ExpiresAt}
	if req.HasScopes {
		scopes := append([]string(nil), req.Scopes...)
		patch.Scopes = &scopes
	}
	if req.HasIPAllowlist {
		allow := append([]string(nil), req.IPAllowlist...)
		patch.IPAllowlist = &allow
	}
	k, err := h.svc.Update(r.Context(), tenantID, apiKeyID, expected, patch)
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	w.Header().Set("ETag", k.ETag())
	writeJSON(w, http.StatusOK, struct {
		Data apiKeyResponse `json:"data"`
	}{Data: toResponse(k)})
}

func (h *Handler) delete(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := auth.TenantFromContext(r.Context())
	if !ok {
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "")
		return
	}
	apiKeyID := chi.URLParam(r, "api_key_id")
	if _, err := h.svc.Revoke(r.Context(), tenantID, apiKeyID); err != nil {
		writeServiceError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) rotate(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := auth.TenantFromContext(r.Context())
	if !ok {
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "")
		return
	}
	apiKeyID := chi.URLParam(r, "api_key_id")

	// RBAC retrofit gate.
	if err := h.enforceWrite(r, tenantID); err != nil {
		writeServiceError(w, r, err)
		return
	}

	var req rotateRequest
	if r.ContentLength > 0 {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation, "Validation failed.", "request body must be JSON")
			return
		}
	}
	grace := GracePeriodDefault
	if req.GracePeriodSeconds != nil {
		grace = *req.GracePeriodSeconds
	}
	res, err := h.svc.Rotate(r.Context(), tenantID, apiKeyID, grace)
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	body := rotateResponse{
		Data:                 toResponse(res.APIKey),
		Secret:               res.Plaintext,
		PredecessorExpiresAt: res.PredecessorExpiresAt,
	}
	w.Header().Set("ETag", res.APIKey.ETag())
	writeJSON(w, http.StatusOK, body)
}

func (h *Handler) revoke(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := auth.TenantFromContext(r.Context())
	if !ok {
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "")
		return
	}
	apiKeyID := chi.URLParam(r, "api_key_id")
	k, err := h.svc.Revoke(r.Context(), tenantID, apiKeyID)
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Data apiKeyResponse `json:"data"`
	}{Data: toResponse(k)})
}

// enforceWrite is the Phase 8 §8.11 retrofit gate scoped to the
// apikey.write permission. Identical shape to tenancy.enforceTenantWrite
// — see CONVENTIONS.md §2.
func (h *Handler) enforceWrite(r *http.Request, tenantID string) error {
	p, _ := auth.PrincipalFromContext(r.Context())
	return authorization.EnforceDestructive(r.Context(), h.checker, p.ActorID, tenantID, "apikey.write")
}

// ---------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------

func toResponse(k APIKey) apiKeyResponse {
	out := apiKeyResponse{
		ID:                   k.ID,
		Object:               "api_key",
		TenantID:             k.TenantID,
		EnvironmentID:        k.EnvironmentID,
		Name:                 k.Name,
		Prefix:               k.Prefix,
		Scopes:               append([]string(nil), k.Scopes...),
		Status:               string(k.Status),
		RateLimitPerMinute:   k.RateLimitPerMinute,
		IPAllowlist:          append([]string(nil), k.IPAllowlist...),
		CreatedBy:            k.CreatedBy,
		CreatedAt:            k.CreatedAt,
		UpdatedAt:            k.UpdatedAt,
		ExpiresAt:            k.ExpiresAt,
		LastUsedAt:           k.LastUsedAt,
		RevokedAt:            k.RevokedAt,
		RotatedAt:            k.RotatedAt,
		PredecessorExpiresAt: k.PredecessorExpiresAt,
		Etag:                 k.ETag(),
	}
	return out
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeProblem(w http.ResponseWriter, r *http.Request, status int, typeURI, title, detail string) {
	p := problem.Problem{
		Type:     typeURI,
		Title:    title,
		Status:   status,
		Detail:   detail,
		Instance: r.URL.Path,
	}
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(p)
}

// writeServiceError maps domain errors to RFC 9457 problem responses
// using the catalogue from CONVENTIONS.md §3.
func writeServiceError(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "")
	case errors.Is(err, auth.ErrCrossTenant):
		writeProblem(w, r, http.StatusForbidden, problem.TypeCrossTenant, "Cross-tenant access denied.", "")
	case errors.Is(err, authorization.ErrPermissionDenied):
		writeProblem(w, r, http.StatusForbidden, problem.TypeForbidden, "Caller lacks the required permission.", "apikey.write required")
	case errors.Is(err, ErrETagMismatch):
		writeProblem(w, r, http.StatusPreconditionFailed, problem.TypePreconditionFailed, "Precondition failed.", "stale or missing If-Match")
	case errors.Is(err, ErrNotFound):
		writeProblem(w, r, http.StatusNotFound, problem.TypeNotFound, "Resource not found.", "")
	case errors.Is(err, ErrGraceOutOfRange):
		writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation, "Validation failed.", "grace_period_seconds out of range")
	case errors.Is(err, ErrNotRotatable):
		writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation, "Validation failed.", "api key is not in a rotatable state")
	case errors.Is(err, ErrInvalidCIDR), errors.Is(err, ErrInvalidInput):
		// Strip the wrapped error chain to a short human detail.
		writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation, "Validation failed.", trimErrPrefix(err.Error()))
	default:
		writeProblem(w, r, http.StatusInternalServerError, problem.TypeURI+"internal", "Unexpected error.", "")
	}
}

func trimErrPrefix(s string) string {
	if i := strings.Index(s, ": "); i >= 0 {
		return s[i+2:]
	}
	return s
}
