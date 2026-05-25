package nginx

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// recorderRunner is a Runner stub that records every invocation. Tests
// override Result for the next call to drive failure paths.
type recorderRunner struct {
	mu    sync.Mutex
	calls [][]string
	// fail, if set, is consulted before recording. It returns the error
	// the Runner should surface for the next call matching `binary`.
	fail map[string]error
}

func newRecorder() *recorderRunner {
	return &recorderRunner{fail: map[string]error{}}
}

func (r *recorderRunner) Run(_ context.Context, name string, args ...string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	full := append([]string{name}, args...)
	r.calls = append(r.calls, full)
	if err, ok := r.fail[name]; ok {
		// One-shot — clear so subsequent calls succeed.
		delete(r.fail, name)
		return err
	}
	return nil
}

func (r *recorderRunner) lastCall(binary string) []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	for i := len(r.calls) - 1; i >= 0; i-- {
		if r.calls[i][0] == binary {
			return r.calls[i]
		}
	}
	return nil
}

// newTestAdapter wires a HostAdapter against a TempDir sandbox + a
// recorderRunner. It seeds the sudoers/snippet sentinel files so
// PreflightSetup passes.
func newTestAdapter(t *testing.T) (*HostAdapter, *recorderRunner) {
	t.Helper()
	root := t.TempDir()
	sitesAvail := filepath.Join(root, "sites-available")
	sitesEnabled := filepath.Join(root, "sites-enabled")
	snippets := filepath.Join(root, "snippets")
	sudoers := filepath.Join(root, "sudoers.d")
	for _, d := range []string{sitesAvail, sitesEnabled, snippets, sudoers} {
		// 0o755 mirrors the production directory mode the operator sets in
		// deploy/host/setup-nginx-adapter.sh — gosec G301 flags the wider
		// mode but the test would not reproduce the host behaviour with
		// 0o750 (the renderer's atomic write also needs `o+rx` on parents
		// for nginx's www-data to traverse).
		if err := os.MkdirAll(d, 0o755); err != nil { //nolint:gosec
			t.Fatalf("mkdir %s: %v", d, err)
		}
	}
	// Seed sentinel setup files. The 0o644 / 0o440 modes mirror the
	// production install modes set by the setup script (gosec G306 wants
	// 0o600; the production files MUST be world-readable so nginx can
	// include the snippet — the test reflects that contract).
	snippetFile := filepath.Join(snippets, "saas-security-headers.conf")
	if err := os.WriteFile(snippetFile, []byte("# test snippet\n"), 0o644); err != nil { //nolint:gosec
		t.Fatalf("seed snippet: %v", err)
	}
	sudoersFile := filepath.Join(sudoers, "saas-controlplane")
	if err := os.WriteFile(sudoersFile, []byte("# test sudoers\n"), 0o440); err != nil { //nolint:gosec
		t.Fatalf("seed sudoers: %v", err)
	}

	r, err := newRenderer()
	if err != nil {
		t.Fatalf("renderer: %v", err)
	}
	rec := newRecorder()
	a := &HostAdapter{
		SitesAvailableDir: sitesAvail,
		SitesEnabledDir:   sitesEnabled,
		SnippetPath:       snippetFile,
		SudoersPath:       sudoersFile,
		NginxBin:          "/usr/sbin/nginx",
		CertbotBin:        "/usr/bin/certbot",
		Runner:            rec,
		renderer:          r,
	}
	return a, rec
}

func validInput() ApplyInput {
	return ApplyInput{
		DeploymentID:  "dep_test01",
		PrimaryDomain: "dev.acme.saas.omarss.net",
		CustomDomains: nil,
		NodePort:      30801,
		OpsEmail:      "ops@example.com",
	}
}

func TestValidate_Accepts_GoldenInput(t *testing.T) {
	if err := validInput().Validate(); err != nil {
		t.Fatalf("expected valid, got %v", err)
	}
}

func TestValidate_RejectsWildcard(t *testing.T) {
	in := validInput()
	in.PrimaryDomain = "*.acme.saas.omarss.net"
	if err := in.Validate(); !errors.Is(err, ErrWildcardDomain) {
		t.Fatalf("want ErrWildcardDomain, got %v", err)
	}
}

func TestValidate_RejectsShellMetacharacters(t *testing.T) {
	in := validInput()
	in.PrimaryDomain = "example.com;rm -rf /"
	if err := in.Validate(); !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("want ErrInvalidInput, got %v", err)
	}
}

