package workflows

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/coreos/go-oidc/v3/oidc"
	"golang.org/x/oauth2"
)

// OIDCConfig configures NewRefreshingHTTPClient. ClientSecret is required
// for confidential clients (operators); public clients may pass an empty
// string. The returned *http.Client auto-refreshes the access token using
// the supplied refresh token; expired refresh tokens cause subsequent
// calls to fail with the underlying oauth2 error.
//
// Per Open Question 3 in the Phase 14 plan: the SDK does NOT cache tokens
// to disk. Caching is the caller's concern (saasctl etc.).
type OIDCConfig struct {
	Issuer       string
	ClientID     string
	ClientSecret string
	Scopes       []string
	AccessToken  string
	RefreshToken string
	// Expiry is when the supplied AccessToken expires. If zero, the client
	// treats the token as already expired and forces a refresh on first use.
	Expiry time.Time
}

// NewRefreshingHTTPClient returns an *http.Client that injects Bearer
// tokens and refreshes them through the OIDC token endpoint as they
// approach expiry. The HTTP client returned can be passed to
// controlplane.NewClientWithResponses / dataplane.NewClientWithResponses
// via WithHTTPClient.
//
// The context supplied here is the long-lived context used for refresh —
// it controls cancellation of the refresh roundtrips, not the eventual
// API calls. Pass a derived context to the API client for per-call
// cancellation.
func NewRefreshingHTTPClient(ctx context.Context, cfg OIDCConfig) (*http.Client, error) {
	if cfg.Issuer == "" {
		return nil, errors.New("oidc: Issuer is required")
	}
	if cfg.RefreshToken == "" {
		return nil, errors.New("oidc: RefreshToken is required")
	}

	provider, err := oidc.NewProvider(ctx, cfg.Issuer)
	if err != nil {
		return nil, err
	}

	oauthCfg := &oauth2.Config{
		ClientID:     cfg.ClientID,
		ClientSecret: cfg.ClientSecret,
		Endpoint:     provider.Endpoint(),
		Scopes:       cfg.Scopes,
	}
	tok := &oauth2.Token{
		AccessToken:  cfg.AccessToken,
		RefreshToken: cfg.RefreshToken,
		TokenType:    "Bearer",
		Expiry:       cfg.Expiry,
	}
	tokenSource := oauthCfg.TokenSource(ctx, tok)
	return oauth2.NewClient(ctx, tokenSource), nil
}
