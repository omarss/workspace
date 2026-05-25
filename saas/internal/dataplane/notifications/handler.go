package notifications

import (
	"context"
	"errors"
	"net/http"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/cursor"
	"github.com/omarss/saas/internal/platform/etag"
	"github.com/omarss/saas/internal/platform/problem"
)

// Handler is the HTTP-facing adapter for the notifications module. It
// implements the relevant subset of the StrictServerInterface; the
// dataplane main binary composes this handler alongside tenancy +
// identity (CONVENTIONS.md §3).
type Handler struct {
	svc *Service
}

// NewHandler wires a Handler over the notifications service.
func NewHandler(svc *Service) *Handler { return &Handler{svc: svc} }

// Service returns the wrapped service.
func (h *Handler) Service() *Service { return h.svc }

// ---------------------------------------------------------------------------
// /v1/notification-channels
// ---------------------------------------------------------------------------

// ListNotificationChannels handles GET /v1/notification-channels.
func (h *Handler) ListNotificationChannels(ctx context.Context, req httpapi.ListNotificationChannelsRequestObject) (httpapi.ListNotificationChannelsResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return listChannelsUnauthorized(), nil
	}
	limit := 25
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	chs, err := h.svc.ListChannels(ctx, tenantID, limit)
	if err != nil {
		if errors.Is(err, auth.ErrUnauthorized) {
			return listChannelsUnauthorized(), nil
		}
		return nil, err
	}
	out := httpapi.NotificationChannelListResponse{Data: make([]httpapi.NotificationChannel, 0, len(chs))}
	for _, c := range chs {
		out.Data = append(out.Data, toAPIChannel(c))
	}
	return httpapi.ListNotificationChannels200JSONResponse(out), nil
}

// CreateNotificationChannel handles POST /v1/notification-channels.
func (h *Handler) CreateNotificationChannel(ctx context.Context, req httpapi.CreateNotificationChannelRequestObject) (httpapi.CreateNotificationChannelResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return createChannelUnauthorized(), nil
	}
	if req.Body == nil {
		return createChannelProblem422("request body required"), nil
	}
	in := CreateChannelInput{
		Provider: ChannelProvider(req.Body.Provider),
		Name:     req.Body.Name,
	}
	if req.Body.Config != nil {
		in.Config = *req.Body.Config
	}
	if req.Body.IsDefaultFor != nil {
		for _, v := range *req.Body.IsDefaultFor {
			in.IsDefaultFor = append(in.IsDefaultFor, string(v))
		}
	}
	if req.Body.Credentials != nil {
		in.Credentials = bundleFromAPI(*req.Body.Credentials)
	}
	ch, err := h.svc.CreateChannel(ctx, tenantID, in)
	if err != nil {
		return createChannelError(err), nil
	}
	etagStr := ch.ETag()
	location := "/v1/notification-channels/" + ch.ID
	return httpapi.CreateNotificationChannel201JSONResponse{
		Headers: httpapi.CreateNotificationChannel201ResponseHeaders{ETag: &etagStr, Location: &location},
		Body:    httpapi.NotificationChannelResponse{Data: toAPIChannel(ch)},
	}, nil
}

// GetNotificationChannel handles GET /v1/notification-channels/{channel_id}.
func (h *Handler) GetNotificationChannel(ctx context.Context, req httpapi.GetNotificationChannelRequestObject) (httpapi.GetNotificationChannelResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return getChannelUnauthorized(), nil
	}
	ch, err := h.svc.GetChannel(ctx, tenantID, req.ChannelId)
	if err != nil {
		return getChannelError(err), nil
	}
	etagStr := ch.ETag()
	return httpapi.GetNotificationChannel200JSONResponse{
		Headers: httpapi.GetNotificationChannel200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.NotificationChannelResponse{Data: toAPIChannel(ch)},
	}, nil
}