func TestValidate_RejectsBadNodePort(t *testing.T) {
	for _, port := range []int{0, 80, 29999, 32768, 65535} {
		in := validInput()
		in.NodePort = port
		if err := in.Validate(); err == nil {
			t.Fatalf("port %d should be rejected", port)
		}
	}
}

func TestValidate_RejectsUnsafeDeploymentID(t *testing.T) {
	for _, bad := range []string{"", "dep test", "dep/test", "dep$test", strings.Repeat("a", 65)} {
		in := validInput()
		in.DeploymentID = bad
		if err := in.Validate(); !errors.Is(err, ErrInvalidInput) {
			t.Fatalf("deployment_id %q should be rejected, got %v", bad, err)
		}
	}
}

func TestRender_IncludesPrimaryAndCustomDomains(t *testing.T) {
	r, err := newRenderer()
	if err != nil {
		t.Fatal(err)
	}
	in := validInput()
	in.CustomDomains = []string{"api.example.com", "app.example.com"}
	out, err := r.render(in)
	if err != nil {
		t.Fatal(err)
	}
	got := string(out)
	if !strings.Contains(got, "dev.acme.saas.omarss.net") {
		t.Errorf("missing primary in vhost output:\n%s", got)
	}
	if !strings.Contains(got, "api.example.com") || !strings.Contains(got, "app.example.com") {
		t.Errorf("missing custom domains:\n%s", got)
	}
	// One server block, one server_name directive — the BYOD case must
	// not produce two vhosts. Count the directive form ("    server_name ")
	// to avoid matching comment text that mentions the directive name.
	if c := strings.Count(got, "\n    server_name "); c != 1 {
		t.Errorf("expected exactly one server_name directive, got %d:\n%s", c, got)
	}
	if strings.Count(got, "server {") != 1 {
		t.Errorf("expected exactly one server { block, got %d", strings.Count(got, "server {"))
	}
}

func TestRender_IncludesSecurityHeadersSnippet(t *testing.T) {
	r, _ := newRenderer()
	out, _ := r.render(validInput())
	got := string(out)
	// The template includes the snippet at the server level AND inside
	// the location / block (nginx add_header has no inheritance — see
	// workspace_personal/CLAUDE.md gotcha #4).
	if c := strings.Count(got, "include /etc/nginx/snippets/saas-security-headers.conf;"); c < 2 {
		t.Errorf("expected snippet included at least twice (server + location), got %d:\n%s", c, got)
	}
}

func TestRender_NodePortInProxyPass(t *testing.T) {
	r, _ := newRenderer()
	in := validInput()
	in.NodePort = 30901
	out, _ := r.render(in)
	if !strings.Contains(string(out), "proxy_pass http://127.0.0.1:30901;") {
		t.Errorf("proxy_pass missing or wrong port:\n%s", out)
	}
}

func TestApply_WritesVhostAndSymlinkAndReloads(t *testing.T) {
	a, rec := newTestAdapter(t)
	in := validInput()
	if err := a.Apply(context.Background(), in); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	// Vhost file exists at the canonical path, 0644.
	vhost := a.vhostPath(in.DeploymentID)
	info, err := os.Stat(vhost)
	if err != nil {
		t.Fatalf("stat vhost: %v", err)
	}
	if info.Mode().Perm() != 0o644 {
		t.Errorf("mode = %v, want 0644", info.Mode().Perm())
	}
	// Symlink points at the vhost.
	target, err := os.Readlink(a.symlinkPath(in.DeploymentID))
	if err != nil {
		t.Fatalf("readlink: %v", err)
	}
	if target != vhost {
		t.Errorf("symlink target = %q, want %q", target, vhost)
	}
	// `nginx -t` then `nginx -s reload` were called in order.
	if len(rec.calls) < 2 {
		t.Fatalf("expected at least 2 nginx calls, got %d", len(rec.calls))
	}
	if rec.calls[0][1] != "-t" {
		t.Errorf("first call argv[1] = %q, want -t (got %v)", rec.calls[0][1], rec.calls[0])
	}
	if rec.calls[1][1] != "-s" || rec.calls[1][2] != "reload" {
		t.Errorf("second call = %v, want nginx -s reload", rec.calls[1])
	}
}

