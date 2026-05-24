// Package pgxpool wraps pgxpool.NewWithConfig with the per-acquire hook that
// binds Row-Level-Security to the request's tenant id. Without this hook,
// RLS silently returns empty result sets (anti-pattern guard, see
// docs/plans/mvp/03-tenants-slice.md).
//
// In pgx v5.9 the hook is `PrepareConn` (the renamed-from-`BeforeAcquire`
// callback fired before each pool acquisition); the foundations doc still
// calls it AfterAcquire because pgx renamed the API after the doc landed.
//
// Phase 3 keeps the package here (renaming to `pgx` would shadow the
// upstream import path) but the binding hook itself now lives in
// internal/platform/tenancy, where it shares package with MustAcquire and
// can be unit-tested without dragging the pool dependency in.
package pgxpool

import (
	"context"

	"github.com/jackc/pgx/v5/pgxpool"

	platformtenancy "github.com/omarss/saas/internal/platform/tenancy"
)

// Options configures NewPool. SkipTenantBinding is for the control plane,
// whose context carries deployment_id rather than tenant_id — the RLS
// machinery is data-plane-only.
type Options struct {
	// DSN — required.
	DSN string
	// MaxConns — defaults to whatever pgxpool.ParseConfig derives from the
	// DSN (usually 4 * GOMAXPROCS). Overridable for tuning.
	MaxConns int32
	// MinConns — keeps a warm pool floor. Default 0 (no minimum).
	MinConns int32
	// SkipTenantBinding — set true for the control plane; the AfterAcquire
	// hook is omitted so pools used outside tenancy do not pay the
	// per-acquire round-trip.
	SkipTenantBinding bool
}

// NewPool builds a pgxpool.Pool with the platform's standard PrepareConn
// hook (tenant.BindOnAcquire) unless opts.SkipTenantBinding is set. Returns
// the pool ready for queries.
func NewPool(ctx context.Context, opts Options) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(opts.DSN)
	if err != nil {
		return nil, err
	}
	if opts.MaxConns > 0 {
		cfg.MaxConns = opts.MaxConns
	}
	if opts.MinConns > 0 {
		cfg.MinConns = opts.MinConns
	}
	if !opts.SkipTenantBinding {
		cfg.PrepareConn = platformtenancy.BindOnAcquire
	}
	return pgxpool.NewWithConfig(ctx, cfg)
}

// NewWithTenantBinding is the Phase-2 entrypoint kept for backward-compat.
// New call sites should prefer NewPool(ctx, Options{DSN: dsn}).
func NewWithTenantBinding(ctx context.Context, dsn string) (*pgxpool.Pool, error) {
	return NewPool(ctx, Options{DSN: dsn})
}
