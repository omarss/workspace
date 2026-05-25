//go:build integration

package nginx

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The integration tests in this file confirm the adapter's outputs are
// accepted by a real nginx binary. We require `nginx` to be on $PATH
// (e.g. via the `nginx:1.26-alpine` docker image, the apt package, or
// the homelab host itself). Tests are skipped automatically when the
// binary is absent so CI without nginx keeps running.

func skipIfNoNginx(t *testing.T) string {
	t.Helper()
	path, err := exec.LookPath("nginx")
	if err != nil {
		t.Skipf("nginx not in PATH: %v", err)
	}
	return path
}

// realNginxRunner wraps exec.Command WITHOUT sudo. The integration test
// drives an unprivileged nginx via -c <test config> so we can validate
// the adapter's emitted vhost end-to-end.
type realNginxRunner struct {
	nginxBin    string
	testConfDir string // directory containing nginx.conf that includes the adapter's sites-enabled/
	t           *testing.T
}

func (r *realNginxRunner) Run(_ context.Context, _ string, args ...string) error {
	// We only honour the `-t` invocation in the integration test — the
	// reload step is a no-op (no live nginx in the test harness).
	if len(args) == 1 && args[0] == "-t" {
		mainConf := filepath.Join(r.testConfDir, "nginx.conf")
		cmd := exec.Command(r.nginxBin, "-t", "-c", mainConf, "-p", r.testConfDir)
		out, err := cmd.CombinedOutput()
		if err != nil {
			return fmt.Errorf("nginx -t failed: %w: %s", err, string(out))
		}
		r.t.Logf("nginx -t output:\n%s", string(out))
		return nil
	}
	// Reload is a no-op in tests; just record.
	r.t.Logf("integration runner ignoring: %v", args)
	return nil
}

// buildMainNginxConf writes a minimal nginx.conf that includes the
// adapter's sites-enabled/ — replicating what the host nginx layout
// already does on the real machine.
func buildMainNginxConf(t *testing.T, root, sitesEnabled string) {
	t.Helper()
	mainConf := fmt.Sprintf(`
# Test nginx.conf — drives the adapter's vhost through `+"`nginx -t`"+`.
daemon off;
pid %[1]s/nginx.pid;
error_log %[1]s/error.log warn;
events { worker_connections 64; }
http {
    access_log off;
    client_body_temp_path %[1]s/client_body;
    proxy_temp_path %[1]s/proxy;
    fastcgi_temp_path %[1]s/fastcgi;
    uwsgi_temp_path %[1]s/uwsgi;
    scgi_temp_path %[1]s/scgi;
    include %[2]s/*.conf;
}
`, root, sitesEnabled)
	if err := os.WriteFile(filepath.Join(root, "nginx.conf"), []byte(mainConf), 0o644); err != nil {
		t.Fatalf("write nginx.conf: %v", err)
	}
}

// installRealSnippet plants the real security-headers snippet at the path
// the adapter renders into the vhost (so `nginx -t` can resolve the
// include directive).
func installRealSnippet(t *testing.T) {
	t.Helper()
	if _, err := os.Stat("/etc/nginx/snippets/saas-security-headers.conf"); errors.Is(err, os.ErrNotExist) {
		t.Skip("/etc/nginx/snippets/saas-security-headers.conf not installed on host; run deploy/host/setup-nginx-adapter.sh first")
	}
}

func TestApply_RealNginx_Integration(t *testing.T) {
	nginxBin := skipIfNoNginx(t)
	installRealSnippet(t)

	a, _ := newTestAdapter(t)
	// The integration runner needs a directory to plant the main nginx.conf
	// in. The adapter's SitesAvailableDir parent is a per-test TempDir
	// (see newTestAdapter); we reuse that for our nginx.conf as well.
	root := filepath.Dir(a.SitesAvailableDir)
	a.NginxBin = nginxBin
	a.Runner = &realNginxRunner{nginxBin: nginxBin, testConfDir: root, t: t}
	buildMainNginxConf(t, root, a.SitesEnabledDir)

	in := validInput()
	in.CustomDomains = []string{"api.example.com"}
	if err := a.Apply(context.Background(), in); err != nil {
		t.Fatalf("Apply: %v", err)
	}

	// Confirm the file is on disk + parses.
	info, err := os.Stat(a.vhostPath(in.DeploymentID))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o644 {
		t.Errorf("mode = %v, want 0644", info.Mode().Perm())
	}

	// Re-run nginx -t standalone to double-check the adapter's emitted
	// config is well-formed (defence in depth — Apply already did this).
	cmd := exec.Command(nginxBin, "-t", "-c", filepath.Join(root, "nginx.conf"), "-p", root)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("standalone nginx -t failed: %v\n%s", err, string(out))
	}
}

func TestIssueCert_RejectsWildcardBeforeShellingOut_Integration(t *testing.T) {
	// Even with a real adapter, wildcard inputs must never reach certbot.
	a, _ := newTestAdapter(t)
	in := validInput()
	in.PrimaryDomain = "*.acme.saas.omarss.net"
	err := a.IssueCert(context.Background(), in)
	if !errors.Is(err, ErrWildcardDomain) {
		t.Fatalf("want ErrWildcardDomain, got %v", err)
	}
}

func TestIssueCert_DryRunArgvShape_Integration(t *testing.T) {
	// Integration variant of the unit test — confirms the adapter does
	// NOT pass `-d *` or any other shell-meta we missed even under a
	// realistic input. Does NOT issue a real cert.
	a, rec := newTestAdapter(t)
	in := validInput()
	in.CustomDomains = []string{"api.example.com", "app.example.com"}
	if err := a.IssueCert(context.Background(), in); err != nil {
		t.Fatalf("IssueCert: %v", err)
	}
	for _, arg := range rec.lastCall("/usr/bin/certbot") {
		if strings.Contains(arg, "*") {
			t.Errorf("wildcard leaked into certbot argv: %q", arg)
		}
		if strings.ContainsAny(arg, ";|&`$") {
			t.Errorf("shell metacharacter leaked into certbot argv: %q", arg)
		}
	}
}
