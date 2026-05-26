package workflows

import (
	"context"

	dp "github.com/omarss/saas/sdk/go/dataplane"
)

// CheckAuthorizationInput is the single-check request (member + permission
// + tenant). Permission must be the platform's canonical
// "resource_type.action" form, e.g. "tenant.read" — the server splits on
// the dot at the handler boundary.
type CheckAuthorizationInput struct {
	MemberID   string
	Permission string
	TenantID   string
}

// CheckResult mirrors the server's response data shape but exposes
// non-pointer fields so callers don't have to nil-check ViaRole.
type CheckResult struct {
	Allowed bool
	ViaRole string
}

// CheckAuthorization wraps POST /v1/authorization/check.
//
// No idempotency key is needed — the endpoint is a pure read. Denied
// checks emit an audit event on the server side; callers do not need to
// log the denial themselves.
func CheckAuthorization(
	ctx context.Context,
	client *dp.ClientWithResponses,
	in CheckAuthorizationInput,
) (CheckResult, error) {
	res, err := client.CheckAuthorizationWithResponse(ctx,
		dp.CheckAuthorizationRequest{
			MemberId:   in.MemberID,
			Permission: in.Permission,
			TenantId:   in.TenantID,
		})
	if err != nil {
		return CheckResult{}, err
	}
	if res.StatusCode() != 200 || res.JSON200 == nil {
		return CheckResult{}, parseProblem(res.StatusCode(), res.Body)
	}
	out := CheckResult{Allowed: res.JSON200.Data.Allowed}
	if res.JSON200.Data.ViaRole != nil {
		out.ViaRole = *res.JSON200.Data.ViaRole
	}
	return out, nil
}

// BatchCheckAuthorization wraps POST /v1/authorization/batch-check. The
// server enforces a 100-check ceiling; this wrapper preserves the input
// order in the returned slice (server contract).
func BatchCheckAuthorization(
	ctx context.Context,
	client *dp.ClientWithResponses,
	checks []CheckAuthorizationInput,
) ([]CheckResult, error) {
	reqChecks := make([]dp.CheckAuthorizationRequest, 0, len(checks))
	for _, c := range checks {
		reqChecks = append(reqChecks, dp.CheckAuthorizationRequest{
			MemberId:   c.MemberID,
			Permission: c.Permission,
			TenantId:   c.TenantID,
		})
	}
	res, err := client.BatchCheckAuthorizationWithResponse(ctx,
		dp.BatchCheckAuthorizationRequest{Checks: reqChecks})
	if err != nil {
		return nil, err
	}
	if res.StatusCode() != 200 || res.JSON200 == nil {
		return nil, parseProblem(res.StatusCode(), res.Body)
	}
	out := make([]CheckResult, 0, len(res.JSON200.Data))
	for _, d := range res.JSON200.Data {
		r := CheckResult{Allowed: d.Allowed}
		if d.ViaRole != nil {
			r.ViaRole = *d.ViaRole
		}
		out = append(out, r)
	}
	return out, nil
}