// UpdateNotificationChannel handles PATCH /v1/notification-channels/{channel_id}.
func (h *Handler) UpdateNotificationChannel(ctx context.Context, req httpapi.UpdateNotificationChannelRequestObject) (httpapi.UpdateNotificationChannelResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return updateChannelUnauthorized(), nil
	}
	if req.Body == nil {
		return updateChannelProblem422("validation-error", "request body required"), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return updateChannelProblem412("malformed If-Match header"), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	patch := ChannelPatch{
		Name: req.Body.Name,
	}
	if req.Body.Status != nil {
		st := ChannelStatus(*req.Body.Status)
		patch.Status = &st
	}
	if req.Body.IsDefaultFor != nil {
		patch.PatchDefaults = true
		for _, v := range *req.Body.IsDefaultFor {
			patch.IsDefaultFor = append(patch.IsDefaultFor, string(v))
		}
	}
	if req.Body.Config != nil {
		patch.PatchConfig = true
		patch.Config = *req.Body.Config
	}
	ch, err := h.svc.UpdateChannel(ctx, tenantID, req.ChannelId, expected, patch)
	if err != nil {
		return updateChannelError(err), nil
	}
	etagStr := ch.ETag()
	return httpapi.UpdateNotificationChannel200JSONResponse{
		Headers: httpapi.UpdateNotificationChannel200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.NotificationChannelResponse{Data: toAPIChannel(ch)},
	}, nil
}

// DeleteNotificationChannel handles DELETE /v1/notification-channels/{channel_id}.
func (h *Handler) DeleteNotificationChannel(ctx context.Context, req httpapi.DeleteNotificationChannelRequestObject) (httpapi.DeleteNotificationChannelResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return deleteChannelUnauthorized(), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return deleteChannelProblem412("malformed If-Match header"), nil //nolint:nilerr // intentionally surfaces as 412 problem response
	}
	if err := h.svc.DeleteChannel(ctx, tenantID, req.ChannelId, expected); err != nil {
		return deleteChannelError(err), nil
	}
	return httpapi.DeleteNotificationChannel204Response{}, nil
}

// RotateNotificationChannelCredentials handles POST
// /v1/notification-channels/{channel_id}/rotate-credentials.
func (h *Handler) RotateNotificationChannelCredentials(ctx context.Context, req httpapi.RotateNotificationChannelCredentialsRequestObject) (httpapi.RotateNotificationChannelCredentialsResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return rotateChannelUnauthorized(), nil
	}
	if req.Body == nil {
		return rotateChannelProblem422("validation-error", "request body required"), nil
	}
	bundle := bundleFromAPI(req.Body.Credentials)
	ch, err := h.svc.RotateChannelCredentials(ctx, tenantID, req.ChannelId, bundle)
	if err != nil {
		return rotateChannelError(err), nil
	}
	etagStr := ch.ETag()
	return httpapi.RotateNotificationChannelCredentials200JSONResponse{
		Headers: httpapi.RotateNotificationChannelCredentials200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.NotificationChannelResponse{Data: toAPIChannel(ch)},
	}, nil
}

// ---------------------------------------------------------------------------
// /v1/notification-workflows
// ---------------------------------------------------------------------------

// ListNotificationWorkflows handles GET /v1/notification-workflows.
func (h *Handler) ListNotificationWorkflows(ctx context.Context, _ httpapi.ListNotificationWorkflowsRequestObject) (httpapi.ListNotificationWorkflowsResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return listWorkflowsUnauthorized(), nil
	}
	wfs, err := h.svc.ListWorkflows(ctx, tenantID)
	if err != nil {
		if errors.Is(err, auth.ErrUnauthorized) {
			return listWorkflowsUnauthorized(), nil
		}
		return nil, err
	}
	out := httpapi.NotificationWorkflowListResponse{Data: make([]httpapi.NotificationWorkflow, 0, len(wfs))}
	for _, w := range wfs {
		out.Data = append(out.Data, toAPIWorkflow(w))
	}
	return httpapi.ListNotificationWorkflows200JSONResponse(out), nil
}

