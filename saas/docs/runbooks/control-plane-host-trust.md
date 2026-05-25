# Control plane host trust model

## Status
Phase 11 design doc. Phase 12a installs the assets described here. Reviewed at
CHECKPOINT 4 before any Phase 12 sub-phase writes to host state.

## Summary

The `saas-controlplane` process runs as a dedicated unprivileged Unix user
(`saas`) on the homelab host. It is the ONLY process that mutates per-Deployment
host state. It calls four external systems:

| System         | How                              | Auth                                 |
|----------------|----------------------------------|--------------------------------------|
| nginx          | edit own files; sudo to reload   | sudoers allow-list (see below)       |
| certbot        | sudo with bounded wildcard glob  | sudoers allow-list (see below)       |
| k3s            | client-go against `/etc/rancher/k3s/k3s.yaml` | kubeconfig the `saas` user reads |
| OpenBao        | AppRole role_id + secret_id      | `/etc/saas/approle/` 0400 files      |
| Postgres host  | superuser psql for per-Deployment DB creation | peer auth as `postgres` UNIX socket via a setuid helper documented in Phase 12c |

## Filesystem ownership

| Path                                    | Owner       | Mode  | Notes |
|-----------------------------------------|-------------|-------|-------|
| `/etc/nginx/sites-available/saas-*.conf` | `saas:saas` | `0644` | controlplane writes directly; no sudo |
| `/etc/nginx/sites-enabled/saas-*.conf`   | `saas:saas` | symlink | same |
| `/etc/nginx/snippets/saas-*.conf`        | `saas:saas` | `0644` | same |
| `/etc/sudoers.d/saas-controlplane`       | `root:root` | `0440` | installed once via setup script |
| `/etc/saas/approle/role_id`              | `saas:saas` | `0400` | rotated by AppRole TTL |
| `/etc/saas/approle/secret_id`            | `saas:saas` | `0400` | rotated by AppRole TTL |
| `/var/lib/saas/k3s-kubeconfig`           | `saas:saas` | `0400` | restricted-scope ServiceAccount kubeconfig (Phase 12b) |
| `/var/log/nginx/saas-<dep_id>.*.log`     | `www-data:adm` | `0640` | nginx writes; controlplane reads via group |

## sudoers (allow-listed commands)

```text
Cmnd_Alias SAAS_NGINX = /usr/sbin/nginx -t,
                        /usr/sbin/nginx -s reload,
                        /usr/bin/systemctl reload nginx

Cmnd_Alias SAAS_CERTBOT = /usr/bin/certbot --nginx -d *.saas.omarss.net --non-interactive --agree-tos -m *,
                          /usr/bin/certbot --nginx -d * --non-interactive --agree-tos -m *

saas ALL=(root) NOPASSWD: SAAS_NGINX, SAAS_CERTBOT
```

The `--non-interactive` flag prevents certbot from prompting on the controlling
terminal. The bounded `-d` glob blocks abuse of the certbot wildcard for
arbitrary domains via shell metacharacters — sudo's command matcher treats
the literal `*` as a glob over the actual argv at call time.

## Phase 12 sub-phases and what each adds

| Phase | Adds                                              | CHECKPOINT |
|-------|---------------------------------------------------|------------|
| 12a   | nginx vhost write + certbot cert issuance         | CP 5       |
| 12b   | k3s namespace + workload via client-go            | CP 6       |
| 12c   | per-Deployment Postgres DB + role on the host     | CP 7       |
| 12d   | OpenBao transit key + KV path + policy            | CP 8       |
| 12e   | composed 13-step §6.2 sequence + destroy reconciler | CP 9     |

## Rollback if approval is withheld

`deploy/` is template-only; nothing under `/etc/` was touched by Phase 11.
Reverting the Phase 11 commits removes the controlplane API surface and the
templates. No host state needs cleaning.

---

## Phase 12a operator steps (CHECKPOINT 5)

Phase 12a ships the host-nginx adapter code, the one-time idempotent
setup script, and a `saasctl debug nginx` helper. The PR itself writes
no host state — the first real `/etc/nginx/sites-available/saas-*.conf`
appears only when the operator runs the smoke deployment below.

### One-time host setup

```bash
sudo bash deploy/host/setup-nginx-adapter.sh
```

The script is idempotent and verifies:

- `saas` system user exists (creates if missing).
- `/etc/sudoers.d/saas-controlplane` matches the file under `deploy/sudoers/`
  (validated with `visudo -cf` before install).
- `/etc/nginx/snippets/saas-security-headers.conf` matches the file under
  `deploy/nginx/snippets/` (mode 0644 root:root).
