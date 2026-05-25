package scrape

import (
	"encoding/json"
	"fmt"
	"os"
)

// Credentials are the two cookies the twitter web client uses to
// authenticate an authenticated session:
//
//	auth_token   — long-lived bearer-equivalent
//	ct0          — CSRF / X-CSRF-Token header value
//
// The user maintains them in a small JSON file on disk. We keep the
// JSON shape flat so future fields (e.g. multiple accounts for
// rotation) can land additively.
type Credentials struct {
	AuthToken string `json:"auth_token"`
	CT0       string `json:"ct0"`
}

// LoadCredentials reads the cookie file. Missing-file is a soft error
// returned to the caller (so the service can run in fixture-only mode
// when cookies haven't been pasted yet); malformed JSON or empty
// fields are hard errors so they don't silently fall through and
// produce confusing 0-row scrapes.
func LoadCredentials(path string) (Credentials, error) {
	body, err := os.ReadFile(path)
	if err != nil {
		return Credentials{}, fmt.Errorf("read cookies %q: %w", path, err)
	}
	var creds Credentials
	if err := json.Unmarshal(body, &creds); err != nil {
		return Credentials{}, fmt.Errorf("parse cookies %q: %w", path, err)
	}
	if creds.AuthToken == "" || creds.CT0 == "" {
		return Credentials{}, fmt.Errorf("cookies %q missing auth_token or ct0", path)
	}
	return creds, nil
}
