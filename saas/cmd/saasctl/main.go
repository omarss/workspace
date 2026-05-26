// Command saasctl is the operator CLI for the SaaS control plane.
//
// Phase 1 shipped only `saasctl version`. Phase 2 adds a dev-convenience
// `tenant` subtree against a Data Plane URL (handy for smoke-testing the
// Phase-2 vertical slice) and stubs `saasctl init` so the eventual easy-setup
// wizard (ADR 016, Phase 15) is discoverable from day one.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/oklog/ulid/v2"
	"github.com/spf13/cobra"
)

func main() {
	root := &cobra.Command{
		Use:   "saasctl",
		Short: "Operator CLI for the SaaS control plane.",
	}
	root.AddCommand(
		versionCmd(),
		initCmd(),
		tenantCmd(),
		deploymentCmd(),
		domainCmd(),
		// Phase 13 — operator inventory + impersonation lifecycle. The
		// subtree calls the same control-plane API as everything else;
		// the operator add / remove flows are deferred to a later phase
		// because they require the gocloak admin client wiring, but
		// `list` + `impersonate` are surfaced now so incident-response
		// runbooks have a stable command set from Phase 13 onward.
		operatorCmd(),
		impersonationCmd(),
	)
	// Phase 12a-d shipped `saasctl debug <adapter>` helpers behind
	// CHECKPOINT 5/6/7/8. Phase 12e composes the four adapters into
	// the full §6.2 provisioning sequence, so the debug subtree is
	// removed — every adapter is now exercised by the production
	// `saasctl deployment create` flow via HostProvisioner.
	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
}

func versionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Print version.",
		Run:   func(*cobra.Command, []string) { fmt.Println("saasctl dev") },
	}
}

// initCmd is the Phase-15 easy-setup wizard placeholder (ADR 016). It exists
// in Phase 2 so the command surface is stable from the first release; the
// implementation prints a polite "not yet implemented" message.
func initCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "init",
		Short: "Bootstrap a local SaaS stack (wired in Phase 15).",
		Run: func(*cobra.Command, []string) {
			fmt.Println("init: not yet implemented; runs in Phase 15")
		},
	}
}

// tenantCmd is a thin dev-convenience subtree. End users will eventually go
// through the generated TS SDK or the Control Plane API; saasctl tenant
// stays a quick smoke-test tool.
func tenantCmd() *cobra.Command {
	var (
		dataPlaneURL string
		mockTenant   string
	)
	c := &cobra.Command{
		Use:   "tenant",
		Short: "Tenant operations against a Data Plane URL (dev convenience).",
	}
	c.PersistentFlags().StringVar(&dataPlaneURL, "data-plane-url", "http://localhost:9090", "Data Plane base URL.")
	c.PersistentFlags().StringVar(&mockTenant, "mock-tenant", "", "X-Mock-Tenant-Id (dev-only).")

	c.AddCommand(&cobra.Command{
		Use:   "list",
		Short: "List tenants visible to the caller.",
		RunE: func(cmd *cobra.Command, _ []string) error {
			return tenantList(cmd.Context(), dataPlaneURL, mockTenant)
		},
	})
	c.AddCommand(&cobra.Command{
		Use:   "create [slug] [name]",
		Short: "Create a tenant (POST /v1/tenants).",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			return tenantCreate(cmd.Context(), dataPlaneURL, mockTenant, args[0], args[1])
		},
	})
	return c
}

func tenantList(ctx context.Context, baseURL, mockTenant string) error {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, baseURL+"/v1/tenants", nil)
	if mockTenant != "" {
		req.Header.Set("X-Mock-Tenant-Id", mockTenant)
	}
	return runRequest(req)
}

func tenantCreate(ctx context.Context, baseURL, mockTenant, slug, name string) error {
	body := map[string]any{"slug": slug, "name": name}
	buf, _ := json.Marshal(body)
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+"/v1/tenants", reader(buf))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())
	if mockTenant != "" {
		req.Header.Set("X-Mock-Tenant-Id", mockTenant)
	}
	return runRequest(req)
}

func runRequest(req *http.Request) error {
	client := &http.Client{Timeout: 15 * time.Second}
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

func reader(b []byte) io.Reader { return &byteReader{b: b} }

type byteReader struct {
	b []byte
	i int
}

func (r *byteReader) Read(p []byte) (int, error) {
	if r.i >= len(r.b) {
		return 0, io.EOF
	}
	n := copy(p, r.b[r.i:])
	r.i += n
	return n, nil
}
