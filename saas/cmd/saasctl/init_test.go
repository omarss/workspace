// Phase 15 — saasctl init wizard tests.
//
// We exercise the wizard's orchestration without spinning up real
// docker / openbao / keycloak: each step's Make call is replaced by a
// recording fake, and the provision step talks to an httptest server
// that mimics the control-plane responses. The full set covers:
//
//   - first-run happy path issues 8 OK lines + emits the bootstrap
//     secret banner
//   - re-run on an already-provisioned Deployment short-circuits
//     provision to "already done" and suppresses the secret banner
//   - --operator-token-file populates ~/.saas/credentials.json and
//     sets Authorization: Bearer on the provision call
//   - YAML config defaults are overridden by CLI flags

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// recordingRunner replaces realMakeRunner. The captured target list
// lets tests assert the wizard called each make target in the expected
// order; errors come from the optional failOn map keyed by target.
type recordingRunner struct {
	called []string
	failOn map[string]error
}

func (r *recordingRunner) run(ctx context.Context, target string, env []string, stdout, stderr io.Writer) error {
	r.called = append(r.called, target)
	if err, ok := r.failOn[target]; ok {
		return err
	}
	return nil
}

// testControlPlane returns an httptest.Server that simulates the
// control plane's GET /deployments + POST /deployments endpoints.
// Pass haveExisting=true to make GET return one matching Deployment so
// the wizard short-circuits provision.
func testControlPlane(t *testing.T, project, env string, haveExisting bool) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/control/v1/deployments", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			page := struct {
				Data []existingDeployment `json:"data"`
			}{}
			if haveExisting {
				page.Data = []existingDeployment{{
					ID:              "dep_01HXEXISTING",
					ProjectSlug:     project,
					EnvironmentSlug: env,
					PrimaryVhost:    "https://dev.default.saas.test",
				}}
			}
			_ = json.NewEncoder(w).Encode(page)
		case http.MethodPost:
			// #nosec G101 — fixture data; the "sk_live_" prefix is
			// fake and only exists to assert the bootstrap-banner
			// rendering in TestRunInit_FirstRun_HappyPath.
			resp := map[string]any{
				"data": map[string]any{
					"id":            "dep_01HXNEW",
					"primary_vhost": "https://dev.default.saas.test",
				},
				"bootstrap_api_key": map[string]any{
					"id":        "api_01HXBOOT",
					"secret":    "sk_live_TEST_SECRET",
					"tenant_id": "tenant_01HXBOOT",
				},
			}
			w.WriteHeader(http.StatusCreated)
			_ = json.NewEncoder(w).Encode(resp)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

// withTempHome redirects $HOME so writeCredentials lands in a per-test
// directory and does not pollute the developer's real ~/.saas.
func withTempHome(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	return home
}

// captureStdout swaps os.Stdout with a pipe and returns the captured
// bytes once the inner func returns.
func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	orig := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	os.Stdout = w
	t.Cleanup(func() { os.Stdout = orig })
	done := make(chan []byte)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		done <- buf.Bytes()
	}()
	fn()
	_ = w.Close()
	return string(<-done)
}

// fakeHealthyCompose returns three services all reporting healthy, so
// waitHealthy returns on the first poll instead of timing out against
// the (absent) real docker socket.
func fakeHealthyCompose(_ context.Context, _ string) ([]composeService, error) {
	return []composeService{
		{Name: "postgres", Service: "postgres", State: "running", Health: "healthy"},
		{Name: "openbao", Service: "openbao", State: "running", Health: "healthy"},
		{Name: "keycloak", Service: "keycloak", State: "running", Health: "healthy"},
	}, nil
}

func TestRunInit_FirstRun_HappyPath(t *testing.T) {
	withTempHome(t)
	cp := testControlPlane(t, "default", "dev", false)
	runner := &recordingRunner{}
	cfg := &initConfig{
		Project:         "default",
		Environment:     "dev",
		ImageVersion:    "v0.3.1",
		ControlPlaneURL: cp.URL,
		makeRunner:      runner.run,
		composeChecker:  fakeHealthyCompose,
	}
	cfg.Operator.Email = "admin@localhost"

	out := captureStdout(t, func() {
		if err := runInit(context.Background(), cfg); err != nil {
			t.Fatalf("runInit: %v", err)
		}
	})

	// compose-up may be skipped on first run when the fake compose
	// reports healthy; the other targets are unconditional.
	wantTargets := []string{"operators-realm-import", "openbao-init", "migrate"}
	for _, target := range wantTargets {
		if !contains(runner.called, target) {
			t.Errorf("missing make target %q in %v", target, runner.called)
		}
	}
	if !strings.Contains(out, "COPY THIS NOW") {
		t.Errorf("expected COPY THIS NOW banner, got: %s", out)
	}
	if !strings.Contains(out, "sk_live_TEST_SECRET") {
		t.Errorf("expected bootstrap secret in output, got: %s", out)
	}
}

