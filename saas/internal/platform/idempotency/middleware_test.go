// Package idempotency_test exercises the Middleware against an in-memory
// Store so the six mandatory cases from docs/plans/mvp/04-platform-patterns.md
// §3.18 run as fast unit tests — no pgx, no testcontainers. The pgx-backed
// store gets a separate integration test under the `integration` build tag.
package idempotency_test

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/idempotency"
	"github.com/omarss/saas/internal/platform/problem"
)

// memStore is the in-memory implementation of idempotency.Store used by these
// tests. It models the same invariants as the pgx-backed store:
//
//   - Claim is atomic: a fresh slot is reserved with InFlight=true; the
//     caller MUST eventually call Finish before the same key with the same
//     body can serve cached replays.
//   - Same key + different body returns the OLD record with the original body
//     hash so the middleware can return 422 idempotency-key-conflict.
//   - An "expired" record (older than ttl) is treated as fresh; the middleware
//     never sees the old payload.
type memStore struct {
	mu      sync.Mutex
	records map[string]*memRecord
	ttl     time.Duration
	now     func() time.Time
	// claimHook lets a test inject a sleep / barrier inside Claim to
	// deterministically reproduce the in-flight contention case.
	claimHook func(key idempotency.Key)
	nextID    int64
}

type memRecord struct {
	id        int64
	bodyHash  []byte
	inFlight  bool
	status    int
	headers   map[string]string
	body      []byte
	createdAt time.Time
}

func newMemStore() *memStore {
	return &memStore{
		records: map[string]*memRecord{},
		ttl:     24 * time.Hour,
		now:     time.Now,
	}
}

