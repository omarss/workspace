package openbao

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	bao "github.com/openbao/openbao/api/v2"
)

// Unit tests covering the pure helpers (input validation, policy
// rendering, name builders) plus mock-server-backed tests of the
// HostAdapter against a stub OpenBao API. The integration test in
// openbao_integration_test.go covers the live OpenBao path.

func TestValidateApplyInput(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name    string
		in      ApplyInput
		wantErr error
	}{
		{
			name: "happy",
			in: ApplyInput{
				DeploymentID:      "dep_test01",
				K3sNamespace:      "saas-dep-test01",
				K3sServiceAccount: "dataplane",
			},
		},
		{
			name: "empty deployment_id",
			in: ApplyInput{
				K3sNamespace:      "saas-dep-test01",
				K3sServiceAccount: "dataplane",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "unsafe deployment_id",
			in: ApplyInput{
				DeploymentID:      "dep' OR 1=1--",
				K3sNamespace:      "saas-x",
				K3sServiceAccount: "dataplane",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "deployment_id with slash",
			in: ApplyInput{
				DeploymentID:      "dep_a/dep_b",
				K3sNamespace:      "saas-x",
				K3sServiceAccount: "dataplane",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "empty namespace",
			in: ApplyInput{
				DeploymentID:      "dep_test01",
				K3sServiceAccount: "dataplane",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "namespace with uppercase",
			in: ApplyInput{
				DeploymentID:      "dep_test01",
				K3sNamespace:      "Saas-X",
				K3sServiceAccount: "dataplane",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "namespace leading hyphen",
			in: ApplyInput{
				DeploymentID:      "dep_test01",
				K3sNamespace:      "-bad",
				K3sServiceAccount: "dataplane",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "empty SA",
			in: ApplyInput{
				DeploymentID: "dep_test01",
				K3sNamespace: "saas-dep-test01",
			},
			wantErr: ErrInvalidInput,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			err := tc.in.Validate()
			if tc.wantErr == nil {
				if err != nil {
					t.Fatalf("Validate: unexpected err %v", err)
				}
				return
			}
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("Validate: got %v, want errors.Is=%v", err, tc.wantErr)
			}
		})
	}
}

func TestValidateRemoveInput(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name    string
		in      RemoveInput
		wantErr error
	}{
		{
			name: "happy",
			in: RemoveInput{
				DeploymentID:      "dep_test01",
				ConfirmDestroyKey: true,
			},
		},
		{
			name:    "missing confirmation",
			in:      RemoveInput{DeploymentID: "dep_test01"},
			wantErr: ErrConfirmationRequired,
		},
		{
			name:    "empty deployment_id",
			in:      RemoveInput{ConfirmDestroyKey: true},
			wantErr: ErrInvalidInput,
		},
		{
			name: "unsafe deployment_id",
			in: RemoveInput{
				DeploymentID:      "dep with space",
				ConfirmDestroyKey: true,
			},
			wantErr: ErrInvalidInput,
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			err := tc.in.Validate()
			if tc.wantErr == nil {
				if err != nil {
					t.Fatalf("Validate: unexpected err %v", err)
				}
				return
			}
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("Validate: got %v, want errors.Is=%v", err, tc.wantErr)
			}
		})
	}
}

// TestRenderPolicyContainsDeploymentID exercises the embedded template
// rendering. The deployment_id must be substituted into every path
// line and the rendered text must NOT contain the literal template
// placeholder (a regression that ships unrendered HCL to OpenBao
// would be catastrophic — the policy would be a glob).
func TestRenderPolicyContainsDeploymentID(t *testing.T) {
	t.Parallel()
	got, err := renderPolicy("dep_test01")
	if err != nil {
		t.Fatalf("renderPolicy: %v", err)
	}
	s := string(got)
	mustContain := []string{
		`transit/encrypt/dep_test01`,
		`transit/decrypt/dep_test01`,
		`transit/datakey/plaintext/dep_test01`,
		`transit/rewrap/dep_test01`,
		`transit/keys/dep_test01`,
		`secret/data/dep_test01/*`,
		`secret/metadata/dep_test01/*`,
	}
	for _, want := range mustContain {
		if !strings.Contains(s, want) {
			t.Errorf("rendered policy missing %q\nrendered:\n%s", want, s)
		}
	}
	if strings.Contains(s, "{{") || strings.Contains(s, "}}") {
		t.Errorf("rendered policy still contains template placeholders:\n%s", s)
	}
}

