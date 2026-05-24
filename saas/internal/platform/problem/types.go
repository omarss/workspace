package problem

// Problem type catalogue. Every URI here MUST correspond to a fragment under
// openapi/problems/ — the catalogue is the source of truth; clients dereference
// the URI to discover semantics. Adding a new entry without a matching
// openapi/problems/<slug>.yaml fragment breaks the round-trip check.
//
// Naming convention: lowercase hyphen-separated slugs, mirroring the
// /problems/<slug> path. AGENTS.md §5.5 specifies RFC 9457 problem-details.
const (
	TypeValidation          = TypeURI + "validation-error"
	TypeUnauthorized        = TypeURI + "unauthorized"
	TypeForbidden           = TypeURI + "forbidden"
	TypeNotFound            = TypeURI + "not-found"
	TypePreconditionFailed  = TypeURI + "precondition-failed"
	TypeIdempotencyConflict = TypeURI + "idempotency-key-conflict"
	TypeIdempotencyInFlight = TypeURI + "idempotency-in-flight"
	TypeCursorGone          = TypeURI + "cursor-gone"
	TypeRateLimited         = TypeURI + "rate-limited"
	TypeCrossTenant         = TypeURI + "cross-tenant-access-denied"
	TypeStepUpRequired      = TypeURI + "step-up-required"
	TypeKidMismatch         = TypeURI + "kid-mismatch"
	TypeKeyRevoked          = TypeURI + "api-key-revoked"
	TypeKeyExpired          = TypeURI + "api-key-expired"
	TypeIPNotAllowed        = TypeURI + "ip-not-allowlisted"
)
