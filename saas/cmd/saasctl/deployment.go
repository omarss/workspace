// Phase 11: saasctl deployment + domain subtrees.
//
// All subcommands speak HTTP against a control-plane URL (default
// http://localhost:8080) with an operator-stub bearer header in local
// dev (Phase 13 swaps to a real Keycloak operators-realm token). The
// commands return raw JSON; the create-deployment path also extracts
// the one-time bootstrap secret and renders it with a "copy now" note
// because the secret is never retrievable again.

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/oklog/ulid/v2"
	"github.com/spf13/cobra"
)

// controlPlaneURL is the default control-plane API root for local dev.
const controlPlaneURL = "http://localhost:8080"

// deploymentCmd is the parent of all `saasctl deployment ...` operations.
func deploymentCmd() *cobra.Command {
	var (
		baseURL  string
		operator string
		scopes   string
	)
	c := &cobra.Command{
		Use:   "deployment",
		Short: "Manage SaaS Deployments (control plane).",
	}
	c.PersistentFlags().StringVar(&baseURL, "control-plane-url", controlPlaneURL, "Control plane base URL.")
	c.PersistentFlags().StringVar(&operator, "mock-operator", "op_local", "X-Mock-Operator-Id (dev-only).")
	c.PersistentFlags().StringVar(&scopes, "mock-scopes", "deployments.write deployments.read", "X-Mock-Operator-Scopes (dev-only).")

	c.AddCommand(deploymentListCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentCreateCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentGetCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentUpgradeCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentRollbackCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentRestartCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentRestoreCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentPurgeCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentDeleteCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentHealthCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentRevisionsCmd(&baseURL, &operator, &scopes))
	// Phase 12e additions.
	c.AddCommand(deploymentLedgerCmd(&baseURL, &operator, &scopes))
	c.AddCommand(deploymentFreezeKeysCmd(&baseURL, &operator, &scopes))
	return c
}

// deploymentLedgerCmd prints the §6.2 provisioning step ledger. Phase
// 12e wires the server-side route at GET /control/v1/deployments/{id}/
// provision-steps (added to the deployments handler once the
// control-plane skeleton lands; until then, the saasctl command exists
// so the CLI surface is stable from CHECKPOINT 9).
func deploymentLedgerCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "ledger <deployment_id>",
		Short: "Print a Deployment's provisioning step ledger.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodGet,
				*baseURL+"/control/v1/deployments/"+args[0]+"/provision-steps", nil, *op, *scopes)
			return runOperatorRequest(req)
		},
	}
}

// deploymentFreezeKeysCmd freezes the per-Deployment OpenBao transit
// key (§18.7). Requires step-up MFA in production (Phase 13); the
// dev path uses the mock-operator headers.
func deploymentFreezeKeysCmd(baseURL, op, scopes *string) *cobra.Command {
	var reason string
	c := &cobra.Command{
		Use:   "freeze-keys <deployment_id>",
		Short: "Freeze a Deployment's per-Deployment OpenBao keys (incident response).",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			body, _ := json.Marshal(map[string]any{"reason": reason})
			req := newOpRequest(cmd.Context(), http.MethodPost,
				*baseURL+"/control/v1/deployments/"+args[0]+"/freeze-keys", reader(body), *op, *scopes)
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
	c.Flags().StringVar(&reason, "reason", "", "Reason for the freeze (recorded in the audit row).")
	_ = c.MarkFlagRequired("reason")
	return c
}

// domainCmd is the parent of all `saasctl domain ...` BYOD operations.
func domainCmd() *cobra.Command {
	var (
		baseURL  string
		operator string
		scopes   string
	)
	c := &cobra.Command{
		Use:   "domain",
		Short: "Manage BYOD custom domain attachments.",
	}
	c.PersistentFlags().StringVar(&baseURL, "control-plane-url", controlPlaneURL, "Control plane base URL.")
	c.PersistentFlags().StringVar(&operator, "mock-operator", "op_local", "X-Mock-Operator-Id (dev-only).")
	c.PersistentFlags().StringVar(&scopes, "mock-scopes", "deployments.write deployments.read", "X-Mock-Operator-Scopes (dev-only).")

	c.AddCommand(domainAttachCmd(&baseURL, &operator, &scopes))
	c.AddCommand(domainListCmd(&baseURL, &operator, &scopes))
	c.AddCommand(domainVerifyCmd(&baseURL, &operator, &scopes))
	c.AddCommand(domainDetachCmd(&baseURL, &operator, &scopes))
	return c
}

// ── deployment subcommands ──────────────────────────────────────────────────

func deploymentListCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List Deployments.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			req := newOpRequest(cmd.Context(), http.MethodGet, *baseURL+"/control/v1/deployments", nil, *op, *scopes)
			return runOperatorRequest(req)
		},
	}
}