// TestRenderPolicyEmptyDeploymentID confirms the renderer refuses a
// blank deployment_id so a typo in the caller doesn't ship a policy
// with no path scoping at all.
func TestRenderPolicyEmptyDeploymentID(t *testing.T) {
	t.Parallel()
	if _, err := renderPolicy(""); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("renderPolicy(\"\"): got %v, want ErrInvalidInput", err)
	}
}

// TestPolicyTemplateMatchesDeployment ensures the embedded copy of
// deployment.hcl.tmpl tracks the canonical file under deploy/. A
// silent divergence (the template in deploy/ is updated but the embed
// is not) would mean live OpenBao policies disagree with the operator-
// facing template file — a foot-gun the test catches at build time.
func TestPolicyTemplateMatchesDeployment(t *testing.T) {
	t.Parallel()
	got, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "deploy", "openbao", "policies", "deployment.hcl.tmpl"))
	if err != nil {
		t.Fatalf("read deploy template: %v", err)
	}
	if !bytes.Equal(bytes.TrimSpace(got), bytes.TrimSpace(policyTemplateBytes)) {
		t.Fatalf("embedded template diverges from deploy/openbao/policies/deployment.hcl.tmpl — copy the deploy file into internal/controlplane/provision/openbao/embed/")
	}
}

// TestApplyResultFieldNaming pins the public API field names so a
// future refactor that accidentally renames Kid → KID etc. surfaces
// here. The composite provisioner in Phase 12e depends on these
// exact names.
func TestApplyResultFieldNaming(t *testing.T) {
	t.Parallel()
	in := ApplyInput{DeploymentID: "dep_x"}
	if in.PolicyName() != "saas-dep_x" {
		t.Errorf("PolicyName = %q, want saas-dep_x", in.PolicyName())
	}
	if in.K8sRoleName() != "dep_x" {
		t.Errorf("K8sRoleName = %q, want dep_x", in.K8sRoleName())
	}
	if in.KVPath() != "secret/data/dep_x" {
		t.Errorf("KVPath = %q, want secret/data/dep_x", in.KVPath())
	}
}

// fakeBaoServer records the requests the adapter makes against a stub
// OpenBao HTTP API. Each handler maps a path-prefix to a canned
// response (and optionally records the body). The shape is faithful
// to OpenBao's wire format so the api/v2 client's parser accepts
// it.
type fakeBaoServer struct {
	mu sync.Mutex
	// requestPaths records every URL path the adapter hit, in order.
	requestPaths []string
	// requestBodies records the raw body for write/POST requests.
	requestBodies map[string][]byte
	// existingTransitKeys is the set of kids the server pretends to
	// already have. Read returns a key body for these.
	existingTransitKeys map[string]bool
	// existingPolicies is the policy name → body map served by the
	// sys/policies/acl/<name> read endpoint.
	existingPolicies map[string]string
	// existingRoles maps kubernetes role name → its data payload.
	existingRoles map[string]map[string]any
	// existingKV maps full KV data paths to the data payload.
	existingKV map[string]map[string]any
	// auditEnabled controls whether sys/audit lists a device.
	auditEnabled bool
}

func newFakeBaoServer() *fakeBaoServer {
	return &fakeBaoServer{
		requestBodies:       make(map[string][]byte),
		existingTransitKeys: make(map[string]bool),
		existingPolicies:    make(map[string]string),
		existingRoles:       make(map[string]map[string]any),
		existingKV:          make(map[string]map[string]any),
		auditEnabled:        true,
	}
}

