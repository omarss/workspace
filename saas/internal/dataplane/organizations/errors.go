package organizations

import "errors"

// Sentinel errors. Translated to RFC 9457 problems by the handler;
// the mapping mirrors CONVENTIONS.md §3.
var (
	// ErrNotFound — the requested resource does not exist OR exists in
	// another tenant. Cross-tenant rows always look like ErrNotFound to
	// avoid existence-leak attacks.
	ErrNotFound = errors.New("organizations: not found")

	// ErrSlugTaken — the (tenant_id, slug) pair is already in use by an
	// active organization. Surfaces as 422 validation-error.
	ErrSlugTaken = errors.New("organizations: organization slug already taken")

	// ErrInvalidInput — generic input validation failure (slug pattern,
	// name length, role id format, ...). Surfaces as 422.
	ErrInvalidInput = errors.New("organizations: invalid input")

	// ErrETagMismatch — optimistic-concurrency check failed: the
	// caller's If-Match referenced a stale row_seq. Surfaces as 412.
	ErrETagMismatch = errors.New("organizations: row_seq mismatch")

	// ErrMultiOrgDisabled — POST /v1/tenants/{id}/organizations called
	// while the tenant has multi_org=false. Surfaces as 405 Method Not
	// Allowed. The default org auto-created on tenant.create is the only
	// organization a non-multi-org tenant may have.
	ErrMultiOrgDisabled = errors.New("organizations: multi-org disabled for this tenant")

	// ErrMemberExists — caller attempted to create a Member that would
	// duplicate an existing active membership for (org, user). Surfaces
	// as 422.
	ErrMemberExists = errors.New("organizations: user already an active member of this organization")

	// ErrInvitationConsumed — accept attempted on an already-accepted or
	// revoked invitation. Surfaces as 410 Gone.
	ErrInvitationConsumed = errors.New("organizations: invitation already consumed")

	// ErrInvitationExpired — accept attempted on an invitation past its
	// expires_at. Surfaces as 410 Gone.
	ErrInvitationExpired = errors.New("organizations: invitation expired")

	// ErrInvalidToken — the provided accept-token did not match the
	// stored hash (constant-time comparison failed). Surfaces as 410
	// Gone — the platform deliberately avoids distinguishing "wrong
	// token" from "unknown invitation" to defeat enumeration.
	ErrInvalidToken = errors.New("organizations: invalid or unknown invitation token")

	// ErrEmailMismatch — accept attempted by a user whose verified
	// email does not match the invitee email. Surfaces as 403 Forbidden.
	ErrEmailMismatch = errors.New("organizations: caller email does not match invitee email")

	// ErrPendingInvitationExists — caller attempted to invite an email
	// that already has a pending invitation for this organization.
	// Surfaces as 422.
	ErrPendingInvitationExists = errors.New("organizations: a pending invitation already exists for this email")
)
