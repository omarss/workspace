package organizations

import (
	"context"
	"errors"
	"net/http"

	openapi_types "github.com/oapi-codegen/runtime/types"

	httpapi "github.com/omarss/saas/internal/dataplane/httpapi"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/cursor"
	"github.com/omarss/saas/internal/platform/etag"
	"github.com/omarss/saas/internal/platform/problem"
)

// Handler is the HTTP-facing adapter for the organizations module. It
// implements the relevant subset of the dataplane StrictServerInterface;
// cmd/dataplane/main.go composes it alongside the other modules
// (CONVENTIONS.md §3).
//
// The handler is intentionally thin: it translates generated request
// objects into application-level inputs, calls the service, and maps
// domain errors to RFC 9457 problem responses. All authorization is
// inside the service via auth.AssertTenant; tenant context is extracted
// from the principal (never headers).
type Handler struct {
	svc *Service
}

// NewHandler wires a Handler over the organizations service.
func NewHandler(svc *Service) *Handler { return &Handler{svc: svc} }

// Service returns the wrapped service.
func (h *Handler) Service() *Service { return h.svc }

// ---------------------------------------------------------------------------
// /v1/tenants/{tenant_id}/organizations
// ---------------------------------------------------------------------------

// ListOrganizations handles GET /v1/tenants/{tenant_id}/organizations.
func (h *Handler) ListOrganizations(ctx context.Context, req httpapi.ListOrganizationsRequestObject) (httpapi.ListOrganizationsResponseObject, error) {
	instance := "/v1/tenants/" + req.TenantId + "/organizations"
	if _, ok := auth.TenantFromContext(ctx); !ok {
		return listOrganizationsUnauthorized(instance), nil
	}
	limit := 25
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	var cur *OrgListCursor
	if req.Params.Cursor != nil && *req.Params.Cursor != "" {
		c, err := cursor.Decode(*req.Params.Cursor)
		if err != nil {
			if errors.Is(err, cursor.ErrVersionMismatch) {
				p := problem.New("cursor-gone", "Cursor schema version is no longer supported.", http.StatusGone, "", instance)
				return httpapi.ListOrganizations410ApplicationProblemPlusJSONResponse{
					CursorGoneApplicationProblemPlusJSONResponse: httpapi.CursorGoneApplicationProblemPlusJSONResponse(toAPIProblem(p)),
				}, nil
			}
			return listOrganizationsUnauthorized(instance), nil
		}
		cur = &OrgListCursor{CreatedAt: c.CreatedAt, ID: c.ID}
	}
	orgs, hasMore, err := h.svc.ListOrganizations(ctx, req.TenantId, limit, cur)
	if err != nil {
		return listOrganizationsError(err, instance), nil
	}
	resp := httpapi.OrganizationListResponse{
		Data:       make([]httpapi.Organization, 0, len(orgs)),
		Pagination: httpapi.Pagination{HasMore: hasMore},
	}
	for _, o := range orgs {
		resp.Data = append(resp.Data, toAPIOrganization(o))
	}
	if hasMore && len(orgs) > 0 {
		last := orgs[len(orgs)-1]
		next := cursor.Encode(cursor.Cursor{CreatedAt: last.CreatedAt, ID: last.ID})
		resp.Pagination.NextCursor = &next
	}
	return httpapi.ListOrganizations200JSONResponse(resp), nil
}

