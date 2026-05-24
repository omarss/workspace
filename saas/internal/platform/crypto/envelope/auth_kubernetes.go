package envelope

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"

	bao "github.com/openbao/openbao/api/v2"
)

// defaultK8sJWTPath is the standard in-pod ServiceAccount token mount per
// the Kubernetes projected token spec.
const defaultK8sJWTPath = "/var/run/secrets/kubernetes.io/serviceaccount/token"

// loginKubernetes posts the in-pod ServiceAccount JWT to OpenBao's k8s auth
// endpoint. The role name MUST equal the deployment_id for data-plane pods —
// Phase 12d's provisioner binds the per-Deployment SA to a role of the same
// name. Phase 4 wires this code path but only exercises it via test fakes;
// the production exercise happens in Phase 12b when the dataplane runs in
// cluster.
func loginKubernetes(ctx context.Context, bc *bao.Client, opts Options) (*bao.Secret, error) {
	if opts.Role == "" {
		return nil, errors.New("envelope: Kubernetes auth requires Role (= deployment_id)")
	}
	path := opts.SAJWTPath
	if path == "" {
		path = defaultK8sJWTPath
	}
	jwt, err := os.ReadFile(path) // #nosec G304 — path is a fixed in-pod mount
	if err != nil {
		return nil, fmt.Errorf("envelope: read SA token at %q: %w", path, err)
	}
	jwtStr := strings.TrimSpace(string(jwt))
	if jwtStr == "" {
		return nil, fmt.Errorf("envelope: empty SA token at %q", path)
	}
	sec, err := bc.Logical().WriteWithContext(ctx, "auth/kubernetes/login", map[string]any{
		"role": opts.Role,
		"jwt":  jwtStr,
	})
	if err != nil {
		return nil, fmt.Errorf("envelope: kubernetes login: %w", err)
	}
	return sec, nil
}
