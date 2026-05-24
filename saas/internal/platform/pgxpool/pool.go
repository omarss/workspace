// Package pgxpool wraps pgxpool.NewWithConfig with the per-acquire hook that
// binds Row-Level-Security to the request's tenant id. Without this hook,
// RLS silently returns empty result sets (anti-pattern guard, see
// docs/plans/mvp/03-tenants-slice.md).
//
// In pgx v5.9 the hook is `PrepareConn` (the renamed-from-`BeforeAcquire`
// callback fired before each pool acquisition); the foundations doc still
// calls it AfterAcquire because pgx renamed the API after the doc landed.
//
// Phase 2 wires this from cmd/dataplane/main.go for the tenancy slice. Phase 3
// promotes the package into internal/platform/pgx/ alongside the otelpgx
// tracer.
package pgxpool

import (
	"context"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/saas/internal/platform/auth"
)

// NewWithTenantBinding constructs a pool that emits
// `SELECT set_config('app.current_tenant_id', $1, false)` on every acquired
// connection — sourced from auth.TenantFromContext. Connections used without
// a tenant in context get an empty GUC, which makes RLS-protected SELECTs
// return zero rows (the safer failure mode).
func NewWithTenantBinding(ctx context.Context, dsn string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, err
	}
	cfg.PrepareConn = func(ctx context.Context, conn *pgx.Conn) (bool, error) {
		tid, _ := auth.TenantFromContext(ctx)
		// set_config(..., is_local=false) is session-scoped; pgxpool returns
		// connections to the pool so the value resets on the next acquire.
		// Phase 11c switches this to SET LOCAL once per-request transactions land.
		_, err := conn.Exec(ctx, "SELECT set_config('app.current_tenant_id', $1, false)", tid)
		if err != nil {
			return false, err
		}
		return true, nil
	}
	return pgxpool.NewWithConfig(ctx, cfg)
}