// CreateOrganization handles POST /v1/tenants/{tenant_id}/organizations.
func (h *Handler) CreateOrganization(ctx context.Context, req httpapi.CreateOrganizationRequestObject) (httpapi.CreateOrganizationResponseObject, error) {
	instance := "/v1/tenants/" + req.TenantId + "/organizations"
	if _, ok := auth.TenantFromContext(ctx); !ok {
		return createOrganizationUnauthorized(instance), nil
	}
	if req.Body == nil {
		return createOrganizationProblem422("request body required", instance), nil
	}
	in := CreateOrganizationInput{
		Slug: req.Body.Slug,
		Name: req.Body.Name,
	}
	if req.Body.Metadata != nil {
		in.Metadata = map[string]string(*req.Body.Metadata)
	}
	o, err := h.svc.CreateOrganization(ctx, req.TenantId, in)
	if err != nil {
		return createOrganizationError(err, instance), nil
	}
	etagStr := o.ETag()
	location := "/v1/organizations/" + o.ID
	return httpapi.CreateOrganization201JSONResponse{
		Headers: httpapi.CreateOrganization201ResponseHeaders{ETag: &etagStr, Location: &location},
		Body:    httpapi.OrganizationResponse{Data: toAPIOrganization(o)},
	}, nil
}

// GetOrganization handles GET /v1/organizations/{organization_id}.
func (h *Handler) GetOrganization(ctx context.Context, req httpapi.GetOrganizationRequestObject) (httpapi.GetOrganizationResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return getOrganizationUnauthorized(instance), nil
	}
	o, err := h.svc.GetOrganization(ctx, tenantID, req.OrganizationId)
	if err != nil {
		return getOrganizationError(err, instance), nil
	}
	etagStr := o.ETag()
	return httpapi.GetOrganization200JSONResponse{
		Headers: httpapi.GetOrganization200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.OrganizationResponse{Data: toAPIOrganization(o)},
	}, nil
}

// UpdateOrganization handles PATCH /v1/organizations/{organization_id}.
func (h *Handler) UpdateOrganization(ctx context.Context, req httpapi.UpdateOrganizationRequestObject) (httpapi.UpdateOrganizationResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return updateOrganizationProblem(http.StatusUnauthorized, "unauthorized", "missing tenant context", instance), nil
	}
	if req.Body == nil {
		return updateOrganizationProblem(http.StatusUnprocessableEntity, "validation-error", "request body required", instance), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return updateOrganizationProblem(http.StatusPreconditionFailed, "precondition-failed", "malformed If-Match header", instance), nil //nolint:nilerr // intentional 412 mapping
	}
	patch := OrgPatch{Name: req.Body.Name}
	if req.Body.Status != nil {
		st := OrganizationStatus(*req.Body.Status)
		patch.Status = &st
	}
	if req.Body.Metadata != nil {
		patch.PatchMetadata = true
		patch.Metadata = map[string]string(*req.Body.Metadata)
	}
	o, err := h.svc.UpdateOrganization(ctx, tenantID, req.OrganizationId, expected, patch)
	if err != nil {
		return updateOrganizationError(err, instance), nil
	}
	etagStr := o.ETag()
	return httpapi.UpdateOrganization200JSONResponse{
		Headers: httpapi.UpdateOrganization200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.OrganizationResponse{Data: toAPIOrganization(o)},
	}, nil
}

// DeleteOrganization handles DELETE /v1/organizations/{organization_id}.
func (h *Handler) DeleteOrganization(ctx context.Context, req httpapi.DeleteOrganizationRequestObject) (httpapi.DeleteOrganizationResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return deleteOrganizationProblem(http.StatusUnauthorized, "unauthorized", "missing tenant context", instance), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return deleteOrganizationProblem(http.StatusPreconditionFailed, "precondition-failed", "malformed If-Match header", instance), nil //nolint:nilerr // intentional 412 mapping
	}
	if err := h.svc.DeleteOrganization(ctx, tenantID, req.OrganizationId, expected); err != nil {
		return deleteOrganizationError(err, instance), nil
	}
	return httpapi.DeleteOrganization204Response{}, nil
}

// ---------------------------------------------------------------------------
// /v1/organizations/{organization_id}/members
// ---------------------------------------------------------------------------

