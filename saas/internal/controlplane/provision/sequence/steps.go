package sequence

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/omarss/saas/internal/controlplane/deployments"
	"github.com/omarss/saas/internal/controlplane/provision/k3s"
	"github.com/omarss/saas/internal/controlplane/provision/nginx"
	"github.com/omarss/saas/internal/controlplane/provision/openbao"
	"github.com/omarss/saas/internal/controlplane/provision/postgres"
)

// BootstrapStore is the place the seed step writes the one-time
// BootstrapResult so the calling handler can retrieve it after Run.
// In-memory by default; production wires the same in-memory store
// because the secret is never persisted (it lives only for the
// duration of the create handler).
type BootstrapStore interface {
	Put(deploymentID string, b deployments.BootstrapResult)
	Get(deploymentID string) (deployments.BootstrapResult, bool)
	Delete(deploymentID string)
}

// MemoryBootstrapStore satisfies BootstrapStore with a plain map.
type MemoryBootstrapStore struct {
	entries map[string]deployments.BootstrapResult
}

// NewMemoryBootstrapStore returns a fresh store.
func NewMemoryBootstrapStore() *MemoryBootstrapStore {
	return &MemoryBootstrapStore{entries: map[string]deployments.BootstrapResult{}}
}

// Put implements BootstrapStore.
func (s *MemoryBootstrapStore) Put(deploymentID string, b deployments.BootstrapResult) {
	s.entries[deploymentID] = b
}

// Get implements BootstrapStore.
func (s *MemoryBootstrapStore) Get(deploymentID string) (deployments.BootstrapResult, bool) {
	b, ok := s.entries[deploymentID]
	return b, ok
}

// Delete implements BootstrapStore.
func (s *MemoryBootstrapStore) Delete(deploymentID string) {
	delete(s.entries, deploymentID)
}

// EventPublisher is the narrow port the orchestrator needs to emit
// `deployment.provisioned` and friends to the control-plane outbox.
type EventPublisher interface {
	Publish(ctx context.Context, eventType, deploymentID string, payload map[string]any) error
}

// StatusUpdater is the narrow port the orchestrator needs to flip
// deployment.status. Satisfied by deployments.Repository.
type StatusUpdater interface {
	UpdateStatus(ctx context.Context, id string, status deployments.Status) error
}

// Adapters bundles the four host adapters + the seeder + the side
// channels (bootstrap store, events, status updater) the orchestrator
// needs to compose the §6.2 sequence. Holding the bundle in one
// struct keeps DefaultSteps's signature short.
type Adapters struct {
	OpenBao  openbao.Adapter
	Postgres postgres.Adapter
	K3s      k3s.Adapter
	Nginx    nginx.Adapter

	// Seeder seeds the bootstrap tenant + admin + api key in the
	// freshly-migrated per-Deployment DB.
	Seeder deployments.BootstrapSeeder

	// BootstrapStore receives the one-time bootstrap result so the
	// handler can extract it after Run().
	BootstrapStore BootstrapStore

	// Events publishes deployment.provisioned + .destroyed + .restored
	// + .upgraded + .rolled_back + .purged + .keys_frozen.
	Events EventPublisher

	// Status flips deployment.status after step 12.
	Status StatusUpdater

	// PostgresAdminDSN is the superuser-equivalent DSN passed to the
	// postgres adapter. Read once from env at HostProvisioner
	// construction; never logged.
	PostgresAdminDSN string

	// PostgresHostExternal optionally overrides the host:port the
	// adapter embeds in the per-Deployment DSN. Empty = use admin DSN's
	// host.
	PostgresHostExternal string

	// K3sNodePort is the port the data-plane pod listens on (NodePort
	// service). For MVP we hard-code 30080 for the first deployment +
	// allocate sequentially; the deployments repo will own the
	// allocation logic in a later phase. Phase 12e accepts a single
	// fixed value via env to unblock CP-9.
	K3sNodePort int

	// K3sHostCIDRs are the CIDRs the host nginx, host Postgres, host
	// OpenBao live in (k3s NetworkPolicy ingress/egress allow lists).
	K3sHostNginxCIDR    string
	K3sHostPostgresCIDR string
	K3sHostOpenBaoCIDR  string

	// NginxOpsEmail is the certbot --email value. Operator-supplied
	// once at controlplane startup.
	NginxOpsEmail string

	// HealthCheckClient pings the public /healthz URL. Defaults to
	// http.DefaultClient with a 5 s per-attempt timeout; tests inject
	// a fake.
	HealthCheckClient HTTPClient

	// HealthCheckTimeout is the wall-clock cap on the healthz poll.
	// Default 2 min.
	HealthCheckTimeout time.Duration

	// HealthCheckInterval is the poll spacing. Default 5 s.
	HealthCheckInterval time.Duration

	// EnvelopeKVPut writes the per-Deployment Postgres password to
	// OpenBao KV at secret/data/<dep_id>/postgres/app_password. The
	// data-plane pod reads it via its envelope.Client.
	//
	// nil means: skip the KV write (used by tests that don't wire
	// envelope client + want to verify only the §6.2 ordering).
	EnvelopeKVPut func(ctx context.Context, deploymentID, path string, data map[string]any) error
}

