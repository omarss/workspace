package openbao

import (
	"bytes"
	"context"
	_ "embed"
	"fmt"
	"text/template"

	bao "github.com/openbao/openbao/api/v2"
)

// policyTemplateBytes is the verbatim copy of
// deploy/openbao/policies/deployment.hcl.tmpl. We embed it here rather
// than reading it from deploy/ at runtime so the adapter has a stable,
// build-time-verified template — operators cannot accidentally swap in
// a wider policy by editing the file in their checkout. Phase 4 owns
// the canonical copy; this file is updated in lockstep when the
// template changes (the policy_template_drift_test asserts equality).
//
//go:embed embed/deployment.hcl.tmpl
var policyTemplateBytes []byte

// policyTemplateData is the data shape rendered into the template.
// Kept as a named struct rather than a generic map[string]any so the
// template's variable name matches a Go field name — a typo in either
// surfaces at compile time, not at provision time.
type policyTemplateData struct {
	DeploymentID string
}

// renderPolicy executes the embedded template with the supplied
// deployment_id. Returns the rendered HCL bytes ready for upload via
// sys/policies/acl/. Pure function — no OpenBao round-trip — so it is
// trivially unit-testable.
func renderPolicy(deploymentID string) ([]byte, error) {
	if deploymentID == "" {
		return nil, fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	tmpl, err := template.New("policy").Parse(string(policyTemplateBytes))
	if err != nil {
		return nil, fmt.Errorf("openbao: parse policy template: %w", err)
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, policyTemplateData{DeploymentID: deploymentID}); err != nil {
		return nil, fmt.Errorf("openbao: render policy template: %w", err)
	}
	return buf.Bytes(), nil
}

// writePolicy installs the rendered policy at sys/policies/acl/<name>.
// OpenBao's API treats `sys/policies/acl/<name>` as an upsert — writing
// the same content twice is a no-op at the catalog level, so Apply is
// safely idempotent. Empty rendered bytes are refused as a defense
// against a template that silently lost its content (e.g. the embed
// file was emptied by a bad merge).
func writePolicy(ctx context.Context, client *bao.Client, name string, rendered []byte) error {
	if name == "" {
		return fmt.Errorf("%w: policy name empty", ErrInvalidInput)
	}
	if len(bytes.TrimSpace(rendered)) == 0 {
		return fmt.Errorf("%w: rendered policy is empty", ErrInvalidInput)
	}

	// OpenBao's sys/policies/acl/<name> endpoint accepts the policy
	// string under the `policy` key. We use Logical().WriteWithContext
	// rather than Sys().PutPolicyWithContext because the Sys helper in
	// api/v2 routes through the same logical write path under the hood
	// but exposes a less ergonomic Context-less variant in some
	// vendored versions — sticking to Logical keeps us pinned to a
	// surface that's stable across openbao/api/v2 patch releases.
	if _, err := client.Logical().WriteWithContext(ctx, "sys/policies/acl/"+name, map[string]any{
		"policy": string(rendered),
	}); err != nil {
		return fmt.Errorf("openbao: write policy %s: %w", name, err)
	}
	return nil
}

// deletePolicy removes the per-Deployment policy. Idempotent: OpenBao
// returns success even when the policy does not exist.
func deletePolicy(ctx context.Context, client *bao.Client, name string) error {
	if name == "" {
		return fmt.Errorf("%w: policy name empty", ErrInvalidInput)
	}
	if _, err := client.Logical().DeleteWithContext(ctx, "sys/policies/acl/"+name); err != nil {
		return fmt.Errorf("openbao: delete policy %s: %w", name, err)
	}
	return nil
}

// readPolicy is the verification helper. Returns the on-disk policy
// content (empty string + nil error when the policy is missing — the
// caller decides whether that is an error).
func readPolicy(ctx context.Context, client *bao.Client, name string) (string, error) {
	if name == "" {
		return "", fmt.Errorf("%w: policy name empty", ErrInvalidInput)
	}
	sec, err := client.Logical().ReadWithContext(ctx, "sys/policies/acl/"+name)
	if err != nil {
		return "", fmt.Errorf("openbao: read policy %s: %w", name, err)
	}
	if sec == nil || sec.Data == nil {
		return "", nil
	}
	got, _ := sec.Data["policy"].(string)
	return got, nil
}