func deploymentCreateCmd(baseURL, op, scopes *string) *cobra.Command {
	var project, env, image, region string
	var modules []string
	c := &cobra.Command{
		Use:   "create",
		Short: "Create a Deployment.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			body := map[string]any{
				"project_slug":     project,
				"environment_slug": env,
				"image_version":    image,
			}
			if region != "" {
				body["region"] = region
			}
			if len(modules) > 0 {
				body["modules"] = modules
			}
			buf, _ := json.Marshal(body)
			req := newOpRequest(cmd.Context(), http.MethodPost, *baseURL+"/control/v1/deployments", reader(buf), *op, *scopes)
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequestWithBootstrap(req)
		},
	}
	c.Flags().StringVar(&project, "project", "", "Project slug.")
	c.Flags().StringVar(&env, "environment", "", "Environment slug.")
	c.Flags().StringVar(&image, "image", "", "Image version (e.g. v0.3.1).")
	c.Flags().StringVar(&region, "region", "", "Region (e.g. ksa-riyadh).")
	c.Flags().StringSliceVar(&modules, "modules", nil, "Modules to enable (comma-separated).")
	_ = c.MarkFlagRequired("project")
	_ = c.MarkFlagRequired("environment")
	_ = c.MarkFlagRequired("image")
	return c
}

func deploymentGetCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "get <deployment_id>",
		Short: "Get a Deployment.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodGet, *baseURL+"/control/v1/deployments/"+args[0], nil, *op, *scopes)
			return runOperatorRequest(req)
		},
	}
}

func deploymentUpgradeCmd(baseURL, op, scopes *string) *cobra.Command {
	var image string
	var noMigrations bool
	c := &cobra.Command{
		Use:   "upgrade <deployment_id>",
		Short: "Upgrade a Deployment to a new image version.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			body, _ := json.Marshal(map[string]any{
				"image_version":  image,
				"run_migrations": !noMigrations,
			})
			req := newOpRequest(cmd.Context(), http.MethodPost, *baseURL+"/control/v1/deployments/"+args[0]+"/upgrade", reader(body), *op, *scopes)
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
	c.Flags().StringVar(&image, "image", "", "New image version.")
	c.Flags().BoolVar(&noMigrations, "no-migrations", false, "Skip running data-plane migrations on the upgrade.")
	_ = c.MarkFlagRequired("image")
	return c
}

func deploymentRollbackCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "rollback <deployment_id>",
		Short: "Roll back to the previous revision.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodPost, *baseURL+"/control/v1/deployments/"+args[0]+"/rollback", nil, *op, *scopes)
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
}

func deploymentRestartCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "restart <deployment_id>",
		Short: "Restart a Deployment's pods.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodPost, *baseURL+"/control/v1/deployments/"+args[0]+"/restart", nil, *op, *scopes)
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
}

func deploymentRestoreCmd(baseURL, op, scopes *string) *cobra.Command {
	var toTimestamp string
	c := &cobra.Command{
		Use:   "restore <deployment_id>",
		Short: "Restore a Deployment to a point in time.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			body, _ := json.Marshal(map[string]any{"to_timestamp": toTimestamp})
			req := newOpRequest(cmd.Context(), http.MethodPost, *baseURL+"/control/v1/deployments/"+args[0]+"/restore", reader(body), *op, *scopes)
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
	c.Flags().StringVar(&toTimestamp, "to-timestamp", "", "RFC3339 target timestamp.")
	_ = c.MarkFlagRequired("to-timestamp")
	return c
}

func deploymentPurgeCmd(baseURL, op, scopes *string) *cobra.Command {
	var confirm bool
	c := &cobra.Command{
		Use:   "purge <deployment_id>",
		Short: "Hard delete a Deployment and all its data.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if !confirm {
				return fmt.Errorf("refusing to purge without --confirm")
			}
			req := newOpRequest(cmd.Context(), http.MethodPost, *baseURL+"/control/v1/deployments/"+args[0]+"/purge", nil, *op, *scopes)
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
	c.Flags().BoolVar(&confirm, "confirm", false, "Required: confirm the destructive purge.")
	return c
}

func deploymentDeleteCmd(baseURL, op, scopes *string) *cobra.Command {
	var retainDays int
	c := &cobra.Command{
		Use:   "delete <deployment_id>",
		Short: "Soft-delete a Deployment.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			url := fmt.Sprintf("%s/control/v1/deployments/%s?retain_days=%d", *baseURL, args[0], retainDays)
			req := newOpRequest(cmd.Context(), http.MethodDelete, url, nil, *op, *scopes)
			return runOperatorRequest(req)
		},
	}
	c.Flags().IntVar(&retainDays, "retain-days", 30, "Retention window before purge eligibility.")
	return c
}

func deploymentHealthCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "health <deployment_id>",
		Short: "Show a Deployment's health.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodGet, *baseURL+"/control/v1/deployments/"+args[0]+"/health", nil, *op, *scopes)
			return runOperatorRequest(req)
		},
	}
}

func deploymentRevisionsCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "revisions <deployment_id>",
		Short: "List a Deployment's revisions.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodGet, *baseURL+"/control/v1/deployments/"+args[0]+"/revisions", nil, *op, *scopes)
			return runOperatorRequest(req)
		},
	}
}

