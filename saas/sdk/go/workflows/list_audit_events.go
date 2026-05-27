package workflows

import (
	"context"
	"time"

	dp "github.com/omarss/saas/sdk/go/dataplane"
)

// ListAuditEventsInput maps to GET /v1/tenants/{tenant_id}/audit-events
// query parameters. All optional filters use zero-value to mean "no
// filter".
type ListAuditEventsInput struct {
	TenantID       string
	Limit          int
	Cursor         string
	Action         string
	ResourceType   string
	ResourceID     string
	ActorID        string
	OccurredAfter  time.Time
	OccurredBefore time.Time
}

// AuditEventsPage is one page of results. NextCursor is empty when there
// are no more results; pass it back unchanged on the next call to
// continue iteration (cursor schema is opaque + versioned, do not parse).
type AuditEventsPage struct {
	Events     []dp.AuditEvent
	NextCursor string
	HasMore    bool
}

// ListAuditEvents wraps GET /v1/tenants/{tenant_id}/audit-events. Cursor
// pagination only — the platform's audit table is monotonic by chain_sequence
// and skipping pages is unsafe (chain verification needs the full slice).
func ListAuditEvents(
	ctx context.Context,
	client *dp.ClientWithResponses,
	in ListAuditEventsInput,
) (AuditEventsPage, error) {
	params := &dp.ListAuditEventsParams{}
	if in.Limit > 0 {
		l := dp.Limit(in.Limit)
		params.Limit = &l
	}
	if in.Cursor != "" {
		c := dp.Cursor(in.Cursor)
		params.Cursor = &c
	}
	if in.Action != "" {
		a := in.Action
		params.Action = &a
	}
	if in.ResourceType != "" {
		rt := in.ResourceType
		params.ResourceType = &rt
	}
	if in.ResourceID != "" {
		rid := in.ResourceID
		params.ResourceId = &rid
	}
	if in.ActorID != "" {
		aid := in.ActorID
		params.ActorId = &aid
	}
	if !in.OccurredAfter.IsZero() {
		t := in.OccurredAfter
		params.OccurredAfter = &t
	}
	if !in.OccurredBefore.IsZero() {
		t := in.OccurredBefore
		params.OccurredBefore = &t
	}

	res, err := client.ListAuditEventsWithResponse(ctx, in.TenantID, params)
	if err != nil {
		return AuditEventsPage{}, err
	}
	if res.StatusCode() != 200 || res.JSON200 == nil {
		return AuditEventsPage{}, parseProblem(res.StatusCode(), res.Body)
	}
	page := AuditEventsPage{
		Events:  res.JSON200.Data,
		HasMore: res.JSON200.Pagination.HasMore,
	}
	if res.JSON200.Pagination.NextCursor != nil {
		page.NextCursor = *res.JSON200.Pagination.NextCursor
	}
	return page, nil
}