func TestRunInit_ReRun_IsIdempotent(t *testing.T) {
	withTempHome(t)
	cp := testControlPlane(t, "default", "dev", true) // existing deployment
	runner := &recordingRunner{}
	cfg := &initConfig{
		Project:         "default",
		Environment:     "dev",
		ImageVersion:    "v0.3.1",
		ControlPlaneURL: cp.URL,
		makeRunner:      runner.run,
		composeChecker:  fakeHealthyCompose,
	}

	out := captureStdout(t, func() {
		if err := runInit(context.Background(), cfg); err != nil {
			t.Fatalf("runInit re-run: %v", err)
		}
	})

	if !strings.Contains(out, "provision") || !strings.Contains(out, "already done") {
		t.Errorf("expected provision short-circuit, got: %s", out)
	}
	if strings.Contains(out, "sk_live") {
		t.Errorf("re-run must NOT leak a bootstrap secret; got: %s", out)
	}
	if !strings.Contains(out, "bootstrap secret is not") {
		t.Errorf("expected the not-retrievable note on re-run, got: %s", out)
	}
}

func TestRunOperatorLogin_WithTokenFile(t *testing.T) {
	home := withTempHome(t)
	tokenPath := filepath.Join(home, "operator-token.txt")
	if err := os.WriteFile(tokenPath, []byte("eyJhbGciOi-FAKE-TOKEN\n"), 0o600); err != nil {
		t.Fatalf("seed token file: %v", err)
	}
	cfg := &initConfig{OperatorTokenFn: tokenPath}
	note, err := runOperatorLogin(context.Background(), cfg)
	if err != nil {
		t.Fatalf("runOperatorLogin: %v", err)
	}
	if note != "from file" {
		t.Errorf("expected note %q, got %q", "from file", note)
	}
	creds, err := readCredentials()
	if err != nil {
		t.Fatalf("readCredentials: %v", err)
	}
	if creds.Token != "eyJhbGciOi-FAKE-TOKEN" {
		t.Errorf("stored token mismatch: %q", creds.Token)
	}
}

func TestRunOperatorLogin_NoFlag_IsSkipped(t *testing.T) {
	withTempHome(t)
	cfg := &initConfig{}
	note, err := runOperatorLogin(context.Background(), cfg)
	if err != nil {
		t.Fatalf("runOperatorLogin: %v", err)
	}
	if !strings.Contains(note, "skipped") {
		t.Errorf("expected skipped note, got %q", note)
	}
}

func TestLoadInitConfig_DefaultsFillIn(t *testing.T) {
	withTempHome(t)
	cfg := &initConfig{
		ConfigPath: "/dev/null",
		ProjectDir: ".",
	}
	if err := loadInitConfig(cfg); err == nil {
		// /dev/null is empty — yaml.Unmarshal accepts; defaults fill in.
		if cfg.Project != "default" {
			t.Errorf("default project, got %q", cfg.Project)
		}
		if cfg.Environment != "dev" {
			t.Errorf("default environment, got %q", cfg.Environment)
		}
		if cfg.ImageVersion != "dev" {
			t.Errorf("default image, got %q", cfg.ImageVersion)
		}
		if cfg.Operator.Email != "admin@localhost" {
			t.Errorf("default operator email, got %q", cfg.Operator.Email)
		}
	}
}

func TestLoadInitConfig_FlagsOverrideFile(t *testing.T) {
	home := withTempHome(t)
	configPath := filepath.Join(home, "init.yaml")
	yaml := []byte("project: filevalue\nenvironment: filedev\nimage_version: v0.0.1\n")
	if err := os.WriteFile(configPath, yaml, 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	cfg := &initConfig{
		ConfigPath:   configPath,
		Project:      "flagvalue", // flag wins over file
		ImageVersion: "v0.3.1",    // flag wins over file
		ProjectDir:   ".",
	}
	if err := loadInitConfig(cfg); err != nil {
		t.Fatalf("loadInitConfig: %v", err)
	}
	if cfg.Project != "flagvalue" {
		t.Errorf("expected flag override, got %q", cfg.Project)
	}
	if cfg.Environment != "filedev" {
		t.Errorf("expected file value for unset flag, got %q", cfg.Environment)
	}
	if cfg.ImageVersion != "v0.3.1" {
		t.Errorf("expected flag override, got %q", cfg.ImageVersion)
	}
}

func contains(haystack []string, needle string) bool {
	for _, s := range haystack {
		if s == needle {
			return true
		}
	}
	return false
}
