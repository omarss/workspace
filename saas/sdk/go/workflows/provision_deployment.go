package workflows

import (
	"context"

	cp "github.com/omarss/saas/sdk/go/controlplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// ProvisionInput is the workflow-level summary of a CreateDeploymentRequest.
// Optional knobs use Go zero-values: empty string / nil map means "leave
// unset, server applies defaults".
type ProvisionInput struct {
	ProjectSlug     string
	EnvironmentSlug string
	ImageVersion    string
	Modules         []string
	Region          string
	DataResidency   string
	Metadata        map[string]string
}

// Provisioned is the payload a successful ProvisionDeployment returns.
// BootstrapSecret is the one-time plaintext bearer that the caller MUST
// persist immediately — the API never re-emits it. We deliberately do NOT
// log or print it anywhere; the field exists only on this struct.
type Provisioned struct {
	Deployment        cp.Deployment
	BootstrapAPIKeyID string
	BootstrapSecret   string
	BootstrapTenantID string
}

// ProvisionDeployment wraps POST /control/v1/deployments. It auto-generates
// an Idempotency-Key unless the caller supplies one via WithIdempotencyKey
// (e.g. for a retry that must reuse the same key).
//
// On 201 it returns the new deployment + bootstrap API key id + secret +
// tenant id. The secret is one-shot per Phase 9: callers must store it
// immediately. On non-201 it returns an *APIError carrying the RFC 9457
// problem-type discriminator.
func ProvisionDeployment(
	ctx context.Context,
	client *cp.ClientWithResponses,
	in ProvisionInput,
	opts ...Option,
) (Provisioned, error) {
	o := collect(opts)
	key := o.idemKey
	if key == "" {
		key = idem.New()
	}

	body := cp.CreateDeploymentRequest{
		ProjectSlug:     in.ProjectSlug,
		EnvironmentSlug: in.EnvironmentSlug,
		ImageVersion:    in.ImageVersion,
	}
	if len(in.Modules) > 0 {
		mods := in.Modules
		body.Modules = &mods
	}
	if in.Region != "" {
		r := in.Region
		body.Region = &r
	}
	if in.DataResidency != "" {
		dr := in.DataResidency
		body.DataResidency = &dr
	}
	if in.Metadata != nil {
		m := in.Metadata
		body.Metadata = &m
	}

	res, err := client.CreateDeploymentWithResponse(ctx,
		&cp.CreateDeploymentParams{IdempotencyKey: key}, body)
	if err != nil {
		return Provisioned{}, err
	}
	if res.StatusCode() != 201 || res.JSON201 == nil {
		return Provisioned{}, parseProblem(res.StatusCode(), res.Body)
	}
	return Provisioned{
		Deployment:        res.JSON201.Data,
		BootstrapAPIKeyID: res.JSON201.BootstrapApiKey.Id,
		BootstrapSecret:   res.JSON201.BootstrapApiKey.Secret,
		BootstrapTenantID: res.JSON201.BootstrapApiKey.TenantId,
	}, nil
}