// ListMembers handles GET /v1/organizations/{organization_id}/members.
func (h *Handler) ListMembers(ctx context.Context, req httpapi.ListMembersRequestObject) (httpapi.ListMembersResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId + "/members"
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return listMembersUnauthorized(instance), nil
	}
	limit := 25
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	var cur *MemberListCursor
	if req.Params.Cursor != nil && *req.Params.Cursor != "" {
		c, err := cursor.Decode(*req.Params.Cursor)
		if err != nil {
			if errors.Is(err, cursor.ErrVersionMismatch) {
				p := problem.New("cursor-gone", "Cursor schema version is no longer supported.", http.StatusGone, "", instance)
				return httpapi.ListMembers410ApplicationProblemPlusJSONResponse{
					CursorGoneApplicationProblemPlusJSONResponse: httpapi.CursorGoneApplicationProblemPlusJSONResponse(toAPIProblem(p)),
				}, nil
			}
			return listMembersUnauthorized(instance), nil
		}
		cur = &MemberListCursor{JoinedAt: c.CreatedAt, ID: c.ID}
	}
	members, hasMore, err := h.svc.ListMembers(ctx, tenantID, req.OrganizationId, limit, cur)
	if err != nil {
		return listMembersError(err, instance), nil
	}
	resp := httpapi.MemberListResponse{
		Data:       make([]httpapi.Member, 0, len(members)),
		Pagination: httpapi.Pagination{HasMore: hasMore},
	}
	for _, m := range members {
		resp.Data = append(resp.Data, toAPIMember(m))
	}
	if hasMore && len(members) > 0 {
		last := members[len(members)-1]
		next := cursor.Encode(cursor.Cursor{CreatedAt: last.JoinedAt, ID: last.ID})
		resp.Pagination.NextCursor = &next
	}
	return httpapi.ListMembers200JSONResponse(resp), nil
}

// GetMember handles GET /v1/organizations/{organization_id}/members/{member_id}.
func (h *Handler) GetMember(ctx context.Context, req httpapi.GetMemberRequestObject) (httpapi.GetMemberResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId + "/members/" + req.MemberId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return getMemberUnauthorized(instance), nil
	}
	m, err := h.svc.GetMember(ctx, tenantID, req.MemberId)
	if err != nil {
		return getMemberError(err, instance), nil
	}
	etagStr := m.ETag()
	return httpapi.GetMember200JSONResponse{
		Headers: httpapi.GetMember200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.MemberResponse{Data: toAPIMember(m)},
	}, nil
}

// UpdateMember handles PATCH /v1/organizations/{organization_id}/members/{member_id}.
func (h *Handler) UpdateMember(ctx context.Context, req httpapi.UpdateMemberRequestObject) (httpapi.UpdateMemberResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId + "/members/" + req.MemberId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return updateMemberProblem(http.StatusUnauthorized, "unauthorized", "missing tenant context", instance), nil
	}
	if req.Body == nil {
		return updateMemberProblem(http.StatusUnprocessableEntity, "validation-error", "request body required", instance), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return updateMemberProblem(http.StatusPreconditionFailed, "precondition-failed", "malformed If-Match header", instance), nil //nolint:nilerr // intentional 412 mapping
	}
	m, err := h.svc.UpdateMemberRole(ctx, tenantID, req.MemberId, expected, req.Body.RoleId)
	if err != nil {
		return updateMemberError(err, instance), nil
	}
	etagStr := m.ETag()
	return httpapi.UpdateMember200JSONResponse{
		Headers: httpapi.UpdateMember200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.MemberResponse{Data: toAPIMember(m)},
	}, nil
}

// RemoveMember handles DELETE /v1/organizations/{organization_id}/members/{member_id}.
func (h *Handler) RemoveMember(ctx context.Context, req httpapi.RemoveMemberRequestObject) (httpapi.RemoveMemberResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId + "/members/" + req.MemberId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return removeMemberProblem(http.StatusUnauthorized, "unauthorized", "missing tenant context", instance), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		return removeMemberProblem(http.StatusPreconditionFailed, "precondition-failed", "malformed If-Match header", instance), nil //nolint:nilerr // intentional 412 mapping
	}
	if err := h.svc.RemoveMember(ctx, tenantID, req.MemberId, expected); err != nil {
		return removeMemberError(err, instance), nil
	}
	return httpapi.RemoveMember204Response{}, nil
}

