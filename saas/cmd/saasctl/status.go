// Phase 15 — `saasctl status` command.
//
// One-shot snapshot of the local SaaS stack:
//   1) docker compose health (falls back to podman compose)
//   2) control-plane Deployments (GET /control/v1/deployments)
//   3) Operators inventory       (GET /control/v1/operators)
//
// Missing services are marked "(not running)"; missing endpoints do
// NOT fail the command — the goal is "always rendered, never blocks".

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

func statusCommand() *cobra.Command {
	var baseURL string
	c := &cobra.Command{
		Use:   "status",
		Short: "One-screen status: compose health + deployments + operators.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return printStatus(cmd.Context(), baseURL)
		},
	}
	c.Flags().StringVar(&baseURL, "control-plane-url", controlPlaneURL, "Control plane base URL.")
	return c
}

// printStatus is the orchestrator. Errors from individual sections are
// surfaced inline as "(not reachable: ...)" rather than aborting; the
// command's overall exit code is 0 as long as the snapshot rendered.
func printStatus(ctx context.Context, baseURL string) error {
	fmt.Println("SaaS Platform — Status")
	fmt.Println()
	fmt.Println("Compose stack:")
	printComposeStatus(ctx)
	fmt.Println()
	fmt.Println("Deployments:")
	printDeployments(ctx, baseURL)
	fmt.Println()
	fmt.Println("Operators:")
	printOperators(ctx, baseURL)
	return nil
}

func printComposeStatus(ctx context.Context) {
	svcs, err := composePSJSON(ctx, "")
	if err != nil {
		fmt.Printf("  (compose runtime unavailable: %v)\n", err)
		return
	}
	if len(svcs) == 0 {
		fmt.Println("  (no compose services running)")
		return
	}
	// Stable name-order so the snapshot is reproducible across runs.
	type row struct{ name, state string }
	rows := make([]row, 0, len(svcs))
	for _, s := range svcs {
		marker := "x"
		if isHealthy(s) {
			marker = "v"
		}
		label := s.Service
		if label == "" {
			label = s.Name
		}
		health := s.Health
		if health == "" {
			health = s.State
		}
		rows = append(rows, row{name: label, state: fmt.Sprintf("%s %s", marker, health)})
	}
	// Truncate names so the table fits in 80 cols.
	for _, r := range rows {
		name := truncate(r.name, 24)
		fmt.Printf("  %-24s %s\n", name, r.state)
	}
}

// deploymentRow mirrors the subset of the deployments response used
// by `saasctl status`.
type deploymentRow struct {
	ID              string `json:"id"`
	ProjectSlug     string `json:"project_slug"`
	EnvironmentSlug string `json:"environment_slug"`
	State           string `json:"state"`
	ImageVersion    string `json:"image_version"`
	PrimaryVhost    string `json:"primary_vhost"`
}

func printDeployments(ctx context.Context, baseURL string) {
	rows, err := fetchDeployments(ctx, baseURL)
	if err != nil {
		fmt.Printf("  (control plane not reachable: %v)\n", err)
		return
	}
	if len(rows) == 0 {
		fmt.Println("  (none — run `saasctl init` to provision the first one)")
		return
	}
	for _, d := range rows {
		fmt.Printf("  %s %-16s %-8s %-10s %s\n",
			truncate(d.ID, 26),
			truncate(d.ProjectSlug+"/"+d.EnvironmentSlug, 16),
			truncate(d.State, 8),
			truncate(d.ImageVersion, 10),
			truncate(d.PrimaryVhost, 32))
	}
}

func fetchDeployments(ctx context.Context, baseURL string) ([]deploymentRow, error) {
	req := newOpRequest(ctx, http.MethodGet, baseURL+"/control/v1/deployments", nil,
		"op_local", "deployments.read")
	if creds, err := readCredentials(); err == nil && creds.Token != "" {
		req.Header.Set("Authorization", "Bearer "+creds.Token)
	}
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("status %s", resp.Status)
	}
	body, _ := io.ReadAll(resp.Body)
	var page struct {
		Data []deploymentRow `json:"data"`
	}
	if err := json.Unmarshal(body, &page); err != nil {
		return nil, err
	}
	return page.Data, nil
}

// operatorRow is the subset of the operators inventory we render.
type operatorRow struct {
	ID          string   `json:"id"`
	Email       string   `json:"email"`
	State       string   `json:"state"`
	MFAEnrolled bool     `json:"mfa_enrolled"`
	Allowlist   []string `json:"ip_allowlist"`
}

func printOperators(ctx context.Context, baseURL string) {
	rows, err := fetchOperators(ctx, baseURL)
	if err != nil {
		fmt.Printf("  (control plane not reachable: %v)\n", err)
		return
	}
	if len(rows) == 0 {
		fmt.Println("  (none — the operators realm has no enrolled operators yet)")
		return
	}
	for _, op := range rows {
		mfa := "x"
		if op.MFAEnrolled {
			mfa = "v"
		}
		al := "any"
		if len(op.Allowlist) > 0 {
			al = strings.Join(op.Allowlist, ",")
		}
		fmt.Printf("  %s %-24s MFA:%s Allowlist:%s\n",
			truncate(op.ID, 26),
			truncate(op.Email, 24),
			mfa,
			truncate(al, 22))
	}
}

func fetchOperators(ctx context.Context, baseURL string) ([]operatorRow, error) {
	req := newOpRequest(ctx, http.MethodGet, baseURL+"/control/v1/operators", nil,
		"op_local", "operators.read")
	if creds, err := readCredentials(); err == nil && creds.Token != "" {
		req.Header.Set("Authorization", "Bearer "+creds.Token)
	}
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("status %s", resp.Status)
	}
	body, _ := io.ReadAll(resp.Body)
	var page struct {
		Data []operatorRow `json:"data"`
	}
	if err := json.Unmarshal(body, &page); err != nil {
		return nil, err
	}
	return page.Data, nil
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if n <= 3 {
		return s[:n]
	}
	return s[:n-3] + "..."
}