// HTTPClient narrows http.Client so tests can substitute a recorder.
type HTTPClient interface {
	Do(req *http.Request) (*http.Response, error)
}

// DefaultSteps returns the §6.2 13-step sequence with each step's Run
// + Rollback closing over `a`. Caller is responsible for `a` being
// fully populated (nil adapters → a Run that returns ErrAdapterNil
// inside the step rather than at construction; the orchestrator
// surfaces the error via the ledger).
func DefaultSteps(a Adapters) []Step {
	return []Step{
		stepValidate(),
		stepAllocateID(),
		stepRecordDesiredState(),
		stepOpenBao(a),
		stepPostgres(a),
		stepSeed(a),
		stepRenderK3s(a),
		stepK3sApply(a),
		stepRenderNginx(),
		stepNginxApply(a),
		stepHealthz(a),
		stepFlipActive(a),
		stepReturnBootstrap(),
	}
}

// 1. validate — handler already enforced slug rules; the step exists
// for ledger symmetry + audit trail.
func stepValidate() Step {
	return Step{
		Name:    "validate",
		Timeout: 5 * time.Second,
		Run:     noopRun,
	}
}

// 2. allocate_id — handler allocates the ulid before INSERT; this is a
// marker step.
func stepAllocateID() Step {
	return Step{
		Name:    "allocate_id",
		Timeout: 5 * time.Second,
		Run:     noopRun,
	}
}

// 3. record_desired_state — handler already INSERTed the deployment
// row + the provision_step rows. Marker step.
func stepRecordDesiredState() Step {
	return Step{
		Name:    "record_desired_state",
		Timeout: 5 * time.Second,
		Run:     noopRun,
	}
}

// 4. openbao — Apply the per-Deployment transit key + policy + k8s
// role + KV namespace. Must precede postgres so the Postgres app
// password has a KV path to write to.
func stepOpenBao(a Adapters) Step {
	return Step{
		Name:    "openbao",
		Timeout: 30 * time.Second,
		Run: func(ctx context.Context, dep DeploymentRef) error {
			if a.OpenBao == nil {
				return fmt.Errorf("%w: openbao", ErrAdapterNil)
			}
			_, err := a.OpenBao.Apply(ctx, openbao.ApplyInput{
				DeploymentID:      dep.ID,
				K3sNamespace:      dep.Namespace,
				K3sServiceAccount: "dataplane",
			})
			return err
		},
		Rollback: func(ctx context.Context, dep DeploymentRef) error {
			if a.OpenBao == nil {
				return nil
			}
			// On rollback we destroy the transit key — the deployment
			// is being torn down anyway, so wrapped DEKs becoming
			// undecryptable is the desired outcome (every byte of
			// per-Deployment ciphertext should also be gone by this
			// point because the postgres rollback below dropped the DB).
			return a.OpenBao.Remove(ctx, openbao.RemoveInput{
				DeploymentID:      dep.ID,
				ConfirmDestroyKey: true,
			})
		},
	}
}

