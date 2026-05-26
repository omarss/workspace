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
	"strings"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"

	db "github.com/omarss/saas/internal/dataplane/db/sqlc"
	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/crypto/envelope"
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

	// Envelope encryption client for the control plane. The controlplane
	// process runs on the host (not in cluster) so AppRole is the auth
	// method. role_id / secret_id come from a 0400 file under
	// /etc/saas/approle/ in production; from env vars in local dev.
	// SAAS_OPENBAO_DISABLED=1 skips the wiring entirely — any later PII
	// path then fails closed (ErrNoEncryptor) rather than silently leaking.
	encClient, err := newControlplaneEnvelopeClient(ctx)
	if err != nil {
		return fmt.Errorf("envelope client: %w", err)
	}
	if encClient != nil {
		defer func() {
			if closeErr := encClient.Close(); closeErr != nil {
				slog.Warn("envelope client close", "err", closeErr)
			}
		}()
	}
	// Phase 4 wires the client into the process; Phase 12 uses it for the
	// Deployment-provisioning code that touches secret/data/<deploymentID>.
	_ = encClient

	// Phase 12e — host provisioner selection. SAAS_HOST_PROVISIONER=true
	// flips on the composite provisioner that composes the four host
	// adapters into the AGENTS.md §6.2 13-step sequence. Default off so
	// `make dev` continues to boot without nginx/k3s/openbao wired —
	// matches the SAAS_RBAC_ENFORCE_DESTRUCTIVE Phase 8 pattern.
	//
	// The selected provisioner satisfies the deployments.Provisioner
	// interface; the deployments service (not yet wired in Phase 12e —
	// lands in the next operator-API phase) will receive it via DI.
	//
	// We do NOT instantiate the destroy reconciler unless the host
	// provisioner is selected — the reconciler needs the four adapters
	// to do its job, and standing it up against nil adapters would log
	// a continuous stream of misconfiguration errors.
	hostProvOn := os.Getenv("SAAS_HOST_PROVISIONER") == "true"
	if hostProvOn {
		slog.Info("controlplane: SAAS_HOST_PROVISIONER=true; host provisioner wiring is active")
		// The full wiring (4 adapters + sequence + reconciler) lives in
		// a separate file (provisioner_wiring.go) so this main stays
		// readable. Errors there are fatal — the operator opted in.
		stop, err := startHostProvisioner(ctx, pool, encClient)
		if err != nil {
			return fmt.Errorf("start host provisioner: %w", err)
		}
		defer stop()
	} else {
		slog.Info("controlplane: SAAS_HOST_PROVISIONER=false; using local-mode provisioner (Postgres only)")
	}
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

// envOr returns the env var value or the supplied default when unset.
func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// newControlplaneEnvelopeClient builds the OpenBao client used by the
// control-plane host process. AppRole auth is the only supported method
// here: the controlplane binary doesn't run in cluster so there's no SA
// JWT to use.
//
// role_id + secret_id sourcing:
//   - production: /etc/saas/approle/{role_id,secret_id} (0400 saas:saas)
//   - local dev:  OPENBAO_APPROLE_ROLE_ID + OPENBAO_APPROLE_SECRET_ID env
//     vars, populated by `make openbao-approle-creds`.
//
// SAAS_OPENBAO_DISABLED=1 short-circuits the wiring entirely; later PII
// persistence paths then surface ErrNoEncryptor.
func newControlplaneEnvelopeClient(ctx context.Context) (*envelope.Client, error) {
	if os.Getenv("SAAS_OPENBAO_DISABLED") == "1" {
		slog.Warn("envelope client disabled via SAAS_OPENBAO_DISABLED; PII writes will fail closed")
		return nil, nil
	}
	addr := envOr("BAO_ADDR", "http://localhost:8200")
	roleID, secretID, err := readApproleCreds()
	if err != nil {
		return nil, fmt.Errorf("read approle creds: %w", err)
	}
	if roleID == "" || secretID == "" {
		// Distinct from SAAS_OPENBAO_DISABLED: missing creds is a config
		// error, not an intentional skip. Surface it.
		return nil, fmt.Errorf("approle credentials not configured (set OPENBAO_APPROLE_ROLE_ID + OPENBAO_APPROLE_SECRET_ID or populate /etc/saas/approle/)")
	}
	return envelope.New(ctx, envelope.Options{
		Address:    addr,
		AuthMethod: envelope.AuthAppRole,
		RoleID:     roleID,
		SecretID:   secretID,
		CACertPath: os.Getenv("SAAS_OPENBAO_CA_CERT"),
	})
}

// readApproleCreds prefers env vars (local dev) then falls back to the
// production file paths under /etc/saas/approle/. The split lets the same
// binary boot locally and in production without code changes.
//
// Note on the env-var-secret rule (ruleguard / forbidigo): the bare
// os.Getenv ban targets generic secrets; the specific keys read here are
// AppRole identifiers used at exactly one boundary (controlplane bootstrap)
// and are the documented escape hatch in 01-foundations.md §5. The cmd/*
// excludes in .golangci.yml already cover this path.
func readApproleCreds() (roleID, secretID string, err error) {
	if r := os.Getenv("OPENBAO_APPROLE_ROLE_ID"); r != "" {
		s := os.Getenv("OPENBAO_APPROLE_SECRET_ID")
		return r, s, nil
	}
	r, rerr := os.ReadFile("/etc/saas/approle/role_id")
	if rerr != nil && !os.IsNotExist(rerr) {
		return "", "", fmt.Errorf("read role_id: %w", rerr)
	}
	s, serr := os.ReadFile("/etc/saas/approle/secret_id")
	if serr != nil && !os.IsNotExist(serr) {
		return "", "", fmt.Errorf("read secret_id: %w", serr)
	}
	return strings.TrimSpace(string(r)), strings.TrimSpace(string(s)), nil
}