func TestApply_IsIdempotent_SameContentNoBackup(t *testing.T) {
	a, _ := newTestAdapter(t)
	in := validInput()
	if err := a.Apply(context.Background(), in); err != nil {
		t.Fatal(err)
	}
	first, _ := os.ReadFile(a.vhostPath(in.DeploymentID))
	if err := a.Apply(context.Background(), in); err != nil {
		t.Fatal(err)
	}
	second, _ := os.ReadFile(a.vhostPath(in.DeploymentID))
	if string(first) != string(second) {
		t.Error("second Apply produced different content for same input")
	}
	// No leftover .bak file (we always remove it on success).
	if _, err := os.Stat(a.vhostPath(in.DeploymentID) + ".bak"); !errors.Is(err, os.ErrNotExist) {
		t.Errorf(".bak file should be removed on success, stat err = %v", err)
	}
}

func TestApply_NginxTestFailure_RollsBackToPreviousFile(t *testing.T) {
	a, rec := newTestAdapter(t)
	in := validInput()

	// First Apply succeeds.
	if err := a.Apply(context.Background(), in); err != nil {
		t.Fatal(err)
	}
	originalContent, _ := os.ReadFile(a.vhostPath(in.DeploymentID))

	// Second Apply with a different port — but make `nginx -t` fail.
	rec.fail["/usr/sbin/nginx"] = errors.New("nginx: configuration file test failed")
	in2 := in
	in2.NodePort = 30999
	err := a.Apply(context.Background(), in2)
	if !errors.Is(err, ErrConfigTestFailed) {
		t.Fatalf("want ErrConfigTestFailed, got %v", err)
	}
	// The vhost on disk must be the original (rolled back).
	got, _ := os.ReadFile(a.vhostPath(in.DeploymentID))
	if string(got) != string(originalContent) {
		t.Errorf("vhost not rolled back on nginx -t failure")
	}
}

func TestApply_NginxTestFailure_FirstApply_UnlinksFile(t *testing.T) {
	a, rec := newTestAdapter(t)
	in := validInput()
	rec.fail["/usr/sbin/nginx"] = errors.New("nginx: configuration file test failed")

	err := a.Apply(context.Background(), in)
	if !errors.Is(err, ErrConfigTestFailed) {
		t.Fatalf("want ErrConfigTestFailed, got %v", err)
	}
	// No prior file existed — adapter must have unlinked the new write
	// AND the symlink so destroy doesn't have to clean up partial state.
	if _, err := os.Stat(a.vhostPath(in.DeploymentID)); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("vhost should be unlinked, stat err = %v", err)
	}
	if _, err := os.Lstat(a.symlinkPath(in.DeploymentID)); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("symlink should be unlinked, stat err = %v", err)
	}
}

func TestApply_PreflightFails_NoVhostWritten(t *testing.T) {
	a, _ := newTestAdapter(t)
	if err := os.Remove(a.SnippetPath); err != nil {
		t.Fatal(err)
	}
	in := validInput()
	err := a.Apply(context.Background(), in)
	if !errors.Is(err, ErrSetupNotComplete) {
		t.Fatalf("want ErrSetupNotComplete, got %v", err)
	}
	if _, err := os.Stat(a.vhostPath(in.DeploymentID)); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("no file should be written when preflight fails, got err=%v", err)
	}
}

func TestRemove_IdempotentWhenMissing(t *testing.T) {
	a, _ := newTestAdapter(t)
	if err := a.Remove(context.Background(), RemoveInput{DeploymentID: "dep_notthere"}); err != nil {
		t.Errorf("Remove of missing dep should be no-op, got %v", err)
	}
}

func TestRemove_DeletesFileAndSymlink(t *testing.T) {
	a, _ := newTestAdapter(t)
	in := validInput()
	if err := a.Apply(context.Background(), in); err != nil {
		t.Fatal(err)
	}
	if err := a.Remove(context.Background(), RemoveInput{DeploymentID: in.DeploymentID}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(a.vhostPath(in.DeploymentID)); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("vhost should be gone, err=%v", err)
	}
	if _, err := os.Lstat(a.symlinkPath(in.DeploymentID)); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("symlink should be gone, err=%v", err)
	}
}

