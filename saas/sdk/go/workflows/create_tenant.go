package workflows

import (
	"context"

	dp "github.com/omarss/saas/sdk/go/dataplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// CreateTenantInput collects the required + optional fields of POST
// /v1/tenants. Metadata is optional and uses an exported map type so the
// caller can pass nil for "no metadata".
type CreateTenantInput struct {
	Slug     string
	Name     string
	Metadata map[string]string
}

// CreateTenant wraps POST /v1/tenants. Auto-generates an Idempotency-Key
// unless WithIdempotencyKey supplies one. Returns the freshly-created
// Tenant on 201; on non-201 returns an *APIError.
func CreateTenant(
	ctx context.Context,
	client *dp.ClientWithResponses,
	in CreateTenantInput,
	opts ...Option,
) (dp.Tenant, error) {
	o := collect(opts)
	key := o.idemKey
	if key == "" {
		key = idem.New()
	}

	body := dp.CreateTenantRequest{
		Slug: in.Slug,
		Name: in.Name,
	}
	if in.Metadata != nil {
		m := dp.Metadata(in.Metadata)
		body.Metadata = &m
	}

	res, err := client.CreateTenantWithResponse(ctx,
		&dp.CreateTenantParams{IdempotencyKey: dp.IdempotencyKey(key)}, body)
	if err != nil {
		return dp.Tenant{}, err
	}
	if res.StatusCode() != 201 || res.JSON201 == nil {
		return dp.Tenant{}, parseProblem(res.StatusCode(), res.Body)
	}
	// JSON201 is a *TenantResponse — unwrap the data envelope.
	return res.JSON201.Data, nil
}