// ── domain subcommands ─────────────────────────────────────────────────────

func domainAttachCmd(baseURL, op, scopes *string) *cobra.Command {
	var domain string
	c := &cobra.Command{
		Use:   "attach <deployment_id>",
		Short: "Attach a custom BYOD domain to a Deployment.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			body, _ := json.Marshal(map[string]any{"domain": domain})
			req := newOpRequest(cmd.Context(), http.MethodPost, *baseURL+"/control/v1/deployments/"+args[0]+"/domains", reader(body), *op, *scopes)
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
	c.Flags().StringVar(&domain, "domain", "", "Custom domain (FQDN).")
	_ = c.MarkFlagRequired("domain")
	return c
}

func domainListCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "list <deployment_id>",
		Short: "List custom domains attached to a Deployment.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodGet, *baseURL+"/control/v1/deployments/"+args[0]+"/domains", nil, *op, *scopes)
			return runOperatorRequest(req)
		},
	}
}

func domainVerifyCmd(baseURL, op, scopes *string) *cobra.Command {
	var domainID string
	c := &cobra.Command{
		Use:   "verify <deployment_id>",
		Short: "Verify the DNS TXT record for an attached domain.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodPost,
				*baseURL+"/control/v1/deployments/"+args[0]+"/domains/"+domainID+"/verify", nil, *op, *scopes)
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
	c.Flags().StringVar(&domainID, "domain-id", "", "Domain id (dom_...).")
	_ = c.MarkFlagRequired("domain-id")
	return c
}

func domainDetachCmd(baseURL, op, scopes *string) *cobra.Command {
	var domainID string
	c := &cobra.Command{
		Use:   "detach <deployment_id>",
		Short: "Detach a custom domain from a Deployment.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodDelete,
				*baseURL+"/control/v1/deployments/"+args[0]+"/domains/"+domainID, nil, *op, *scopes)
			return runOperatorRequest(req)
		},
	}
	c.Flags().StringVar(&domainID, "domain-id", "", "Domain id (dom_...).")
	_ = c.MarkFlagRequired("domain-id")
	return c
}

// ── helpers ────────────────────────────────────────────────────────────────

// newOpRequest builds an http.Request with the mock-operator headers
// pre-populated. Phase 13 swaps these for a real Keycloak bearer token.
func newOpRequest(ctx context.Context, method, url string, body io.Reader, operatorID, scopes string) *http.Request {
	req, _ := http.NewRequestWithContext(ctx, method, url, body)
	if operatorID != "" {
		req.Header.Set("X-Mock-Operator-Id", operatorID)
	}
	if scopes != "" {
		req.Header.Set("X-Mock-Operator-Scopes", scopes)
	}
	return req
}

// runOperatorRequest dispatches and prints the response body. Non-2xx
// statuses surface as command errors so the shell exit code reflects
// the result.
func runOperatorRequest(req *http.Request) error {
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	body, _ := io.ReadAll(resp.Body)
	fmt.Println(resp.Status)
	fmt.Println(string(body))
	if resp.StatusCode >= 400 {
		return fmt.Errorf("request failed: %s", resp.Status)
	}
	return nil
}

// runOperatorRequestWithBootstrap is the create-deployment variant that
// extracts the one-time bootstrap secret and prints a copy-now banner.
// Falls back to plain response printing if the body isn't shaped as the
// CreateDeploymentResponse.
func runOperatorRequestWithBootstrap(req *http.Request) error {
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	body, _ := io.ReadAll(resp.Body)
	fmt.Println(resp.Status)
	if resp.StatusCode >= 400 {
		fmt.Println(string(body))
		return fmt.Errorf("request failed: %s", resp.Status)
	}
	var parsed struct {
		Data struct {
			ID           string `json:"id"`
			PrimaryVhost string `json:"primary_vhost"`
		} `json:"data"`
		BootstrapAPIKey struct {
			ID       string `json:"id"`
			Secret   string `json:"secret"`
			TenantID string `json:"tenant_id"`
		} `json:"bootstrap_api_key"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil || parsed.Data.ID == "" {
		fmt.Println(string(body))
		return nil
	}
	fmt.Printf("Deployment created: %s\n", parsed.Data.ID)
	fmt.Printf("Primary vhost:      %s\n", parsed.Data.PrimaryVhost)
	fmt.Printf("Bootstrap tenant:   %s\n", parsed.BootstrapAPIKey.TenantID)
	fmt.Printf("Bootstrap API key:  %s\n", parsed.BootstrapAPIKey.ID)
	fmt.Printf("Bootstrap secret:   %s\n", parsed.BootstrapAPIKey.Secret)
	fmt.Println()
	fmt.Println(strings.Repeat("=", 70))
	fmt.Println("IMPORTANT: copy the bootstrap secret NOW. It will not be shown again.")
	fmt.Println(strings.Repeat("=", 70))
	return nil
}