func TestIssueCert_BuildsCorrectArgv(t *testing.T) {
	a, rec := newTestAdapter(t)
	in := validInput()
	in.CustomDomains = []string{"api.example.com"}

	if err := a.IssueCert(context.Background(), in); err != nil {
		t.Fatalf("IssueCert: %v", err)
	}
	call := rec.lastCall("/usr/bin/certbot")
	if call == nil {
		t.Fatal("certbot was not invoked")
	}
	argv := strings.Join(call, " ")
	for _, want := range []string{
		"--nginx", "--non-interactive", "--agree-tos",
		"-m ops@example.com",
		"--cert-name dep_test01",
		"--keep-until-expiring",
		"-d dev.acme.saas.omarss.net",
		"-d api.example.com",
	} {
		if !strings.Contains(argv, want) {
			t.Errorf("certbot argv missing %q in:\n  %s", want, argv)
		}
	}
}

func TestIssueCert_ClassifiesRateLimit(t *testing.T) {
	a, rec := newTestAdapter(t)
	rec.fail["/usr/bin/certbot"] = errors.New("too many certificates already issued for: omarss.net")
	err := a.IssueCert(context.Background(), validInput())
	if !errors.Is(err, ErrRateLimited) {
		t.Fatalf("want ErrRateLimited, got %v", err)
	}
}

func TestIssueCert_ClassifiesACMEUnreachable(t *testing.T) {
	a, rec := newTestAdapter(t)
	rec.fail["/usr/bin/certbot"] = errors.New("urn:ietf:params:acme:error:unauthorized :: Fetching http://x/.well-known/...: connection refused")
	err := a.IssueCert(context.Background(), validInput())
	if !errors.Is(err, ErrACMEUnreachable) {
		t.Fatalf("want ErrACMEUnreachable, got %v", err)
	}
}

func TestIssueCert_RejectsEmptyOpsEmail(t *testing.T) {
	a, _ := newTestAdapter(t)
	in := validInput()
	in.OpsEmail = ""
	err := a.IssueCert(context.Background(), in)
	if !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("want ErrInvalidInput, got %v", err)
	}
}

func TestIssueCert_RejectsWildcard(t *testing.T) {
	a, _ := newTestAdapter(t)
	in := validInput()
	in.PrimaryDomain = "*.acme.saas.omarss.net"
	err := a.IssueCert(context.Background(), in)
	if !errors.Is(err, ErrWildcardDomain) {
		t.Fatalf("want ErrWildcardDomain, got %v", err)
	}
}

func TestSudoRunner_RefusesNonAllowlistedBinary(t *testing.T) {
	r := &SudoRunner{SudoPath: "/bin/true"} // ensure no real sudo invocation
	err := r.Run(context.Background(), "/usr/bin/rm", "-rf", "/")
	if !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("want ErrInvalidInput, got %v", err)
	}
}

func TestAtomicWrite_RestoresModeAcrossUmask(t *testing.T) {
	// Simulate umask 077 — the result must still be 0644.
	old := setUmask(0o077)
	defer setUmask(old)

	dir := t.TempDir()
	path := filepath.Join(dir, "vhost.conf")
	if err := atomicWrite(path, []byte("hello\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0o644 {
		t.Errorf("mode = %v, want 0644", info.Mode().Perm())
	}
}

func TestEnsureSymlink_IdempotentSameTarget(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "target")
	if err := os.WriteFile(src, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link")
	if err := ensureSymlink(src, link); err != nil {
		t.Fatal(err)
	}
	// Second call must not error.
	if err := ensureSymlink(src, link); err != nil {
		t.Fatalf("second call: %v", err)
	}
}

func TestEnsureSymlink_ReplacesOldTarget(t *testing.T) {
	dir := t.TempDir()
	oldT := filepath.Join(dir, "old")
	newT := filepath.Join(dir, "new")
	for _, p := range []string{oldT, newT} {
		if err := os.WriteFile(p, nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink(oldT, link); err != nil {
		t.Fatal(err)
	}
	if err := ensureSymlink(newT, link); err != nil {
		t.Fatal(err)
	}
	got, _ := os.Readlink(link)
	if got != newT {
		t.Errorf("link target = %q, want %q", got, newT)
	}
}

// containsAny smoke test — guards against accidental case-folding bugs.
func TestContainsAny_CaseInsensitive(t *testing.T) {
	if !containsAny("TOO MANY CERTIFICATES", "too many") {
		t.Fatal("expected match (case-insensitive)")
	}
	if containsAny("hello", "world") {
		t.Fatal("expected no match")
	}
}

// fmt is imported transitively in the tests above; keep this import alive
// so changes don't accidentally remove it during refactors.
var _ = fmt.Sprintf