// ---------------------------------------------------------------------------
// /v1/organizations/{organization_id}/invitations + /v1/invitations/...
// ---------------------------------------------------------------------------

// CreateInvitation handles POST /v1/organizations/{organization_id}/invitations.
// Returns 202 with the one-time plaintext token + accept URL. Subsequent
// reads of the invitation return only token_prefix.
func (h *Handler) CreateInvitation(ctx context.Context, req httpapi.CreateInvitationRequestObject) (httpapi.CreateInvitationResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId + "/invitations"
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return createInvitationUnauthorized(instance), nil
	}
	if req.Body == nil {
		return createInvitationProblem422("request body required", instance), nil
	}
	in := CreateInvitationInput{
		InviteeEmail:   string(req.Body.InviteeEmail),
		ProposedRoleID: req.Body.ProposedRoleId,
	}
	if req.Body.ExpiresInSeconds != nil {
		v := int64(*req.Body.ExpiresInSeconds)
		in.ExpiresInSeconds = &v
	}
	inv, encodedToken, err := h.svc.CreateInvitation(ctx, tenantID, req.OrganizationId, in)
	if err != nil {
		return createInvitationError(err, instance), nil
	}
	apiInv := toAPIInvitation(inv)
	return httpapi.CreateInvitation202JSONResponse(httpapi.CreateInvitationResponse{
		Data:      apiInv,
		AcceptUrl: h.svc.buildAcceptURL(inv.ID, encodedToken),
		State:     encodedToken,
		ExpiresAt: inv.ExpiresAt,
	}), nil
}

// ListInvitations handles GET /v1/organizations/{organization_id}/invitations.
func (h *Handler) ListInvitations(ctx context.Context, req httpapi.ListInvitationsRequestObject) (httpapi.ListInvitationsResponseObject, error) {
	instance := "/v1/organizations/" + req.OrganizationId + "/invitations"
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return listInvitationsUnauthorized(instance), nil
	}
	limit := 25
	if req.Params.Limit != nil {
		limit = *req.Params.Limit
	}
	invs, err := h.svc.ListInvitations(ctx, tenantID, req.OrganizationId, limit)
	if err != nil {
		return listInvitationsError(err, instance), nil
	}
	resp := httpapi.InvitationListResponse{Data: make([]httpapi.Invitation, 0, len(invs))}
	for _, inv := range invs {
		resp.Data = append(resp.Data, toAPIInvitation(inv))
	}
	return httpapi.ListInvitations200JSONResponse(resp), nil
}

// GetInvitation handles GET /v1/invitations/{invitation_id}.
func (h *Handler) GetInvitation(ctx context.Context, req httpapi.GetInvitationRequestObject) (httpapi.GetInvitationResponseObject, error) {
	instance := "/v1/invitations/" + req.InvitationId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return getInvitationUnauthorized(instance), nil
	}
	inv, err := h.svc.GetInvitation(ctx, tenantID, req.InvitationId)
	if err != nil {
		return getInvitationError(err, instance), nil
	}
	etagStr := inv.ETag()
	return httpapi.GetInvitation200JSONResponse{
		Headers: httpapi.GetInvitation200ResponseHeaders{ETag: &etagStr},
		Body:    httpapi.InvitationResponse{Data: toAPIInvitation(inv)},
	}, nil
}

