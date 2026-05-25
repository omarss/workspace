package audit

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
)

// HashSize is the length of a SHA-256 output in bytes.
const HashSize = sha256.Size

// ErrInvalidPrevHash is returned when a stored prev_hash has the wrong
// length. The chain is unverifiable in that state — the verifier surfaces
// the row as a mismatch with reason="prev_hash".
var ErrInvalidPrevHash = errors.New("audit: prev_hash must be 32 bytes")

// Genesis returns the initial prev_hash for tenantID's chain. Every
// tenant's chain starts here — making the genesis explicit (rather than
// NULL) keeps the chain rooted: a malicious INSERT of a row with no
// preceding row would otherwise be indistinguishable from a legitimate
// first row.
//
// The genesis hash is deterministic from tenantID, so the verifier can
// recompute it without state — only the chain rows themselves are
// persisted.
func Genesis(tenantID string) []byte {
	sum := sha256.Sum256([]byte(tenantID + "|audit-chain-genesis|v1"))
	return sum[:]
}

// ComputeRowHash returns sha256(prev_hash || JCS(body)). body MUST NOT
// include prev_hash, row_hash, or chain_sequence — those fields are
// self-referential and including them would make the hash undefined.
// The repository is responsible for assembling the canonical body
// before calling this.
func ComputeRowHash(prevHash []byte, body map[string]any) ([]byte, error) {
	if len(prevHash) != HashSize {
		return nil, ErrInvalidPrevHash
	}
	canon, err := Canonical(body)
	if err != nil {
		return nil, err
	}
	h := sha256.New()
	_, _ = h.Write(prevHash)
	_, _ = h.Write(canon)
	return h.Sum(nil), nil
}

// HexHash returns the lowercase hex encoding of h. Used by the
// HTTP response shape — hex is more terminal-friendly than base64 and
// matches the AGENTS.md §8.6 spec.
func HexHash(h []byte) string {
	return hex.EncodeToString(h)
}
