package envelope

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"

	bao "github.com/openbao/openbao/api/v2"
)

// AuthMethod selects which OpenBao auth flow Client.New runs at startup.
type AuthMethod string

const (
	// AuthKubernetes posts the in-pod ServiceAccount JWT to
	// auth/kubernetes/login. Role name is the deployment_id; Phase 12d
	// provisions one role per Deployment.
	AuthKubernetes AuthMethod = "kubernetes"
	// AuthAppRole posts (role_id, secret_id) to auth/approle/login. Used by
	// the control-plane host process where there is no SA JWT available.
	AuthAppRole AuthMethod = "approle"
)

// Options configures Client.New. Required fields depend on AuthMethod.
type Options struct {
	// Address is the OpenBao listener URL ("http://127.0.0.1:8200" locally,
	// "https://openbao.svc:8200" in cluster).
	Address string
	// CACertPath is the PEM-encoded CA bundle for TLS verification.
	// Optional; required only when AuthMethod uses TLS.
	CACertPath string
	// AuthMethod chooses between AuthKubernetes and AuthAppRole.
	AuthMethod AuthMethod
	// Role is the k8s auth role name (must equal deployment_id for data-plane
	// pods). Required when AuthMethod == AuthKubernetes.
	Role string
	// SAJWTPath overrides the default in-pod ServiceAccount token path
	// ("/var/run/secrets/kubernetes.io/serviceaccount/token"). Useful for
	// test fakes that drop a token file in a tmp directory.
	SAJWTPath string
	// RoleID + SecretID are the AppRole credentials. Required when
	// AuthMethod == AuthAppRole. The control plane sources these from
	// /etc/saas/approle/{role_id,secret_id} in production; from env vars
	// OPENBAO_APPROLE_ROLE_ID / OPENBAO_APPROLE_SECRET_ID in local dev.
	RoleID   string
	SecretID string
	// RenewIncrement is the lease renewal increment in seconds. Defaults to
	// 3600 (1 h) when zero. The lifetime watcher renews around 2/3 of TTL.
	RenewIncrement int
}

// Client wraps the bao API client and a background lifetime watcher that
// keeps the auth token fresh. Construct exactly one per process and share it
// across handlers. Closing the Client stops the renewal goroutine.
type Client struct {
	bao *bao.Client

	stopOnce sync.Once
	watcher  *bao.LifetimeWatcher
	watchWG  sync.WaitGroup
}

// New constructs a Client, authenticates via opts.AuthMethod, and starts the
// lifetime watcher. The caller owns the returned Client and must Close it on
// shutdown.
func New(ctx context.Context, opts Options) (*Client, error) {
	if opts.Address == "" {
		return nil, errors.New("envelope: Address is required")
	}
	cfg := bao.DefaultConfig()
	cfg.Address = opts.Address
	if opts.CACertPath != "" {
		if err := cfg.ConfigureTLS(&bao.TLSConfig{CACert: opts.CACertPath}); err != nil {
			return nil, fmt.Errorf("envelope: configure TLS: %w", err)
		}
	}
	bc, err := bao.NewClient(cfg)
	if err != nil {
		return nil, fmt.Errorf("envelope: new bao client: %w", err)
	}

	var auth *bao.Secret
	switch opts.AuthMethod {
	case AuthKubernetes:
		auth, err = loginKubernetes(ctx, bc, opts)
	case AuthAppRole:
		auth, err = loginAppRole(ctx, bc, opts)
	default:
		return nil, fmt.Errorf("envelope: unknown auth method %q", opts.AuthMethod)
	}
	if err != nil {
		return nil, err
	}
	if auth == nil || auth.Auth == nil || auth.Auth.ClientToken == "" {
		return nil, errors.New("envelope: auth response carried no client token")
	}

	bc.SetToken(auth.Auth.ClientToken)

	c := &Client{bao: bc}
	if err := c.startLifetimeWatcher(auth, opts.RenewIncrement); err != nil {
		// A renewal failure shouldn't block startup — the token is still
		// valid for its initial TTL. Log via the caller's logger? We return
		// the error so the operator can decide; the recommended pattern is
		// to log+continue.
		return nil, fmt.Errorf("envelope: start lifetime watcher: %w", err)
	}
	return c, nil
}

// startLifetimeWatcher kicks off the bao lifetime renewal loop. The watcher
// publishes renewal events on its RenewCh; we currently consume + discard
// them. DoneCh signals an unrecoverable renewal failure — when that fires
// the watcher goroutine returns and the Client surfaces stale-token errors
// on subsequent calls (which the caller's retry logic can then handle).
func (c *Client) startLifetimeWatcher(auth *bao.Secret, increment int) error {
	if !auth.Auth.Renewable {
		// Some auth methods return non-renewable tokens (e.g. when the role
		// has token_max_ttl <= token_ttl). Skip the watcher in that case;
		// the caller is responsible for re-authenticating.
		return nil
	}
	if increment <= 0 {
		increment = 3600
	}
	w, err := c.bao.NewLifetimeWatcher(&bao.LifetimeWatcherInput{
		Secret:    auth,
		Increment: increment,
	})
	if err != nil {
		return err
	}
	c.watcher = w
	c.watchWG.Add(1)
	go func() {
		defer c.watchWG.Done()
		go w.Start()
		for {
			select {
			case err := <-w.DoneCh():
				// DoneCh fires once. err==nil means the secret reached its
				// max TTL and the watcher gave up gracefully; err != nil
				// signals a renewal failure. Either way we exit and let the
				// caller's circuit-breaker handle the next request.
				_ = err
				return
			case <-w.RenewCh():
				// Renewed; nothing to do.
			}
		}
	}()
	return nil
}

// Close stops the lifetime watcher and releases its goroutine. Safe to call
// more than once.
func (c *Client) Close() error {
	c.stopOnce.Do(func() {
		if c.watcher != nil {
			c.watcher.Stop()
		}
	})
	c.watchWG.Wait()
	return nil
}

// Logical returns the underlying bao Logical client. Exposed for KV helpers
// + tests; production code should not call it directly.
func (c *Client) Logical() *bao.Logical {
	return c.bao.Logical()
}

// NewForTest builds a Client pre-loaded with a static token, skipping the
// auth-method flow. Test-only — integration tests reach for this when the
// compose stack already exposes a working token (root token in local dev).
// Production paths must use New.
func NewForTest(address, token string) *Client {
	cfg := bao.DefaultConfig()
	cfg.Address = address
	bc, err := bao.NewClient(cfg)
	if err != nil {
		// Test-only helper; panic on misconfiguration so a typo doesn't
		// silently degrade to a no-op Client.
		panic("envelope.NewForTest: " + err.Error())
	}
	bc.SetToken(token)
	return &Client{bao: bc}
}

// validateKid rejects empty kids and the wildcard form. A kid with `/`,
// whitespace, or `..` would be path-traversal into another transit key —
// reject those at the package boundary.
func validateKid(kid string) error {
	if kid == "" {
		return ErrEmptyKID
	}
	if strings.ContainsAny(kid, "/ \t\r\n") || strings.Contains(kid, "..") {
		return fmt.Errorf("envelope: invalid kid %q", kid)
	}
	return nil
}
