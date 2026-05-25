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
	"github.com/omarss/saas/internal/dataplane/notifications"
	"github.com/omarss/saas/internal/dataplane/organizations"
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
// social-providers); Phase 6 adds the notifications handler (channels,
// workflows, send).
type strictServer struct {
	tenancyHandler       *tenancy.Handler
	identityHandler      *identity.Handler
	notificationsHandler *notifications.Handler
	organizationsHandler *organizations.Handler
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

// Notifications delegation -------------------------------------------------------

func (s *strictServer) ListNotificationChannels(ctx context.Context, r httpapi.ListNotificationChannelsRequestObject) (httpapi.ListNotificationChannelsResponseObject, error) {
	return s.notificationsHandler.ListNotificationChannels(ctx, r)
}

func (s *strictServer) CreateNotificationChannel(ctx context.Context, r httpapi.CreateNotificationChannelRequestObject) (httpapi.CreateNotificationChannelResponseObject, error) {
	return s.notificationsHandler.CreateNotificationChannel(ctx, r)
}

func (s *strictServer) GetNotificationChannel(ctx context.Context, r httpapi.GetNotificationChannelRequestObject) (httpapi.GetNotificationChannelResponseObject, error) {
	return s.notificationsHandler.GetNotificationChannel(ctx, r)
}

func (s *strictServer) UpdateNotificationChannel(ctx context.Context, r httpapi.UpdateNotificationChannelRequestObject) (httpapi.UpdateNotificationChannelResponseObject, error) {
	return s.notificationsHandler.UpdateNotificationChannel(ctx, r)
}

func (s *strictServer) DeleteNotificationChannel(ctx context.Context, r httpapi.DeleteNotificationChannelRequestObject) (httpapi.DeleteNotificationChannelResponseObject, error) {
	return s.notificationsHandler.DeleteNotificationChannel(ctx, r)
}

func (s *strictServer) RotateNotificationChannelCredentials(ctx context.Context, r httpapi.RotateNotificationChannelCredentialsRequestObject) (httpapi.RotateNotificationChannelCredentialsResponseObject, error) {
	return s.notificationsHandler.RotateNotificationChannelCredentials(ctx, r)
}

func (s *strictServer) ListNotificationWorkflows(ctx context.Context, r httpapi.ListNotificationWorkflowsRequestObject) (httpapi.ListNotificationWorkflowsResponseObject, error) {
	return s.notificationsHandler.ListNotificationWorkflows(ctx, r)
}

func (s *strictServer) RegisterNotificationWorkflow(ctx context.Context, r httpapi.RegisterNotificationWorkflowRequestObject) (httpapi.RegisterNotificationWorkflowResponseObject, error) {
	return s.notificationsHandler.RegisterNotificationWorkflow(ctx, r)
}

func (s *strictServer) UpdateNotificationWorkflow(ctx context.Context, r httpapi.UpdateNotificationWorkflowRequestObject) (httpapi.UpdateNotificationWorkflowResponseObject, error) {
	return s.notificationsHandler.UpdateNotificationWorkflow(ctx, r)
}

func (s *strictServer) ListNotifications(ctx context.Context, r httpapi.ListNotificationsRequestObject) (httpapi.ListNotificationsResponseObject, error) {
	return s.notificationsHandler.ListNotifications(ctx, r)
}

func (s *strictServer) SendNotification(ctx context.Context, r httpapi.SendNotificationRequestObject) (httpapi.SendNotificationResponseObject, error) {
	return s.notificationsHandler.SendNotification(ctx, r)
}

func (s *strictServer) GetNotification(ctx context.Context, r httpapi.GetNotificationRequestObject) (httpapi.GetNotificationResponseObject, error) {
	return s.notificationsHandler.GetNotification(ctx, r)
}

// Organizations delegation -------------------------------------------------------

func (s *strictServer) ListOrganizations(ctx context.Context, r httpapi.ListOrganizationsRequestObject) (httpapi.ListOrganizationsResponseObject, error) {
	return s.organizationsHandler.ListOrganizations(ctx, r)
}

func (s *strictServer) CreateOrganization(ctx context.Context, r httpapi.CreateOrganizationRequestObject) (httpapi.CreateOrganizationResponseObject, error) {
	return s.organizationsHandler.CreateOrganization(ctx, r)
}

func (s *strictServer) GetOrganization(ctx context.Context, r httpapi.GetOrganizationRequestObject) (httpapi.GetOrganizationResponseObject, error) {
	return s.organizationsHandler.GetOrganization(ctx, r)
}

func (s *strictServer) UpdateOrganization(ctx context.Context, r httpapi.UpdateOrganizationRequestObject) (httpapi.UpdateOrganizationResponseObject, error) {
	return s.organizationsHandler.UpdateOrganization(ctx, r)
}

func (s *strictServer) DeleteOrganization(ctx context.Context, r httpapi.DeleteOrganizationRequestObject) (httpapi.DeleteOrganizationResponseObject, error) {
	return s.organizationsHandler.DeleteOrganization(ctx, r)
}

func (s *strictServer) ListMembers(ctx context.Context, r httpapi.ListMembersRequestObject) (httpapi.ListMembersResponseObject, error) {
	return s.organizationsHandler.ListMembers(ctx, r)
}

func (s *strictServer) GetMember(ctx context.Context, r httpapi.GetMemberRequestObject) (httpapi.GetMemberResponseObject, error) {
	return s.organizationsHandler.GetMember(ctx, r)
}

func (s *strictServer) UpdateMember(ctx context.Context, r httpapi.UpdateMemberRequestObject) (httpapi.UpdateMemberResponseObject, error) {
	return s.organizationsHandler.UpdateMember(ctx, r)
}

func (s *strictServer) RemoveMember(ctx context.Context, r httpapi.RemoveMemberRequestObject) (httpapi.RemoveMemberResponseObject, error) {
	return s.organizationsHandler.RemoveMember(ctx, r)
}

func (s *strictServer) ListInvitations(ctx context.Context, r httpapi.ListInvitationsRequestObject) (httpapi.ListInvitationsResponseObject, error) {
	return s.organizationsHandler.ListInvitations(ctx, r)
}

func (s *strictServer) CreateInvitation(ctx context.Context, r httpapi.CreateInvitationRequestObject) (httpapi.CreateInvitationResponseObject, error) {
	return s.organizationsHandler.CreateInvitation(ctx, r)
}

func (s *strictServer) GetInvitation(ctx context.Context, r httpapi.GetInvitationRequestObject) (httpapi.GetInvitationResponseObject, error) {
	return s.organizationsHandler.GetInvitation(ctx, r)
}

func (s *strictServer) RevokeInvitation(ctx context.Context, r httpapi.RevokeInvitationRequestObject) (httpapi.RevokeInvitationResponseObject, error) {
	return s.organizationsHandler.RevokeInvitation(ctx, r)
}

func (s *strictServer) AcceptInvitation(ctx context.Context, r httpapi.AcceptInvitationRequestObject) (httpapi.AcceptInvitationResponseObject, error) {
	return s.organizationsHandler.AcceptInvitation(ctx, r)
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

	// Tenant service uses a fan-out publisher so the organizations
	// subscriber can react to tenant.created in-process. The outbox
	// remains the durable audit log; the in-memory fan-out is best-effort
	// (a future Phase 10 EventBus will replace it with a real subscriber
	// pool). Subscribers see the event AFTER the outbox row is persisted
	// so a subscriber crash never loses the audit row.
	tenantEventFanout := &tenantEventFanout{
		outbox: outbox.NewPgxEventPublisher(queries, deploymentID),
	}
	tenantSvc := tenancy.NewService(
		tenancy.NewPgxRepository(queries),
		tenantEventFanout,
	)

	// Phase 6 — Notifications module. Wired first so the Identity service
	// can take a non-nil Notify hook when NOTIFICATIONS_ENABLED=true.
	notificationsSvc := notifications.NewService(notifications.Config{
		Repo:         notifications.NewPgxRepository(queries, envAdapter, envAdapter, deploymentID),
		Events:       outbox.NewPgxEventPublisher(queries, deploymentID),
		DeploymentID: deploymentID,
	})

	var identityNotify identity.NotificationsHook
	if envOr("NOTIFICATIONS_ENABLED", "false") == "true" {
		identityNotify = &notificationsIdentityHook{svc: notificationsSvc}
		slog.Info("identity password-reset / email-verify routed through notifications module")
	} else {
		slog.Info("identity password-reset / email-verify uses keycloak SMTP fallback (NOTIFICATIONS_ENABLED unset)")
	}

	identitySvc := identity.NewService(identity.Config{
		Repo:         identity.NewPgxRepository(queries, envAdapter, envAdapter, deploymentID),
		Provider:     newKeycloakProvider(),
		Hasher:       identity.NewHMACEmailHasher(encClient),
		Events:       outbox.NewPgxEventPublisher(queries, deploymentID),
		Notify:       identityNotify,
		DeploymentID: deploymentID,
		Realm:        envOr("SAAS_KEYCLOAK_REALM", ""),
		ClientID:     envOr("SAAS_KEYCLOAK_CLIENT_ID", ""),
	})

	// Phase 7 — Organizations module. Members + invitations.
	//
	// The invitation accept path is a documented CONVENTIONS.md §2 exception:
	// it consumes a state token whose hash matches a single invitation row;
	// the caller's JWT tenant is constant-time-compared to inv.tenant_id
	// before the service mutates state. The repo uses the same envelope
	// adapter as Identity / Notifications.
	orgsService := organizations.NewService(organizations.Config{
		OrganizationRepo: organizations.NewPgxOrganizationRepo(queries),
		MemberRepo:       organizations.NewPgxMemberRepo(queries),
		InvitationRepo:   organizations.NewPgxInvitationRepo(queries, envAdapter, envAdapter, deploymentID),
		EmailHasher:      identity.NewHMACEmailHasher(encClient),
		Notifier:         organizations.NewNotificationsEmailNotifier(notificationsSvc),
		Tenants:          organizations.NewTenantLookupAdapter(tenantSvc),
		Users:            &identityUserLookupAdapter{svc: identitySvc},
		Events:           outbox.NewPgxEventPublisher(queries, deploymentID),
		DeploymentID:     deploymentID,
		PublicBaseURL:    envOr("SAAS_PUBLIC_BASE_URL", ""),
	})

	// Tenant.created subscriber: auto-creates the default Organization for
	// every new tenant. Phase 7 hooks it inline via the tenantEventFanout
	// publisher; a future Phase 10 EventBus will route the same event
	// through the same Handle method.
	tenantEventFanout.subscriber = organizations.NewTenantCreatedSubscriber(orgsService)

	srv := &strictServer{
		tenancyHandler:       tenancy.NewHandler(tenantSvc),
		identityHandler:      identity.NewHandler(identitySvc),
		notificationsHandler: notifications.NewHandler(notificationsSvc),
		organizationsHandler: organizations.NewHandler(orgsService),
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

// notificationsIdentityHook adapts notifications.Service to the
// identity.NotificationsHook interface. The adapter exists so Identity
// (Phase 5) does not need to import the Notifications package directly,
// keeping the modules dependency-decoupled and the test surface narrow.
type notificationsIdentityHook struct {
	svc *notifications.Service
}

func (h *notificationsIdentityHook) SendPasswordReset(ctx context.Context, tenantID, userID, resetURL string, ttlMinutes int) error {
	_, err := h.svc.SendPasswordReset(ctx, tenantID, userID, resetURL, ttlMinutes)
	return err
}

func (h *notificationsIdentityHook) SendEmailVerify(ctx context.Context, tenantID, userID, verifyURL string, ttlMinutes int) error {
	_, err := h.svc.SendEmailVerify(ctx, tenantID, userID, verifyURL, ttlMinutes)
	return err
}

// identityUserLookupAdapter bridges organizations.UserLookup to the
// Identity service. The adapter is here (not in the organizations
// package) so the organizations module does not import identity directly
// — keeps the dep graph one-way and the test surface narrow.
type identityUserLookupAdapter struct {
	svc *identity.Service
}

func (a *identityUserLookupAdapter) LookupUser(ctx context.Context, tenantID, userID string) (organizations.UserInfo, error) {
	u, err := a.svc.Get(ctx, tenantID, userID)
	if err != nil {
		return organizations.UserInfo{}, err
	}
	return organizations.UserInfo{
		UserID: u.ID,
		Email:  u.Email,
		Name:   u.Name,
	}, nil
}

// tenantEventFanout duplicates every event into the outbox (durable audit
// log) AND a single in-process subscriber. The fan-out is intentionally
// best-effort: a subscriber error is logged but does NOT roll back the
// outbox write. The outbox stays authoritative; subscribers are reactive.
type tenantEventFanout struct {
	outbox interface {
		Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error
	}
	subscriber *organizations.TenantCreatedSubscriber
}

func (f *tenantEventFanout) Publish(ctx context.Context, eventType, tenantID string, payload map[string]any) error {
	if err := f.outbox.Publish(ctx, eventType, tenantID, payload); err != nil {
		return err
	}
	if f.subscriber != nil && eventType == "tenant.created" {
		if err := f.subscriber.Handle(ctx, payload); err != nil {
			slog.Warn("tenant.created subscriber handle failed", "tenant_id", tenantID, "err", err)
		}
	}
	return nil
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
