package apikeys

import (
	"math"
	"sync"
	"time"
)

// RateLimiter is an in-memory per-key token bucket. Each api_key gets
// a bucket sized to its rate_limit_per_minute (or the deployment
// default when null); tokens refill linearly at limit/60 tokens per
// second.
//
// MVP is single-replica per AGENTS.md §15; multi-replica path is the
// same Redis watcher ADR 005 documents for Casbin. This implementation
// stays compact and reuses the existing in-process sync.Mutex.
type RateLimiter struct {
	defaultRPM int

	mu      sync.Mutex
	buckets map[string]*tokenBucket
	now     func() time.Time
}

type tokenBucket struct {
	tokens float64
	last   time.Time
	limit  int
}

// DefaultRPM is the fallback bucket size when an api_key has no
// rate_limit_per_minute override. Configurable per Deployment via the
// SAAS_DEFAULT_API_KEY_RPM env var (read in main.go); the value here
// matches docs/plans/mvp/10-api-keys.md Open Question #2.
const DefaultRPM = 600

// NewRateLimiter constructs a limiter with the supplied default RPM.
// Pass 0 to use DefaultRPM.
func NewRateLimiter(defaultRPM int) *RateLimiter {
	if defaultRPM <= 0 {
		defaultRPM = DefaultRPM
	}
	return &RateLimiter{
		defaultRPM: defaultRPM,
		buckets:    map[string]*tokenBucket{},
		now:        time.Now,
	}
}

// WithClock substitutes the limiter's clock; tests only.
func (r *RateLimiter) WithClock(now func() time.Time) *RateLimiter {
	r.now = now
	return r
}

// Allow consumes one token from the bucket for apiKeyID. perKeyRPM is
// the row's rate_limit_per_minute override (nil = use default).
// Returns (allowed, info); when allowed is false the info struct has
// retry-after seconds populated for the 429 response.
func (r *RateLimiter) Allow(apiKeyID string, perKeyRPM *int) (bool, RateLimitInfo) {
	limit := r.defaultRPM
	if perKeyRPM != nil && *perKeyRPM > 0 {
		limit = *perKeyRPM
	}
	r.mu.Lock()
	defer r.mu.Unlock()

	now := r.now()
	b, ok := r.buckets[apiKeyID]
	if !ok {
		b = &tokenBucket{tokens: float64(limit), last: now, limit: limit}
		r.buckets[apiKeyID] = b
	}
	// Refill since last touch.
	elapsed := now.Sub(b.last).Seconds()
	if elapsed > 0 {
		refill := (float64(b.limit) / 60.0) * elapsed
		b.tokens = math.Min(float64(b.limit), b.tokens+refill)
		b.last = now
	}
	// Resize the bucket if the row's limit changed since last call.
	if b.limit != limit {
		b.limit = limit
		if b.tokens > float64(limit) {
			b.tokens = float64(limit)
		}
	}
	if b.tokens < 1.0 {
		// Compute retry-after as the seconds needed to accumulate
		// one token. retry == 60 / limit.
		retry := int(math.Ceil(60.0 / float64(limit)))
		if retry < 1 {
			retry = 1
		}
		return false, RateLimitInfo{Limit: limit, Remaining: 0, RetryAfter: retry}
	}
	b.tokens -= 1.0
	return true, RateLimitInfo{Limit: limit, Remaining: int(b.tokens), RetryAfter: 0}
}
