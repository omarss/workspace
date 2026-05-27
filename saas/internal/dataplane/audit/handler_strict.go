package audit

import (
	"context"
	"errors"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/problem"
)

// StrictServer entries for the audit endpoints (AGENTS.md §8.6). Mirrors
// the Phase 9 apikeys pattern: the typed StrictServerInterface methods
// here are delegated to from cmd/dataplane/main.go's strictServer.
//
// The raw chi Mount() in handler.go remains as a thin local alternative
// used by the security_test.go HTTP tests — it exercises the same Service
// surface so behaviour is consistent across both paths.

// ListAuditEvents handles GET /v1/tenants/{tenant_id}/audit-events.
func (h *Handler) ListAuditEvents(ctx context.Context, req httpapi.ListAuditEventsRequestObject) (httpapi.ListAuditEventsResponseObject, error) {
	filter := ListFilter{TenantID: req.TenantId, Limit: 25}
	if req.Params.Limit != nil {
		filter.Limit = *req.Params.Limit
	}
	if req.Params.Action != nil {
		filter.Action = *req.Params.Action
	}
	if req.Params.ResourceType != nil {
		filter.ResourceType = *req.Params.ResourceType
	}
	if req.Params.ResourceId != nil {
		filter.ResourceID = *req.Params.ResourceId
	}
	if req.Params.ActorId != nil {
		filter.ActorID = *req.Params.ActorId
	}
	if req.Params.OccurredAfter != nil {
		filter.OccurredFrom = *req.Params.OccurredAfter
	}
	if req.Params.OccurredBefore != nil {
		filter.OccurredTo = *req.Params.OccurredBefore
	}
	events, hasMore, err := h.svc.List(ctx, filter)
	if err != nil {
		return listErrorResponse(err, "/v1/tenants/"+req.TenantId+"/audit-events"), nil
	}
	resp := httpapi.AuditEventListResponse{
		Data:       make([]httpapi.AuditEvent, 0, len(events)),
		Pagination: httpapi.Pagination{HasMore: hasMore},
	}
	for _, e := range events {
		resp.Data = append(resp.Data, toHTTPAuditEvent(e))
	}
	return httpapi.ListAuditEvents200JSONResponse(resp), nil
}

// GetAuditEvent handles GET /v1/audit-events/{audit_event_id}.
func (h *Handler) GetAuditEvent(ctx context.Context, req httpapi.GetAuditEventRequestObject) (httpapi.GetAuditEventResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return httpapi.GetAuditEvent401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(
				newProblem(401, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "", "/v1/audit-events/"+req.AuditEventId),
			),
		}, nil
	}
	e, err := h.svc.Get(ctx, tenantID, req.AuditEventId)
	if err != nil {
		switch {
		case errors.Is(err, ErrNotFound):
			return httpapi.GetAuditEvent404ApplicationProblemPlusJSONResponse{
				NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(
					newProblem(404, problem.TypeNotFound, "Resource not found.", "", "/v1/audit-events/"+req.AuditEventId),
				),
			}, nil
		case errors.Is(err, auth.ErrUnauthorized):
			return httpapi.GetAuditEvent401ApplicationProblemPlusJSONResponse{
				UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(
					newProblem(401, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "", "/v1/audit-events/"+req.AuditEventId),
				),
			}, nil
		case errors.Is(err, auth.ErrCrossTenant):
			return httpapi.GetAuditEvent403ApplicationProblemPlusJSONResponse{
				ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(
					newProblem(403, problem.TypeCrossTenant, "Cross-tenant access denied.", "", "/v1/audit-events/"+req.AuditEventId),
				),
			}, nil
		}
		return nil, err
	}
	wire := toHTTPAuditEvent(e)
	return httpapi.GetAuditEvent200JSONResponse(httpapi.AuditEventResponse{Data: wire}), nil
}

