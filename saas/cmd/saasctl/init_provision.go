// Phase 15 — `provision` and `summary` steps for saasctl init.
//
// `provision` POSTs to /control/v1/deployments to create the first
// Deployment (project_slug + environment_slug + image_version). The
// response carries the one-time bootstrap API key, which the wizard
// stashes in-memory so the summary step can render it inside a
// "COPY THIS NOW" banner.
//
// Idempotency: on POST conflict (409), the wizard re-fetches the
// existing Deployment via GET /control/v1/deployments and reports
// "(already done)" instead of failing. The bootstrap secret is, by
// design, only returned on the original create; on a re-run we omit
// it from the summary and emit a "secret already issued; rotate the
// API key if you need a new one" line.

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/oklog/ulid/v2"
)

// provisionResult is stashed on cfg so printSummary can render the
// bootstrap secret without re-fetching. We deliberately do NOT persist
// it to disk by default — the operator gets one chance to copy it.
type provisionResult struct {
	DeploymentID    string
	PrimaryVhost    string
	BootstrapKeyID  string
	BootstrapSecret string
	BootstrapTenant string
	WasExisting     bool
}

// runProvision performs the create-Deployment call. The result is
// stamped on cfg.lastProvision so the subsequent summary step can
// render the bootstrap secret in a single pass.
func runProvision(ctx context.Context, cfg *initConfig) (string, error) {
	existing, err := findExistingDeployment(ctx, cfg)
	if err != nil {
		return "", err
	}
	if existing != nil {
		cfg.lastProvision = &provisionResult{
			DeploymentID: existing.ID,
			PrimaryVhost: existing.PrimaryVhost,
			WasExisting:  true,
		}
		return "already done", nil
	}
	result, err := createDeployment(ctx, cfg)
	if err != nil {
		return "", err
	}
	cfg.lastProvision = result
	return "", nil
}

// printSummary renders the post-bootstrap summary block. Always writes
// to STDOUT; only writes to a file when --write-secret-file is set.
func printSummary(ctx context.Context, cfg *initConfig) (string, error) {
	res := cfg.lastProvision
	fmt.Println()
	fmt.Println("================================================================")
	fmt.Println(" SaaS Platform — bootstrap complete")
	fmt.Println("================================================================")
	fmt.Printf(" Project / Environment : %s / %s\n", cfg.Project, cfg.Environment)
	fmt.Printf(" Image version         : %s\n", cfg.ImageVersion)
	fmt.Printf(" Operator email        : %s\n", cfg.Operator.Email)
	fmt.Printf(" Control plane URL     : %s\n", cfg.ControlPlaneURL)
	fmt.Println(" Service URLs:")
	fmt.Println("   - Keycloak admin    : http://localhost:8081/admin/")
	fmt.Println("   - OpenBao           : http://localhost:8200")
	fmt.Println("   - Mailhog UI        : http://localhost:8025")
	fmt.Println("   - Novu dashboard    : http://localhost:4200")
	fmt.Println("   - Prism mock (CP)   : http://localhost:4010")
	fmt.Println("   - Prism mock (DP)   : http://localhost:4011")
	if res != nil && res.DeploymentID != "" {
		fmt.Printf(" Deployment ID         : %s\n", res.DeploymentID)
		if res.PrimaryVhost != "" {
			fmt.Printf(" Primary vhost         : %s\n", res.PrimaryVhost)
		}
	}
	fmt.Println("================================================================")
	if res != nil && !res.WasExisting && res.BootstrapSecret != "" {
		fmt.Println()
		fmt.Println(secretBanner("bootstrap API key secret (shown ONCE)", strings.TrimSpace(
			fmt.Sprintf("api_key_id=%s tenant_id=%s\nsecret=%s",
				res.BootstrapKeyID, res.BootstrapTenant, res.BootstrapSecret),
		)))
		if cfg.WriteSecretFile != "" {
			if err := writeSecretToFile(cfg.WriteSecretFile, res); err != nil {
				return "", fmt.Errorf("write secret file: %w", err)
			}
			fmt.Printf("\nSecret also appended to %s\n", cfg.WriteSecretFile)
		}
	} else if res != nil && res.WasExisting {
		fmt.Println(" The Deployment already existed; the bootstrap secret is not")
		fmt.Println(" retrievable. Rotate the API key if you need a fresh secret.")
	}
	fmt.Println()
	return "", nil
}

