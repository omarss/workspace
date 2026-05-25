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