func (f *fakeBaoServer) handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		defer f.mu.Unlock()

		path := strings.TrimPrefix(r.URL.Path, "/v1/")
		f.requestPaths = append(f.requestPaths, r.Method+" "+path)

		if r.Body != nil {
			body, _ := readAll(r.Body)
			if len(body) > 0 {
				f.requestBodies[r.Method+" "+path] = body
			}
		}

		switch {
		case strings.HasPrefix(path, "transit/keys/") && r.Method == http.MethodGet:
			kid := strings.TrimPrefix(path, "transit/keys/")
			if !f.existingTransitKeys[kid] {
				w.WriteHeader(http.StatusNotFound)
				_, _ = w.Write([]byte(`{"errors":[]}`))
				return
			}
			writeJSON(w, map[string]any{
				"data": map[string]any{
					"type":           "aes256-gcm96",
					"name":           kid,
					"latest_version": 1,
				},
			})
			return

		case strings.HasPrefix(path, "transit/keys/") && (r.Method == http.MethodPost || r.Method == http.MethodPut):
			// Strip /config suffix if present (config endpoint).
			kid := strings.TrimSuffix(strings.TrimPrefix(path, "transit/keys/"), "/config")
			f.existingTransitKeys[kid] = true
			w.WriteHeader(http.StatusNoContent)
			return

		case strings.HasPrefix(path, "transit/keys/") && r.Method == http.MethodDelete:
			kid := strings.TrimPrefix(path, "transit/keys/")
			delete(f.existingTransitKeys, kid)
			w.WriteHeader(http.StatusNoContent)
			return

		case strings.HasPrefix(path, "sys/policies/acl/") && (r.Method == http.MethodPost || r.Method == http.MethodPut):
			name := strings.TrimPrefix(path, "sys/policies/acl/")
			body := f.requestBodies[r.Method+" "+path]
			var payload struct {
				Policy string `json:"policy"`
			}
			_ = json.Unmarshal(body, &payload)
			f.existingPolicies[name] = payload.Policy
			w.WriteHeader(http.StatusNoContent)
			return

		case strings.HasPrefix(path, "sys/policies/acl/") && r.Method == http.MethodGet:
			name := strings.TrimPrefix(path, "sys/policies/acl/")
			pol, ok := f.existingPolicies[name]
			if !ok {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			writeJSON(w, map[string]any{
				"data": map[string]any{
					"name":   name,
					"policy": pol,
				},
			})
			return

		case strings.HasPrefix(path, "sys/policies/acl/") && r.Method == http.MethodDelete:
			name := strings.TrimPrefix(path, "sys/policies/acl/")
			delete(f.existingPolicies, name)
			w.WriteHeader(http.StatusNoContent)
			return

		case strings.HasPrefix(path, "auth/kubernetes/role/") && (r.Method == http.MethodPost || r.Method == http.MethodPut):
			name := strings.TrimPrefix(path, "auth/kubernetes/role/")
			body := f.requestBodies[r.Method+" "+path]
			var payload map[string]any
			_ = json.Unmarshal(body, &payload)
			f.existingRoles[name] = payload
			w.WriteHeader(http.StatusNoContent)
			return

		case strings.HasPrefix(path, "auth/kubernetes/role/") && r.Method == http.MethodGet:
			name := strings.TrimPrefix(path, "auth/kubernetes/role/")
			data, ok := f.existingRoles[name]
			if !ok {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			writeJSON(w, map[string]any{"data": data})
			return

		case strings.HasPrefix(path, "auth/kubernetes/role/") && r.Method == http.MethodDelete:
			name := strings.TrimPrefix(path, "auth/kubernetes/role/")
			delete(f.existingRoles, name)
			w.WriteHeader(http.StatusNoContent)
			return

		case strings.HasPrefix(path, "secret/data/") && (r.Method == http.MethodPost || r.Method == http.MethodPut):
			body := f.requestBodies[r.Method+" "+path]
			var payload struct {
				Data map[string]any `json:"data"`
			}
			_ = json.Unmarshal(body, &payload)
			f.existingKV[path] = payload.Data
			writeJSON(w, map[string]any{
				"data": map[string]any{
					"version":      1,
					"created_time": "2026-05-26T00:00:00Z",
				},
			})
			return

		case strings.HasPrefix(path, "secret/data/") && r.Method == http.MethodGet:
			data, ok := f.existingKV[path]
			if !ok {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			writeJSON(w, map[string]any{
				"data": map[string]any{
					"data":     data,
					"metadata": map[string]any{"version": 1},
				},
			})
			return

		case strings.HasPrefix(path, "secret/metadata/") && (r.Method == "LIST" || r.URL.Query().Get("list") == "true"):
			prefix := strings.TrimPrefix(path, "secret/metadata/")
			var keys []string
			for k := range f.existingKV {
				inner := strings.TrimPrefix(k, "secret/data/")
				if strings.HasPrefix(inner, prefix) {
					tail := strings.TrimPrefix(inner, prefix)
					if tail != "" {
						keys = append(keys, tail)
					}
				}
			}
			if len(keys) == 0 {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			writeJSON(w, map[string]any{
				"data": map[string]any{"keys": keys},
			})
			return

		case strings.HasPrefix(path, "secret/metadata/") && r.Method == http.MethodDelete:
			leaf := strings.TrimPrefix(path, "secret/metadata/")
			fullData := "secret/data/" + leaf
			delete(f.existingKV, fullData)
			w.WriteHeader(http.StatusNoContent)
			return

		case path == "sys/audit" && r.Method == http.MethodGet:
			if !f.auditEnabled {
				writeJSON(w, map[string]any{"data": map[string]any{}})
				return
			}
			writeJSON(w, map[string]any{
				"data": map[string]any{
					"file/": map[string]any{"type": "file"},
				},
			})
			return
		}

		// Default: 404.
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"errors":["not found"]}`))
	})
}

// readAll consumes an http.Request.Body into a buffer.
func readAll(r interface{ Read(p []byte) (int, error) }) ([]byte, error) {
	const chunk = 4096
	var out []byte
	buf := make([]byte, chunk)
	for {
		n, err := r.Read(buf)
		if n > 0 {
			out = append(out, buf[:n]...)
		}
		if err != nil {
			if err.Error() == "EOF" || strings.Contains(err.Error(), "EOF") {
				return out, nil
			}
			return out, err
		}
	}
}

func writeJSON(w http.ResponseWriter, body map[string]any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(body)
}

// newAdapterWithFakeServer wires the adapter to a fakeBaoServer-backed
// API.
func newAdapterWithFakeServer(t *testing.T) (*HostAdapter, *fakeBaoServer, func()) {
	t.Helper()
	f := newFakeBaoServer()
	srv := httptest.NewServer(f.handler())

	cfg := bao.DefaultConfig()
	cfg.Address = srv.URL
	bc, err := bao.NewClient(cfg)
	if err != nil {
		srv.Close()
		t.Fatalf("bao.NewClient: %v", err)
	}
	bc.SetToken("test-token")
	a, err := NewHostAdapter(bc)
	if err != nil {
		srv.Close()
		t.Fatalf("NewHostAdapter: %v", err)
	}
	return a, f, srv.Close
}

func TestHostAdapter_Apply_HappyPath(t *testing.T) {
	t.Parallel()
	a, f, stop := newAdapterWithFakeServer(t)
	defer stop()

	ctx := context.Background()
	in := ApplyInput{
		DeploymentID:      "dep_test01",
		K3sNamespace:      "saas-dep-test01",
		K3sServiceAccount: "dataplane",
	}
	res, err := a.Apply(ctx, in)
	if err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if res.Kid != "dep_test01" {
		t.Errorf("Kid = %q, want dep_test01", res.Kid)
	}
	if res.PolicyName != "saas-dep_test01" {
		t.Errorf("PolicyName = %q, want saas-dep_test01", res.PolicyName)
	}
	if res.K8sRoleName != "dep_test01" {
		t.Errorf("K8sRoleName = %q, want dep_test01", res.K8sRoleName)
	}
	if res.KVPath != "secret/data/dep_test01" {
		t.Errorf("KVPath = %q, want secret/data/dep_test01", res.KVPath)
	}

	// Confirm the fake server saw each provisioning step.
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.existingTransitKeys["dep_test01"] {
		t.Error("transit key not created on server")
	}
	if got := f.existingPolicies["saas-dep_test01"]; got == "" {
		t.Error("policy not created on server")
	} else if !strings.Contains(got, "dep_test01") {
		t.Errorf("policy did not contain deployment_id, got: %s", got)
	}
	role := f.existingRoles["dep_test01"]
	if role == nil {
		t.Error("k8s role not created on server")
	} else {
		if v, _ := role["bound_service_account_names"].([]any); len(v) != 1 || v[0] != "dataplane" {
			t.Errorf("bound_service_account_names = %v, want [dataplane]", v)
		}
		if v, _ := role["bound_service_account_namespaces"].([]any); len(v) != 1 || v[0] != "saas-dep-test01" {
			t.Errorf("bound_service_account_namespaces = %v, want [saas-dep-test01]", v)
		}
		if v, _ := role["token_policies"].([]any); len(v) != 1 || v[0] != "saas-dep_test01" {
			t.Errorf("token_policies = %v, want [saas-dep_test01]", v)
		}
	}
	if marker, ok := f.existingKV["secret/data/dep_test01/_provisioned"]; !ok {
		t.Error("kv marker not created on server")
	} else if marker["deployment_id"] != "dep_test01" {
		t.Errorf("kv marker missing deployment_id, got %v", marker)
	}
}

func TestHostAdapter_Apply_Idempotent(t *testing.T) {
	t.Parallel()
	a, f, stop := newAdapterWithFakeServer(t)
	defer stop()

	ctx := context.Background()
	in := ApplyInput{
		DeploymentID:      "dep_idem",
		K3sNamespace:      "saas-dep-idem",
		K3sServiceAccount: "dataplane",
	}
	if _, err := a.Apply(ctx, in); err != nil {
		t.Fatalf("first Apply: %v", err)
	}
	firstCount := len(f.requestPaths)
	// Second Apply re-uses existing artifacts; the transit key read
	// short-circuits before re-write. We expect the second Apply not
	// to grow the request count by more than a small bounded amount
	// (reads + the still-issued policy / role / KV writes which are
	// no-ops at the catalog level).
	if _, err := a.Apply(ctx, in); err != nil {
		t.Fatalf("second Apply: %v", err)
	}
	if len(f.requestPaths) <= firstCount {
		t.Fatalf("second Apply made no requests at all: %d -> %d", firstCount, len(f.requestPaths))
	}
}

func TestHostAdapter_Apply_RejectsBadInput(t *testing.T) {
	t.Parallel()
	a, _, stop := newAdapterWithFakeServer(t)
	defer stop()

	ctx := context.Background()
	_, err := a.Apply(ctx, ApplyInput{
		DeploymentID:      "",
		K3sNamespace:      "saas-x",
		K3sServiceAccount: "dataplane",
	})
	if !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("Apply with empty deployment_id: got %v, want ErrInvalidInput", err)
	}
}

func TestHostAdapter_Remove_HappyPath(t *testing.T) {
	t.Parallel()
	a, f, stop := newAdapterWithFakeServer(t)
	defer stop()

	ctx := context.Background()
	in := ApplyInput{
		DeploymentID:      "dep_remove",
		K3sNamespace:      "saas-dep-remove",
		K3sServiceAccount: "dataplane",
	}
	if _, err := a.Apply(ctx, in); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	if err := a.Remove(ctx, RemoveInput{
		DeploymentID:      "dep_remove",
		ConfirmDestroyKey: true,
	}); err != nil {
		t.Fatalf("Remove: %v", err)
	}

	f.mu.Lock()
	defer f.mu.Unlock()
	if f.existingTransitKeys["dep_remove"] {
		t.Error("transit key still exists after Remove")
	}
	if _, ok := f.existingPolicies["saas-dep_remove"]; ok {
		t.Error("policy still exists after Remove")
	}
	if _, ok := f.existingRoles["dep_remove"]; ok {
		t.Error("k8s role still exists after Remove")
	}
}

func TestHostAdapter_Remove_RequiresConfirmation(t *testing.T) {
	t.Parallel()
	a, _, stop := newAdapterWithFakeServer(t)
	defer stop()

	ctx := context.Background()
	err := a.Remove(ctx, RemoveInput{DeploymentID: "dep_x"})
	if !errors.Is(err, ErrConfirmationRequired) {
		t.Fatalf("Remove without confirmation: got %v, want ErrConfirmationRequired", err)
	}
}

func TestHostAdapter_VerifyAccess_MissingPolicy(t *testing.T) {
	t.Parallel()
	a, f, stop := newAdapterWithFakeServer(t)
	defer stop()

	ctx := context.Background()
	in := ApplyInput{
		DeploymentID:      "dep_partial",
		K3sNamespace:      "saas-dep-partial",
		K3sServiceAccount: "dataplane",
	}
	if _, err := a.Apply(ctx, in); err != nil {
		t.Fatalf("Apply: %v", err)
	}

	// Simulate a manual policy delete after provision.
	f.mu.Lock()
	delete(f.existingPolicies, "saas-dep_partial")
	f.mu.Unlock()

	err := a.VerifyAccess(ctx, "dep_partial")
	if !errors.Is(err, ErrVerificationFailed) {
		t.Fatalf("VerifyAccess: got %v, want ErrVerificationFailed", err)
	}
}

func TestHostAdapter_NewHostAdapterRejectsNilClient(t *testing.T) {
	t.Parallel()
	if _, err := NewHostAdapter(nil); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("NewHostAdapter(nil): got %v, want ErrInvalidInput", err)
	}
}

func TestReadTokenFile_JSON(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	path := filepath.Join(dir, "init.json")
	body := `{
  "unseal_keys_b64": ["a","b","c","d","e"],
  "unseal_keys_hex": ["1","2","3","4","5"],
  "unseal_shares": 5,
  "unseal_threshold": 3,
  "recovery_keys_b64": null,
  "recovery_keys_hex": null,
  "recovery_keys_shares": 0,
  "recovery_keys_threshold": 0,
  "root_token": "hvs.AAAA_secret_token_value"
}`
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, err := readTokenFile(path)
	if err != nil {
		t.Fatalf("readTokenFile: %v", err)
	}
	if got != "hvs.AAAA_secret_token_value" {
		t.Errorf("got token %q, want hvs.AAAA_secret_token_value", got)
	}
}

func TestReadTokenFile_RawText(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	path := filepath.Join(dir, "token")
	if err := os.WriteFile(path, []byte("  hvs.RAW_TOKEN  \n"), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, err := readTokenFile(path)
	if err != nil {
		t.Fatalf("readTokenFile: %v", err)
	}
	if got != "hvs.RAW_TOKEN" {
		t.Errorf("got %q, want hvs.RAW_TOKEN", got)
	}
}

func TestReadTokenFile_Empty(t *testing.T) {
	t.Parallel()
	dir := t.TempDir()
	path := filepath.Join(dir, "empty")
	if err := os.WriteFile(path, nil, 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	if _, err := readTokenFile(path); err == nil {
		t.Fatal("expected error on empty token file")
	}
}

func TestNewClient_AmbiguousAuth(t *testing.T) {
	t.Parallel()
	_, err := NewClient(context.Background(), ClientConfig{
		Address:         "http://127.0.0.1:8200",
		Token:           "abc",
		AppRoleRoleID:   "r1",
		AppRoleSecretID: "s1",
	})
	if err == nil {
		t.Fatal("expected error when both Token and AppRole are set")
	}
}

func TestNewClient_NoAuth(t *testing.T) {
	t.Parallel()
	_, err := NewClient(context.Background(), ClientConfig{
		Address: "http://127.0.0.1:8200",
	})
	if err == nil {
		t.Fatal("expected error when no auth is configured")
	}
}
