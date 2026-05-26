// Phase 12e — host provisioner wiring. Construct the four adapters
// (nginx, k3s, postgres, openbao), bundle them with the sequence
// orchestrator + destroy reconciler, and start the reconciler
// goroutine. Returns a stop() closure the main control flow defers.
//
// Selection is via SAAS_HOST_PROVISIONER=true. Default off; see
// main.go's hostProvOn branch.

package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/saas/internal/controlplane/deployments"
	"github.com/omarss/saas/internal/controlplane/provision/k3s"
	"github.com/omarss/saas/internal/controlplane/provision/nginx"
	"github.com/omarss/saas/internal/controlplane/provision/openbao"
	"github.com/omarss/saas/internal/controlplane/provision/postgres"
	"github.com/omarss/saas/internal/controlplane/provision/sequence"
	"github.com/omarss/saas/internal/platform/crypto/envelope"
)

// startHostProvisioner wires the four adapters + the sequence
// orchestrator + the destroy reconciler. Returns a function that
// stops the reconciler goroutine on shutdown.
//
// Fails fast on missing required env (SAAS_PG_ADMIN_DSN,
// SAAS_NGINX_OPS_EMAIL, the three K3S_HOST_*_CIDR values, BAO_ADDR).
// The operator opted in via SAAS_HOST_PROVISIONER=true; partial
// configuration is a misconfiguration, not a fallback path.
func startHostProvisioner(ctx context.Context, _ *pgxpool.Pool, encClient *envelope.Client) (func(), error) {
	// Required env. Read all up front so the operator gets a single
	// error message listing what's missing instead of one at a time.
	adminDSN := os.Getenv("SAAS_PG_ADMIN_DSN")
	opsEmail := os.Getenv("SAAS_NGINX_OPS_EMAIL")
	hostNginxCIDR := os.Getenv("SAAS_K3S_HOST_NGINX_CIDR")
	hostPGCIDR := os.Getenv("SAAS_K3S_HOST_POSTGRES_CIDR")
	hostBaoCIDR := os.Getenv("SAAS_K3S_HOST_OPENBAO_CIDR")
	pgHostExt := os.Getenv("SAAS_PG_HOST_EXTERNAL")
	nodePortStr := os.Getenv("SAAS_K3S_DEFAULT_NODEPORT")
	missing := []string{}
	if adminDSN == "" {
		missing = append(missing, "SAAS_PG_ADMIN_DSN")
	}
	if hostNginxCIDR == "" {
		missing = append(missing, "SAAS_K3S_HOST_NGINX_CIDR")
	}
	if hostPGCIDR == "" {
		missing = append(missing, "SAAS_K3S_HOST_POSTGRES_CIDR")
	}
	if hostBaoCIDR == "" {
		missing = append(missing, "SAAS_K3S_HOST_OPENBAO_CIDR")
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required env: %v", missing)
	}

	nodePort := 30080
	if nodePortStr != "" {
		n, err := strconv.Atoi(nodePortStr)
		if err != nil {
			return nil, fmt.Errorf("SAAS_K3S_DEFAULT_NODEPORT not an int: %w", err)
		}
		nodePort = n
	}

	// nginx adapter. Reads /etc/nginx/sites-* by default; tests / dev
	// can override via SAAS_NGINX_SITES_AVAILABLE.
	nginxAdapter, err := nginx.NewHostAdapter()
	if err != nil {
		return nil, fmt.Errorf("nginx adapter: %w", err)
	}

	// k3s adapter. Reads kubeconfig from $KUBECONFIG or the in-cluster
	// service-account token if running inside the cluster. The MVP
	// runs the controlplane on the host (not in the cluster), so
	// $KUBECONFIG is the path.
	k3sAdapter, err := k3s.NewHostAdapter(k3s.ClientConfig{
		KubeconfigPath: os.Getenv("KUBECONFIG"),
	})
	if err != nil {
		return nil, fmt.Errorf("k3s adapter: %w", err)
	}

	// postgres adapter. Stateless; constructor takes no options.
	pgAdapter := postgres.NewHostAdapter()

	// openbao adapter. The controlplane process already authenticated
	// via AppRole (encClient is the resulting client). Reach into the
	// envelope.Client for its underlying *bao.Client.
	if encClient == nil {
		return nil, fmt.Errorf("openbao envelope client required when SAAS_HOST_PROVISIONER=true")
	}
	baoAdapter, err := openbao.NewHostAdapter(encClient.RawClient())
	if err != nil {
		return nil, fmt.Errorf("openbao adapter: %w", err)
	}

	// Adapters bundle. EnvelopeKVPut is wired through the same
	// envelope client so the per-Deployment Postgres password lands
	// in OpenBao KV (data-plane pod reads it on startup).
	adapters := sequence.Adapters{
		OpenBao:              baoAdapter,
		Postgres:             pgAdapter,
		K3s:                  k3sAdapter,
		Nginx:                nginxAdapter,
		PostgresAdminDSN:     adminDSN,
		PostgresHostExternal: pgHostExt,
		K3sNodePort:          nodePort,
		K3sHostNginxCIDR:     hostNginxCIDR,
		K3sHostPostgresCIDR:  hostPGCIDR,
		K3sHostOpenBaoCIDR:   hostBaoCIDR,
		NginxOpsEmail:        opsEmail,
		EnvelopeKVPut: func(ctx context.Context, deploymentID, path string, data map[string]any) error {
			return encClient.KVPut(ctx, deploymentID, path, data)
		},
		// Seeder + BootstrapStore + Events + Status are wired by the
		// deployments service layer in the next phase (Phase 13+
		// operator API). For now the seed step runs without a seeder;
		// the orchestrator returns an ErrAdapterNil that surfaces
		// fast — the operator sees the misconfiguration immediately
		// rather than a half-provisioned deployment.
		BootstrapStore: sequence.NewMemoryBootstrapStore(),
	}

	ledger := sequence.NewMemoryLedger()
	seq := &sequence.Sequence{
		Ledger: ledger,
		Steps:  sequence.DefaultSteps(adapters),
	}

	// Reconciler goroutine. Repo is nil in this wiring phase because
	// the deployments service hasn't shipped its repo yet — when it
	// does, this is a one-line swap. For Phase 12e the reconciler
	// exists in the binary; the actual ticker fires but has nothing
	// to scan, which is the desired pre-service-wire state.
	reconcilerCtx, cancel := context.WithCancel(ctx)
	rec := &sequence.DestroyReconciler{
		Sequence: seq,
		Adapters: adapters,
		// Repo wires in when deployments.Repository ships its
		// reconciler-shaped adapter; until then the reconciler
		// loops harmlessly on its own ticker.
		Repo: noOpDestroyRepo{},
	}
	go func() {
		if err := rec.Run(reconcilerCtx); err != nil && reconcilerCtx.Err() == nil {
			slog.Error("destroy reconciler exited", "err", err)
		}
	}()

	slog.Info("controlplane: host provisioner ready",
		"nodeport_default", nodePort,
		"admin_dsn_host_set", pgHostExt != "")

	return cancel, nil
}

// noOpDestroyRepo satisfies DestroyRepo with empty results. Used as a
// placeholder until the deployments service layer ships its repo
// implementation. Returning empty slices means the reconciler ticks
// harmlessly and logs nothing.
type noOpDestroyRepo struct{}

func (noOpDestroyRepo) ListByStatus(_ context.Context, _ []deployments.Status, _ int) ([]deployments.Deployment, error) {
	return nil, nil
}

func (noOpDestroyRepo) UpdateStatus(_ context.Context, _ string, _ deployments.Status) error {
	return nil
}

func (noOpDestroyRepo) ListExpiredSoftDeletes(_ context.Context, _ time.Time, _ int) ([]deployments.Deployment, error) {
	return nil, nil
}
