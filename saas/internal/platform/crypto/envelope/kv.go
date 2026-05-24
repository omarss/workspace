package envelope

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// KVPut writes data at secret/data/<deploymentID>/<path>. KV v2 wraps every
// payload under the literal `data` key — callers pass the inner map and the
// helper handles the wrapping.
//
// path must not contain ".." or start with "/" — the validation rejects
// path-traversal into another Deployment's namespace.
func (c *Client) KVPut(ctx context.Context, deploymentID, path string, data map[string]any) error {
	full, err := kvDataPath(deploymentID, path)
	if err != nil {
		return err
	}
	if _, err := c.bao.Logical().WriteWithContext(ctx, full, map[string]any{
		"data": data,
	}); err != nil {
		return fmt.Errorf("envelope: kv put: %w", err)
	}
	return nil
}

// KVGet reads from secret/data/<deploymentID>/<path>. Returns ErrNotFound
// when the path does not exist (vs a transport error which is wrapped).
func (c *Client) KVGet(ctx context.Context, deploymentID, path string) (map[string]any, error) {
	full, err := kvDataPath(deploymentID, path)
	if err != nil {
		return nil, err
	}
	sec, err := c.bao.Logical().ReadWithContext(ctx, full)
	if err != nil {
		return nil, fmt.Errorf("envelope: kv get: %w", err)
	}
	if sec == nil || sec.Data == nil {
		return nil, ErrNotFound
	}
	raw, ok := sec.Data["data"].(map[string]any)
	if !ok || raw == nil {
		return nil, ErrNotFound
	}
	return raw, nil
}

// KVDelete removes both the live value and all historical versions at
// secret/metadata/<deploymentID>/<path>. KV v2 distinguishes between
// soft-delete (DELETE /data/...) and hard-delete (DELETE /metadata/...);
// we always hard-delete because the platform does not need version history
// for secrets stored by the application layer.
func (c *Client) KVDelete(ctx context.Context, deploymentID, path string) error {
	full, err := kvMetadataPath(deploymentID, path)
	if err != nil {
		return err
	}
	if _, err := c.bao.Logical().DeleteWithContext(ctx, full); err != nil {
		return fmt.Errorf("envelope: kv delete: %w", err)
	}
	return nil
}

// kvDataPath builds the KV v2 "data" sub-path for a (deploymentID, path)
// pair and validates the inputs.
func kvDataPath(deploymentID, path string) (string, error) {
	if err := validateKVInputs(deploymentID, path); err != nil {
		return "", err
	}
	return "secret/data/" + deploymentID + "/" + strings.Trim(path, "/"), nil
}

// kvMetadataPath builds the KV v2 "metadata" sub-path (used for delete).
func kvMetadataPath(deploymentID, path string) (string, error) {
	if err := validateKVInputs(deploymentID, path); err != nil {
		return "", err
	}
	return "secret/metadata/" + deploymentID + "/" + strings.Trim(path, "/"), nil
}

// validateKVInputs forbids empty deployment IDs and any path that contains
// `..` or starts with `/`. Either pattern would let a caller escape the
// per-Deployment namespace.
func validateKVInputs(deploymentID, path string) error {
	if deploymentID == "" {
		return errors.New("envelope: empty deploymentID")
	}
	if strings.ContainsAny(deploymentID, "/ \t\r\n") {
		return fmt.Errorf("envelope: invalid deploymentID %q", deploymentID)
	}
	if path == "" {
		return errors.New("envelope: empty kv path")
	}
	if strings.Contains(path, "..") || strings.HasPrefix(path, "/") {
		return fmt.Errorf("envelope: invalid kv path %q", path)
	}
	return nil
}

// ErrNotFound is returned by KVGet when the requested path has no data.
var ErrNotFound = errors.New("envelope: kv path not found")