// RevokeInvitation handles DELETE /v1/invitations/{invitation_id}.
func (h *Handler) RevokeInvitation(ctx context.Context, req httpapi.RevokeInvitationRequestObject) (httpapi.RevokeInvitationResponseObject, error) {
	instance := "/v1/invitations/" + req.InvitationId
	tenantID, ok := auth.TenantFromContext(ctx)
	if !ok {
		return revokeInvitationUnauthorized(instance), nil
	}
	expected, parseErr := etag.Parse(req.Params.IfMatch)
	if parseErr != nil {
		p := problem.New("precondition-failed", "Precondition failed.", http.StatusPreconditionFailed, "malformed If-Match header", instance)
		resp := httpapi.RevokeInvitation412ApplicationProblemPlusJSONResponse{
			PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
		return resp, nil //nolint:nilerr // intentional: malformed If-Match maps to a 412 problem response
	}
	if err := h.svc.RevokeInvitation(ctx, tenantID, req.InvitationId, expected); err != nil {
		return revokeInvitationError(err, instance), nil
	}
	return httpapi.RevokeInvitation204Response{}, nil
}

// AcceptInvitation handles POST /v1/invitations/{invitation_id}/accept.
// Documented exception: the service consumes a token-bound invitation row
// whose tenant_id is constant-time-compared to the caller's JWT tenant.
func (h *Handler) AcceptInvitation(ctx context.Context, req httpapi.AcceptInvitationRequestObject) (httpapi.AcceptInvitationResponseObject, error) {
	instance := "/v1/invitations/" + req.InvitationId + "/accept"
	if _, ok := auth.PrincipalFromContext(ctx); !ok {
		return acceptInvitationUnauthorized(instance), nil
	}
	if req.Body == nil || req.Body.Token == "" {
		return acceptInvitationProblem422("validation-error", "request body required", instance), nil
	}
	m, err := h.svc.AcceptInvitation(ctx, req.Body.Token)
	if err != nil {
		return acceptInvitationError(err, instance), nil
	}
	return httpapi.AcceptInvitation200JSONResponse(httpapi.MemberResponse{Data: toAPIMember(m)}), nil
}

// ---------------------------------------------------------------------------
// mapping helpers
// ---------------------------------------------------------------------------

func toAPIOrganization(o Organization) httpapi.Organization {
	out := httpapi.Organization{
		Id:        o.ID,
		Object:    httpapi.OrganizationObject("organization"),
		TenantId:  o.TenantID,
		Slug:      o.Slug,
		Name:      o.Name,
		Status:    httpapi.OrganizationStatus(o.Status),
		CreatedAt: o.CreatedAt,
		UpdatedAt: o.UpdatedAt,
		Etag:      o.ETag(),
	}
	if len(o.Metadata) > 0 {
		m := httpapi.Metadata(o.Metadata)
		out.Metadata = &m
	}
	if o.DeletedAt != nil {
		t := *o.DeletedAt
		out.DeletedAt = &t
	}
	return out
}

func toAPIMember(m Member) httpapi.Member {
	out := httpapi.Member{
		Id:             m.ID,
		Object:         httpapi.MemberObject("member"),
		TenantId:       m.TenantID,
		OrganizationId: m.OrganizationID,
		UserId:         m.UserID,
		Status:         httpapi.MemberStatus(m.Status),
		JoinedAt:       m.JoinedAt,
		UpdatedAt:      m.UpdatedAt,
		RoleId:         m.RoleID,
		Etag:           m.ETag(),
	}
	if m.RemovedAt != nil {
		t := *m.RemovedAt
		out.RemovedAt = &t
	}
	return out
}

func toAPIInvitation(inv Invitation) httpapi.Invitation {
	out := httpapi.Invitation{
		Id:               inv.ID,
		Object:           httpapi.InvitationObject("invitation"),
		TenantId:         inv.TenantID,
		OrganizationId:   inv.OrganizationID,
		InviteeEmail:     openapi_types.Email(inv.InviteeEmail),
		TokenPrefix:      inv.TokenPrefix,
		Status:           httpapi.InvitationStatus(inv.Status),
		ExpiresAt:        inv.ExpiresAt,
		ProposedRoleId:   inv.ProposedRoleID,
		AcceptedAt:       inv.AcceptedAt,
		AcceptedByUserId: inv.AcceptedByUserID,
		RevokedAt:        inv.RevokedAt,
		RevokedByUserId:  inv.RevokedByUserID,
		CreatedAt:        inv.CreatedAt,
		UpdatedAt:        inv.UpdatedAt,
		Etag:             inv.ETag(),
	}
	if inv.InvitedByUserID != "" {
		v := inv.InvitedByUserID
		out.InvitedByUserId = &v
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
// error translation — one helper block per endpoint family
// ---------------------------------------------------------------------------

func listOrganizationsUnauthorized(instance string) httpapi.ListOrganizations401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.ListOrganizations401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func listOrganizationsError(err error, instance string) httpapi.ListOrganizationsResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return listOrganizationsUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.ListOrganizations403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return listOrganizationsUnauthorized(instance)
	}
}

func createOrganizationUnauthorized(instance string) httpapi.CreateOrganization401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.CreateOrganization401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createOrganizationProblem422(detail, instance string) httpapi.CreateOrganization422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, instance)
	return httpapi.CreateOrganization422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createOrganizationError(err error, instance string) httpapi.CreateOrganizationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return createOrganizationUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.CreateOrganization403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrMultiOrgDisabled):
		p := problem.New("multi-org-disabled", "Multi-organization mode is not enabled for this tenant.", http.StatusMethodNotAllowed, "", instance)
		return httpapi.CreateOrganization405ApplicationProblemPlusJSONResponse(toAPIProblem(p))
	case errors.Is(err, ErrSlugTaken):
		return createOrganizationProblem422("organization slug already taken", instance)
	case errors.Is(err, ErrInvalidInput):
		return createOrganizationProblem422("invalid organization input", instance)
	default:
		return createOrganizationProblem422("create failed", instance)
	}
}

