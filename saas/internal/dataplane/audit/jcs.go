// Package audit owns the Phase 10 audit-log module: hash-chained,
// append-only row inserts driven by the outbox dispatcher, plus the
// chain-walking integrity verifier consumed by the control plane.
//
// The canonical-JSON layer lives in this file. Per ADR 012 the chain
// row_hash is sha256(prev_hash || JCS(canonical body)) where JCS is the
// RFC 8785 JSON Canonicalization Scheme, implemented by the vetted
// gowebpki/jcs v1.0.1 library (Apache-2.0, derived from the RFC author's
// reference implementation).
//
// The Canonical() function is the ONLY source of canonical bytes in the
// codebase. Any alternate canonicalisation path is a security incident:
// a single off-by-one in number serialisation breaks the chain forever.
// The jcs_test.go RFC 8785 §3.4 reference vectors serve double duty as a
// sanity check on the library AND as a tripwire if we ever swap
// implementations (the vectors are spec-frozen).
package audit

import (
	"encoding/json"
	"fmt"

	"github.com/gowebpki/jcs"
)

// Canonical returns the RFC 8785 JCS bytes for v. v must be
// JSON-marshallable via encoding/json's default rules — the library
// handles UTF-16 key ordering, ECMAScript-canonical number form, and
// JSON-string-escape rules from the canonicalisation side; encoding/json
// handles the initial value-to-bytes step.
//
// Why two stages: jcs.Transform takes raw JSON bytes, not Go values, so
// we marshal once to get a canonicalisable representation then transform.
// The extra Marshal pass is negligible relative to the hash chain's
// per-row I/O.
func Canonical(v any) ([]byte, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, fmt.Errorf("audit jcs marshal: %w", err)
	}
	canon, err := jcs.Transform(raw)
	if err != nil {
		return nil, fmt.Errorf("audit jcs transform: %w", err)
	}
	return canon, nil
}

// CanonicalBytes is a convenience for callers who already hold raw JSON
// bytes (e.g. an outbox event's payload column). Skips the extra Marshal
// step but still validates the input is well-formed JSON via the
// library's own parser.
func CanonicalBytes(raw []byte) ([]byte, error) {
	canon, err := jcs.Transform(raw)
	if err != nil {
		return nil, fmt.Errorf("audit jcs transform: %w", err)
	}
	return canon, nil
}
