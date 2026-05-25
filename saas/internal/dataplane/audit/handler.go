package audit

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/problem"
)

// Handler exposes the data-plane audit endpoints (AGENTS.md §8.6). The
// surface is read-only; new rows enter the table exclusively through
// the outbox subscriber.
//
// Phase 9 documented the rationale for using raw chi routes instead of
// the generated StrictServerInterface — see apikeys/handler.go header.
// Phase 10 follows the same convention.
type Handler struct {
	svc *Service
}

// NewHandler builds a Handler over svc.
func NewHandler(svc *Service) *Handler {
	return &Handler{svc: svc}
}

// Mount registers the read endpoints on r. The export endpoint is
// idempotent (no state mutated) so it shares the read-side
// AssertTenant gate.
func (h *Handler) Mount(r chi.Router) {
	r.Get("/v1/tenants/{tenant_id}/audit-events", h.list)
	r.Get("/v1/audit-events/{audit_event_id}", h.get)
	r.Post("/v1/audit-events/export", h.export)
}

// ---------------------------------------------------------------------
// Handler bodies
// ---------------------------------------------------------------------

func (h *Handler) list(w http.ResponseWriter, r *http.Request) {
	tenantID := chi.URLParam(r, "tenant_id")
	filter := ListFilter{
		TenantID:     tenantID,
		Action:       r.URL.Query().Get("action"),
		ResourceType: r.URL.Query().Get("resource_type"),
		ResourceID:   r.URL.Query().Get("resource_id"),
		ActorID:      r.URL.Query().Get("actor_id"),
		Limit:        parseLimit(r.URL.Query().Get("limit")),
	}
	if v := r.URL.Query().Get("occurred_after"); v != "" {
		t, err := time.Parse(time.RFC3339Nano, v)
		if err != nil {
			writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation,
				"Validation failed.", "occurred_after must be RFC3339")
			return
		}
		filter.OccurredFrom = t
	}
	if v := r.URL.Query().Get("occurred_before"); v != "" {
		t, err := time.Parse(time.RFC3339Nano, v)
		if err != nil {
			writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation,
				"Validation failed.", "occurred_before must be RFC3339")
			return
		}
		filter.OccurredTo = t
	}
	events, hasMore, err := h.svc.List(r.Context(), filter)
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	resp := struct {
		Data       []map[string]any `json:"data"`
		Pagination struct {
			HasMore bool `json:"has_more"`
		} `json:"pagination"`
	}{Data: make([]map[string]any, 0, len(events))}
	resp.Pagination.HasMore = hasMore
	for _, e := range events {
		resp.Data = append(resp.Data, eventToWire(e))
	}
	writeJSON(w, http.StatusOK, resp)
}

func (h *Handler) get(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := auth.TenantFromContext(r.Context())
	if !ok {
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized,
			"Missing or invalid bearer token / API key.", "")
		return
	}
	id := chi.URLParam(r, "audit_event_id")
	e, err := h.svc.Get(r.Context(), tenantID, id)
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, struct {
		Data map[string]any `json:"data"`
	}{Data: eventToWire(e)})
}

func (h *Handler) export(w http.ResponseWriter, r *http.Request) {
	tenantID, ok := auth.TenantFromContext(r.Context())
	if !ok {
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized,
			"Missing or invalid bearer token / API key.", "")
		return
	}
	var req struct {
		TenantID       string `json:"tenant_id"`
		Action         string `json:"action"`
		ResourceType   string `json:"resource_type"`
		ResourceID     string `json:"resource_id"`
		ActorID        string `json:"actor_id"`
		Format         string `json:"format"`
		OccurredAfter  string `json:"occurred_after"`
		OccurredBefore string `json:"occurred_before"`
		Limit          int    `json:"limit"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation,
			"Validation failed.", "request body must be JSON")
		return
	}
	if req.TenantID == "" {
		req.TenantID = tenantID
	}
	filter := ListFilter{
		TenantID:     req.TenantID,
		Action:       req.Action,
		ResourceType: req.ResourceType,
		ResourceID:   req.ResourceID,
		ActorID:      req.ActorID,
		Limit:        req.Limit,
	}
	if req.OccurredAfter != "" {
		t, err := time.Parse(time.RFC3339Nano, req.OccurredAfter)
		if err != nil {
			writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation,
				"Validation failed.", "occurred_after must be RFC3339")
			return
		}
		filter.OccurredFrom = t
	}
	if req.OccurredBefore != "" {
		t, err := time.Parse(time.RFC3339Nano, req.OccurredBefore)
		if err != nil {
			writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation,
				"Validation failed.", "occurred_before must be RFC3339")
			return
		}
		filter.OccurredTo = t
	}
	format := ExportFormat(req.Format)
	if format == "" {
		format = ExportFormatJSON
	}
	body, contentType, err := h.svc.Export(r.Context(), filter, format)
	if err != nil {
		writeServiceError(w, r, err)
		return
	}
	w.Header().Set("Content-Type", contentType)
	if format == ExportFormatCSV {
		w.Header().Set("Content-Disposition", `attachment; filename="audit-events.csv"`)
	}
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

// ---------------------------------------------------------------------
// helpers — mirror apikeys/handler.go for consistency
// ---------------------------------------------------------------------

func parseLimit(s string) int {
	if s == "" {
		return 25
	}
	n, err := strconv.Atoi(s)
	if err != nil || n < 1 {
		return 25
	}
	if n > 200 {
		return 200
	}
	return n
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

func writeServiceError(w http.ResponseWriter, r *http.Request, err error) {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		writeProblem(w, r, http.StatusUnauthorized, problem.TypeUnauthorized,
			"Missing or invalid bearer token / API key.", "")
	case errors.Is(err, auth.ErrCrossTenant):
		writeProblem(w, r, http.StatusForbidden, problem.TypeCrossTenant,
			"Cross-tenant access denied.", "")
	case errors.Is(err, ErrNotFound):
		writeProblem(w, r, http.StatusNotFound, problem.TypeNotFound,
			"Resource not found.", "")
	case errors.Is(err, ErrExportTooLarge):
		writeProblem(w, r, http.StatusRequestEntityTooLarge, problem.TypeValidation,
			"Export exceeds sync size budget.", "use async export (v1 roadmap)")
	case errors.Is(err, ErrInvalidInput):
		writeProblem(w, r, http.StatusUnprocessableEntity, problem.TypeValidation,
			"Validation failed.", err.Error())
	default:
		writeProblem(w, r, http.StatusInternalServerError, problem.TypeURI+"internal",
			"Unexpected error.", "")
	}
}
