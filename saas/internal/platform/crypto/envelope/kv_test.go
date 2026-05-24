package envelope

import (
	"strings"
	"testing"
)

// TestKVPathValidation exercises the path-traversal guard at every
// boundary that constructs a KV API path. The tests use unexported
// helpers so the assertion is on the path-building logic, not on a live
// OpenBao response.
func TestKVPathValidation(t *testing.T) {
	cases := []struct {
		name         string
		deploymentID string
		path         string
		wantErr      bool
	}{
		{"happy", "dep_A", "smtp/creds", false},
		{"leading-slash", "dep_A", "/smtp/creds", true},
		{"dotdot", "dep_A", "../dep_B/smtp", true},
		{"empty-deployment", "", "smtp", true},
		{"empty-path", "dep_A", "", true},
		{"deployment-traversal", "dep/A", "smtp", true},
		{"deployment-whitespace", "dep A", "smtp", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := kvDataPath(tc.deploymentID, tc.path)
			if (err != nil) != tc.wantErr {
				t.Errorf("kvDataPath: err=%v, want error=%v", err, tc.wantErr)
			}
			_, err = kvMetadataPath(tc.deploymentID, tc.path)
			if (err != nil) != tc.wantErr {
				t.Errorf("kvMetadataPath: err=%v, want error=%v", err, tc.wantErr)
			}
		})
	}
}

// TestKVPath_DeploymentNamespaceCarriesThrough asserts the constructed
// path includes the deployment_id prefix and no global wildcard form.
// A copy-paste regression that drops the namespace would expose every
// Deployment's secrets under the same path.
func TestKVPath_DeploymentNamespaceCarriesThrough(t *testing.T) {
	got, err := kvDataPath("dep_X", "smtp/creds")
	if err != nil {
		t.Fatalf("kvDataPath: %v", err)
	}
	if !strings.HasPrefix(got, "secret/data/dep_X/") {
		t.Errorf("path %q missing deployment namespace prefix", got)
	}
	if strings.Contains(got, "//") {
		t.Errorf("path %q contains double slash", got)
	}
}

// TestParseKeyVersion covers the wrapped-DEK prefix parser. OpenBao emits
// either "vault:v3:<b64>" (Vault compat) or "openbao:v3:<b64>"; we accept
// both. Anything else returns 0 — the rewrap walker treats version 0 as
// "unknown" and re-wraps the row.
func TestParseKeyVersion(t *testing.T) {
	cases := []struct {
		in   string
		want int
	}{
		{"vault:v3:abc", 3},
		{"openbao:v12:zzz", 12},
		{"vault:v0:abc", 0},
		{"", 0},
		{"malformed", 0},
		{"vault:vX:abc", 0},
		{"vault:3:abc", 0},
	}
	for _, tc := range cases {
		got := parseKeyVersion(tc.in)
		if got != tc.want {
			t.Errorf("parseKeyVersion(%q) = %d, want %d", tc.in, got, tc.want)
		}
	}
}