- `/var/www/letsencrypt` exists for the ACME http-01 webroot.
- POSIX ACL `u:saas:rwx` (and `default:u:saas:rwx`) on both
  `/etc/nginx/sites-available` and `/etc/nginx/sites-enabled` so the
  adapter can write `saas-<dep_id>.conf` files without `sudo`.
- `nginx -t` passes and nginx reloads.

### Verify the setup

```bash
# Sudoers rule covers the four allowed binaries.
sudo -l -U saas | grep -E "nginx|certbot"

# Snippet is in place.
ls -la /etc/nginx/snippets/saas-security-headers.conf

# ACLs grant the saas user write access (default ACL inherits onto new
# files so the adapter can rename(2) without sudo).
getfacl /etc/nginx/sites-available | grep -A1 saas
getfacl /etc/nginx/sites-enabled   | grep -A1 saas
```

### CP-5 smoke deployment (first real vhost on disk)

Run the saasctl debug helper to invoke the nginx adapter directly. This
is the only operator-facing path that writes to `/etc/nginx/` in Phase
12a — Phase 12e wires it into the full provisioning sequence and the
debug helper goes away.

```bash
# Build a non-prod saasctl (default).
make build

# Apply (no certbot — confirm the file shape first):
./bin/saasctl debug nginx apply dep_test01 \
    --primary-domain test.saas.omarss.net \
    --node-port 30801 \
    --skip-certbot

# Inspect the resulting file:
sudo cat /etc/nginx/sites-available/saas-dep_test01.conf
ls -la /etc/nginx/sites-enabled/saas-dep_test01.conf
sudo nginx -t

# Once happy with the shape, optionally issue a real cert (requires DNS
# already resolving test.saas.omarss.net → this host's external IP):
./bin/saasctl debug nginx apply dep_test01 \
    --primary-domain test.saas.omarss.net \
    --node-port 30801 \
    --ops-email ops@omarss.net

# Clean up before Phase 12b:
./bin/saasctl debug nginx remove dep_test01
# If a cert was issued and you want it gone:
sudo certbot delete --cert-name dep_test01
```

### Failure modes you may see

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `ErrSetupNotComplete: sudoers rule missing` | setup script not run | `sudo bash deploy/host/setup-nginx-adapter.sh` |
| `ErrSetupNotComplete: ... not writable by current user` | ACLs missing — saas user can't write to sites-* | Re-run setup script (idempotent) |
| `ErrConfigTestFailed` after Apply | template emitted invalid nginx config | adapter has already rolled back; inspect `sudo nginx -t` stderr |
| `ErrACMEUnreachable` after IssueCert | DNS for primary domain does not resolve to this host | Fix DNS A/AAAA records; certbot caches an unexpired cert, so retry is free |
| `ErrRateLimited` after IssueCert | Let's Encrypt 50-certs/registered-domain/week hit | Wait the documented LE quota window; do NOT loop |

### What approval (CP 5) means

By proceeding past CHECKPOINT 5 the operator accepts:

- The platform owns `/etc/nginx/sites-{available,enabled}/saas-*.conf` and
  may rewrite them at any time. Other vhosts (claw, apps, swet, sync,
  qudrat) are NEVER touched by the adapter.
- `sudo nginx -t / -s reload / certbot --nginx` is the entire sudo
  surface granted to the `saas` user.
- BYOD attaches re-issue the per-Deployment multi-SAN cert (one cert
  per Deployment, identified by `--cert-name <deployment_id>`).
- `make -C ../homelab apply-nginx` MUST NOT be run from any platform
  code path — it clobbers certbot's 443 blocks (workspace_personal
  CLAUDE.md gotcha #1).

### Phase 12a rollback

If the operator rejects CP 5:

```bash
# Remove the test vhost.
./bin/saasctl debug nginx remove dep_test01
sudo certbot delete --cert-name dep_test01 --non-interactive || true

# Undo the host setup.
sudo rm -f /etc/sudoers.d/saas-controlplane
sudo rm -f /etc/nginx/snippets/saas-security-headers.conf
sudo setfacl -x u:saas /etc/nginx/sites-available 2>/dev/null || true
sudo setfacl -x u:saas /etc/nginx/sites-enabled   2>/dev/null || true
sudo setfacl -x default:u:saas /etc/nginx/sites-available 2>/dev/null || true
sudo setfacl -x default:u:saas /etc/nginx/sites-enabled   2>/dev/null || true
sudo nginx -t && sudo nginx -s reload

# Revert the PR; no further host state remains.
```
