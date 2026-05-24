// Package tenancy contains the per-request tenant-binding mechanism that
// pairs with pgx and (later) Casbin. It is intentionally distinct from
// internal/dataplane/tenancy/, which owns the Tenant *resource* — this
// package is pure mechanism, no domain model.
//
// CONVENTIONS.md documents the deliberate name collision: platform/tenancy =
// mechanism (the GUC binding, the MustAcquire helper); dataplane/tenancy =
// resource (the Tenant CRUD module). Tests must import this package by
// alias when both are needed (`platformtenancy "...platform/tenancy"`).
package tenancy

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/saas/internal/platform/auth"
)

// ErrNoTenantInContext is returned by MustAcquire when the request context
// lacks a tenant. Surface this as 401 — never 500 — so monitoring catches
// missing-middleware bugs as auth failures rather than infrastructure noise.
var ErrNoTenantInContext = errors.New("tenancy: no tenant in context; refusing to acquire connection")

// BindOnAcquire is wired into pgxpool.Config.PrepareConn (named
// `AfterAcquire` in the foundations doc; pgx v5.9 renamed the hook). It
// emits SET app.current_tenant_id on every pooled connection acquisition,
// sourcing the value from auth.TenantFromContext.
//
// When the request context has no tenant we still set the GUC, but to the
// empty string — that is the SAFER failure mode: RLS-protected SELECTs return
// zero rows instead of leaking data from a previously-acquired connection's
// session state. Connectionless utility paths (/healthz, migrate, the outbox
// dispatcher) use context.Background() and accept the empty-GUC behaviour.
func BindOnAcquire(ctx context.Context, conn *pgx.Conn) (bool, error) {
	tid, _ := auth.TenantFromContext(ctx)
	// set_config(..., is_local=false) is session-scoped; pgxpool resets the
	// session on the next acquisition by re-running this hook. Phase 11c
	// will switch to SET LOCAL once per-request transactions land, so the
	// value is scoped to a single transaction.
	if _, err := conn.Exec(ctx, "SELECT set_config('app.current_tenant_id', $1, false)", tid); err != nil {
		return false, err
	}
	return true, nil
}

// MustAcquire wraps pgxpool.Pool.Acquire with the missing-tenant guard. Use
// for every tenant-bound query path. Returns ErrNoTenantInContext when the
// context has no tenant — handlers surface this as 401, not 500.
//
// Cross-cutting paths that legitimately have no tenant (migrate, /healthz,
// background dispatchers) call pool.Acquire directly with
// context.Background().
func MustAcquire(ctx context.Context, pool *pgxpool.Pool) (*pgxpool.Conn, error) {
	if _, ok := auth.TenantFromContext(ctx); !ok {
		return nil, ErrNoTenantInContext
	}
	return pool.Acquire(ctx)
}
