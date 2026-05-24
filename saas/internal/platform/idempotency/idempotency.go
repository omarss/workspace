// Package idempotency provides the AGENTS.md section 5.2 Idempotency-Key
// middleware. The Phase 2 implementation is minimal: same-tenant + same-route +
// same-method + same-body-hash returns the cached response; same key with a
// different body returns 422 idempotency-key-conflict. Concurrent in-flight
// requests get 409. Real production hardening (cleanup cron, body streaming,
// wait-on-in-flight with backoff) lands in Phase 3 (ADR 010).
package idempotency

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"io"
	"net/http"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/problem"
)

// Store abstracts the persistence used by the middleware. Callers wire the
// pgx-backed store in cmd/dataplane; tests use an in-memory variant.
type Store interface {
	// Claim atomically inserts-or-fetches a record. Fresh=true means this
	// caller owns the slot and must proceed with the request.
	Claim(ctx context.Context, key Key, requestBodyHash []byte) (ClaimResult, error)
	// Finish records the response status / headers / body once the handler
	// produced it. Idempotent.
	Finish(ctx context.Context, recordID int64, status int, headers map[string]string, body []byte) error
}

// Key identifies one idempotency record.
type Key struct {
	TenantID       string
	IdempotencyKey string
	Route          string
	Method         string
}

// ClaimResult is the outcome of a Store.Claim call.
type ClaimResult struct {
	ID              int64
	Fresh           bool // true when we own this slot; false → cached/in-flight
	InFlight        bool
	BodyHash        []byte
	ResponseStatus  int
	ResponseHeaders map[string]string
	ResponseBody    []byte
}

// Middleware honours the Idempotency-Key header on POST and state-transition
// PATCH endpoints. GET / HEAD / OPTIONS / DELETE pass through.
func Middleware(store Store) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method != http.MethodPost && r.Method != http.MethodPatch {
				next.ServeHTTP(w, r)
				return
			}
			key := r.Header.Get("Idempotency-Key")
			if key == "" {
				// Idempotency is required at the spec level via OAS, but the
				// middleware itself permits the handler to handle the
				// missing-key case if the spec ever marks it optional.
				next.ServeHTTP(w, r)
				return
			}
			tid, ok := auth.TenantFromContext(r.Context())
			if !ok {
				writeProblem(w, http.StatusUnauthorized, "unauthorized", "missing tenant context", r.URL.Path)
				return
			}

			body, err := io.ReadAll(r.Body)
			if err != nil {
				writeProblem(w, http.StatusBadRequest, "bad-request", "could not read body", r.URL.Path)
				return
			}
			_ = r.Body.Close()
			r.Body = io.NopCloser(bytes.NewReader(body))
			sum := sha256.Sum256(body)

			res, err := store.Claim(r.Context(), Key{
				TenantID:       tid,
				IdempotencyKey: key,
				Route:          r.URL.Path,
				Method:         r.Method,
			}, sum[:])
			if err != nil {
				writeProblem(w, http.StatusInternalServerError, "internal", err.Error(), r.URL.Path)
				return
			}
			if !res.Fresh {
				if !bytes.Equal(res.BodyHash, sum[:]) {
					writeProblem(w, http.StatusUnprocessableEntity, "idempotency-key-conflict",
						"key reused with different body", r.URL.Path)
					return
				}
				if res.InFlight {
					writeProblem(w, http.StatusConflict, "idempotency-in-flight",
						"concurrent request still processing", r.URL.Path)
					return
				}
				for k, v := range res.ResponseHeaders {
					w.Header().Set(k, v)
				}
				if res.ResponseStatus != 0 {
					w.WriteHeader(res.ResponseStatus)
				}
				_, _ = w.Write(res.ResponseBody)
				return
			}

			rec := &recorder{ResponseWriter: w, status: http.StatusOK, headers: map[string]string{}}
			next.ServeHTTP(rec, r)
			// Capture only the response headers we care about replaying.
			for _, h := range []string{"Content-Type", "ETag", "Location"} {
				if v := w.Header().Get(h); v != "" {
					rec.headers[h] = v
				}
			}
			_ = store.Finish(r.Context(), res.ID, rec.status, rec.headers, rec.body.Bytes())
		})
	}
}

type recorder struct {
	http.ResponseWriter
	status      int
	wroteStatus bool
	headers     map[string]string
	body        bytes.Buffer
}

func (r *recorder) WriteHeader(code int) {
	r.status = code
	r.wroteStatus = true
	r.ResponseWriter.WriteHeader(code)
}

func (r *recorder) Write(b []byte) (int, error) {
	if !r.wroteStatus {
		r.wroteStatus = true
	}
	r.body.Write(b)
	return r.ResponseWriter.Write(b)
}

func writeProblem(w http.ResponseWriter, status int, slug, detail, instance string) {
	p := problem.New(slug, slug, status, detail, instance)
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(p)
}
