// Command dataplane is the per-Deployment data-plane API server. Phase 2
// adds the /v1/tenants vertical slice on top of Phase 1's /healthz. One
// dataplane process per Deployment, bound to one Postgres DB.
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
	httpapi "github.com/omarss/saas/internal/dataplane/httpapi" // package dataplaneapi
	"github.com/omarss/saas/internal/dataplane/tenancy"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/idempotency"
	platformlog "github.com/omarss/saas/internal/platform/log"
	platformotel "github.com/omarss/saas/internal/platform/otel"
	"github.com/omarss/saas/internal/platform/outbox"
	"github.com/omarss/saas/internal/platform/pgxpool"
)

var (
	version = "dev"
	commit  = "unknown"
)

func main() {
	if err := run(); err != nil {
		slog.Error("dataplane exited", "err", err)
		os.Exit(1)
	}
}

// strictServer composes the per-module handlers into the single
// StrictServerInterface oapi-codegen expects. Phase 2 ships /healthz and the
// tenancy handler; later phases extend this with identity, organisations, etc.
type strictServer struct {
	tenancyHandler *tenancy.Handler
}

// GetHealthz implements the Phase-1 liveness probe inline so the data plane
// remains responsive when the DB is unreachable.
func (s *strictServer) GetHealthz(_ context.Context, _ httpapi.GetHealthzRequestObject) (httpapi.GetHealthzResponseObject, error) {
	v := version
	c := commit
	return httpapi.GetHealthz200JSONResponse{
		Status:  httpapi.Ok,
		Version: &v,
		Commit:  &c,
	}, nil
}

// Tenants delegation -----------------------------------------------------------

func (s *strictServer) ListTenants(ctx context.Context, r httpapi.ListTenantsRequestObject) (httpapi.ListTenantsResponseObject, error) {
	return s.tenancyHandler.ListTenants(ctx, r)
}

func (s *strictServer) CreateTenant(ctx context.Context, r httpapi.CreateTenantRequestObject) (httpapi.CreateTenantResponseObject, error) {
	return s.tenancyHandler.CreateTenant(ctx, r)
}

func (s *strictServer) GetTenant(ctx context.Context, r httpapi.GetTenantRequestObject) (httpapi.GetTenantResponseObject, error) {
	return s.tenancyHandler.GetTenant(ctx, r)
}

func (s *strictServer) UpdateTenant(ctx context.Context, r httpapi.UpdateTenantRequestObject) (httpapi.UpdateTenantResponseObject, error) {
	return s.tenancyHandler.UpdateTenant(ctx, r)
}

func (s *strictServer) DeleteTenant(ctx context.Context, r httpapi.DeleteTenantRequestObject) (httpapi.DeleteTenantResponseObject, error) {
	return s.tenancyHandler.DeleteTenant(ctx, r)
}

func run() error {
	// platformlog.New installs the PII-redacting JSON slog handler from
	// internal/platform/log. Every log record passing through slog.Default()
	// goes through the redactor's ReplaceAttr hook, satisfying AGENTS.md
	// §18.5 (PII never logged plaintext). Without this default the per-call
	// redactor is silently bypassed.
	logger := platformlog.New(platformlog.Options{Level: slog.LevelInfo})
	slog.SetDefault(logger)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Wire the platform OTel skeleton. Phase 3 ships a no-op shutdown fn so
	// cmd/* boots stay identical even before the real OTLP exporter lands in
	// Phase 15 (DX polish). The defer ensures spans flush on SIGTERM.
	shutdownOtel, err := platformotel.Init(ctx, "saas-dataplane")
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

	deploymentID := envOr("SAAS_DEPLOYMENT_ID", "dep_local_dev")
	dsn := os.Getenv("DATAPLANE_DATABASE_URL")
	if dsn == "" {
		return fmt.Errorf("DATAPLANE_DATABASE_URL is required")
	}

	pool, err := pgxpool.NewPool(ctx, pgxpool.Options{DSN: dsn})
	if err != nil {
		return fmt.Errorf("pgxpool: %w", err)
	}
	defer pool.Close()
	queries := db.New(pool)

	tenantSvc := tenancy.NewService(
		tenancy.NewPgxRepository(queries),
		outbox.NewPgxEventPublisher(queries, deploymentID),
	)
	srv := &strictServer{tenancyHandler: tenancy.NewHandler(tenantSvc)}

	// Outbox dispatcher: one goroutine per process. Phase 2 publisher is a
	// stdout logger; real delivery (HTTP/NATS) is post-MVP.
	dispatcher := outbox.New(queries, outbox.NewLoggerPublisher(slog.Default()))
	go func() {
		if err := dispatcher.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
			slog.Error("outbox dispatcher exited", "err", err)
		}
	}()

	// Idempotency cleanup ticker. ADR 010 mandates a periodic sweep so the
	// 24h-TTL'd records don't accumulate. Interval is overridable via
	// IDEMPOTENCY_CLEANUP_INTERVAL for fast-test scenarios.
	cleanupInterval := envDuration("IDEMPOTENCY_CLEANUP_INTERVAL", idempotency.DefaultCleanupInterval)
	cleaner := idempotency.NewCleaner(queries, cleanupInterval, slog.Default())
	go func() {
		if err := cleaner.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
			slog.Error("idempotency cleaner exited", "err", err)
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
	// Layer 1 (auth): dev-only mock middleware in Phase 2; real JWT lands in Phase 5.
	r.Use(auth.MockMiddleware)
	// Idempotency-Key handling for POST + state-transition PATCH.
	r.Use(idempotency.Middleware(idempotency.NewPgxStore(queries)))

	httpapi.HandlerFromMux(httpapi.NewStrictHandler(srv, nil), r)

	httpSrv := &http.Server{
		Addr:              ":9090",
		Handler:           otelhttp.NewHandler(r, "saas-dataplane"),
		ReadHeaderTimeout: 5 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		slog.Info("dataplane listening", "addr", httpSrv.Addr)
		if err := httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
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
	return httpSrv.Shutdown(shutdownCtx)
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// envDuration reads an env var as a duration ("250ms", "5s", "15m"). On parse
// error or absence, returns the supplied default.
func envDuration(k string, def time.Duration) time.Duration {
	v := os.Getenv(k)
	if v == "" {
		return def
	}
	d, err := time.ParseDuration(v)
	if err != nil {
		slog.Warn("invalid duration env var; using default", "key", k, "value", v, "default", def)
		return def
	}
	return d
}
