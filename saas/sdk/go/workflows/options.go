package workflows

// Option configures a single workflow invocation. Currently the only knob
// is idempotency-key override; additional knobs (e.g. per-request
// User-Agent, custom HTTP headers) can be added without breaking the
// option-pattern call sites.
type Option func(*options)

type options struct {
	// idemKey overrides the auto-generated idempotency key. Zero value
	// means "auto-generate via internal/idem".
	idemKey string
}

// WithIdempotencyKey overrides the auto-generated idempotency key for the
// next workflow call. Use this when retrying a failed call with the same
// key (per AGENTS.md §5.2: same key + same body returns the cached
// response; same key + different body returns 422).
func WithIdempotencyKey(key string) Option {
	return func(o *options) { o.idemKey = key }
}

func collect(opts []Option) options {
	var o options
	for _, opt := range opts {
		opt(&o)
	}
	return o
}
