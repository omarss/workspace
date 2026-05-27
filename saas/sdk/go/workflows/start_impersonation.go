package workflows

import (
	"context"
	"time"

	cp "github.com/omarss/saas/sdk/go/controlplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// StartImpersonationInput targets POST
// /control/v1/deployments/{deployment_id}/impersonation-sessions (Phase 13).
//
// Per ADR for operator-mode impersonation: the operator's caller must
// already be a step-up-MFA-authenticated operator token; the data-plane
// access token returned here is short-lived (capped at 15 minutes by the
// platform — DurationSeconds is clamped server-side).
type StartImpersonationInput struct {
	DeploymentID    string
	TargetMemberID  string
	Reason          string
	DurationSeconds int
}

// ImpersonationSession is the workflow result. Token is the impersonation
// access token; it MUST be treated as a secret and never logged.
type ImpersonationSession struct {
	Token     string
	ExpiresAt time.Time
}

// StartImpersonation wraps the start endpoint. Auto-generates an
// Idempotency-Key on each call so a retry with the same key returns the
// same session id (server-side replay).
func StartImpersonation(
	ctx context.Context,
	client *cp.ClientWithResponses,
	in StartImpersonationInput,
	opts ...Option,
) (ImpersonationSession, error) {
	o := collect(opts)
	key := o.idemKey
	if key == "" {
		key = idem.New()
	}

	body := cp.StartImpersonationRequest{
		TargetMemberId: in.TargetMemberID,
		Reason:         in.Reason,
	}
	if in.DurationSeconds > 0 {
		d := in.DurationSeconds
		body.DurationSeconds = &d
	}

	res, err := client.StartImpersonationSessionWithResponse(ctx, in.DeploymentID,
		&cp.StartImpersonationSessionParams{IdempotencyKey: key}, body)
	if err != nil {
		return ImpersonationSession{}, err
	}
	if res.StatusCode() != 201 || res.JSON201 == nil {
		return ImpersonationSession{}, parseProblem(res.StatusCode(), res.Body)
	}
	return ImpersonationSession{Token: res.JSON201.Token, ExpiresAt: res.JSON201.ExpiresAt}, nil
}
