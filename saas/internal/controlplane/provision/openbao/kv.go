package openbao

import (
	"context"
	"fmt"
	"time"

	bao "github.com/openbao/openbao/api/v2"
)

// provisionedMarkerPath is the leaf under secret/data/<dep_id>/ that
// the adapter writes to materialise the namespace. KV v2 has no
// explicit "create namespace" call — the namespace is implicit in the
// first write. Writing a single marker means `bao kv list
// secret/<dep_id>/` returns at least one entry, which is the operator
// signal that the path is provisioned.
const provisionedMarkerPath = "_provisioned"

// initKVPath writes a small marker under secret/data/<dep_id>/_provisioned
// so the KV namespace is visible to `bao kv list`. The marker stores
// metadata only (no secrets) — provisioned_at, deployment_id, and the
// hard-coded marker label. Future hardening: include the platform
// release version that provisioned the Deployment so operators can
// trace which migration ran the bootstrap.
//
// IMPORTANT: this marker is metadata, never a secret. The redactor
// list in internal/platform/log/redact.go does not need an entry for
// the keys we write here.
func initKVPath(ctx context.Context, client *bao.Client, deploymentID string) error {
	if deploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}

	// KV v2 wraps the user payload under the literal "data" key.
	full := "secret/data/" + deploymentID + "/" + provisionedMarkerPath
	body := map[string]any{
		"data": map[string]any{
			"deployment_id":  deploymentID,
			"provisioned_at": time.Now().UTC().Format(time.RFC3339),
			"marker":         "saas-controlplane-provisioned",
			"platform_layer": "phase-12d-openbao-provisioner",
		},
	}

	if _, err := client.Logical().WriteWithContext(ctx, full, body); err != nil {
		return fmt.Errorf("openbao: write kv marker at %s: %w", full, err)
	}
	return nil
}

// removeKVPath purges every key under secret/data/<dep_id>/ by deleting
// the metadata for each path the lister finds. KV v2 stores history
// under secret/metadata/ — deleting the metadata wipes both the live
// value and the version history, which is what we want for the destroy
// reconciler (no value should survive a destroyed Deployment).
//
// Implementation: list the metadata prefix; recursively delete each
// child. The list-and-delete loop is bounded to the entries we find;
// no recursion-bomb defence is needed because OpenBao does not return
// cyclic listings.
func removeKVPath(ctx context.Context, client *bao.Client, deploymentID string) error {
	if deploymentID == "" {
		return fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	return deleteKVTree(ctx, client, "secret/metadata/"+deploymentID+"/")
}

// deleteKVTree walks a KV v2 metadata subtree and deletes every leaf.
// listPath ends with a trailing slash — OpenBao's LIST semantics
// require the directory form.
func deleteKVTree(ctx context.Context, client *bao.Client, listPath string) error {
	sec, err := client.Logical().ListWithContext(ctx, listPath)
	if err != nil {
		return fmt.Errorf("openbao: list %s: %w", listPath, err)
	}
	if sec == nil || sec.Data == nil {
		// Empty directory or missing path. Nothing to delete.
		return nil
	}
	raw, ok := sec.Data["keys"].([]any)
	if !ok {
		return nil
	}
	for _, k := range raw {
		key, ok := k.(string)
		if !ok || key == "" {
			continue
		}
		// A trailing slash means the entry is a sub-directory; recurse.
		// Anything else is a leaf — delete its metadata.
		if key[len(key)-1] == '/' {
			if err := deleteKVTree(ctx, client, listPath+key); err != nil {
				return err
			}
			continue
		}
		fullMetadata := listPath + key
		if _, err := client.Logical().DeleteWithContext(ctx, fullMetadata); err != nil {
			return fmt.Errorf("openbao: delete kv metadata %s: %w", fullMetadata, err)
		}
	}
	return nil
}

// readKVMarker is the verification helper. Returns the marker data map
// (or nil when the marker is missing) plus any transport error.
func readKVMarker(ctx context.Context, client *bao.Client, deploymentID string) (map[string]any, error) {
	if deploymentID == "" {
		return nil, fmt.Errorf("%w: deployment_id empty", ErrInvalidInput)
	}
	full := "secret/data/" + deploymentID + "/" + provisionedMarkerPath
	sec, err := client.Logical().ReadWithContext(ctx, full)
	if err != nil {
		return nil, fmt.Errorf("openbao: read kv marker at %s: %w", full, err)
	}
	if sec == nil || sec.Data == nil {
		return nil, nil
	}
	inner, ok := sec.Data["data"].(map[string]any)
	if !ok {
		return nil, nil
	}
	return inner, nil
}
