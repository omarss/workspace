// Phase 12d CP-8 verification helper: `saasctl debug bao apply/remove
// <deployment_id>` exercises the OpenBao adapter directly so the
// operator can verify per-Deployment transit key + policy + k8s auth
// role + KV path against the homelab OpenBao before Phase 12e composes
// nginx + k3s + Postgres + OpenBao into the full provisioning
// sequence.
//
// Build-tagged `!prod` — the prod binary literally does not link this
// file, mirroring the Phase 12a/b/c debug_nginx.go / debug_k3s.go /
// debug_postgres.go patterns.
//
// remove is gated behind --confirm-destroy-key + a 5-second countdown
// because deleting a transit key is IRREVERSIBLE; any ciphertext
// encrypted under that key becomes permanently undecryptable. This is
// the OpenBao analogue of the Phase 12c --confirm-drop-database flag.

//go:build !prod

package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/spf13/cobra"

	"github.com/omarss/saas/internal/controlplane/provision/openbao"
)

// debugBaoCmd is the CP-8 helper subtree. Attached to `saasctl debug`
// from debug_nginx.go's debugCmd().
func debugBaoCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "bao",
		Short: "Invoke the per-Deployment OpenBao adapter directly (CP-8 verification).",
		Long: `Apply or remove per-Deployment OpenBao state on the instance pointed at
by --bao-addr.

Pre-requisites:
  1. OpenBao is initialised + unsealed (compose dev: 'make openbao-init').
  2. The supplied token has create capabilities on transit/keys/*,
     sys/policies/acl/*, auth/kubernetes/role/*, secret/data/*,
     and secret/metadata/*. The dev path is to point at
     /openbao/secrets/init.json which contains the root token; this
     is dev-only per ADR 006.
  3. Phase 4's 'make openbao-init' has enabled the kubernetes auth
     method (auth/kubernetes/).

Phase 12d-only debug command. Removed in Phase 12e once the composite
provisioner owns the full sequence.`,
	}
	c.AddCommand(debugBaoApplyCmd())
	c.AddCommand(debugBaoRemoveCmd())
	c.AddCommand(debugBaoVerifyCmd())
	return c
}

// commonClientFlags wires the three auth-method flags + address into
// the parent cobra.Command. Shared between apply/remove/verify so the
// operator-facing surface is uniform.
type baoClientFlags struct {
	addr       string
	caCertPath string
	token      string
	tokenFile  string
	roleID     string
	secretID   string
}

func (f *baoClientFlags) attach(c *cobra.Command) {
	c.Flags().StringVar(&f.addr, "bao-addr", "http://127.0.0.1:8200", "OpenBao listener URL.")
	c.Flags().StringVar(&f.caCertPath, "bao-ca-cert", "", "PEM-encoded CA bundle for TLS verification (only required when --bao-addr is https://).")
	c.Flags().StringVar(&f.token, "bao-token", "", "Static OpenBao token (mutually exclusive with --bao-token-file and --bao-approle-*).")
	c.Flags().StringVar(&f.tokenFile, "bao-token-file", "", "Path to a JSON init.json (extracts root_token) or a raw token text file.")
	c.Flags().StringVar(&f.roleID, "bao-approle-role-id", "", "AppRole role_id (production auth path; pair with --bao-approle-secret-id).")
	c.Flags().StringVar(&f.secretID, "bao-approle-secret-id", "", "AppRole secret_id (production auth path).")
}

func (f *baoClientFlags) toConfig() openbao.ClientConfig {
	return openbao.ClientConfig{
		Address:         f.addr,
		CACertPath:      f.caCertPath,
		Token:           f.token,
		TokenFile:       f.tokenFile,
		AppRoleRoleID:   f.roleID,
		AppRoleSecretID: f.secretID,
	}
}

