package audit

import (
	"bytes"
	"context"
	"errors"
	"time"
)

// IntegrityResult is the structured return shape consumed by the
// control-plane integrity verify endpoint. Mirrors the AGENTS.md §8.6
// AuditIntegrityResponse schema.
//
// Verified=true means EVERY row's prev_hash and row_hash agree with the
// stored value AND chain_sequence is gap-free per tenant. Any deviation
// short-circuits with the first offending row.
type IntegrityResult struct {
	Verified              bool      `json:"verified"`
	RowsChecked           int       `json:"rows_checked"`
	TenantsChecked        int       `json:"tenants_checked"`
	FirstMismatchID       *string   `json:"first_mismatch_id"`
	FirstMismatchTenantID *string   `json:"first_mismatch_tenant_id"`
	FirstMismatchSequence *int64    `json:"first_mismatch_sequence"`
	FirstMismatchReason   *string   `json:"first_mismatch_reason"`
	VerifiedAt            time.Time `json:"verified_at"`
}

// Mismatch reason constants. Stable strings so external tools can match
// on them programmatically.
const (
	ReasonSequenceGap = "sequence-gap"
	ReasonPrevHash    = "prev_hash"
	ReasonRowHash     = "row_hash"
)

// ErrStreamAborted is returned by the stream callback to abort iteration
// without polluting the IntegrityResult shape. The verifier converts the
// abort into a normal "tampered" return.
var errChainTampered = errors.New("audit: chain tampered")

// VerifyChain walks repo's chain (optionally scoped to tenantFilter) in
// (tenant_id, chain_sequence) order, recomputing each row_hash and
// comparing to the stored value. The first mismatch terminates the walk.
//
// The clock is injected so tests can pin VerifiedAt. Production callers
// pass time.Now.
func VerifyChain(ctx context.Context, repo Repository, tenantFilter string, clock func() time.Time) (IntegrityResult, error) {
	if clock == nil {
		clock = time.Now
	}
	out := IntegrityResult{VerifiedAt: clock().UTC()}
	var (
		currentTenant string
		expectedPrev  []byte
		expectedSeq   int64
		tenantSet     = map[string]struct{}{}
		mismatch      bool
	)
	err := repo.StreamForVerify(ctx, tenantFilter, func(e Event) error {
		if e.TenantID != currentTenant {
			currentTenant = e.TenantID
			expectedPrev = Genesis(currentTenant)
			expectedSeq = 0
			tenantSet[currentTenant] = struct{}{}
		}
		out.RowsChecked++
		// Sequence-gap check: chains MUST be monotonic and contiguous.
		if e.ChainSequence != expectedSeq+1 {
			recordMismatch(&out, e, ReasonSequenceGap)
			mismatch = true
			return errChainTampered
		}
		// prev_hash check: the stored prev_hash must match the previous
		// row's row_hash (or Genesis for the first row).
		if !bytes.Equal(e.PrevHash, expectedPrev) {
			recordMismatch(&out, e, ReasonPrevHash)
			mismatch = true
			return errChainTampered
		}
		// row_hash recomputation. The body comes from the same
		// CanonicalBody() helper used at insert time so the hash math
		// is symmetric.
		want, err := ComputeRowHash(expectedPrev, e.CanonicalBody())
		if err != nil {
			return err
		}
		if !bytes.Equal(e.RowHash, want) {
			recordMismatch(&out, e, ReasonRowHash)
			mismatch = true
			return errChainTampered
		}
		expectedPrev = e.RowHash
		expectedSeq = e.ChainSequence
		return nil
	})
	if err != nil && !errors.Is(err, errChainTampered) {
		return out, err
	}
	out.TenantsChecked = len(tenantSet)
	out.Verified = !mismatch
	return out, nil
}

func recordMismatch(out *IntegrityResult, e Event, reason string) {
	id := e.ID
	tenant := e.TenantID
	seq := e.ChainSequence
	r := reason
	out.FirstMismatchID = &id
	out.FirstMismatchTenantID = &tenant
	out.FirstMismatchSequence = &seq
	out.FirstMismatchReason = &r
}
