package workflows

import (
	"context"

	cp "github.com/omarss/saas/sdk/go/controlplane"
)

// VerifyAuditIntegrityInput targets GET
// /control/v1/deployments/{deployment_id}/audit-integrity. If TenantID is
// non-empty the server scopes the chain verification to that tenant.
type VerifyAuditIntegrityInput struct {
	DeploymentID string
	TenantID     string
}

// AuditIntegrityResult flattens the AuditIntegrityResponse.Data nested
// struct so callers can switch on Verified + FirstMismatchSequence
// without dereferencing optionals.
type AuditIntegrityResult struct {
	Verified              bool
	RowsChecked           int
	TenantsChecked        int
	FirstMismatchID       string
	FirstMismatchTenantID string
	FirstMismatchSequence int64
	FirstMismatchReason   string
}

// VerifyAuditIntegrity walks the audit hash chain and returns the first
// mismatch (if any). It is a read-only endpoint — no idempotency key.
func VerifyAuditIntegrity(
	ctx context.Context,
	client *cp.ClientWithResponses,
	in VerifyAuditIntegrityInput,
) (AuditIntegrityResult, error) {
	params := &cp.VerifyDeploymentAuditIntegrityParams{}
	if in.TenantID != "" {
		t := in.TenantID
		params.TenantId = &t
	}
	res, err := client.VerifyDeploymentAuditIntegrityWithResponse(ctx, in.DeploymentID, params)
	if err != nil {
		return AuditIntegrityResult{}, err
	}
	if res.StatusCode() != 200 || res.JSON200 == nil {
		return AuditIntegrityResult{}, parseProblem(res.StatusCode(), res.Body)
	}
	d := res.JSON200.Data
	out := AuditIntegrityResult{
		Verified:       d.Verified,
		RowsChecked:    d.RowsChecked,
		TenantsChecked: d.TenantsChecked,
	}
	if d.FirstMismatchId != nil {
		out.FirstMismatchID = *d.FirstMismatchId
	}
	if d.FirstMismatchTenantId != nil {
		out.FirstMismatchTenantID = *d.FirstMismatchTenantId
	}
	if d.FirstMismatchSequence != nil {
		out.FirstMismatchSequence = *d.FirstMismatchSequence
	}
	if d.FirstMismatchReason != nil {
		out.FirstMismatchReason = string(*d.FirstMismatchReason)
	}
	return out, nil
}