// UpdateNotificationWorkflow handles PATCH /v1/notification-workflows/{workflow_id}.
func (h *Handler) UpdateNotificationWorkflow(ctx context.Context, req httpapi.UpdateNotificationWorkflowRequestObject) (httpapi.UpdateNotificationWorkflowResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return updateWorkflowUnauthorized(), nil
	}
	if req.Body == nil {
		return updateWorkflowProblem422("request body required"), nil
	}
	patch := WorkflowPatch{
		NovuWorkflowID: req.Body.NovuWorkflowId,
		Description:    req.Body.Description,
	}
	wf, err := h.svc.UpdateWorkflow(ctx, tenantID, req.WorkflowId, patch)
	if err != nil {
		return updateWorkflowError(err), nil
	}
	return httpapi.UpdateNotificationWorkflow200JSONResponse(httpapi.NotificationWorkflowResponse{Data: toAPIWorkflow(wf)}), nil
}

// RegisterNotificationWorkflow handles POST /v1/notification-workflows.
func (h *Handler) RegisterNotificationWorkflow(ctx context.Context, req httpapi.RegisterNotificationWorkflowRequestObject) (httpapi.RegisterNotificationWorkflowResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return registerWorkflowUnauthorized(), nil
	}
	if req.Body == nil {
		return registerWorkflowProblem422("request body required"), nil
	}
	in := RegisterWorkflowInput{
		Name:           req.Body.Name,
		NovuWorkflowID: req.Body.NovuWorkflowId,
	}
	if req.Body.Description != nil {
		in.Description = *req.Body.Description
	}
	wf, err := h.svc.RegisterWorkflow(ctx, tenantID, in)
	if err != nil {
		return registerWorkflowError(err), nil
	}
	return httpapi.RegisterNotificationWorkflow201JSONResponse(httpapi.NotificationWorkflowResponse{Data: toAPIWorkflow(wf)}), nil
}

// ---------------------------------------------------------------------------
// /v1/notifications
// ---------------------------------------------------------------------------

// ListNotifications handles GET /v1/notifications.
func (h *Handler) ListNotifications(ctx context.Context, req httpapi.ListNotificationsRequestObject) (httpapi.ListNotificationsResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return listNotificationsUnauthorized(), nil
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
				p := problem.New("cursor-gone", "Cursor schema version is no longer supported.", http.StatusGone, "", "/v1/notifications")
				return httpapi.ListNotifications410ApplicationProblemPlusJSONResponse{
					CursorGoneApplicationProblemPlusJSONResponse: httpapi.CursorGoneApplicationProblemPlusJSONResponse(toAPIProblem(p)),
				}, nil
			}
			return listNotificationsUnauthorized(), nil
		}
		cur = &ListCursor{QueuedAt: c.CreatedAt, ID: c.ID}
	}
	notifs, hasMore, err := h.svc.ListNotifications(ctx, tenantID, limit, cur)
	if err != nil {
		if errors.Is(err, auth.ErrUnauthorized) {
			return listNotificationsUnauthorized(), nil
		}
		return nil, err
	}
	resp := httpapi.NotificationListResponse{
		Data:       make([]httpapi.Notification, 0, len(notifs)),
		Pagination: httpapi.Pagination{HasMore: hasMore},
	}
	for _, n := range notifs {
		resp.Data = append(resp.Data, toAPINotification(n))
	}
	if hasMore && len(notifs) > 0 {
		last := notifs[len(notifs)-1]
		next := cursor.Encode(cursor.Cursor{CreatedAt: last.QueuedAt, ID: last.ID})
		resp.Pagination.NextCursor = &next
	}
	return httpapi.ListNotifications200JSONResponse(resp), nil
}