func getOrganizationUnauthorized(instance string) httpapi.GetOrganization401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.GetOrganization401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func getOrganizationError(err error, instance string) httpapi.GetOrganizationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return getOrganizationUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.GetOrganization403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.GetOrganization404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateOrganizationProblem(status int, slug, detail, instance string) httpapi.UpdateOrganizationResponseObject {
	p := problem.New(slug, statusTitle(status), status, detail, instance)
	switch status {
	case http.StatusUnauthorized:
		return httpapi.UpdateOrganization401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case http.StatusPreconditionFailed:
		return httpapi.UpdateOrganization412ApplicationProblemPlusJSONResponse{
			PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return httpapi.UpdateOrganization422ApplicationProblemPlusJSONResponse{
			IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateOrganizationError(err error, instance string) httpapi.UpdateOrganizationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return updateOrganizationProblem(http.StatusUnauthorized, "unauthorized", "", instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.UpdateOrganization403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return updateOrganizationProblem(http.StatusPreconditionFailed, "precondition-failed", "stale or missing If-Match", instance)
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.UpdateOrganization404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidInput):
		return updateOrganizationProblem(http.StatusUnprocessableEntity, "validation-error", "invalid organization input", instance)
	default:
		return updateOrganizationProblem(http.StatusUnprocessableEntity, "validation-error", "update failed", instance)
	}
}

func deleteOrganizationProblem(status int, slug, detail, instance string) httpapi.DeleteOrganizationResponseObject {
	p := problem.New(slug, statusTitle(status), status, detail, instance)
	switch status {
	case http.StatusUnauthorized:
		return httpapi.DeleteOrganization401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case http.StatusPreconditionFailed:
		return httpapi.DeleteOrganization412ApplicationProblemPlusJSONResponse{
			PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return httpapi.DeleteOrganization422ApplicationProblemPlusJSONResponse{
			IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func deleteOrganizationError(err error, instance string) httpapi.DeleteOrganizationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return deleteOrganizationProblem(http.StatusUnauthorized, "unauthorized", "", instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.DeleteOrganization403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return deleteOrganizationProblem(http.StatusPreconditionFailed, "precondition-failed", "stale or missing If-Match", instance)
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.DeleteOrganization404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidInput):
		return deleteOrganizationProblem(http.StatusUnprocessableEntity, "validation-error", "cannot delete organization with active members", instance)
	default:
		return deleteOrganizationProblem(http.StatusUnprocessableEntity, "validation-error", "delete failed", instance)
	}
}

func listMembersUnauthorized(instance string) httpapi.ListMembers401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.ListMembers401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func listMembersError(err error, instance string) httpapi.ListMembersResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return listMembersUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.ListMembers403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.ListMembers404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.ListMembers404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func getMemberUnauthorized(instance string) httpapi.GetMember401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.GetMember401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func getMemberError(err error, instance string) httpapi.GetMemberResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return getMemberUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.GetMember403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.GetMember404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateMemberProblem(status int, slug, detail, instance string) httpapi.UpdateMemberResponseObject {
	p := problem.New(slug, statusTitle(status), status, detail, instance)
	switch status {
	case http.StatusUnauthorized:
		return httpapi.UpdateMember401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case http.StatusPreconditionFailed:
		return httpapi.UpdateMember412ApplicationProblemPlusJSONResponse{
			PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return httpapi.UpdateMember422ApplicationProblemPlusJSONResponse{
			IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func updateMemberError(err error, instance string) httpapi.UpdateMemberResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return updateMemberProblem(http.StatusUnauthorized, "unauthorized", "", instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.UpdateMember403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return updateMemberProblem(http.StatusPreconditionFailed, "precondition-failed", "stale or missing If-Match", instance)
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.UpdateMember404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidInput):
		return updateMemberProblem(http.StatusUnprocessableEntity, "validation-error", "invalid member input", instance)
	default:
		return updateMemberProblem(http.StatusUnprocessableEntity, "validation-error", "update failed", instance)
	}
}

func removeMemberProblem(status int, slug, detail, instance string) httpapi.RemoveMemberResponseObject {
	p := problem.New(slug, statusTitle(status), status, detail, instance)
	switch status {
	case http.StatusUnauthorized:
		return httpapi.RemoveMember401ApplicationProblemPlusJSONResponse{
			UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case http.StatusPreconditionFailed:
		return httpapi.RemoveMember412ApplicationProblemPlusJSONResponse{
			PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		return httpapi.RemoveMember404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func removeMemberError(err error, instance string) httpapi.RemoveMemberResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return removeMemberProblem(http.StatusUnauthorized, "unauthorized", "", instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.RemoveMember403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		return removeMemberProblem(http.StatusPreconditionFailed, "precondition-failed", "stale or missing If-Match", instance)
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.RemoveMember404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func createInvitationUnauthorized(instance string) httpapi.CreateInvitation401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.CreateInvitation401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createInvitationProblem422(detail, instance string) httpapi.CreateInvitation422ApplicationProblemPlusJSONResponse {
	p := problem.New("validation-error", "Validation failed.", http.StatusUnprocessableEntity, detail, instance)
	return httpapi.CreateInvitation422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func createInvitationError(err error, instance string) httpapi.CreateInvitationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return createInvitationUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.CreateInvitation403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrNotFound):
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.CreateInvitation404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrPendingInvitationExists):
		return createInvitationProblem422("a pending invitation already exists for this email", instance)
	case errors.Is(err, ErrInvalidInput):
		return createInvitationProblem422("invalid invitation input", instance)
	default:
		return createInvitationProblem422("invitation create failed", instance)
	}
}

func listInvitationsUnauthorized(instance string) httpapi.ListInvitations401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.ListInvitations401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func listInvitationsError(err error, instance string) httpapi.ListInvitationsResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return listInvitationsUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.ListInvitations403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.ListInvitations404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func getInvitationUnauthorized(instance string) httpapi.GetInvitation401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.GetInvitation401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func getInvitationError(err error, instance string) httpapi.GetInvitationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return getInvitationUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.GetInvitation403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.GetInvitation404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func revokeInvitationUnauthorized(instance string) httpapi.RevokeInvitation401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.RevokeInvitation401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func revokeInvitationError(err error, instance string) httpapi.RevokeInvitationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return revokeInvitationUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.RevokeInvitation403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrETagMismatch):
		p := problem.New("precondition-failed", "Precondition failed.", http.StatusPreconditionFailed, "stale or missing If-Match", instance)
		return httpapi.RevokeInvitation412ApplicationProblemPlusJSONResponse{
			PreconditionFailedApplicationProblemPlusJSONResponse: httpapi.PreconditionFailedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvitationConsumed), errors.Is(err, ErrInvitationExpired):
		p := problem.New("invitation-gone", "Invitation already consumed or expired.", http.StatusGone, "", instance)
		return httpapi.RevokeInvitation410ApplicationProblemPlusJSONResponse(toAPIProblem(p))
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.RevokeInvitation404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func acceptInvitationUnauthorized(instance string) httpapi.AcceptInvitation401ApplicationProblemPlusJSONResponse {
	p := problem.New("unauthorized", "Missing or invalid bearer token / API key.", http.StatusUnauthorized, "", instance)
	return httpapi.AcceptInvitation401ApplicationProblemPlusJSONResponse{
		UnauthorizedApplicationProblemPlusJSONResponse: httpapi.UnauthorizedApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func acceptInvitationProblem422(slug, detail, instance string) httpapi.AcceptInvitation422ApplicationProblemPlusJSONResponse {
	p := problem.New(slug, "Validation failed.", http.StatusUnprocessableEntity, detail, instance)
	return httpapi.AcceptInvitation422ApplicationProblemPlusJSONResponse{
		IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse: httpapi.IdempotencyConflictOrValidationApplicationProblemPlusJSONResponse(toAPIProblem(p)),
	}
}

func acceptInvitationError(err error, instance string) httpapi.AcceptInvitationResponseObject {
	switch {
	case errors.Is(err, auth.ErrUnauthorized):
		return acceptInvitationUnauthorized(instance)
	case errors.Is(err, auth.ErrCrossTenant), errors.Is(err, ErrEmailMismatch):
		p := problem.New("forbidden", "Caller lacks permission for this resource.", http.StatusForbidden, "", instance)
		return httpapi.AcceptInvitation403ApplicationProblemPlusJSONResponse{
			ForbiddenApplicationProblemPlusJSONResponse: httpapi.ForbiddenApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	case errors.Is(err, ErrInvalidToken):
		// Per service contract, ErrInvalidToken collapses unknown / wrong
		// token / unknown invitation into 410 Gone to defeat enumeration.
		p := problem.New("invitation-gone", "Invitation token is invalid or unknown.", http.StatusGone, "", instance)
		return httpapi.AcceptInvitation410ApplicationProblemPlusJSONResponse(toAPIProblem(p))
	case errors.Is(err, ErrInvitationConsumed), errors.Is(err, ErrInvitationExpired):
		p := problem.New("invitation-gone", "Invitation already consumed or expired.", http.StatusGone, "", instance)
		return httpapi.AcceptInvitation410ApplicationProblemPlusJSONResponse(toAPIProblem(p))
	case errors.Is(err, ErrMemberExists):
		return acceptInvitationProblem422("validation-error", "caller is already a member of this organization", instance)
	default:
		p := problem.New("not-found", "Resource not found.", http.StatusNotFound, "", instance)
		return httpapi.AcceptInvitation404ApplicationProblemPlusJSONResponse{
			NotFoundApplicationProblemPlusJSONResponse: httpapi.NotFoundApplicationProblemPlusJSONResponse(toAPIProblem(p)),
		}
	}
}

func statusTitle(status int) string {
	switch status {
	case http.StatusUnauthorized:
		return "Unauthorized."
	case http.StatusPreconditionFailed:
		return "Precondition failed."
	case http.StatusUnprocessableEntity:
		return "Validation failed."
	default:
		return "Error."
	}
}
