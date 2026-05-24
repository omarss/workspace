// Package id wraps oklog/ulid behind a small helper. Every public id in the
// platform is "<prefix>_<ulid>" — Crockford base32, 26 characters,
// lexicographically sortable by creation time.
//
// AGENTS.md §11.5 lists the prefixes; the constants below are the
// authoritative table. Modules MUST call New(PrefixXxx) instead of literal
// strings so a prefix-name typo fails the build, not at runtime.
package id

import "github.com/oklog/ulid/v2"

// Prefix constants — mirror AGENTS.md §11.5. Keep alphabetised so additions
// stay easy to review.
const (
	PrefixAPIKey       = "apik"
	PrefixAudit        = "audit"
	PrefixChannel      = "chan"
	PrefixDeployment   = "dep"
	PrefixDomain       = "dom"
	PrefixEvent        = "evt"
	PrefixIdempotency  = "idem"
	PrefixInvitation   = "inv"
	PrefixMember       = "member"
	PrefixNotification = "notif"
	PrefixOperator     = "op"
	PrefixOrg          = "org"
	PrefixPermission   = "perm"
	PrefixRole         = "role"
	PrefixTenant       = "tenant"
	PrefixUser         = "user"
	PrefixWorkflow     = "wf"
)

// New returns a new id of the form "<prefix>_<ulid>". ulid.Make is
// thread-safe (internal locked monotonic entropy), so callers do not need
// to coordinate. The prefix is passed without the underscore separator —
// callers use the PrefixXxx constants above.
func New(prefix string) string {
	return prefix + "_" + ulid.Make().String()
}
