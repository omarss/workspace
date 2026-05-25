// Phase 12a CP-5 verification helper: `saasctl debug nginx apply/remove
// <deployment_id>` writes/removes a real nginx vhost on the host.
//
// This subcommand is build-tagged `!prod` so it is excluded from production
// binaries. Phase 12e composes the full provisioning sequence and removes
// these helpers; until then this is the only operator-facing way to invoke
// the nginx adapter outside the integration tests.
//
// Why a build tag rather than a flag-gated subcommand: the safest
// guarantee that `saasctl debug` cannot ship to a customer is that it
// literally is not compiled into the binary the release pipeline
// produces (cmd/Makefile sets `-tags prod` for release artifacts in
// Phase 13). This file lives here as a development-only seam.

//go:build !prod

package main

import (
	"context"
	"errors"
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/omarss/saas/internal/controlplane/provision/nginx"
)

// debugCmd registers `saasctl debug ...`. Currently only `debug nginx`;
// later sub-phases (12b/c/d) may attach their own verification helpers.
func debugCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "debug",
		Short: "Phase-12 verification helpers (REMOVED in Phase 12e).",
		Long: `Debug helpers for CHECKPOINT 5-9 verification.

These commands are compiled in only when the binary is built WITHOUT the
'prod' build tag. They invoke individual provisioner adapters directly
to let the operator inspect host state before the full provisioning
sequence is wired up (Phase 12e).`,
	}
	c.AddCommand(debugNginxCmd())
	return c
}

// debugNginxCmd is the CP-5 helper subtree.
func debugNginxCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "nginx",
		Short: "Invoke the host-nginx adapter directly (CP-5 verification).",
	}
	c.AddCommand(debugNginxApplyCmd())
	c.AddCommand(debugNginxRemoveCmd())
	return c
}

// debugNginxApplyCmd writes the first real vhost on disk.
func debugNginxApplyCmd() *cobra.Command {
	var (
		primaryDomain string
		customDomains []string
		nodePort      int
		opsEmail      string
		skipCertbot   bool
	)
	c := &cobra.Command{
		Use:   "apply <deployment_id>",
		Short: "Render + install a per-Deployment nginx vhost.",
		Long: `Render the pre-certbot vhost from deploy/nginx/vhost.conf.tmpl, install
at /etc/nginx/sites-available/saas-<deployment_id>.conf, symlink into
sites-enabled/, run 'sudo nginx -t' + 'sudo nginx -s reload', then
optionally run 'sudo certbot --nginx' to issue the TLS cert.

Pre-requisites:
  1. deploy/host/setup-nginx-adapter.sh has been run (one-time).
  2. DNS for <primary_domain> resolves to this host (only needed when
     --skip-certbot is false).

Phase 12a-only debug command. Removed in Phase 12e.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			adapter, err := nginx.NewHostAdapter()
			if err != nil {
				return fmt.Errorf("init adapter: %w", err)
			}
			in := nginx.ApplyInput{
				DeploymentID:  args[0],
				PrimaryDomain: primaryDomain,
				CustomDomains: customDomains,
				NodePort:      nodePort,
				OpsEmail:      opsEmail,
			}
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}

			if err := adapter.Apply(ctx, in); err != nil {
				if errors.Is(err, nginx.ErrSetupNotComplete) {
					fmt.Fprintln(os.Stderr, "host setup is not complete. Run:")
					fmt.Fprintln(os.Stderr, "  sudo bash deploy/host/setup-nginx-adapter.sh")
				}
				return err
			}
			fmt.Printf("vhost installed: /etc/nginx/sites-available/saas-%s.conf\n", in.DeploymentID)

			if skipCertbot {
				fmt.Println("--skip-certbot set; not issuing TLS cert (port 80 listener is up).")
				return nil
			}
			if err := adapter.IssueCert(ctx, in); err != nil {
				fmt.Fprintf(os.Stderr, "certbot failed: %v\n", err)
				fmt.Fprintln(os.Stderr, "the vhost is installed and serves on :80; re-run with --skip-certbot to verify and then issue the cert manually.")
				return err
			}
			fmt.Println("certbot issued cert and certbot --nginx injected the 443 server block.")
			return nil
		},
	}
	c.Flags().StringVar(&primaryDomain, "primary-domain", "", "Primary vhost FQDN, e.g. dev.acme.saas.omarss.net (required).")
	c.Flags().StringSliceVar(&customDomains, "custom-domain", nil, "Optional BYOD custom domain(s); repeatable.")
	c.Flags().IntVar(&nodePort, "node-port", 30800, "k3s NodePort the vhost proxies to (30000-32767).")
	c.Flags().StringVar(&opsEmail, "ops-email", "ops@omarss.net", "Email passed to certbot -m.")
	c.Flags().BoolVar(&skipCertbot, "skip-certbot", false, "Install the vhost but skip the certbot --nginx run.")
	_ = c.MarkFlagRequired("primary-domain")
	return c
}

// debugNginxRemoveCmd removes the symlink + vhost file + reloads nginx.
// Does NOT delete the cert — operator can `sudo certbot delete --cert-name
// <deployment_id>` separately.
func debugNginxRemoveCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "remove <deployment_id>",
		Short: "Remove a per-Deployment nginx vhost (does not delete cert).",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			adapter, err := nginx.NewHostAdapter()
			if err != nil {
				return fmt.Errorf("init adapter: %w", err)
			}
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}
			if err := adapter.Remove(ctx, nginx.RemoveInput{DeploymentID: args[0]}); err != nil {
				return err
			}
			fmt.Printf("vhost removed: /etc/nginx/sites-available/saas-%s.conf\n", args[0])
			fmt.Println("note: TLS cert (if any) was NOT deleted. Run `sudo certbot delete --cert-name " + args[0] + "` to remove.")
			return nil
		},
	}
}