func (s *memStore) Claim(_ context.Context, key idempotency.Key, hash []byte) (idempotency.ClaimResult, error) {
	if s.claimHook != nil {
		s.claimHook(key)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	k := key.TenantID + "|" + key.IdempotencyKey + "|" + key.Route + "|" + key.Method
	if rec, ok := s.records[k]; ok {
		// Expired records are reclaimed as fresh — mirrors the pg-side
		// behaviour where the cleanup goroutine deletes anything past TTL.
		if s.now().Sub(rec.createdAt) > s.ttl {
			delete(s.records, k)
		} else {
			return idempotency.ClaimResult{
				ID:              rec.id,
				Fresh:           false,
				InFlight:        rec.inFlight,
				BodyHash:        rec.bodyHash,
				ResponseStatus:  rec.status,
				ResponseHeaders: rec.headers,
				ResponseBody:    rec.body,
			}, nil
		}
	}
	s.nextID++
	rec := &memRecord{
		id:        s.nextID,
		bodyHash:  append([]byte(nil), hash...),
		inFlight:  true,
		createdAt: s.now(),
	}
	s.records[k] = rec
	return idempotency.ClaimResult{ID: rec.id, Fresh: true, InFlight: true, BodyHash: rec.bodyHash}, nil
}

func (s *memStore) Finish(_ context.Context, id int64, status int, headers map[string]string, body []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, rec := range s.records {
		if rec.id == id {
			rec.inFlight = false
			rec.status = status
			rec.headers = headers
			rec.body = append([]byte(nil), body...)
			return nil
		}
	}
	return fmt.Errorf("record %d not found", id)
}

// echoHandler is the test downstream: writes back a fixed payload so the
// middleware has a deterministic byte sequence to cache.
func echoHandler(t *testing.T, called *atomic.Int32) http.Handler {
	t.Helper()
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called.Add(1)
		body, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"echo":"` + string(body) + `"}`))
	})
}

// makeReq builds a POST request with the tenant context populated by
// auth.ContextWithTenant — the middleware reads the tenant from context, not
// from a header (layer 1 of the eight-layer isolation invariant). Only POST is
// covered here because the idempotency middleware only engages on POST and the
// state-transition PATCH path (which routes through the same code).
func makeReq(body, key string) *http.Request {
	r := httptest.NewRequest(http.MethodPost, "/v1/things", strings.NewReader(body))
	r = r.WithContext(auth.ContextWithTenant(r.Context(), "ten_test"))
	if key != "" {
		r.Header.Set("Idempotency-Key", key)
	}
	return r
}

func TestIdempotency_MissingKey_PassesThrough(t *testing.T) {
	t.Parallel()
	store := newMemStore()
	var called atomic.Int32
	h := idempotency.Middleware(store)(echoHandler(t, &called))

	w := httptest.NewRecorder()
	h.ServeHTTP(w, makeReq(`hello`, ""))

	if got := called.Load(); got != 1 {
		t.Fatalf("handler called %d times, want 1", got)
	}
	if w.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201", w.Code)
	}
}

func TestIdempotency_FreshKey_HandlerRuns(t *testing.T) {
	t.Parallel()
	store := newMemStore()
	var called atomic.Int32
	h := idempotency.Middleware(store)(echoHandler(t, &called))

	w := httptest.NewRecorder()
	h.ServeHTTP(w, makeReq(`hello`, "k1"))

	if got := called.Load(); got != 1 {
		t.Fatalf("handler called %d times, want 1", got)
	}
	if w.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201", w.Code)
	}
	// The Store MUST hold one finished record so the next call serves cached.
	store.mu.Lock()
	defer store.mu.Unlock()
	if len(store.records) != 1 {
		t.Fatalf("store has %d records, want 1", len(store.records))
	}
	for _, rec := range store.records {
		if rec.inFlight {
			t.Fatalf("record still in-flight after Finish")
		}
	}
}

func TestIdempotency_SameKey_SameBody_ReturnsCached(t *testing.T) {
	t.Parallel()
	store := newMemStore()
	var called atomic.Int32
	h := idempotency.Middleware(store)(echoHandler(t, &called))

	w1 := httptest.NewRecorder()
	h.ServeHTTP(w1, makeReq(`hello`, "k1"))
	w2 := httptest.NewRecorder()
	h.ServeHTTP(w2, makeReq(`hello`, "k1"))

	if got := called.Load(); got != 1 {
		t.Fatalf("handler called %d times, want exactly 1 (replay should not invoke)", got)
	}
	if w1.Code != w2.Code {
		t.Fatalf("status mismatch: first=%d replay=%d", w1.Code, w2.Code)
	}
	if w1.Body.String() != w2.Body.String() {
		t.Fatalf("body mismatch: first=%q replay=%q", w1.Body.String(), w2.Body.String())
	}
	if w1.Header().Get("Content-Type") != w2.Header().Get("Content-Type") {
		t.Fatalf("content-type mismatch: first=%q replay=%q", w1.Header().Get("Content-Type"), w2.Header().Get("Content-Type"))
	}
}

func TestIdempotency_SameKey_DifferentBody_Returns422(t *testing.T) {
	t.Parallel()
	store := newMemStore()
	var called atomic.Int32
	h := idempotency.Middleware(store)(echoHandler(t, &called))

	w1 := httptest.NewRecorder()
	h.ServeHTTP(w1, makeReq(`hello`, "k1"))

	w2 := httptest.NewRecorder()
	h.ServeHTTP(w2, makeReq(`world`, "k1"))

	if w2.Code != http.StatusUnprocessableEntity {
		t.Fatalf("second request status = %d, want 422", w2.Code)
	}
	var p problem.Problem
	if err := json.Unmarshal(w2.Body.Bytes(), &p); err != nil {
		t.Fatalf("decode problem: %v\nbody=%s", err, w2.Body.String())
	}
	if !strings.Contains(p.Type, "idempotency-key-conflict") {
		t.Fatalf("problem.Type = %q, want suffix idempotency-key-conflict", p.Type)
	}
	if got := called.Load(); got != 1 {
		t.Fatalf("handler called %d times, want 1 (conflict path must not invoke handler)", got)
	}
}

func TestIdempotency_InFlight_BlocksUntilTimeout(t *testing.T) {
	t.Parallel()
	store := newMemStore()
	// Drive the in-flight contention deterministically: the second request's
	// Claim hits the store WHILE the first request's handler is still
	// inside ServeHTTP (hasn't called Finish yet). The hook releases the
	// gate once the second goroutine has observed the in-flight row.
	gate := make(chan struct{})
	released := make(chan struct{})
	var first atomic.Bool
	store.claimHook = func(key idempotency.Key) {
		// Only the second caller is throttled. First request must not block
		// on its own gate signal.
		if !first.CompareAndSwap(false, true) {
			<-gate
		}
	}

	var called atomic.Int32
	slow := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called.Add(1)
		// Hold the response until the second request has seen the in-flight
		// row and we explicitly release it. This guarantees the in-flight
		// branch fires instead of racing the cached-replay branch.
		<-released
		_, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusCreated)
	})
	h := idempotency.Middleware(store)(slow)

	first1 := httptest.NewRecorder()
	go h.ServeHTTP(first1, makeReq(`hello`, "k1"))

	// Give goroutine 1 a moment to claim. Without this the second Claim
	// may win the lock first.
	time.Sleep(10 * time.Millisecond)
	close(gate) // release the second caller's hook

	second := httptest.NewRecorder()
	h.ServeHTTP(second, makeReq(`hello`, "k1"))

	if second.Code != http.StatusConflict {
		t.Fatalf("second request status = %d, want 409 (in-flight)", second.Code)
	}
	// Now let goroutine 1 finish so the test cleans up.
	close(released)
	time.Sleep(50 * time.Millisecond)
	if got := called.Load(); got != 1 {
		t.Fatalf("handler invoked %d times, want exactly 1 (the in-flight branch must not invoke)", got)
	}
}

func TestIdempotency_Expired_TreatedAsFresh(t *testing.T) {
	t.Parallel()
	store := newMemStore()
	store.ttl = 100 * time.Millisecond
	// Move "now" backwards so the first record is born already-aged.
	base := time.Now()
	store.now = func() time.Time { return base }

	var called atomic.Int32
	h := idempotency.Middleware(store)(echoHandler(t, &called))

	w1 := httptest.NewRecorder()
	h.ServeHTTP(w1, makeReq(`hello`, "k1"))

	// Advance the clock past the TTL — the next Claim must reclaim the slot.
	store.now = func() time.Time { return base.Add(time.Hour) }

	w2 := httptest.NewRecorder()
	h.ServeHTTP(w2, makeReq(`hello`, "k1"))

	if got := called.Load(); got != 2 {
		t.Fatalf("handler called %d times, want 2 (expired record should reclaim)", got)
	}
	if w2.Code != http.StatusCreated {
		t.Fatalf("second status = %d, want 201", w2.Code)
	}
}

// Compile-time check: memStore satisfies the Store interface. If the
// interface widens, this fails at compile time before the tests run.
var _ idempotency.Store = (*memStore)(nil)

// helper: silence unused-imports for sha256 / bytes when reorganising tests.
var (
	_ = sha256.Sum256
	_ = bytes.Equal
)
