package workflows

import (
	"context"
	"time"

	dp "github.com/omarss/saas/sdk/go/dataplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// CreateAPIKeyInput targets POST /v1/tenants/{tenant_id}/api-keys.
//
// Scopes are required and must match the platform's "resource.action"
// regex (server-side validation; the SDK does not pre-validate). The
// optional fields are pointer-less here for ergonomics; pass the zero
// value to leave a field unset.
type CreateAPIKeyInput struct {
	TenantID           string
	Name               string
	Scopes             []string
	EnvironmentID      string
	ExpiresAt          time.Time
	RateLimitPerMinute int
	IPAllowlist        []string
}

// MintedAPIKey carries both the persisted metadata (Data) and the
// one-time plaintext bearer (Secret). The Secret is returned ONCE; the
// platform never echoes it again. Persist immediately and never log.
type MintedAPIKey struct {
	Data   dp.APIKey
	Secret string
}

// CreateAPIKey wraps the create-API-key endpoint. Per Phase 9 the
// response carries the plaintext bearer exactly once; this wrapper does
// not redact it, but README + AGENTS.md §18.6 require callers to treat it
// as a secret.
func CreateAPIKey(
	ctx context.Context,
	client *dp.ClientWithResponses,
	in CreateAPIKeyInput,
	opts ...Option,
) (MintedAPIKey, error) {
	o := collect(opts)
	key := o.idemKey
	if key == "" {
		key = idem.New()
	}

	body := dp.CreateAPIKeyRequest{
		Name:   in.Name,
		Scopes: in.Scopes,
	}
	if in.EnvironmentID != "" {
		eid := in.EnvironmentID
		body.EnvironmentId = &eid
	}
	if !in.ExpiresAt.IsZero() {
		t := in.ExpiresAt
		body.ExpiresAt = &t
	}
	if in.RateLimitPerMinute > 0 {
		r := in.RateLimitPerMinute
		body.RateLimitPerMinute = &r
	}
	if len(in.IPAllowlist) > 0 {
		ips := in.IPAllowlist
		body.IpAllowlist = &ips
	}

	res, err := client.CreateAPIKeyWithResponse(ctx, in.TenantID,
		&dp.CreateAPIKeyParams{IdempotencyKey: dp.IdempotencyKey(key)}, body)
	if err != nil {
		return MintedAPIKey{}, err
	}
	if res.StatusCode() != 201 || res.JSON201 == nil {
		return MintedAPIKey{}, parseProblem(res.StatusCode(), res.Body)
	}
	return MintedAPIKey{Data: res.JSON201.Data, Secret: res.JSON201.Secret}, nil
}