// SendNotification handles POST /v1/notifications/send.
func (h *Handler) SendNotification(ctx context.Context, req httpapi.SendNotificationRequestObject) (httpapi.SendNotificationResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return sendNotificationUnauthorized(), nil
	}
	if req.Body == nil {
		return sendNotificationProblem422("validation-error", "request body required"), nil
	}
	sendReq := SendRequest{
		WorkflowName: req.Body.WorkflowName,
		ToUserID:     req.Body.To.UserId,
	}
	if req.Body.Payload != nil {
		sendReq.Payload = *req.Body.Payload
	}
	res, err := h.svc.Send(ctx, tenantID, sendReq)
	if err != nil {
		return sendNotificationError(err), nil
	}
	return httpapi.SendNotification202JSONResponse(httpapi.NotificationResponse{Data: toAPINotification(res.Notification)}), nil
}

// GetNotification handles GET /v1/notifications/{notification_id}.
func (h *Handler) GetNotification(ctx context.Context, req httpapi.GetNotificationRequestObject) (httpapi.GetNotificationResponseObject, error) {
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return getNotificationUnauthorized(), nil
	}
	n, err := h.svc.GetNotification(ctx, tenantID, req.NotificationId)
	if err != nil {
		return getNotificationError(err), nil
	}
	return httpapi.GetNotification200JSONResponse(httpapi.NotificationResponse{Data: toAPINotification(n)}), nil
}

// ---------------------------------------------------------------------------
// mapping helpers
// ---------------------------------------------------------------------------

func toAPIChannel(c Channel) httpapi.NotificationChannel {
	out := httpapi.NotificationChannel{
		Id:                 c.ID,
		Object:             httpapi.NotificationChannelObjectNotificationChannel,
		Provider:           httpapi.NotificationChannelProvider(c.Provider),
		Name:               c.Name,
		Status:             httpapi.NotificationChannelStatus(c.Status),
		CredentialsPresent: c.HasSecrets(),
		Etag:               c.ETag(),
		CreatedAt:          c.CreatedAt,
		UpdatedAt:          c.UpdatedAt,
	}
	if len(c.Config) > 0 {
		cfg := c.Config
		out.Config = &cfg
	}
	if len(c.IsDefaultFor) > 0 {
		defaults := make([]httpapi.NotificationChannelIsDefaultFor, 0, len(c.IsDefaultFor))
		for _, v := range c.IsDefaultFor {
			defaults = append(defaults, httpapi.NotificationChannelIsDefaultFor(v))
		}
		out.IsDefaultFor = &defaults
	}
	if c.LastRotatedAt != nil {
		t := *c.LastRotatedAt
		out.LastRotatedAt = &t
	}
	return out
}

func toAPIWorkflow(w Workflow) httpapi.NotificationWorkflow {
	out := httpapi.NotificationWorkflow{
		Id:             w.ID,
		Object:         httpapi.NotificationWorkflowObject("notification_workflow"),
		Name:           w.Name,
		NovuWorkflowId: w.NovuWorkflowID,
		CreatedAt:      w.CreatedAt,
	}
	if w.Description != "" {
		d := w.Description
		out.Description = &d
	}
	return out
}

func toAPINotification(n Notification) httpapi.Notification {
	out := httpapi.Notification{
		Id:                n.ID,
		Object:            httpapi.NotificationObject("notification"),
		TenantId:          n.TenantID,
		WorkflowName:      n.WorkflowName,
		ToUserId:          n.ToUserID,
		Status:            httpapi.NotificationStatus(n.Status),
		QueuedAt:          n.QueuedAt,
		SentAt:            n.SentAt,
		DeliveredAt:       n.DeliveredAt,
		FailedAt:          n.FailedAt,
		FailureReason:     n.FailureReason,
		NovuTransactionId: n.NovuTransactionID,
	}
	return out
}