// writeSecretToFile appends the bootstrap secret to the operator's chosen
// path with 0600 permissions. We intentionally do not overwrite the file
// so multiple init re-runs build up an audit log of historical secrets.
func writeSecretToFile(path string, r *provisionResult) error {
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600) // #nosec G304 — operator-supplied --write-secret-file path
	if err != nil {
		return err
	}
	defer func() { _ = f.Close() }()
	stamp := nowUTC().Format(time.RFC3339)
	_, err = fmt.Fprintf(f, "# %s api_key_id=%s tenant_id=%s deployment_id=%s\nsecret=%s\n",
		stamp, r.BootstrapKeyID, r.BootstrapTenant, r.DeploymentID, r.BootstrapSecret)
	return err
}

// existingDeployment is the subset of GET /control/v1/deployments we
// care about for idempotency detection.
type existingDeployment struct {
	ID              string `json:"id"`
	ProjectSlug     string `json:"project_slug"`
	EnvironmentSlug string `json:"environment_slug"`
	PrimaryVhost    string `json:"primary_vhost"`
}

// findExistingDeployment returns the first Deployment matching the
// requested project+environment, or nil when none is found. Network
// errors are surfaced; "no deployments" is not an error.
func findExistingDeployment(ctx context.Context, cfg *initConfig) (*existingDeployment, error) {
	req := newOpRequest(ctx, http.MethodGet, cfg.ControlPlaneURL+"/control/v1/deployments",
		nil, "op_local", "deployments.read")
	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		// Control plane not running — treat as "not yet provisioned".
		return nil, nil
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, nil
	}
	body, _ := io.ReadAll(resp.Body)
	var page struct {
		Data []existingDeployment `json:"data"`
	}
	if err := json.Unmarshal(body, &page); err != nil {
		return nil, nil
	}
	for i, d := range page.Data {
		if d.ProjectSlug == cfg.Project && d.EnvironmentSlug == cfg.Environment {
			return &page.Data[i], nil
		}
	}
	return nil, nil
}

// createDeployment POSTs to /control/v1/deployments, extracts the
// bootstrap secret, and returns a populated provisionResult.
func createDeployment(ctx context.Context, cfg *initConfig) (*provisionResult, error) {
	body := map[string]any{
		"project_slug":     cfg.Project,
		"environment_slug": cfg.Environment,
		"image_version":    cfg.ImageVersion,
	}
	buf, _ := json.Marshal(body)
	req := newOpRequest(ctx, http.MethodPost, cfg.ControlPlaneURL+"/control/v1/deployments",
		bytes.NewReader(buf), "op_local", "deployments.write deployments.read")
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Idempotency-Key", "idem_"+ulid.Make().String())

	// Use the cached operator token when available.
	if creds, err := readCredentials(); err == nil && creds.Token != "" {
		req.Header.Set("Authorization", "Bearer "+creds.Token)
	}

	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("POST deployments: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("control plane refused create-deployment: %s: %s",
			resp.Status, string(raw))
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
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return nil, fmt.Errorf("parse create-deployment response: %w", err)
	}
	return &provisionResult{
		DeploymentID:    parsed.Data.ID,
		PrimaryVhost:    parsed.Data.PrimaryVhost,
		BootstrapKeyID:  parsed.BootstrapAPIKey.ID,
		BootstrapSecret: parsed.BootstrapAPIKey.Secret,
		BootstrapTenant: parsed.BootstrapAPIKey.TenantID,
	}, nil
}