// ExportAuditEvents handles POST /v1/audit-events/export.
func (h *Handler) ExportAuditEvents(ctx context.Context, req httpapi.ExportAuditEventsRequestObject) (httpapi.ExportAuditEventsResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return httpapi.ExportAuditEvents401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(
				newProblem(401, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "", "/v1/audit-events/export"),
			),
		}, nil
	}
	body := req.Body
	if body == nil {
		body = &httpapi.ExportAuditEventsRequest{}
	}
	filter := ListFilter{TenantID: tenantID}
	if body.TenantId != nil && *body.TenantId != "" {
		filter.TenantID = *body.TenantId
	}
	if body.Action != nil {
		filter.Action = *body.Action
	}
	if body.ResourceType != nil {
		filter.ResourceType = *body.ResourceType
	}
	if body.ResourceId != nil {
		filter.ResourceID = *body.ResourceId
	}
	if body.ActorId != nil {
		filter.ActorID = *body.ActorId
	}
	if body.OccurredAfter != nil {
		filter.OccurredFrom = *body.OccurredAfter
	}
	if body.OccurredBefore != nil {
		filter.OccurredTo = *body.OccurredBefore
	}
	if body.Limit != nil {
		filter.Limit = *body.Limit
	}
	format := ExportFormatJSON
	if body.Format != nil {
		format = ExportFormat(*body.Format)
	}
	out, _, err := h.svc.Export(ctx, filter, format)
	if err != nil {
		switch {
		case errors.Is(err, auth.ErrCrossTenant):
			return httpapi.ExportAuditEvents403ApplicationProblemPlusJSONResponse{
				ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(
					newProblem(403, problem.TypeCrossTenant, "Cross-tenant access denied.", "", "/v1/audit-events/export"),
				),
			}, nil
		case errors.Is(err, auth.ErrUnauthorized):
			return httpapi.ExportAuditEvents401ApplicationProblemPlusJSONResponse{
				UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(
					newProblem(401, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "", "/v1/audit-events/export"),
				),
			}, nil
		case errors.Is(err, ErrExportTooLarge):
			return httpapi.ExportAuditEvents413ApplicationProblemPlusJSONResponse(
				newProblem(413, problem.TypeValidation, "Export exceeds sync size budget.", "use async export (v1 roadmap)", "/v1/audit-events/export"),
			), nil
		}
		return nil, err
	}
	if format == ExportFormatCSV {
		return httpapi.ExportAuditEvents200TextcsvResponse{
			Body:          bytesReader(out),
			ContentLength: int64(len(out)),
		}, nil
	}
	// JSON path — re-decode into the typed shape so the spec/wire match.
	var wire httpapi.AuditEventListResponse
	if err := unmarshalAuditList(out, &wire); err != nil {
		return nil, err
	}
	return httpapi.ExportAuditEvents200JSONResponse(wire), nil
}

// listErrorResponse maps a Service-level List error to the typed
// problem response.
func listErrorResponse(err error, instance string) httpapi.ListAuditEventsResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return httpapi.ListAuditEvents401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(
				newProblem(401, problem.TypeUnauthorized, "Missing or invalid bearer token / API key.", "", instance),
			),
		}
	case errors.Is(err, auth.ErrCrossTenant):
		return httpapi.ListAuditEvents403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(
				newProblem(403, problem.TypeCrossTenant, "Cross-tenant access denied.", "", instance),
			),
		}
	}
	// Generic 401 envelope is used as a catch-all to satisfy the typed
	// interface; the orchestrator-side log captures the real error.
	return httpapi.ListAuditEvents401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(
			newProblem(500, problem.TypeURI+"internal", "Unexpected error.", err.Error(), instance),
		),
	}
}

func toHTTPAuditEvent(e Event) httpapi.AuditEvent {
	var ipPtr, uaPtr, ridPtr, resIDPtr *string
	if e.IPAddress != "" {
		v := e.IPAddress
		ipPtr = &v
	}
	if e.UserAgent != "" {
		v := e.UserAgent
		uaPtr = &v
	}
	if e.RequestID != "" {
		v := e.RequestID
		ridPtr = &v
	}
	if e.ResourceID != "" {
		v := e.ResourceID
		resIDPtr = &v
	}
	var metaPtr *map[string]interface{}
	if e.Metadata != nil {
		m := e.Metadata
		metaPtr = &m
	}
	return httpapi.AuditEvent{
		Id:            e.ID,
		TenantId:      e.TenantID,
		ActorType:     httpapi.AuditEventActorType(e.ActorType),
		ActorId:       e.ActorID,
		Action:        e.Action,
		ResourceType:  e.ResourceType,
		ResourceId:    resIDPtr,
		OccurredAt:    e.OccurredAt.UTC(),
		IpAddress:     ipPtr,
		UserAgent:     uaPtr,
		RequestId:     ridPtr,
		Metadata:      metaPtr,
		PrevHash:      HexHash(e.PrevHash),
		RowHash:       HexHash(e.RowHash),
		ChainSequence: e.ChainSequence,
	}
}