// bundleFromAPI converts the OpenAPI-generated CredentialsBundle into the
// domain CredentialsBundle. The conversion is lossless — every field has
// a 1:1 mapping.
func bundleFromAPI(in httpapi.CredentialsBundle) CredentialsBundle {
	out := CredentialsBundle{}
	if in.Smtp != nil {
		out.SMTP = &SMTPCredentials{
			Username: in.Smtp.Username,
			Password: in.Smtp.Password,
		}
	}
	if in.Sendgrid != nil {
		out.SendGrid = &SendGridCredentials{APIKey: in.Sendgrid.ApiKey}
	}
	if in.Ses != nil {
		out.SES = &SESCredentials{
			AccessKeyID:     in.Ses.AccessKeyId,
			SecretAccessKey: in.Ses.SecretAccessKey,
		}
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
// error translation — one block per endpoint to match identity's style
// ---------------------------------------------------------------------------

const (
	pathChannels      = "/v1/notification-channels"
	pathWorkflows     = "/v1/notification-workflows"
	pathNotifications = "/v1/notifications"
)

func listChannelsUnauthorized() httpapi.ListNotificationChannels401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathChannels)
	return httpapi.ListNotificationChannels401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createChannelUnauthorized() httpapi.CreateNotificationChannel401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathChannels)
	return httpapi.CreateNotificationChannel401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createChannelProblem422(detail string) httpapi.CreateNotificationChannel422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, pathChannels)
	return httpapi.CreateNotificationChannel422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createChannelError(err error) httpapi.CreateNotificationChannelResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return createChannelUnauthorized()
	case errors.Is(err, ErrNameTaken):
		return createChannelProblem422("channel name already taken")
	case errors.Is(err, ErrInvalidProvider):
		return createChannelProblem422("invalid channel provider")
	case errors.Is(err, ErrInvalidCredentials):
		return createChannelProblem422(err.Error())
	case errors.Is(err, ErrInvalidInput):
		return createChannelProblem422("invalid input")
	default:
		return createChannelProblem422("create failed")
	}
}

func getChannelUnauthorized() httpapi.GetNotificationChannel401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathChannels)
	return httpapi.GetNotificationChannel401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func getChannelError(err error) httpapi.GetNotificationChannelResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return getChannelUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", pathChannels)
		return httpapi.GetNotificationChannel403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", pathChannels)
		return httpapi.GetNotificationChannel404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateChannelUnauthorized() httpapi.UpdateNotificationChannel401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathChannels)
	return httpapi.UpdateNotificationChannel401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateChannelProblem422(slug, detail string) httpapi.UpdateNotificationChannel422ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, "Validation failed.", http.StatusUnprocessableEntity, detail, pathChannels)
	return httpapi.UpdateNotificationChannel422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateChannelProblem412(detail string) httpapi.UpdateNotificationChannel412ApplicationProblemPlusJSONResponse {
	p := problem.New("precondition-failed", "Precondition failed.", http.StatusPreconditionFailed, detail, pathChannels)
	return httpapi.UpdateNotificationChannel412ApplicationProblemPlusJSONResponse{
		PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateChannelError(err error) httpapi.UpdateNotificationChannelResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return updateChannelUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", pathChannels)
		return httpapi.UpdateNotificationChannel403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return updateChannelProblem412("stale or missing If-Match")
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", pathChannels)
		return httpapi.UpdateNotificationChannel404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidInput):
		return updateChannelProblem422("validation-error", "invalid input")
	default:
		return updateChannelProblem422("validation-error", "update failed")
	}
}

func deleteChannelUnauthorized() httpapi.DeleteNotificationChannel401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathChannels)
	return httpapi.DeleteNotificationChannel401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func deleteChannelProblem412(detail string) httpapi.DeleteNotificationChannel412ApplicationProblemPlusJSONResponse {
	p := problem.New("precondition-failed", "Precondition failed.", http.StatusPreconditionFailed, detail, pathChannels)
	return httpapi.DeleteNotificationChannel412ApplicationProblemPlusJSONResponse{
		PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func deleteChannelError(err error) httpapi.DeleteNotificationChannelResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return deleteChannelUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", pathChannels)
		return httpapi.DeleteNotificationChannel403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return deleteChannelProblem412("stale or missing If-Match")
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", pathChannels)
		return httpapi.DeleteNotificationChannel404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return deleteChannelProblem412("delete failed")
	}
}

