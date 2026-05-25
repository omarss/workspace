package deployments

import "errors"

// Sentinel errors. The handler layer maps these to RFC 7807 problem types;
// keep them stable — the type slug in the problem document is derived from
// the error identifier.
var (
	// ErrNotFound — the deployment_id (or domain_id) does not exist.
	ErrNotFound = errors.New("deployments: not found")

	// ErrSlugTaken — project_slug + environment_slug uniqueness violated.
	ErrSlugTaken = errors.New("deployments: project/environment slug taken")

	// ErrInvalidStatusTransition — caller asked for an action incompatible
	// with the current status (e.g. purge before destroy).
	ErrInvalidStatusTransition = errors.New("deployments: invalid status transition")

	// ErrDomainLimitReached — Deployment already has the max configured
	// number of BYOD domains attached (default 5).
	ErrDomainLimitReached = errors.New("deployments: domain limit reached")

	// ErrCustomDomainInPlatformZone — caller attempted to attach a domain
	// that is a subdomain of *.saas.omarss.net. BYOD is for external
	// customer-owned domains only.
	ErrCustomDomainInPlatformZone = errors.New("deployments: custom domain falls inside the platform zone")

	// ErrInvalidDomain — domain failed FQDN shape validation (length,
	// label rules, wildcards forbidden).
	ErrInvalidDomain = errors.New("deployments: invalid domain")

	// ErrDomainTaken — the domain is already attached to some Deployment.
	ErrDomainTaken = errors.New("deployments: domain already attached")

	// ErrEtagMismatch — If-Match did not match the current row_seq-derived
	// ETag. Maps to 412.
	ErrEtagMismatch = errors.New("deployments: etag mismatch")

	// ErrProvisionerNotConfigured — service called without a Provisioner
	// wired in. Programmer error; surfaces a 500.
	ErrProvisionerNotConfigured = errors.New("deployments: provisioner not configured")

	// ErrOperatorRequired — caller is not an operator. The controlplane is
	// operator-only.
	ErrOperatorRequired = errors.New("deployments: operator principal required")
)