// 5. postgres — CREATE DATABASE + role + grants + migrations + RLS
// verify. After Apply, persist the generated app password in OpenBao
// KV so the data-plane pod can read its DSN.
func stepPostgres(a Adapters) Step {
	return Step{
		Name:    "postgres",
		Timeout: 2 * time.Minute,
		Run: func(ctx context.Context, dep DeploymentRef) error {
			if a.Postgres == nil {
				return fmt.Errorf("%w: postgres", ErrAdapterNil)
			}
			res, err := a.Postgres.Apply(ctx, postgres.ApplyInput{
				DeploymentID:    dep.ID,
				ProjectSlug:     dep.ProjectSlug,
				EnvironmentSlug: dep.EnvironmentSlug,
				AdminDSN:        a.PostgresAdminDSN,
				HostExternal:    a.PostgresHostExternal,
			})
			if err != nil {
				return err
			}
			// Store the password + DSN in OpenBao KV. The data-plane
			// pod reads this via its envelope.Client at startup.
			if a.EnvelopeKVPut != nil {
				kvErr := a.EnvelopeKVPut(ctx, dep.ID, "postgres/app_password", map[string]any{
					"role":     res.RoleName,
					"password": res.RolePassword,
					"dsn":      res.PerDeploymentDSN,
				})
				if kvErr != nil {
					return fmt.Errorf("kv put postgres password: %w", kvErr)
				}
			}
			return nil
		},
		Rollback: func(ctx context.Context, dep DeploymentRef) error {
			if a.Postgres == nil {
				return nil
			}
			return a.Postgres.Remove(ctx, postgres.RemoveInput{
				DeploymentID:        dep.ID,
				ProjectSlug:         dep.ProjectSlug,
				EnvironmentSlug:     dep.EnvironmentSlug,
				AdminDSN:            a.PostgresAdminDSN,
				ConfirmDropDatabase: true,
			})
		},
	}
}

// 6. seed — bootstrap tenant + admin + first API key in the new DB.
// Stores the BootstrapResult so the handler can return the one-time
// secret in the create response.
func stepSeed(a Adapters) Step {
	return Step{
		Name:    "seed",
		Timeout: 30 * time.Second,
		Run: func(ctx context.Context, dep DeploymentRef) error {
			if a.Seeder == nil {
				return fmt.Errorf("%w: bootstrap seeder", ErrAdapterNil)
			}
			res, err := a.Seeder.Seed(ctx, &deployments.Deployment{
				ID:              dep.ID,
				ProjectSlug:     dep.ProjectSlug,
				EnvironmentSlug: dep.EnvironmentSlug,
				DBName:          dep.DBName,
				DBAppRole:       dep.RoleName,
			}, "")
			if err != nil {
				return err
			}
			if a.BootstrapStore != nil {
				a.BootstrapStore.Put(dep.ID, res)
			}
			return nil
		},
		// Rollback: nothing to undo — postgres.Rollback dropped the DB
		// (and with it every seeded row).
		Rollback: noopRun,
	}
}

// 7. render_k3s — the adapter's Apply does this inline; we expose a
// dedicated step for ledger granularity but the work happens inside
// k3s_apply. Marker step.
func stepRenderK3s(_ Adapters) Step {
	return Step{
		Name:    "render_k3s",
		Timeout: 10 * time.Second,
		Run:     noopRun,
	}
}

// 8. k3s_apply — render + SSA the namespace + ServiceAccount + 3
// NetworkPolicies + Service + Deployment; wait for rollout.
func stepK3sApply(a Adapters) Step {
	return Step{
		Name:    "k3s_apply",
		Timeout: 5 * time.Minute,
		Run: func(ctx context.Context, dep DeploymentRef) error {
			if a.K3s == nil {
				return fmt.Errorf("%w: k3s", ErrAdapterNil)
			}
			port := a.K3sNodePort
			if port == 0 {
				port = 30080
			}
			return a.K3s.Apply(ctx, k3s.ApplyInput{
				DeploymentID:     dep.ID,
				ProjectSlug:      dep.ProjectSlug,
				EnvironmentSlug:  dep.EnvironmentSlug,
				ImageVersion:     dep.ImageVersion,
				NodePort:         port,
				HostNginxCIDR:    a.K3sHostNginxCIDR,
				HostPostgresCIDR: a.K3sHostPostgresCIDR,
				HostOpenBaoCIDR:  a.K3sHostOpenBaoCIDR,
			})
		},
		Rollback: func(ctx context.Context, dep DeploymentRef) error {
			if a.K3s == nil {
				return nil
			}
			return a.K3s.Remove(ctx, k3s.RemoveInput{DeploymentID: dep.ID})
		},
	}
}

// 9. render_nginx — the adapter's Apply renders + writes the vhost
// inline; we expose a dedicated step for ledger granularity. Marker.
func stepRenderNginx() Step {
	return Step{
		Name:    "render_nginx",
		Timeout: 10 * time.Second,
		Run:     noopRun,
	}
}

