// Phase 13 — saasctl operator + impersonation subtrees.
//
// All commands speak HTTP against a control-plane URL with operator
// mock headers (Phase 11 dev pattern). The real PKCE login flow lands
// alongside the gocloak admin client wiring in a later phase; for now
// the subtree exists so operator runbooks have a stable command set
// from CHECKPOINT 9 onward.

package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"

	"github.com/oklog/ulid/v2"
	"github.com/spf13/cobra"
)

// operatorCmd is the parent for operator-inventory commands. Read-only
// for MVP; write paths (add / remove / update-allowlist) land with the
// gocloak admin client wiring.
func operatorCmd() *cobra.Command {
	var (
		baseURL  string
		operator string
		scopes   string
	)
	c := &cobra.Command{
		Use:   "operator",
		Short: "Inspect operator inventory (control plane).",
	}
	c.PersistentFlags().StringVar(&baseURL, "control-plane-url", controlPlaneURL, "Control plane base URL.")
	c.PersistentFlags().StringVar(&operator, "mock-operator", "op_local", "X-Mock-Operator-Id (dev-only).")
	c.PersistentFlags().StringVar(&scopes, "mock-scopes", "operators.read", "X-Mock-Operator-Scopes (dev-only).")

	c.AddCommand(&cobra.Command{
		Use:   "list",
		Short: "List active operators (GET /control/v1/operators).",
		RunE: func(cmd *cobra.Command, _ []string) error {
			req := newOpRequest(cmd.Context(), http.MethodGet,
				baseURL+"/control/v1/operators", nil, operator, scopes)
			return runOperatorRequest(req)
		},
	})
	return c
}

// impersonationCmd is the parent for impersonation lifecycle commands.
// Per AGENTS.md §18.4 the mint endpoint requires step-up + the
// tenants.impersonate scope; the CLI just hands the request off — the
// server enforces the policy.
func impersonationCmd() *cobra.Command {
	var (
		baseURL  string
		operator string
		scopes   string
	)
	c := &cobra.Command{
		Use:   "impersonation",
		Short: "Start / end operator-impersonation sessions against a Deployment.",
	}
	c.PersistentFlags().StringVar(&baseURL, "control-plane-url", controlPlaneURL, "Control plane base URL.")
	c.PersistentFlags().StringVar(&operator, "mock-operator", "op_local", "X-Mock-Operator-Id (dev-only).")
	c.PersistentFlags().StringVar(&scopes, "mock-scopes",
		"tenants.impersonate deployments.read", "X-Mock-Operator-Scopes (dev-only).")

	c.AddCommand(impersonationStartCmd(&baseURL, &operator, &scopes))
	c.AddCommand(impersonationEndCmd(&baseURL, &operator, &scopes))
	return c
}

// impersonationStartCmd posts to /control/v1/deployments/{id}/impersonation-sessions.
// Prints the JWT + session id; the operator copies the JWT into the
// data-plane Authorization header for the duration.
func impersonationStartCmd(baseURL, op, scopes *string) *cobra.Command {
	var (
		tenant   string
		member   string
		reason   string
		duration int
	)
	c := &cobra.Command{
		Use:   "start <deployment_id>",
		Short: "Mint an operator-impersonation token (≤15 min).",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if strings.TrimSpace(reason) == "" {
				return fmt.Errorf("--reason is required (audit will record it verbatim)")
			}
			body := map[string]any{
				"target_tenant_id": tenant,
				"reason":           reason,
			}
			if member != "" {
				body["target_member_id"] = member
			}
			if duration > 0 {
				body["duration_seconds"] = duration
			}
			buf, _ := json.Marshal(body)
			req := newOpRequest(cmd.Context(), http.MethodPost,
				*baseURL+"/control/v1/deployments/"+args[0]+"/impersonation-sessions",
				reader(buf), *op, *scopes)
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runImpersonationStart(req)
		},
	}
	c.Flags().StringVar(&tenant, "tenant", "", "Target tenant_id the operator is acting AS (required).")
	c.Flags().StringVar(&member, "member", "", "Target member_id (optional).")
	c.Flags().StringVar(&reason, "reason", "", "Audit-visible reason; max 256 chars (required).")
	c.Flags().IntVar(&duration, "duration", 0, "Duration in seconds (default 300, max 900).")
	_ = c.MarkFlagRequired("tenant")
	_ = c.MarkFlagRequired("reason")
	return c
}

// impersonationEndCmd posts to .../impersonation-sessions/{id}/end.
func impersonationEndCmd(baseURL, op, scopes *string) *cobra.Command {
	return &cobra.Command{
		Use:   "end <deployment_id> <session_id>",
		Short: "Revoke an active impersonation session.",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			req := newOpRequest(cmd.Context(), http.MethodPost,
				*baseURL+"/control/v1/deployments/"+args[0]+"/impersonation-sessions/"+args[1]+"/end",
				nil, *op, *scopes)
			req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
			return runOperatorRequest(req)
		},
	}
}

// runImpersonationStart prints the issued JWT prominently with a copy-now
// banner. The token is shown ONCE — losing it means starting another
// session (audit-visible). The 2xx body shape mirrors the OpenAPI
// StartImpersonationResponse.
func runImpersonationStart(req *http.Request) error {
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	fmt.Println(resp.Status)
	if resp.StatusCode >= 400 {
		// Just dump the problem-details body verbatim; saasctl is
		// expected to be parsed by humans during incident response.
		var buf [4096]byte
		n, _ := resp.Body.Read(buf[:])
		fmt.Println(string(buf[:n]))
		return fmt.Errorf("request failed: %s", resp.Status)
	}
	var parsed struct {
		Token     string `json:"token"`
		ExpiresAt string `json:"expires_at"`
		SessionID string `json:"session_id,omitempty"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	// Intentionally swallow the *Fprintln/f errors: stdout writes are
	// best-effort during incident response; the structured error
	// (non-zero status) is conveyed by the function's return value.
	_, _ = fmt.Fprintln(os.Stdout, strings.Repeat("=", 70))
	_, _ = fmt.Fprintln(os.Stdout, "Impersonation token issued. Copy NOW — it is not retrievable.")
	_, _ = fmt.Fprintln(os.Stdout, strings.Repeat("=", 70))
	if parsed.SessionID != "" {
		_, _ = fmt.Fprintf(os.Stdout, "Session ID:  %s\n", parsed.SessionID)
	}
	_, _ = fmt.Fprintf(os.Stdout, "Expires at:  %s\n", parsed.ExpiresAt)
	_, _ = fmt.Fprintf(os.Stdout, "Token:       %s\n", parsed.Token)
	return nil
}
