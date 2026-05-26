// Phase 12c CP-7 verification helper: `saasctl debug postgres apply/remove
// <deployment_id>` exercises the Postgres adapter directly so the
// operator can verify per-Deployment database + role + grants +
// migrations + RLS on the homelab Postgres before Phase 12e composes
// nginx + k3s + Postgres + OpenBao into the full provisioning sequence.
//
// Build-tagged `!prod` — the prod binary literally does not link this
// file, mirroring the Phase 12a/12b debug_nginx.go / debug_k3s.go
// patterns. The prod release pipeline (Phase 13) sets `-tags prod`.

//go:build !prod

package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/spf13/cobra"

	"github.com/omarss/saas/internal/controlplane/provision/postgres"
)

// debugPostgresCmd is the CP-7 helper subtree. Attached to `saasctl
// debug` from debug_nginx.go's debugCmd().
func debugPostgresCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "postgres",
		Short: "Invoke the host-Postgres adapter directly (CP-7 verification).",
		Long: `Apply or remove a per-Deployment Postgres database + app role on
the host instance pointed at by --admin-dsn.

Pre-requisites:
  1. The admin DSN's role has CREATE DATABASE and CREATE ROLE
     privileges (typically the superuser-equivalent maintenance
     role; the dev homelab uses 'saas' with both flags set).
  2. The host Postgres allows password-based connections (md5 or
     scram-sha-256 in pg_hba.conf; not 'trust' or 'peer' only).

Phase 12c-only debug command. Removed in Phase 12e once the composite
provisioner owns the full sequence.`,
	}
	c.AddCommand(debugPostgresApplyCmd())
	c.AddCommand(debugPostgresRemoveCmd())
	return c
}

