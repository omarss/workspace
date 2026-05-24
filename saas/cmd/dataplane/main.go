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
	"github.com/omarss/saas/internal/dataplane/identity"
	"github.com/omarss/saas/internal/dataplane/tenancy"
	"github.com/omarss/saas/internal/platform/auth"
	platformcrypto "github.com/omarss/saas/internal/platform/crypto"
	"github.com/omarss/saas/internal/platform/crypto/envelope"
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
// tenancy handler; Phase 5 adds the identity handler (/v1/users +
// social-providers); later phases extend this with organisations, etc.
type strictServer struct {
	tenancyHandler  *tenancy.Handler
	identityHandler *identity.Handler
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

// Identity delegation -----------------------------------------------------------

func (s *strictServer) ListUsers(ctx context.Context, r httpapi.ListUsersRequestObject) (httpapi.ListUsersResponseObject, error) {
	return s.identityHandler.ListUsers(ctx, r)
}

func (s *strictServer) CreateUser(ctx context.Context, r httpapi.CreateUserRequestObject) (httpapi.CreateUserResponseObject, error) {
	return s.identityHandler.CreateUser(ctx, r)
}

func (s *strictServer) GetUser(ctx context.Context, r httpapi.GetUserRequestObject) (httpapi.GetUserResponseObject, error) {
	return s.identityHandler.GetUser(ctx, r)
}

func (s *strictServer) UpdateUser(ctx context.Context, r httpapi.UpdateUserRequestObject) (httpapi.UpdateUserResponseObject, error) {
	return s.identityHandler.UpdateUser(ctx, r)
}

func (s *strictServer) DeleteUser(ctx context.Context, r httpapi.DeleteUserRequestObject) (httpapi.DeleteUserResponseObject, error) {
	return s.identityHandler.DeleteUser(ctx, r)
}

func (s *strictServer) DisableUser(ctx context.Context, r httpapi.DisableUserRequestObject) (httpapi.DisableUserResponseObject, error) {
	return s.identityHandler.DisableUser(ctx, r)
}

func (s *strictServer) EnableUser(ctx context.Context, r httpapi.EnableUserRequestObject) (httpapi.EnableUserResponseObject, error) {
	return s.identityHandler.EnableUser(ctx, r)
}

func (s *strictServer) TriggerPasswordReset(ctx context.Context, r httpapi.TriggerPasswordResetRequestObject) (httpapi.TriggerPasswordResetResponseObject, error) {
	return s.identityHandler.TriggerPasswordReset(ctx, r)
}

func (s *strictServer) TriggerEmailVerify(ctx context.Context, r httpapi.TriggerEmailVerifyRequestObject) (httpapi.TriggerEmailVerifyResponseObject, error) {
	return s.identityHandler.TriggerEmailVerify(ctx, r)
}

func (s *strictServer) ListSocialProviders(ctx context.Context, r httpapi.ListSocialProvidersRequestObject) (httpapi.ListSocialProvidersResponseObject, error) {
	return s.identityHandler.ListSocialProviders(ctx, r)
}

func (s *strictServer) LinkSocialProvider(ctx context.Context, r httpapi.LinkSocialProviderRequestObject) (httpapi.LinkSocialProviderResponseObject, error) {
	return s.identityHandler.LinkSocialProvider(ctx, r)
}

func (s *strictServer) UnlinkSocialProvider(ctx context.Context, r httpapi.UnlinkSocialProviderRequestObject) (httpapi.UnlinkSocialProviderResponseObject, error) {
	return s.identityHandler.UnlinkSocialProvider(ctx, r)
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

	// Envelope encryption client. Data-plane pods authenticate to OpenBao
	// via the Kubernetes auth method (the in-pod SA JWT maps to a role
	// named after this deployment_id; Phase 12d provisions the role).
	// Local dev sets SAAS_OPENBAO_DISABLED=1 to skip this — the persistence
	// walker degrades to ErrNoEncryptor at the first call, which is loud
	// rather than silent.
	encClient, err := newEnvelopeClient(ctx, deploymentID)
	if err != nil {
		return fmt.Errorf("envelope client: %w", err)
	}
	if encClient != nil {
		defer func() {
			if err := encClient.Close(); err != nil {
				slog.Warn("envelope client close", "err", err)
			}
		}()
	}
	// Wire envelope encryption into the Identity module. tenant.Metadata is
	// not PII per AGENTS.md §18.7 so the tenancy module stays plaintext;
	// User.Email + Name + Phone go through the strict walker.
	envAdapter := platformcrypto.NewEnvelopeAdapter(encClient)

	tenantSvc := tenancy.NewService(
		tenancy.NewPgxRepository(queries),
		outbox.NewPgxEventPublisher(queries, deploymentID),
	)

	identitySvc := identity.NewService(identity.Config{
		Repo:         identity.NewPgxRepository(queries, envAdapter, envAdapter, deploymentID),
		Provider:     newKeycloakProvider(),
		Hasher:       identity.NewHMACEmailHasher(encClient),
		Events:       outbox.NewPgxEventPublisher(queries, deploymentID),
		DeploymentID: deploymentID,
		Realm:        envOr("SAAS_KEYCLOAK_REALM", ""),
		ClientID:     envOr("SAAS_KEYCLOAK_CLIENT_ID", ""),
	})

	srv := &strictServer{
		tenancyHandler:  tenancy.NewHandler(tenantSvc),
		identityHandler: identity.NewHandler(identitySvc),
	}

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
	// Layer 1 (auth): JWT verifier first (Phase 5), then the dev-only mock
	// middleware. In production the mock is a compile-time no-op (build tag
	// `prod`), so only the JWT path executes. In dev the chain is:
	//   1. JWT verifier — sets Principal from a Bearer token if present.
	//   2. Mock middleware — sets Principal from X-Mock-Tenant-Id otherwise.
	// The JWT verifier is wired only when OIDC_JWKS_URL is set; without it
	// dev boots with mock-only auth (Phase 5 plan §5.7).
	if verifier, vErr := newJWTVerifier(ctx); vErr != nil {
		return fmt.Errorf("jwt verifier: %w", vErr)
	} else if verifier != nil {
		slog.Info("JWT verifier wired", "issuer", os.Getenv("OIDC_ISSUER"), "audience", os.Getenv("OIDC_AUDIENCE"))
		r.Use(verifier.Middleware)
	} else {
		slog.Warn("OIDC_JWKS_URL not set; running with mock-only auth (dev mode)")
	}
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

// newEnvelopeClient wires the data-plane envelope client using Kubernetes
// auth. In cluster the in-pod SA JWT is used; the role name MUST equal the
// deployment_id (Phase 12d provisions the role). Returns nil when
// SAAS_OPENBAO_DISABLED=1 so local dev without a running bao still boots —
// any actual PII persistence path then returns ErrNoEncryptor.
func newEnvelopeClient(ctx context.Context, deploymentID string) (*envelope.Client, error) {
	if os.Getenv("SAAS_OPENBAO_DISABLED") == "1" {
		slog.Warn("envelope client disabled via SAAS_OPENBAO_DISABLED; PII writes will fail closed")
		return nil, nil
	}
	addr := envOr("BAO_ADDR", "http://localhost:8200")
	jwtPath := envOr("SAAS_OPENBAO_SA_TOKEN_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/token")
	return envelope.New(ctx, envelope.Options{
		Address:    addr,
		AuthMethod: envelope.AuthKubernetes,
		Role:       deploymentID,
		SAJWTPath:  jwtPath,
		CACertPath: os.Getenv("SAAS_OPENBAO_CA_CERT"),
	})
}

// newKeycloakProvider wires the gocloak v14 adapter using the per-deployment
// Keycloak service-account configured via env (KEYCLOAK_BASE_URL +
// KEYCLOAK_ADMIN_CLIENT_ID + KEYCLOAK_ADMIN_CLIENT_SECRET).
//
// When KEYCLOAK_BASE_URL is empty (local dev without Keycloak) the function
// returns a stub provider whose every call returns an error — that surfaces
// as ErrProviderUnavailable from the service, not a silent success. The
// service-level unit tests substitute their own provider via the Config.
func newKeycloakProvider() identity.IdentityProvider {
	baseURL := os.Getenv("KEYCLOAK_BASE_URL")
	if baseURL == "" {
		slog.Warn("KEYCLOAK_BASE_URL not set; identity provider returns ErrProviderUnavailable for every call")
		return stubIdentityProvider{}
	}
	clientID := envOr("KEYCLOAK_ADMIN_CLIENT_ID", "saas-data-admin")
	clientSecret := os.Getenv("KEYCLOAK_ADMIN_CLIENT_SECRET")
	masterRealm := envOr("KEYCLOAK_ADMIN_REALM", "master")
	// NOTE: the token fetcher below intentionally returns an error in this
	// build. The full LoginClient call needs the per-deployment client
	// credentials provisioned by Phase 12d's bootstrap runbook. Until then
	// the service surfaces ErrProviderUnavailable, which the §17.3 matrix
	// already covers via the fake provider.
	_ = masterRealm
	return identity.NewKeycloakProvider(baseURL, func(ctx context.Context) (string, error) {
		// LoginClient hits /realms/{master}/protocol/openid-connect/token with
		// the client_credentials grant. Per Phase 5 plan anti-patterns we never
		// LoginAdmin — only service-account client_credentials.
		_, _, _ = ctx, clientID, clientSecret // referenced via closure
		return "", errors.New("identity: KeycloakProvider token fetcher not wired (Phase 5c)")
	})
}

// stubIdentityProvider is the dev-mode no-op provider. Every method returns
// an error so callers fail closed.
type stubIdentityProvider struct{}

func (stubIdentityProvider) CreateUser(_ context.Context, _ string, _ identity.User) (string, error) {
	return "", errors.New("identity: keycloak provider unavailable (KEYCLOAK_BASE_URL unset)")
}

func (stubIdentityProvider) UpdateUser(_ context.Context, _, _, _, _ string) error {
	return errors.New("identity: keycloak provider unavailable")
}

func (stubIdentityProvider) SetEnabled(_ context.Context, _, _ string, _ bool) error {
	return errors.New("identity: keycloak provider unavailable")
}

func (stubIdentityProvider) TriggerPasswordReset(_ context.Context, _, _ string) error {
	return errors.New("identity: keycloak provider unavailable")
}

func (stubIdentityProvider) TriggerEmailVerify(_ context.Context, _, _ string) error {
	return errors.New("identity: keycloak provider unavailable")
}

func (stubIdentityProvider) DeleteUser(_ context.Context, _, _ string) error {
	return errors.New("identity: keycloak provider unavailable")
}

func (stubIdentityProvider) StartSocialLogin(_ context.Context, _ identity.StartSocialLoginArgs) (string, error) {
	return "", errors.New("identity: keycloak provider unavailable")
}

func (stubIdentityProvider) ListIdentityProviderLinks(_ context.Context, _, _ string) ([]identity.Provider, error) {
	return nil, errors.New("identity: keycloak provider unavailable")
}

func (stubIdentityProvider) UnlinkIdentityProvider(_ context.Context, _, _ string, _ identity.Provider) error {
	return errors.New("identity: keycloak provider unavailable")
}

// newJWTVerifier wires the Phase-5 JWT verifier when OIDC_JWKS_URL,
// OIDC_ISSUER, and OIDC_AUDIENCE are all populated. Returns (nil, nil) when
// the env is incomplete so dev boots without a Keycloak instance running.
// Returns an error only when the cache initial prime fails — that's a
// configuration-vs-availability issue worth failing closed on at boot.
func newJWTVerifier(ctx context.Context) (*auth.JWTVerifier, error) {
	jwksURL := os.Getenv("OIDC_JWKS_URL")
	issuer := os.Getenv("OIDC_ISSUER")
	audience := os.Getenv("OIDC_AUDIENCE")
	if jwksURL == "" || issuer == "" || audience == "" {
		return nil, nil
	}
	return auth.NewJWTVerifier(ctx, jwksURL, issuer, audience)
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
