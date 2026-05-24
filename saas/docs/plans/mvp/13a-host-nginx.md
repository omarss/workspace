# Phase 12a — Real Host nginx Vhost Adapter (incl. BYOD multi-server_name) + sudoers + certbot

> **Goal**: Implement the real `NginxAdapter` that the control-plane Provisioner composition will call (Phase 12e). Render per-Deployment nginx vhost files from `deploy/nginx/vhost.conf.tmpl`, install them at `/etc/nginx/sites-available/saas-*.conf`, symlink to `sites-enabled/`, validate with `nginx -t`, reload via `sudo systemctl reload nginx`, then run `sudo certbot --nginx -d <primary> [-d <byod1>...]` exactly once per cert. Support multi-server_name for BYOD via the same vhost block. Install the shared `/etc/nginx/snippets/saas-security-headers.conf` snippet idempotently. Detach removes the symlink + reloads + runs `certbot delete` for the freed domain.
>
> **Why now**: 00-master.md gates this immediately after CHECKPOINT 4. Phase 11 produced the BYOD endpoints and a local-mode provisioner; this phase replaces the nginx portion of the provisioner with a real adapter and ends in CHECKPOINT 5 where the user inspects the first real vhost on disk.
>
> **What this phase does NOT do**: No k3s provisioning (Phase 12b). No Postgres provisioning (Phase 12c). No OpenBao key creation (Phase 12d). No full end-to-end provisioning sequence (Phase 12e). No wildcard cert via DNS-01 — ADR 008 in this phase decides the long-term path but the MVP code uses per-domain HTTP-01.
>
> **Maps to AGENTS.md**: §6.1 (nginx layout), §6.2 step 9 (render vhost) + step 10 (apply-nginx + certbot), §6.5 (nginx + TLS), §6.7 (homelab gotchas — workspace_personal/CLAUDE.md gotcha #1 is the central anti-pattern here). `01-foundations.md` §10 (vhost pattern, sudoers, anti-patterns, ADR 008 decision matrix).
>
> **Estimated subagent sessions**: 2 (one for adapter + template + sudoers install; one for tests + integration with Phase 11 BYOD).

---

## Pre-flight

1. AGENTS.md §6.1, §6.2, §6.5, §6.7.
2. workspace_personal/CLAUDE.md — apply-nginx + certbot gotchas section (the central operator pain point this phase avoids).
3. `01-foundations.md` §10 (verbatim template + sudoers).
4. `12-control-plane-skeleton.md` — confirm the LocalProvisioner shape that this adapter mirrors.
5. CHECKPOINT 4 approved (user has reviewed sudoers + template + k3s manifest set).
6. Confirm host has nginx + certbot installed and the `saas` user exists. Local dev workaround: run inside a Docker container with nginx + certbot for the integration tests (see §12a.6 below).

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Cert issuance | Per-vhost HTTP-01 via `certbot --nginx` for both primary (`*.saas.omarss.net`) AND BYOD domains | Wildcard DNS-01 for `*.saas.omarss.net` + per-vhost HTTP-01 for BYOD (deferred to ADR 008 follow-up if LE rate-limit becomes an issue) |
| File ownership for vhost files | `saas:saas` mode 0644 — platform writes them without sudo; only reload + certbot need sudo (per `01-foundations.md` §10) | root:root + always sudo (refused — more sudo surface) |
| Reload mechanism | `sudo /usr/sbin/nginx -s reload` after `sudo /usr/sbin/nginx -t` | `systemctl reload nginx` (also allowed; equivalent) |
| Snippet installation | One-time idempotent setup; the install function checks the snippet hash and only writes if changed | Always overwrite (refused — touches mtime, triggers reload) |
| certbot post-hook | Configured to call `systemctl reload nginx` once per renewal | None (refused — newly issued cert needs the listener reload) |
| Failure handling | If certbot fails, the vhost file is REMOVED and nginx reloaded so the platform doesn't leave a half-configured listener | Leave + mark failed (refused — half-configured listeners answer with default `_` vhost) |
| BYOD certbot invocation | One certbot call per attach (issues a NEW cert with `-d <byod>` appended to the existing primary cert via `--cert-name <dep_id>`) | Separate cert per BYOD (refused — more LE calls; harder to manage SANs) |
| nginx user | The system nginx (Ubuntu's `www-data`); the platform process is `saas`. The vhost file refers to upstream `127.0.0.1:<nodeport>` so the in-cluster k3s service reachable from the host | nginx-ingress in-cluster (refused — defeats the homelab pattern; mixes layers) |

If the user disagrees on any default, stop.

---

## Tasks

### 12a.1 Vhost template — `deploy/nginx/vhost.conf.tmpl`

```nginx
# Managed by saas-controlplane. DO NOT edit by hand.
# Deployment:   {{ .DeploymentID }}
# Primary:      {{ .PrimaryVhost }}
{{- range .CustomDomains }}
# BYOD:         {{ . }}
{{- end }}
#
# Pre-certbot configuration. certbot is run by the platform once after
# this file is installed; on success certbot injects a `listen 443 ssl;`
# block and a per-cert `server_name` selector. Do NOT run homelab's
# bulk apply-nginx — it clobbers certbot's edits (gotcha #1).

server {
    listen 80;
    server_name {{ .PrimaryVhost }}{{ range .CustomDomains }} {{ . }}{{ end }};

    include /etc/nginx/snippets/saas-security-headers.conf;

    # ACME http-01 challenges (well-known) — certbot writes here.
    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        try_files $uri =404;
    }

    # SaaS-verify endpoint for BYOD ownership proof (alternative to DNS TXT).
    location = /.well-known/saas-verify/ {
        return 404;
    }

    location / {
        include /etc/nginx/snippets/saas-security-headers.conf;
        proxy_pass http://127.0.0.1:{{ .NodePort }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
```

### 12a.2 Shared snippet — `deploy/nginx/snippets/saas-security-headers.conf`

```nginx
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
add_header Content-Security-Policy "default-src 'none'; frame-ancestors 'none'" always;
# DO NOT set add_header inside a location block without including this snippet —
# nginx add_header has no inheritance and any per-location header drops the parent's.
```

### 12a.3 Sudoers file — `deploy/nginx/saas-controlplane.sudoers`

```text
# /etc/sudoers.d/saas-controlplane  (mode 0440)
# Owned root:root. Validate with `visudo -cf deploy/nginx/saas-controlplane.sudoers`
# BEFORE deploying.
Cmnd_Alias SAAS_NGINX   = /usr/sbin/nginx -t, /usr/sbin/nginx -s reload, /usr/bin/systemctl reload nginx
Cmnd_Alias SAAS_CERTBOT = /usr/bin/certbot --nginx -d *.saas.omarss.net --non-interactive --agree-tos -m *, /usr/bin/certbot --nginx -d * -d * --non-interactive --agree-tos -m *, /usr/bin/certbot delete --cert-name *
saas ALL=(root) NOPASSWD: SAAS_NGINX, SAAS_CERTBOT
```

`-d * -d *` allows BYOD certs with multiple SANs. The wildcards are bound to the host's actual installed certbot binary path; do not let the operator parameterize the binary path.

### 12a.4 Adapter — `internal/controlplane/provision/nginx/`

```text
internal/controlplane/provision/nginx/
  adapter.go        # NginxAdapter implements deployments.Provisioner partial (vhost + cert paths)
  template.go       # text/template loader for vhost.conf.tmpl
  sudo.go           # `os/exec` wrapper that runs sudo nginx -t / -s reload / certbot
  setup.go          # one-time idempotent setup: install snippet + sudoers
  adapter_test.go   # integration test against a dockerized nginx + certbot (or skipped in CI)
```

`adapter.go`:

```go
package nginx

import (
    "context"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "text/template"
)

type Adapter struct {
    SitesAvailableDir string // /etc/nginx/sites-available
    SitesEnabledDir   string // /etc/nginx/sites-enabled
    WebrootDir        string // /var/www/letsencrypt
    Email             string // ops@omarss.net
    DryRun            bool   // for local dev; logs commands instead of running
    Tmpl              *template.Template
}

type RenderInput struct {
    DeploymentID  string
    PrimaryVhost  string
    CustomDomains []string
    NodePort      int
}

// ApplyVhost renders the vhost, installs it, validates nginx, and reloads.
// Idempotent — re-running with the same input is a no-op (file hash matches).
func (a *Adapter) ApplyVhost(ctx context.Context, in RenderInput) error {
    fname := filepath.Join(a.SitesAvailableDir, "saas-"+in.DeploymentID+".conf")
    var buf bytes.Buffer
    if err := a.Tmpl.Execute(&buf, in); err != nil { return fmt.Errorf("render: %w", err) }

    // Write to a temp file, fsync, then rename — atomic.
    tmp := fname + ".tmp"
    if err := os.WriteFile(tmp, buf.Bytes(), 0644); err != nil { return err }
    if err := os.Rename(tmp, fname); err != nil { return err }

    // Symlink into sites-enabled.
    link := filepath.Join(a.SitesEnabledDir, "saas-"+in.DeploymentID+".conf")
    _ = os.Remove(link)
    if err := os.Symlink(fname, link); err != nil { return err }

    if err := a.sudoNginxTest(ctx); err != nil {
        // Pre-flight failure — remove the file + symlink so we don't leave bad state.
        _ = os.Remove(link); _ = os.Remove(fname)
        return fmt.Errorf("nginx -t: %w", err)
    }
    return a.sudoReload(ctx)
}

// IssueCertificate runs certbot --nginx for the deployment.
// On BYOD attach, this is re-called with the expanded -d list using --cert-name <dep_id>.
func (a *Adapter) IssueCertificate(ctx context.Context, deploymentID, primary string, customDomains []string) error {
    args := []string{"--nginx", "--non-interactive", "--agree-tos",
        "-m", a.Email, "--cert-name", deploymentID, "-d", primary}
    for _, d := range customDomains {
        args = append(args, "-d", d)
    }
    return a.sudoCertbot(ctx, args...)
}

// DeleteCertificate removes the cert for a Deployment (after destroy + retention).
func (a *Adapter) DeleteCertificate(ctx context.Context, deploymentID string) error {
    return a.sudoCertbot(ctx, "delete", "--cert-name", deploymentID, "--non-interactive")
}

// RemoveVhost is the inverse of ApplyVhost. Used by destroy + by failed-provision rollback.
func (a *Adapter) RemoveVhost(ctx context.Context, deploymentID string) error {
    fname := filepath.Join(a.SitesAvailableDir, "saas-"+deploymentID+".conf")
    link  := filepath.Join(a.SitesEnabledDir,   "saas-"+deploymentID+".conf")
    _ = os.Remove(link)
    _ = os.Remove(fname)
    if err := a.sudoNginxTest(ctx); err != nil { return err }
    return a.sudoReload(ctx)
}

// BYOD multi-server_name: on attach, re-render with the expanded CustomDomains
// list, validate, reload, then re-issue cert. On detach: remove from list,
// re-render, reload, run certbot delete for the freed domain.
func (a *Adapter) AttachDomain(ctx context.Context, dep *Deployment, dd *DeploymentDomain) error {
    customs := append(currentCustomDomains(dep), dd.Domain)
    if err := a.ApplyVhost(ctx, RenderInput{
        DeploymentID: dep.ID, PrimaryVhost: dep.PrimaryVhost, CustomDomains: customs, NodePort: nodePortFor(dep),
    }); err != nil { return err }
    // Pre-flight DNS resolution to the host's external IP.
    if err := dnsResolvesToUs(ctx, dd.Domain, a.HostExternalIP); err != nil {
        // Roll back vhost.
        _ = a.ApplyVhost(ctx, RenderInput{DeploymentID: dep.ID, PrimaryVhost: dep.PrimaryVhost, CustomDomains: dep.CustomDomains, NodePort: nodePortFor(dep)})
        return err
    }
    return a.IssueCertificate(ctx, dep.ID, dep.PrimaryVhost, customs)
}
```

`sudo.go`:

```go
func (a *Adapter) sudoNginxTest(ctx context.Context) error {
    if a.DryRun { return nil }
    return exec.CommandContext(ctx, "sudo", "/usr/sbin/nginx", "-t").Run()
}

func (a *Adapter) sudoReload(ctx context.Context) error {
    if a.DryRun { return nil }
    return exec.CommandContext(ctx, "sudo", "/usr/sbin/nginx", "-s", "reload").Run()
}

func (a *Adapter) sudoCertbot(ctx context.Context, args ...string) error {
    if a.DryRun { return nil }
    return exec.CommandContext(ctx, "sudo", append([]string{"/usr/bin/certbot"}, args...)...).Run()
}
```

`setup.go`:

```go
// InstallSnippet installs /etc/nginx/snippets/saas-security-headers.conf
// idempotently. Compares the existing file's hash to the embedded one and
// skips the write if identical.
func InstallSnippet(ctx context.Context) error {
    target := "/etc/nginx/snippets/saas-security-headers.conf"
    expected := embeddedSnippet
    if existing, err := os.ReadFile(target); err == nil {
        if bytes.Equal(existing, expected) { return nil }
    }
    // Write via tmp+rename. Requires the snippets dir to be writable by the saas user
    // (chmod 0775 by the host setup script — see docs/runbooks/host-setup.md).
    return atomicWrite(target, expected, 0644)
}

// InstallSudoers copies the sudoers file into /etc/sudoers.d/ ONLY after
// `visudo -cf` validates the source. Runs at platform boot if missing.
func InstallSudoers(ctx context.Context) error {
    src := "/opt/saas/deploy/nginx/saas-controlplane.sudoers"
    if err := exec.CommandContext(ctx, "sudo", "/usr/sbin/visudo", "-cf", src).Run(); err != nil {
        return fmt.Errorf("visudo -cf failed: %w", err)
    }
    return exec.CommandContext(ctx, "sudo", "/usr/bin/install", "-m", "0440", "-o", "root", "-g", "root",
        src, "/etc/sudoers.d/saas-controlplane").Run()
}
```

### 12a.5 Domain verification flow (BYOD)

Add to the adapter a "domain verify" step that the control-plane DomainService calls when `POST /control/v1/deployments/{id}/domains/{id}/verify` runs:

```go
// VerifyDomain pre-flights DNS + does an HTTPS reachability check.
// Returns nil if the platform's vhost answers on the custom domain.
func (a *Adapter) VerifyDomain(ctx context.Context, dep *Deployment, dd *DeploymentDomain) error {
    // 1. Resolve the domain — must point at the platform's external IP.
    if err := dnsResolvesToUs(ctx, dd.Domain, a.HostExternalIP); err != nil {
        return fmt.Errorf("dns: %w", err)
    }
    // 2. HTTPS reachability — issue cert if not yet, then GET /.well-known/saas-verify/<token>.
    // Path: issue the cert first (adds the SAN), then probe.
    customs := append(currentCustomDomains(dep), dd.Domain)
    if err := a.IssueCertificate(ctx, dep.ID, dep.PrimaryVhost, customs); err != nil {
        return fmt.Errorf("certbot: %w", err)
    }
    // 3. Probe.
    resp, err := httpClient.Get("https://" + dd.Domain + "/.well-known/saas-verify/" + dd.VerificationRecord.RecordValue)
    if err != nil { return fmt.Errorf("probe: %w", err) }
    defer resp.Body.Close()
    if resp.StatusCode != 200 { return fmt.Errorf("probe returned %d", resp.StatusCode) }
    return nil
}
```

The probe is satisfied by the control-plane's `/.well-known/saas-verify/{token}` handler that returns 200 OK with the deployment_id when the token matches. The control plane is reachable via the same nginx vhost (since we just added the custom domain to the server_name list).

### 12a.6 Integration test environment

Real nginx + certbot can't run in CI as-is (LE rate limits, root requirement). Solutions:

(a) **Dockerized nginx + certbot in test container.** Use `nginx:1.27` + `certbot/certbot` images on a shared volume in a dedicated test compose file. Skip the certbot step (use `certbot --dry-run` or skip outright) since cert issuance can't be verified offline. Mark these tests with `//go:build integration`.

(b) **Mock at the `sudo` layer.** Default for unit tests. The adapter accepts a `Runner` interface; tests inject a recorder that captures the exec calls and asserts the right command was invoked.

`adapter_test.go` covers both:

- Unit (mock runner): render → write → symlink → mock nginx -t → mock reload → mock certbot. Assert exact command shape.
- Integration (real nginx in docker): real file writes + real nginx -t + real reload; certbot stubbed via `--dry-run`.

### 12a.7 Hook the adapter into the control-plane wiring

`cmd/controlplane/main.go`:

```go
nginxAdapter := &nginx.Adapter{
    SitesAvailableDir: "/etc/nginx/sites-available",
    SitesEnabledDir:   "/etc/nginx/sites-enabled",
    WebrootDir:        "/var/www/letsencrypt",
    Email:             "ops@omarss.net",
    DryRun:            os.Getenv("SAAS_NGINX_DRYRUN") == "1",
    Tmpl:              template.Must(template.New("vhost").Parse(string(embeddedVhostTmpl))),
}
if err := nginx.InstallSnippet(ctx); err != nil { return err }
if err := nginx.InstallSudoers(ctx); err != nil { return err }

// At this point the LocalProvisioner from Phase 11 is augmented with the
// real nginx adapter. The provisioner composition lands fully in Phase 12e;
// for now the nginx adapter is reachable via a CompositeProvisioner that
// delegates non-nginx steps to LocalProvisioner.
provisioner := &deployments.CompositeProvisioner{
    Local: localProvisioner,
    Nginx: nginxAdapter,
    // k3s, postgres, openbao stay nil for Phase 12a — set in Phase 12b/c/d.
}
```

### 12a.8 ADR 008

`docs/adr/008-cert-issuance-strategy.md`:

```markdown
# ADR 008 — Certificate issuance: per-vhost HTTP-01 (incl. BYOD); wildcard DNS-01 deferred

## Status
Accepted (2026-05-24).

## Context
Each Deployment needs TLS for:
1. Its primary vhost `<env>.<project>.saas.omarss.net`.
2. Zero or more BYOD custom domains (per ADR 015).

Two options for the primary vhost:
(A) Per-vhost HTTP-01 via `certbot --nginx -d <vhost>`.
(B) Wildcard `*.saas.omarss.net` via DNS-01 (requires API access to the
    omarss.net DNS provider).

Let's Encrypt's rate limits:
- 50 certs per registered domain per week (omarss.net subdomains share).
- 100 SANs per cert.
- 5 duplicates per week.

At MVP scale (~5 deployments) (A) is fine. At sustained ~30/week new
deployments, (A) hits the rate limit; (B) avoids it for the primary vhost
but still uses (A) for BYOD (different registered domains).

## Decision
For MVP:
- Per-vhost HTTP-01 for everything (primary + BYOD).
- One cert per Deployment, with `--cert-name <deployment_id>`.
- BYOD attach adds the new domain as an additional `-d` to the existing
  `--cert-name` cert (cert is reissued; same name; certbot handles renewal).

If a rate-limit becomes an operational issue:
- Migrate primary vhosts to wildcard DNS-01 via the omarss.net DNS API
  (Cloudflare, Route53, or whatever the registrar provides). Documented
  migration runbook.
- BYOD always stays per-domain HTTP-01.

## Consequences
+ One cert per Deployment is easy to revoke / delete on destroy.
+ Multi-SAN certs (primary + BYOD) reload together.
- 50/week rate limit caps deployment rate. Documented.
- Multi-SAN cert reissue happens on every BYOD attach. Cert reissue is
  free of LE rate limit; what costs is "duplicate certs" which is 5/week.
  Re-issue with --expand uses the duplicate quota — accept and document.
```

### 12a.9 Audit emission

NginxAdapter emits via the control-plane outbox:
- `deployment.vhost_applied`
- `deployment.cert_issued`
- `deployment.cert_failed`
- `deployment.vhost_removed`
- `deployment.cert_deleted`
- `deployment.domain_attached_to_vhost`
- `deployment.domain_detached_from_vhost`

Control-plane audit subscriber (Phase 11) consumes these into `control_plane_audit_event`.

### 12a.10 Tests

`adapter_test.go`:

- Render matches golden file (one for "primary only", one for "primary + 2 BYOD").
- ApplyVhost writes via tmp+rename (atomic).
- nginx -t failure → file removed + symlink removed + return error.
- certbot failure → vhost reverted to previous state.
- Re-run ApplyVhost with same input is a no-op (file hash matches).
- AttachDomain extends server_name, reissues cert, probes via .well-known/saas-verify/.
- DetachDomain shrinks server_name, reissues cert, calls certbot delete for the freed domain.
- RemoveVhost cleans up + reloads.

### 12a.11 saasctl

No new saasctl surface — Phase 11's `saasctl domain attach/verify/detach` now talks to the real adapter.

### 12a.12 Commits

```bash
git add deploy/nginx/vhost.conf.tmpl deploy/nginx/snippets/ deploy/nginx/saas-controlplane.sudoers
git commit -m "add nginx vhost template snippet sudoers"

git add internal/controlplane/provision/nginx/
git commit -m "implement nginx adapter with byod and certbot"

git add cmd/controlplane/main.go
git commit -m "wire nginx adapter into control plane"

git add docs/adr/008-cert-issuance-strategy.md
git commit -m "add cert issuance adr"
```

---

## Verification checklist

```bash
# 1. Sudoers validates.
$ sudo /usr/sbin/visudo -cf deploy/nginx/saas-controlplane.sudoers
# Expected: "parsed OK"

# 2. Snippet installs idempotently.
$ sudo make -C deploy/nginx install-snippet
$ ls -la /etc/nginx/snippets/saas-security-headers.conf
$ sudo make -C deploy/nginx install-snippet  # second run is no-op (mtime unchanged)

# 3. Sudoers installed.
$ sudo cp deploy/nginx/saas-controlplane.sudoers /etc/sudoers.d/saas-controlplane
$ sudo chmod 0440 /etc/sudoers.d/saas-controlplane
$ sudo /usr/sbin/visudo -c

# 4. Real-vhost provision (TEST DEPLOYMENT — pick a benign name).
$ ./bin/saasctl deployment create --project saastest --environment dev --image v0.3.1
# Expected:
#   - Phase 11 LocalProvisioner created DB
#   - Phase 12a NginxAdapter wrote /etc/nginx/sites-available/saas-dep_....conf
#   - nginx -t passed
#   - nginx -s reload succeeded
#   - certbot --nginx -d dev.saastest.saas.omarss.net --cert-name dep_... succeeded (real cert!)
$ ls -la /etc/nginx/sites-available/saas-dep_*.conf
$ ls -la /etc/nginx/sites-enabled/saas-dep_*.conf
$ sudo certbot certificates --cert-name dep_...
$ curl -I https://dev.saastest.saas.omarss.net/healthz
# Expected: 200 (since data plane isn't reachable yet, this might 502 from nginx — fine; the
# vhost listener is up + cert valid).

# 5. BYOD attach (using a domain you own; otherwise dry-run).
$ ./bin/saasctl domain attach dep_... --domain api.example.com
# Expected: vhost re-rendered with server_name "dev.saastest... api.example.com";
# DNS pre-flight + cert reissue. If DNS unset, the verify step fails politely.

# 6. Detach.
$ ./bin/saasctl domain detach dep_... --domain-id dom_...
$ sudo certbot certificates --cert-name dep_...
# Expected: cert no longer lists api.example.com.

# 7. Destroy + remove vhost.
$ ./bin/saasctl deployment delete dep_... --retain-days 0
# After purge:
$ ./bin/saasctl deployment purge dep_...
$ ls /etc/nginx/sites-enabled/saas-dep_*.conf
# Expected: no such file (vhost removed)
$ sudo certbot certificates --cert-name dep_...
# Expected: not found (cert deleted)

# 8. Re-running apply-nginx in homelab does NOT clobber.
$ # Optional: verify the homelab gotcha #1 doesn't apply because we do not bulk-apply.
$ ls /etc/nginx/sites-enabled/saas-*.conf
$ sudo make -C ../homelab apply-nginx       # if curious; do NOT actually run this on a live deployment
# Expected: re-running would clobber certbot blocks. The platform never calls this.
```

---

## Anti-pattern guards

- **NEVER** `make -C ../homelab apply-nginx` from the platform. The platform writes ONLY per-vhost files prefixed `saas-`. The bulk apply target is for homelab's own vhosts (claw, apps, swet, sync, qudrat).
- **NEVER** write to `/etc/nginx/sites-available/` without the `saas-` prefix. Collides with homelab namespace.
- **NEVER** issue certs without `--cert-name <deployment_id>`. Without the name, certbot's renewal machinery loses track.
- **NEVER** leave a half-configured vhost. If certbot fails, RemoveVhost rolls back.
- **NEVER** use `add_header` inside a location without including the shared snippet — nginx has no header inheritance (gotcha #4).
- **NEVER** use `if` inside an nginx location to set headers — gotcha #5; use regex location blocks.
- **NEVER** call `certbot --nginx -d ...` without `--non-interactive --agree-tos -m <email>`. The interactive prompt blocks the goroutine indefinitely.
- **NEVER** allow a BYOD domain to be a subdomain of `*.saas.omarss.net`. Phase 11 attach handler enforces; the adapter double-checks.
- **NEVER** write the vhost file with mode != 0644 owner != saas:saas. Other modes break the platform's own re-render path.
- **NEVER** call `sudo certbot delete` from a path that doesn't double-check `--cert-name` is a known Deployment id. Catastrophic if it deletes the homelab's apps.omarss.net cert.

---

## Open questions

1. **certbot post-hook for nginx reload.** Default: configured in `/etc/letsencrypt/cli.ini` once during host setup: `post-hook = sudo /usr/sbin/nginx -s reload`. Confirm.
2. **Host external IP for DNS pre-flight.** Default: discovered via `https://ifconfig.me/ip` at startup; cached. Alternative: configured per env var `SAAS_HOST_EXTERNAL_IP`. Default OK?
3. **Should the BYOD probe path live in nginx or in the data plane?** Default: in nginx (the well-known path returns a 200 OK with a token check — handled by the control-plane reverse proxy through to a dedicated handler `/.well-known/saas-verify/{token}`). The probe response is generated by the control plane on port 8080 via the same vhost. Confirm.
4. **Cert renewal alerting.** certbot logs renewals to syslog. Wire a slog-emitting renewal hook later. Out of MVP.

---

## Phase 12a — Definition of done

- [ ] `deploy/nginx/vhost.conf.tmpl`, `deploy/nginx/snippets/saas-security-headers.conf`, `deploy/nginx/saas-controlplane.sudoers` committed
- [ ] `internal/controlplane/provision/nginx/` complete with adapter, template loader, sudo runner, setup, tests
- [ ] `make install-snippet` and `make install-sudoers` idempotent host-setup targets
- [ ] cmd/controlplane wires the adapter via CompositeProvisioner
- [ ] At least one real vhost installed at `/etc/nginx/sites-available/saas-<dep_id>.conf` + symlink
- [ ] `nginx -t` passes after install
- [ ] `nginx -s reload` succeeds
- [ ] certbot issues a real cert with `--cert-name <dep_id>`
- [ ] BYOD attach extends server_name + reissues cert
- [ ] BYOD detach shrinks server_name + reissues + certbot delete for the freed domain
- [ ] Vhost removal on destroy is clean
- [ ] `make -C ../homelab apply-nginx` is NOT in any platform code path (lint check)
- [ ] §17.4 partial test (vhost happy path + partial-failure cleanup) passes
- [ ] ADR 008 committed
- [ ] All Phase 2-11 tests still green
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 5 — First real nginx vhost on disk

### What was done
- deploy/nginx/{vhost.conf.tmpl, snippets/saas-security-headers.conf, saas-controlplane.sudoers}
- internal/controlplane/provision/nginx/{adapter, template, sudo, setup, tests}.go
- cmd/controlplane/main.go wired the adapter (alongside LocalProvisioner for non-nginx steps)
- One real vhost on disk at `/etc/nginx/sites-available/saas-<dep_id>.conf`
- One real cert via certbot `--cert-name <dep_id>`
- docs/adr/008-cert-issuance-strategy.md

### What to verify (user runs these)
```bash
$ ls -la /etc/nginx/sites-available/saas-*.conf
$ ls -la /etc/nginx/sites-enabled/saas-*.conf
$ sudo /usr/sbin/nginx -t
$ sudo certbot certificates --cert-name <dep_id>
$ curl -I https://<env>.<project>.saas.omarss.net/healthz
$ cat /etc/sudoers.d/saas-controlplane
$ ls -la /etc/nginx/snippets/saas-security-headers.conf
```

### What approval means
By proceeding past CHECKPOINT 5, you accept:
- The platform owns `/etc/nginx/sites-available/saas-*.conf` and `/etc/nginx/sites-enabled/saas-*.conf`. Other vhosts (apps, claw, swet, sync, qudrat) remain owned by the homelab Makefile and are never touched.
- The platform runs `sudo nginx -t / -s reload / certbot` per the sudoers file. No other sudo surface is granted.
- BYOD attaches reissue the primary cert as a multi-SAN cert (using LE's duplicate-cert quota).
- The certbot post-hook is configured in `cli.ini` once during host setup.

### Rollback if rejected
```bash
$ sudo rm -f /etc/nginx/sites-enabled/saas-* /etc/nginx/sites-available/saas-* /etc/sudoers.d/saas-controlplane
$ sudo /usr/sbin/nginx -t && sudo /usr/sbin/nginx -s reload
$ sudo certbot delete --cert-name <dep_id> --non-interactive
$ git revert <hashes for the 4 phase-12a commits>
```

---

End of Phase 12a. Next: `13b-k3s-clientgo.md`.
