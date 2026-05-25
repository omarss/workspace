package notifications

import (
	"encoding/json"
	"fmt"
	"strings"
)

// SMTPCredentials carries the SMTP secret payload. host / port / from
// live on Channel.Config (plaintext); username / password live here and
// flow through the envelope walker.
type SMTPCredentials struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// SendGridCredentials carries the SendGrid HTTP API secret.
type SendGridCredentials struct {
	APIKey string `json:"api_key"`
}

// SESCredentials carries the AWS SES HTTP secret. AccessKeyID is mildly
// sensitive (it leaks the AWS account principal); SecretAccessKey is
// strictly sensitive.
type SESCredentials struct {
	AccessKeyID     string `json:"access_key_id"`
	SecretAccessKey string `json:"secret_access_key"`
}

// CredentialsBundle is the JSON shape used inside the envelope plaintext.
// Exactly one of the per-provider fields is populated based on the channel
// provider; the others are omitted. Keeping them in one struct lets the
// envelope walker work over a single string field without per-provider
// generics.
type CredentialsBundle struct {
	SMTP     *SMTPCredentials     `json:"smtp,omitempty"`
	SendGrid *SendGridCredentials `json:"sendgrid,omitempty"`
	SES      *SESCredentials      `json:"ses,omitempty"`
}

// MarshalCredentials serialises bundle to a compact JSON string suitable
// for storage in Channel.Secrets prior to envelope encryption. Returns an
// empty string for the in-app provider (no external creds — by design).
func MarshalCredentials(bundle CredentialsBundle) (string, error) {
	// in_app: nil bundle is acceptable and yields an empty payload.
	if bundle.SMTP == nil && bundle.SendGrid == nil && bundle.SES == nil {
		return "", nil
	}
	b, err := json.Marshal(bundle)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

// UnmarshalCredentials decodes a previously-marshalled credentials JSON
// string back into a bundle. Returns ErrInvalidCredentials when payload
// is structurally broken; the caller is responsible for asserting
// per-provider field presence after the parse.
func UnmarshalCredentials(payload string) (CredentialsBundle, error) {
	if strings.TrimSpace(payload) == "" {
		return CredentialsBundle{}, nil
	}
	var bundle CredentialsBundle
	if err := json.Unmarshal([]byte(payload), &bundle); err != nil {
		return CredentialsBundle{}, fmt.Errorf("%w: %w", ErrInvalidCredentials, err)
	}
	return bundle, nil
}

// ValidateCredentialsForProvider asserts that bundle matches the shape
// expected for provider. Returns ErrInvalidCredentials on mismatch (e.g.
// SMTP bundle for a SendGrid provider, or a SendGrid bundle missing
// api_key).
//
// The in_app provider rejects any non-empty bundle — Novu's in-app
// channel uses Novu's internal credentials, not the BYOK shape.
func ValidateCredentialsForProvider(provider ChannelProvider, bundle CredentialsBundle) error {
	switch provider {
	case ProviderSMTP:
		if bundle.SMTP == nil ||
			strings.TrimSpace(bundle.SMTP.Username) == "" ||
			strings.TrimSpace(bundle.SMTP.Password) == "" {
			return fmt.Errorf("%w: smtp requires username + password", ErrInvalidCredentials)
		}
		if bundle.SendGrid != nil || bundle.SES != nil {
			return fmt.Errorf("%w: smtp bundle must not carry other providers", ErrInvalidCredentials)
		}
	case ProviderSendGrid:
		if bundle.SendGrid == nil || strings.TrimSpace(bundle.SendGrid.APIKey) == "" {
			return fmt.Errorf("%w: sendgrid requires api_key", ErrInvalidCredentials)
		}
		if bundle.SMTP != nil || bundle.SES != nil {
			return fmt.Errorf("%w: sendgrid bundle must not carry other providers", ErrInvalidCredentials)
		}
	case ProviderSES:
		if bundle.SES == nil ||
			strings.TrimSpace(bundle.SES.AccessKeyID) == "" ||
			strings.TrimSpace(bundle.SES.SecretAccessKey) == "" {
			return fmt.Errorf("%w: ses requires access_key_id + secret_access_key", ErrInvalidCredentials)
		}
		if bundle.SMTP != nil || bundle.SendGrid != nil {
			return fmt.Errorf("%w: ses bundle must not carry other providers", ErrInvalidCredentials)
		}
	case ProviderInApp:
		if bundle.SMTP != nil || bundle.SendGrid != nil || bundle.SES != nil {
			return fmt.Errorf("%w: in_app channel does not accept external credentials", ErrInvalidCredentials)
		}
	default:
		return ErrInvalidProvider
	}
	return nil
}

// CredentialsForNovuIntegration produces the map[string]any payload Novu
// expects on PUT /v1/integrations/{id}. The platform calls this from the
// outbox worker after decrypting the channel envelope.
func CredentialsForNovuIntegration(provider ChannelProvider, bundle CredentialsBundle, config map[string]string) map[string]any {
	out := map[string]any{}
	switch provider {
	case ProviderSMTP:
		if bundle.SMTP != nil {
			out["user"] = bundle.SMTP.Username
			out["password"] = bundle.SMTP.Password
		}
		if config != nil {
			if v, ok := config["host"]; ok {
				out["host"] = v
			}
			if v, ok := config["port"]; ok {
				out["port"] = v
			}
			if v, ok := config["from"]; ok {
				out["from"] = v
			}
			if v, ok := config["starttls"]; ok {
				out["secure"] = v
			}
		}
	case ProviderSendGrid:
		if bundle.SendGrid != nil {
			out["apiKey"] = bundle.SendGrid.APIKey
		}
		if config != nil {
			if v, ok := config["from"]; ok {
				out["from"] = v
			}
		}
	case ProviderSES:
		if bundle.SES != nil {
			out["accessKeyId"] = bundle.SES.AccessKeyID
			out["secretAccessKey"] = bundle.SES.SecretAccessKey
		}
		if config != nil {
			if v, ok := config["region"]; ok {
				out["region"] = v
			}
			if v, ok := config["from"]; ok {
				out["from"] = v
			}
		}
	case ProviderInApp:
		// No-op — Novu uses its built-in in-app channel.
	}
	return out
}