func debugPostgresApplyCmd() *cobra.Command {
	var (
		projectSlug     string
		environmentSlug string
		adminDSN        string
		hostExternal    string
	)
	c := &cobra.Command{
		Use:   "apply <deployment_id>",
		Short: "Provision per-Deployment DB + role + migrations + RLS verify.",
		Long: `Run the full provisioning flow for one Deployment:

  1. CREATE DATABASE saas_<project>_<env> (idempotent).
  2. CREATE ROLE saas_<project>_<env>_app with a fresh password,
     or rotate the password if the role exists.
  3. GRANT CONNECT + USAGE + default privileges to the role.
  4. Apply the embedded data-plane migrations as the role.
  5. Tighten audit_event grants (SELECT + INSERT only).
  6. Verify FORCE RLS on every tenant-bound table + run the
     role-bound cross-tenant probe.

On success the freshly generated app-role password is printed ONCE
to stdout. Capture it before the terminal scrolls — Phase 12c does
NOT persist it anywhere. Phase 12d wires OpenBao KV storage.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}
			in := postgres.ApplyInput{
				DeploymentID:    args[0],
				ProjectSlug:     projectSlug,
				EnvironmentSlug: environmentSlug,
				AdminDSN:        adminDSN,
				HostExternal:    hostExternal,
			}
			adapter := postgres.NewHostAdapter()
			res, err := adapter.Apply(ctx, in)
			if err != nil {
				if errors.Is(err, postgres.ErrRLSNotEnforced) || errors.Is(err, postgres.ErrRLSProbeFailed) {
					fmt.Fprintln(os.Stderr, "RLS invariant failed AFTER migrations applied. The DB and role exist but tenant isolation is not enforced; inspect with:")
					fmt.Fprintln(os.Stderr, "  psql -d", in.DBName(), "-c \"SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relkind='r' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname='public');\"")
				}
				return err
			}
			fmt.Println("postgres adapter Apply succeeded.")
			fmt.Println("  database:", res.DBName)
			fmt.Println("  app role:", res.RoleName)
			fmt.Println("  password (CAPTURE NOW — Phase 12c does not persist this):")
			fmt.Println("    ", res.RolePassword)
			fmt.Println("  per-deployment DSN (for CP-7 smoke):")
			fmt.Println("    ", res.PerDeploymentDSN)
			return nil
		},
	}
	c.Flags().StringVar(&projectSlug, "project-slug", "", "Project slug for the DB name (REQUIRED, [a-z][a-z0-9_]*).")
	c.Flags().StringVar(&environmentSlug, "environment-slug", "", "Environment slug for the DB name (REQUIRED, [a-z][a-z0-9_]*).")
	c.Flags().StringVar(&adminDSN, "admin-dsn", "", "Admin DSN with CREATE DATABASE / CREATE ROLE privileges (REQUIRED).")
	c.Flags().StringVar(&hostExternal, "host-external", "", "Optional host:port override for the returned per-Deployment DSN (default: host parsed from --admin-dsn).")
	_ = c.MarkFlagRequired("project-slug")
	_ = c.MarkFlagRequired("environment-slug")
	_ = c.MarkFlagRequired("admin-dsn")
	return c
}

func debugPostgresRemoveCmd() *cobra.Command {
	var (
		projectSlug         string
		environmentSlug     string
		adminDSN            string
		confirmDropDatabase bool
	)
	c := &cobra.Command{
		Use:   "remove <deployment_id>",
		Short: "DROP DATABASE + DROP ROLE for one Deployment (requires --confirm-drop-database).",
		Long: `Remove the per-Deployment DB and role. Destructive: every row in
the per-Deployment DB is unrecoverable after this command returns.

The --confirm-drop-database flag is REQUIRED. The command displays a
5-second countdown before executing as a final defense against
accidental destruction (the operator can ^C during the countdown to
abort).`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			if ctx == nil {
				ctx = context.Background()
			}
			in := postgres.RemoveInput{
				DeploymentID:        args[0],
				ProjectSlug:         projectSlug,
				EnvironmentSlug:     environmentSlug,
				AdminDSN:            adminDSN,
				ConfirmDropDatabase: confirmDropDatabase,
			}
			if !confirmDropDatabase {
				// Validate would reject this, but surface the message
				// early so the operator gets the runbook hint.
				fmt.Fprintln(os.Stderr, "refusing to drop without --confirm-drop-database.")
				return postgres.ErrConfirmationRequired
			}
			fmt.Fprintf(os.Stderr, "DROP DATABASE %s + DROP ROLE %s in 5 seconds. ^C to abort.\n", in.DBName(), in.RoleName())
			for i := 5; i > 0; i-- {
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(time.Second):
					fmt.Fprintf(os.Stderr, "  %d...\n", i)
				}
			}
			adapter := postgres.NewHostAdapter()
			if err := adapter.Remove(ctx, in); err != nil {
				if errors.Is(err, postgres.ErrConnectionsOpen) {
					fmt.Fprintln(os.Stderr, "DROP DATABASE failed because clients are still connected.")
					fmt.Fprintln(os.Stderr, "terminate them and retry, or run:")
					fmt.Fprintf(os.Stderr, "  psql \"%s\" -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='%s';\"\n", adminDSN, in.DBName())
				}
				return err
			}
			fmt.Println("postgres adapter Remove succeeded.")
			fmt.Println("  database dropped:", in.DBName())
			fmt.Println("  role dropped:   ", in.RoleName())
			return nil
		},
	}
	c.Flags().StringVar(&projectSlug, "project-slug", "", "Project slug used when --admin-dsn applied the deployment (REQUIRED).")
	c.Flags().StringVar(&environmentSlug, "environment-slug", "", "Environment slug used when --admin-dsn applied the deployment (REQUIRED).")
	c.Flags().StringVar(&adminDSN, "admin-dsn", "", "Admin DSN with DROP DATABASE / DROP ROLE privileges (REQUIRED).")
	c.Flags().BoolVar(&confirmDropDatabase, "confirm-drop-database", false, "Explicit confirmation for the destructive DROP. REQUIRED.")
	_ = c.MarkFlagRequired("project-slug")
	_ = c.MarkFlagRequired("environment-slug")
	_ = c.MarkFlagRequired("admin-dsn")
	return c
}
