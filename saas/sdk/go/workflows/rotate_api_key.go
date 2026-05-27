package workflows

import (
	"context"
	"time"

	dp "github.com/omarss/saas/sdk/go/dataplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// RotateAPIKeyInput targets POST /v1/api-keys/{id}/rotate.
//
// GracePeriodSeconds is optional (0 means "use server default of 86400" —
// see openapi/data-plane.yaml RotateAPIKeyRequest.default). The previous
// plaintext keeps authenticating until PredecessorExpiresAt elapses.
type RotateAPIKeyInput struct {
	APIKeyID           string
	GracePeriodSeconds int
}

// RotatedAPIKey carries the new plaintext (Secret) — returned once — plus
// the timestamp at which the old plaintext stops authenticating. Callers
// must persist Secret immediately; the platform never re-emits it.
type RotatedAPIKey struct {
	Data                 dp.APIKey
	Secret               string
	PredecessorExpiresAt time.Time
}

// RotateAPIKey wraps the rotate endpoint. Auto-generates an
// Idempotency-Key per the platform contract (rotation is on the "required"
// idempotency list — AGENTS.md §11.idempotency).
func RotateAPIKey(
	ctx context.Context,
	client *dp.ClientWithResponses,
	in RotateAPIKeyInput,
	opts ...Option,
) (RotatedAPIKey, error) {
	o := collect(opts)
	key := o.idemKey
	if key == "" {
		key = idem.New()
	}

	var body dp.RotateAPIKeyRequest
	if in.GracePeriodSeconds > 0 {
		s := in.GracePeriodSeconds
		body.GracePeriodSeconds = &s
	}

	res, err := client.RotateAPIKeyWithResponse(ctx, in.APIKeyID,
		&dp.RotateAPIKeyParams{IdempotencyKey: dp.IdempotencyKey(key)}, body)
	if err != nil {
		return RotatedAPIKey{}, err
	}
	if res.StatusCode() != 200 || res.JSON200 == nil {
		return RotatedAPIKey{}, parseProblem(res.StatusCode(), res.Body)
	}
	return RotatedAPIKey{
		Data:                 res.JSON200.Data,
		Secret:               res.JSON200.Secret,
		PredecessorExpiresAt: res.JSON200.PredecessorExpiresAt,
	}, nil
}
