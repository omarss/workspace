// Command controlplane is the operator-only API server. Phase 1 exposed only
// /healthz; Phase 3 wires the shared platform stack (pgxpool, mock auth, outbox
// dispatcher, platform slog handler, OTel boot). The real operator endpoint
// surface lands in Phase 12.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
	"github.com/omarss/saas/internal/platform/auth"
	platformlog "github.com/omarss/saas/internal/platform/log"
	platformotel "github.com/omarss/saas/internal/platform/otel"
	"github.com/omarss/saas/internal/platform/outbox"
	"github.com/omarss/saas/internal/platform/pgxpool"
)

// version and commit are set at link time via -ldflags="-X main.version=..."
// in the release pipeline. Defaults are useful for `go run` and `go test`.
var (
	version = "dev"
	commit  = "unknown"
)

func main() {
	if err := run(); err != nil {
		slog.Error("controlplane exited", "err", err)
		os.Exit(1)
	}
}

func run() error {
	// platformlog.New installs the PII-redacting JSON slog handler from
	// internal/platform/log. Same rationale as cmd/dataplane: redaction has
	// to be the default, not opt-in. See AGENTS.md §18.5.
	logger := platformlog.New(platformlog.Options{Level: slog.LevelInfo})
	slog.SetDefault(logger)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Phase 3 OTel boot — no-op shutdown until the OTLP exporter wires up in
	// Phase 15. Centralising the call here keeps both binaries identical.
	shutdownOtel, err := platformotel.Init(ctx, "saas-controlplane")
	if err != nil {
		return fmt.Errorf("otel init: %w", err)
	}
	defer func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if shutdownErr := shutdownOtel(shutdownCtx); shutdownErr != nil {
			slog.Warn("otel shutdown returned error", "err", shutdownErr)
		}
	}()

	// CONTROLPLANE_DATABASE_URL points at the platform's *own* postgres
	// database (NOT a per-Deployment data-plane DB). The control plane stores
	// operator state, deployment metadata, and the outbox of provisioning
	// events. Tenants don't exist on this plane, so SkipTenantBinding is set
	// to true — the pgx PrepareConn hook would otherwise emit SET
	// app.current_tenant_id = '' on every acquire and confuse audits.
	dsn := os.Getenv("CONTROLPLANE_DATABASE_URL")
	if dsn == "" {
		return fmt.Errorf("CONTROLPLANE_DATABASE_URL is required")
	}
	pool, err := pgxpool.NewPool(ctx, pgxpool.Options{DSN: dsn, SkipTenantBinding: true})
	if err != nil {
		return fmt.Errorf("pgxpool: %w", err)
	}
	defer pool.Close()
	// The control plane currently shares the dataplane sqlc-generated queries
	// (db package) only so it can drive the outbox dispatcher off a Queries
	// handle bound to its own pool. Phase 12 introduces a dedicated
	// internal/controlplane/db/sqlc package; this borrow is temporary and
	// documented here to make the future split easy.
	queries := db.New(pool)

	// Outbox dispatcher for the control plane. Phase 3 wires the NoOp
	// publisher so the dispatcher loop exists and the goroutine lifecycle is
	// validated; deployment.provisioned / .updated / .rolled_back events land
	// in Phase 12 alongside the real publisher implementation.
	dispatcher := outbox.New(queries, outbox.NewLoggerPublisher(slog.Default()))
	go func() {
		if err := dispatcher.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
			slog.Error("controlplane outbox dispatcher exited", "err", err)
		}
	}()

	r := chi.NewRouter()
	r.Use(middleware.RequestID)
	// middleware.RealIP is deprecated in chi v5.3.0 (IP spoofing CVE).
	// Real-IP handling will be reintroduced as an explicit ProxyHeaders
	// middleware once we know the trusted-proxy CIDRs (nginx-only in homelab).
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(60 * time.Second))
	// Phase 3 reuses MockMiddleware so local dev / contract tests have a
	// uniform identity-injection mechanism. Operator endpoints in Phase 12
	// will gate on the `operators` scope set by Phase 14's real operator
	// JWT verifier — at which point this line swaps for the production
	// auth.OperatorJWTMiddleware. The mock is a NO-OP in `prod` builds via
	// build tag (see internal/platform/auth/middleware_prod.go).
	//
	// TODO Phase 13: replace with the operators-realm JWT verifier.
	r.Use(auth.MockMiddleware)

	// Idempotency middleware is intentionally NOT wired on the control plane
	// in Phase 3. The idempotency_record table is a data-plane migration; the
	// control-plane schema lands in Phase 12 with the deployments table and
	// its own idempotency_record. Wiring the dataplane-bound store here would
	// hit the wrong DB.
	//
	// TODO Phase 11: introduce migrations/controlplane/NNNNNN_idempotency.up.sql
	// and wire idempotency.Middleware(idempotency.NewPgxStore(queries)) here.

	r.Get("/healthz", func(w http.ResponseWriter, req *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprintf(w, `{"status":"ok","version":%q,"commit":%q}`, version, commit)
	})

	srv := &http.Server{
		Addr:              ":8080",
		Handler:           otelhttp.NewHandler(r, "saas-controlplane"),
		ReadHeaderTimeout: 5 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		slog.Info("controlplane listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	select {
	case <-ctx.Done():
	case err := <-errCh:
		return err
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return srv.Shutdown(shutdownCtx)
}