func debugBaoApplyCmd() *cobra.Command {
	var (
		k3sNamespace      string
		k3sServiceAccount string
		auditLogPath      string
	)
	flags := &baoClientFlags{}
	c := &cobra.Command{
		Use:   "apply <deployment_id>",
		Short: "Provision per-Deployment transit key + policy + k8s role + KV namespace.",
		Long: `Run the five-step provisioning flow for one Deployment:

  1. EnsureTransitKey: write transit/keys/<dep_id> with
     aes256-gcm96 + 90d auto-rotate (idempotent: pre-read).
  2. WritePolicy: render the embedded HCL template with the
     deployment_id; install at sys/policies/acl/saas-<dep_id>.
  3. ConfigureK8sRole: bind the SA <sa> in <namespace> to the
     policy via auth/kubernetes/role/<dep_id> (ttl=1h / max_ttl=24h).
  4. InitKVPath: seed secret/data/<dep_id>/_provisioned so the
     namespace shows up in 'bao kv list'.
  5. VerifyAccess: read each artifact back to confirm landed.

Apply is idempotent — re-running on an already-provisioned Deployment
is a no-op except for the audit log entries.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}
			bc, err := openbao.NewClient(ctx, flags.toConfig())
			if err != nil {
				return err
			}
			adapter, err := openbao.NewHostAdapter(bc)
			if err != nil {
				return err
			}
			in := openbao.ApplyInput{
				DeploymentID:      args[0],
				K3sNamespace:      k3sNamespace,
				K3sServiceAccount: k3sServiceAccount,
				AuditLogPath:      auditLogPath,
			}
			res, err := adapter.Apply(ctx, in)
			if err != nil {
				if errors.Is(err, openbao.ErrK8sAuthMissing) {
					fmt.Fprintln(os.Stderr, "auth/kubernetes/ is not enabled on OpenBao. Re-run:")
					fmt.Fprintln(os.Stderr, "  make openbao-init")
				}
				return err
			}
			fmt.Println("openbao adapter Apply succeeded.")
			fmt.Println("  kid (transit key):       ", res.Kid)
			fmt.Println("  policy:                  ", res.PolicyName)
			fmt.Println("  k8s auth role:           ", res.K8sRoleName)
			fmt.Println("  kv namespace:            ", res.KVPath)
			fmt.Println()
			fmt.Println("Verify with:")
			fmt.Printf("  bao read transit/keys/%s\n", res.Kid)
			fmt.Printf("  bao policy read %s\n", res.PolicyName)
			fmt.Printf("  bao read auth/kubernetes/role/%s\n", res.K8sRoleName)
			fmt.Printf("  bao kv get %s/_provisioned\n", "secret/"+args[0])
			return nil
		},
	}
	c.Flags().StringVar(&k3sNamespace, "k3s-namespace", "", "Per-Deployment k3s namespace (REQUIRED; canonically saas-<dep_id>).")
	c.Flags().StringVar(&k3sServiceAccount, "k3s-service-account", "dataplane", "Per-Deployment k3s ServiceAccount (canonically 'dataplane').")
	c.Flags().StringVar(&auditLogPath, "audit-log-path", "", "Reserved for future per-Deployment audit device; ignored in Phase 12d (ADR 016).")
	flags.attach(c)
	_ = c.MarkFlagRequired("k3s-namespace")
	return c
}

func debugBaoRemoveCmd() *cobra.Command {
	var confirmDestroyKey bool
	flags := &baoClientFlags{}
	c := &cobra.Command{
		Use:   "remove <deployment_id>",
		Short: "Destroy per-Deployment OpenBao state (requires --confirm-destroy-key).",
		Long: `Remove all OpenBao state for one Deployment:

  1. Purge secret/metadata/<dep_id>/ (KV namespace + version history).
  2. Delete auth/kubernetes/role/<dep_id>.
  3. Delete sys/policies/acl/saas-<dep_id>.
  4. Set deletion_allowed=true on transit/keys/<dep_id>/config, then
     DELETE the transit key.

IRREVERSIBLE: deleting the transit key permanently destroys the key
material. Any ciphertext encrypted under this key becomes
unrecoverable after this command returns.

The --confirm-destroy-key flag is REQUIRED. The command displays a
5-second countdown before executing as a final defense against
accidental destruction (^C during the countdown to abort).`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}
			if !confirmDestroyKey {
				fmt.Fprintln(os.Stderr, "refusing to destroy without --confirm-destroy-key.")
				fmt.Fprintln(os.Stderr, "deleting a transit key is IRREVERSIBLE; any ciphertext encrypted under it")
				fmt.Fprintln(os.Stderr, "becomes permanently undecryptable.")
				return openbao.ErrConfirmationRequired
			}

			bc, err := openbao.NewClient(ctx, flags.toConfig())
			if err != nil {
				return err
			}
			adapter, err := openbao.NewHostAdapter(bc)
			if err != nil {
				return err
			}
			fmt.Fprintf(os.Stderr, "destroying OpenBao state for %s in 5 seconds. ^C to abort.\n", args[0])
			for i := 5; i > 0; i-- {
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(time.Second):
					fmt.Fprintf(os.Stderr, "  %d...\n", i)
				}
			}
			if err := adapter.Remove(ctx, openbao.RemoveInput{
				DeploymentID:      args[0],
				ConfirmDestroyKey: true,
			}); err != nil {
				return err
			}
			fmt.Println("openbao adapter Remove succeeded.")
			fmt.Println("  transit key destroyed:   ", args[0])
			fmt.Println("  policy deleted:          ", "saas-"+args[0])
			fmt.Println("  k8s role deleted:        ", args[0])
			fmt.Println("  kv namespace purged:     ", "secret/data/"+args[0]+"/*")
			return nil
		},
	}
	c.Flags().BoolVar(&confirmDestroyKey, "confirm-destroy-key", false, "Explicit confirmation for the destructive transit key delete. REQUIRED.")
	flags.attach(c)
	return c
}

func debugBaoVerifyCmd() *cobra.Command {
	flags := &baoClientFlags{}
	c := &cobra.Command{
		Use:   "verify <deployment_id>",
		Short: "Read-only probe: confirm all per-Deployment OpenBao artifacts exist.",
		Long: `Re-run the read-only post-Apply verification probe for an existing
Deployment. Useful after a manual 'bao policy edit' or to confirm the
state survived a restart. Does NOT modify any state.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}
			bc, err := openbao.NewClient(ctx, flags.toConfig())
			if err != nil {
				return err
			}
			adapter, err := openbao.NewHostAdapter(bc)
			if err != nil {
				return err
			}
			if err := adapter.VerifyAccess(ctx, args[0]); err != nil {
				return err
			}
			fmt.Println("openbao adapter VerifyAccess succeeded — all artifacts present.")
			return nil
		},
	}
	flags.attach(c)
	return c
}