func rotateChannelUnauthorized() httpapi.RotateNotificationChannelCredentials401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathChannels)
	return httpapi.RotateNotificationChannelCredentials401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func rotateChannelProblem422(slug, detail string) httpapi.RotateNotificationChannelCredentials422ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, "Validation failed.", http.StatusUnprocessableEntity, detail, pathChannels)
	return httpapi.RotateNotificationChannelCredentials422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func rotateChannelError(err error) httpapi.RotateNotificationChannelCredentialsResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return rotateChannelUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", pathChannels)
		return httpapi.RotateNotificationChannelCredentials403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", pathChannels)
		return httpapi.RotateNotificationChannelCredentials404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidCredentials):
		return rotateChannelProblem422("validation-error", err.Error())
	default:
		return rotateChannelProblem422("validation-error", "rotation failed")
	}
}

func listWorkflowsUnauthorized() httpapi.ListNotificationWorkflows401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathWorkflows)
	return httpapi.ListNotificationWorkflows401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func registerWorkflowUnauthorized() httpapi.RegisterNotificationWorkflow401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathWorkflows)
	return httpapi.RegisterNotificationWorkflow401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func registerWorkflowProblem422(detail string) httpapi.RegisterNotificationWorkflow422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, pathWorkflows)
	return httpapi.RegisterNotificationWorkflow422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func registerWorkflowError(err error) httpapi.RegisterNotificationWorkflowResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return registerWorkflowUnauthorized()
	case errors.Is(err, ErrNameTaken):
		return registerWorkflowProblem422("workflow name already taken")
	case errors.Is(err, ErrInvalidInput):
		return registerWorkflowProblem422("invalid input")
	default:
		return registerWorkflowProblem422("register failed")
	}
}

func updateWorkflowUnauthorized() httpapi.UpdateNotificationWorkflow401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathWorkflows)
	return httpapi.UpdateNotificationWorkflow401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateWorkflowProblem422(detail string) httpapi.UpdateNotificationWorkflow422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, pathWorkflows)
	return httpapi.UpdateNotificationWorkflow422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func updateWorkflowError(err error) httpapi.UpdateNotificationWorkflowResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return updateWorkflowUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", pathWorkflows)
		return httpapi.UpdateNotificationWorkflow403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", pathWorkflows)
		return httpapi.UpdateNotificationWorkflow404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidInput):
		return updateWorkflowProblem422("invalid input")
	default:
		return updateWorkflowProblem422("update failed")
	}
}

func listNotificationsUnauthorized() httpapi.ListNotifications401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathNotifications)
	return httpapi.ListNotifications401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func sendNotificationUnauthorized() httpapi.SendNotification401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathNotifications)
	return httpapi.SendNotification401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func sendNotificationProblem422(slug, detail string) httpapi.SendNotification422ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, "Validation failed.", http.StatusUnprocessableEntity, detail, pathNotifications)
	return httpapi.SendNotification422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func sendNotificationError(err error) httpapi.SendNotificationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return sendNotificationUnauthorized()
	case errors.Is(err, ErrWorkflowNotRegistered), errors.Is(err, ErrUserNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, err.Error(), pathNotifications)
		return httpapi.SendNotification404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidInput):
		return sendNotificationProblem422("validation-error", "invalid input")
	default:
		return sendNotificationProblem422("validation-error", "send failed")
	}
}

func getNotificationUnauthorized() httpapi.GetNotification401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", pathNotifications)
	return httpapi.GetNotification401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func getNotificationError(err error) httpapi.GetNotificationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return getNotificationUnauthorized()
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", pathNotifications)
		return httpapi.GetNotification403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", pathNotifications)
		return httpapi.GetNotification404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}