// 10. nginx_apply — install the vhost + reload nginx + issue cert via
// certbot --nginx.
func stepNginxApply(a Adapters) Step {
	return Step{
		Name:    "nginx_apply",
		Timeout: 2 * time.Minute,
		Run: func(ctx context.Context, dep DeploymentRef) error {
			if a.Nginx == nil {
				return fmt.Errorf("%w: nginx", ErrAdapterNil)
			}
			port := a.K3sNodePort
			if port == 0 {
				port = 30080
			}
			in := nginx.ApplyInput{
				DeploymentID:  dep.ID,
				PrimaryDomain: dep.PrimaryDomain,
				CustomDomains: dep.CustomDomains,
				NodePort:      port,
				OpsEmail:      a.NginxOpsEmail,
			}
			if err := a.Nginx.Apply(ctx, in); err != nil {
				return fmt.Errorf("nginx apply: %w", err)
			}
			// Cert issuance is optional in environments without a
			// public IP (local dev, k3d test clusters). Empty ops_email
			// skips it — useful for integration tests.
			if a.NginxOpsEmail == "" {
				return nil
			}
			if err := a.Nginx.IssueCert(ctx, in); err != nil {
				return fmt.Errorf("nginx certbot: %w", err)
			}
			return nil
		},
		Rollback: func(ctx context.Context, dep DeploymentRef) error {
			if a.Nginx == nil {
				return nil
			}
			return a.Nginx.Remove(ctx, nginx.RemoveInput{DeploymentID: dep.ID})
		},
	}
}

// 11. healthz — poll https://<primary>/healthz until 200 or timeout.
// This is the end-to-end probe; success confirms nginx + cert +
// k3s + Postgres + OpenBao all wire up correctly.
func stepHealthz(a Adapters) Step {
	return Step{
		Name:    "healthz",
		Timeout: 5 * time.Minute,
		Run: func(ctx context.Context, dep DeploymentRef) error {
			return pollHealthz(ctx, a, dep)
		},
		Rollback: noopRun,
	}
}

// pollHealthz polls until 200 or the parent timeout. Each attempt is
// bounded by its own 5 s client timeout so a hung TCP connection doesn't
// eat the whole window.
func pollHealthz(ctx context.Context, a Adapters, dep DeploymentRef) error {
	client := a.HealthCheckClient
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	timeout := a.HealthCheckTimeout
	if timeout <= 0 {
		timeout = 2 * time.Minute
	}
	interval := a.HealthCheckInterval
	if interval <= 0 {
		interval = 5 * time.Second
	}
	if dep.PrimaryDomain == "" {
		return fmt.Errorf("%w: primary domain empty", ErrHealthCheckFailed)
	}
	deadline := time.Now().Add(timeout)
	url := "https://" + dep.PrimaryDomain + "/healthz"
	for {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			return fmt.Errorf("%w: build request: %w", ErrHealthCheckFailed, err)
		}
		resp, err := client.Do(req)
		if err == nil {
			closeBody(resp)
			if resp.StatusCode == http.StatusOK {
				return nil
			}
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("%w: deadline exceeded", ErrHealthCheckFailed)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(interval):
		}
	}
}

// closeBody closes resp.Body, silencing the linter that demands every
// http.Response body be closed even on a non-2xx.
func closeBody(resp *http.Response) {
	if resp == nil || resp.Body == nil {
		return
	}
	_ = resp.Body.Close()
}

// 12. flip_active — UPDATE deployment SET status='active'; emit the
// deployment.provisioned event.
func stepFlipActive(a Adapters) Step {
	return Step{
		Name:    "flip_active",
		Timeout: 10 * time.Second,
		Run: func(ctx context.Context, dep DeploymentRef) error {
			if a.Status != nil {
				if err := a.Status.UpdateStatus(ctx, dep.ID, deployments.StatusActive); err != nil {
					return fmt.Errorf("update status active: %w", err)
				}
			}
			if a.Events != nil {
				if err := a.Events.Publish(ctx, "deployment.provisioned", dep.ID, map[string]any{
					"deployment_id": dep.ID,
					"image_version": dep.ImageVersion,
				}); err != nil {
					return fmt.Errorf("publish event: %w", err)
				}
			}
			return nil
		},
		Rollback: noopRun,
	}
}

// 13. return_bootstrap — handler reads from BootstrapStore. Marker.
func stepReturnBootstrap() Step {
	return Step{
		Name:    "return_bootstrap",
		Timeout: 5 * time.Second,
		Run:     noopRun,
	}
}

// noopRun is the shared "do nothing" callback for the metadata-only
// steps (validate, allocate_id, record_desired_state, render_*,
// return_bootstrap). Centralised so a future signature change to
// Step.Run is a single edit.
func noopRun(_ context.Context, _ DeploymentRef) error { return nil }
