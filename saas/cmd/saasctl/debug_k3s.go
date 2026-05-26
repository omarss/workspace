// Phase 12b CP-6 verification helper: `saasctl debug k3s apply/remove
// <deployment_id>` exercises the k3s adapter directly so the operator
// can verify per-Deployment namespace + NetworkPolicy creation against
// the real k3s cluster before Phase 12e composes nginx + k3s + Postgres
// + OpenBao into the full provisioning sequence.
//
// Build-tagged `!prod` — the prod binary literally does not link this
// file, mirroring the Phase 12a debug_nginx.go pattern (the build-tag
// guarantee on cmd/saasctl/debug_register_prod.go also excludes the
// import chain that brings in client-go + kustomize, keeping the
// release binary lean).

//go:build !prod

package main

import (
	"context"
	"errors"
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/omarss/saas/internal/controlplane/provision/k3s"
)

// debugK3sCmd is the CP-6 helper subtree. Attached to `saasctl debug`
// from debug_nginx.go's debugCmd() — see init() below.
func debugK3sCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "k3s",
		Short: "Invoke the k3s adapter directly (CP-6 verification).",
		Long: `Apply or remove a per-Deployment k3s manifest set on the cluster
referenced by $KUBECONFIG (or ~/.kube/config).

Pre-requisites:
  1. kubectl get nodes works for the invoking user.
  2. The cluster's CNI enforces NetworkPolicy (k3s with flannel
     by default does NOT enforce — install calico or cilium per
     AGENTS.md §6).
  3. The data-plane image tag is reachable from the cluster. For
     CP-6 the rollout will time out cleanly when the image is not
     pullable; the manifests still apply and the NetworkPolicy
     cross-namespace probe remains the primary acceptance test.

Phase 12b-only debug command. Removed in Phase 12e once the composite
provisioner owns the full sequence.`,
	}
	c.AddCommand(debugK3sApplyCmd())
	c.AddCommand(debugK3sRemoveCmd())
	return c
}

// debugK3sApplyCmd writes the first real k3s manifest set on the
// cluster.
func debugK3sApplyCmd() *cobra.Command {
	var (
		projectSlug      string
		environmentSlug  string
		imageVersion     string
		nodePort         int
		hostNginxCIDR    string
		hostPostgresCIDR string
		hostOpenBaoCIDR  string
		kubeconfig       string
		skipWaitReady    bool
	)
	c := &cobra.Command{
		Use:   "apply <deployment_id>",
		Short: "Render + server-side-apply a per-Deployment k3s manifest set.",
		Long: `Render the embedded kustomize overlay (deploy/k3s/base + the Phase
12b overlay template) for the given deployment_id, decode the
multi-doc YAML into typed objects, and server-side-apply each in the
order Namespace -> ServiceAccount -> NetworkPolicy -> Service ->
Deployment with FieldManager="saas-controlplane" + Force=true. Block
on the data-plane Deployment rollout (5 min by default).

The three host CIDR flags are REQUIRED. Default-deny + a missing
allow would trap pods (no DNS = crashloop, no Postgres = crashloop);
the adapter refuses an empty CIDR for that reason.

For CP-6 verification on a homelab loopback k3s, /32 of the host's
own loopback addresses are typically the right choice.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			adapter, err := k3s.NewHostAdapter(k3s.ClientConfig{KubeconfigPath: kubeconfig})
			if err != nil {
				if errors.Is(err, k3s.ErrNoKubeconfig) {
					fmt.Fprintln(os.Stderr, "no kubeconfig found. Either:")
					fmt.Fprintln(os.Stderr, "  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml")
					fmt.Fprintln(os.Stderr, "  or pass --kubeconfig <path>")
				}
				return fmt.Errorf("init adapter: %w", err)
			}
			in := k3s.ApplyInput{
				DeploymentID:     args[0],
				ProjectSlug:      projectSlug,
				EnvironmentSlug:  environmentSlug,
				ImageVersion:     imageVersion,
				NodePort:         nodePort,
				HostNginxCIDR:    hostNginxCIDR,
				HostPostgresCIDR: hostPostgresCIDR,
				HostOpenBaoCIDR:  hostOpenBaoCIDR,
			}
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}

			if err := adapter.Apply(ctx, in); err != nil {
				// ErrRolloutTimeout is expected when the operator runs
				// CP-6 against a cluster that cannot pull the dataplane
				// image. The manifests themselves still applied — make
				// that explicit in the message and exit non-zero so the
				// operator notices.
				if errors.Is(err, k3s.ErrRolloutTimeout) && skipWaitReady {
					fmt.Fprintln(os.Stderr, "manifests applied; rollout timed out (--skip-wait-ready). Inspect with kubectl get pods.")
					return nil
				}
				return err
			}
			fmt.Printf("k3s manifests applied + Deployment rolled out: namespace=%s\n", in.NamespaceName())
			return nil
		},
	}
	c.Flags().StringVar(&projectSlug, "project-slug", "", "Project slug for labels (defaults to deployment_id).")
	c.Flags().StringVar(&environmentSlug, "environment-slug", "", "Environment slug for labels (defaults to deployment_id).")
	c.Flags().StringVar(&imageVersion, "image-version", "v0.3.1", "Data-plane image tag the overlay applies.")
	c.Flags().IntVar(&nodePort, "node-port", 30800, "k3s NodePort the data-plane Service binds (30000-32767).")
	c.Flags().StringVar(&hostNginxCIDR, "host-nginx-cidr", "", "Source CIDR for the allow-ingress-from-host-nginx NetworkPolicy (REQUIRED).")
	c.Flags().StringVar(&hostPostgresCIDR, "host-postgres-cidr", "", "Destination CIDR for the egress-to-Postgres allow rule (REQUIRED).")
	c.Flags().StringVar(&hostOpenBaoCIDR, "host-openbao-cidr", "", "Destination CIDR for the egress-to-OpenBao allow rule (REQUIRED).")
	c.Flags().StringVar(&kubeconfig, "kubeconfig", "", "Override the kubeconfig path (otherwise $KUBECONFIG, then ~/.kube/config).")
	c.Flags().BoolVar(&skipWaitReady, "skip-wait-ready", false, "Suppress non-zero exit on rollout timeout (manifests still apply).")
	_ = c.MarkFlagRequired("host-nginx-cidr")
	_ = c.MarkFlagRequired("host-postgres-cidr")
	_ = c.MarkFlagRequired("host-openbao-cidr")
	return c
}

// debugK3sRemoveCmd deletes the namespace (which cascades to every
// resource inside).
func debugK3sRemoveCmd() *cobra.Command {
	var kubeconfig string
	c := &cobra.Command{
		Use:   "remove <deployment_id>",
		Short: "Delete the per-Deployment namespace (cascades to all resources).",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			adapter, err := k3s.NewHostAdapter(k3s.ClientConfig{KubeconfigPath: kubeconfig})
			if err != nil {
				return fmt.Errorf("init adapter: %w", err)
			}
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}
			if err := adapter.Remove(ctx, k3s.RemoveInput{DeploymentID: args[0]}); err != nil {
				return err
			}
			fmt.Printf("namespace deleted: saas-%s (k8s gc cascades to NetworkPolicies, SA, Service, Deployment).\n", args[0])
			return nil
		},
	}
	c.Flags().StringVar(&kubeconfig, "kubeconfig", "", "Override the kubeconfig path.")
	return c
}
