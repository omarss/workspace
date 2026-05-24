package envelope

import (
	"context"
	"errors"
	"fmt"

	bao "github.com/openbao/openbao/api/v2"
)

// loginAppRole posts (role_id, secret_id) to OpenBao's AppRole login endpoint.
// Used by the control-plane host process: there's no Kubernetes SA available
// because the controlplane binary runs on the host, not in cluster.
//
// Production: role_id + secret_id come from /etc/saas/approle/{role_id,
// secret_id} (0400 saas:saas). Local dev: env vars OPENBAO_APPROLE_ROLE_ID +
// OPENBAO_APPROLE_SECRET_ID, populated by `make openbao-approle-creds`.
func loginAppRole(ctx context.Context, bc *bao.Client, opts Options) (*bao.Secret, error) {
	if opts.RoleID == "" || opts.SecretID == "" {
		return nil, errors.New("envelope: AppRole auth requires RoleID and SecretID")
	}
	sec, err := bc.Logical().WriteWithContext(ctx, "auth/approle/login", map[string]any{
		"role_id":   opts.RoleID,
		"secret_id": opts.SecretID,
	})
	if err != nil {
		return nil, fmt.Errorf("envelope: approle login: %w", err)
	}
	return sec, nil
}
