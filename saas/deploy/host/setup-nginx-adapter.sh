#!/usr/bin/env bash
#
# deploy/host/setup-nginx-adapter.sh — one-time idempotent host setup for
# the Phase 12a nginx adapter. Run as root on the homelab host BEFORE
# the controlplane process tries to provision its first deployment.
#
# This script does NOT touch existing certbot blocks in any vhost file.
# It only adds the platform-wide assets: the `saas` system user, the
# sudoers allow-list, the shared security-headers snippet, the ACME
# webroot, and the POSIX ACLs that grant the `saas` user write access
# to /etc/nginx/sites-{available,enabled}/ for files matching saas-*.conf.
#
# Safe to re-run. Each step is gated by an idempotency check; if all
# checks pass the script reports "already configured" and exits 0.
#
# Inputs (env vars, all optional):
#   SAAS_HOME     home directory for the saas user (default /var/lib/saas)
#   ACME_WEBROOT  ACME http-01 webroot dir (default /var/www/letsencrypt)
#   SUDOERS_SRC   path to sudoers source file (default deploy/sudoers/saas-controlplane,
#                 resolved relative to this script's parent-parent dir so the script
#                 works whether invoked from saas/ or from a checked-out clone)
#   SNIPPET_SRC   path to security-headers snippet source (default deploy/nginx/snippets/saas-security-headers.conf)
#
# See docs/runbooks/control-plane-host-trust.md for the full trust model.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "setup-nginx-adapter.sh: must run as root (try: sudo bash $0)" >&2
    exit 1
fi

# Resolve script-relative paths so this works invoked from any cwd.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

SAAS_HOME="${SAAS_HOME:-/var/lib/saas}"
ACME_WEBROOT="${ACME_WEBROOT:-/var/www/letsencrypt}"
SUDOERS_SRC="${SUDOERS_SRC:-$repo_root/deploy/sudoers/saas-controlplane}"
SNIPPET_SRC="${SNIPPET_SRC:-$repo_root/deploy/nginx/snippets/saas-security-headers.conf}"

# Pre-flight: source files exist.
for f in "$SUDOERS_SRC" "$SNIPPET_SRC"; do
    if [[ ! -f "$f" ]]; then
        echo "setup-nginx-adapter.sh: missing source file $f" >&2
        exit 2
    fi
done

# Pre-flight: required binaries.
for bin in nginx certbot setfacl getfacl visudo install useradd id; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "setup-nginx-adapter.sh: $bin not in PATH (install nginx + certbot + acl + sudo packages first)" >&2
        exit 3
    fi
done

# 1. Ensure the saas user exists.
if ! id -u saas >/dev/null 2>&1; then
    useradd --system --shell /usr/sbin/nologin --home "$SAAS_HOME" --create-home saas
    echo "  + created system user 'saas' (home=$SAAS_HOME)"
else
    echo "  - system user 'saas' already exists"
fi

# 2. Validate + install the sudoers rule (refuse to copy invalid syntax).
visudo -cf "$SUDOERS_SRC" >/dev/null
install -m 0440 -o root -g root "$SUDOERS_SRC" /etc/sudoers.d/saas-controlplane
echo "  + installed /etc/sudoers.d/saas-controlplane (validated with visudo -cf)"

# 3. Install the shared security-headers snippet.
install -d -m 0755 -o root -g root /etc/nginx/snippets
install -m 0644 -o root -g root "$SNIPPET_SRC" /etc/nginx/snippets/saas-security-headers.conf
echo "  + installed /etc/nginx/snippets/saas-security-headers.conf"

# 4. ACME webroot for http-01 challenges. certbot --nginx will use this
#    when port 80 is the listener; we pre-create the dir + ownership so
#    the first cert issue does not race on `mkdir`.
install -d -m 0755 -o root -g root "$ACME_WEBROOT"
echo "  + ensured $ACME_WEBROOT (mode 0755 root:root)"

# 5. POSIX ACLs for sites-{available,enabled}. The base dirs stay root-
#    owned (we don't want to broaden the default); a directory ACL grants
#    rwx to the saas user AND inherits onto new entries so the
#    controlplane can create+rename its vhost files without sudo.
for dir in /etc/nginx/sites-available /etc/nginx/sites-enabled; do
    if [[ ! -d "$dir" ]]; then
        install -d -m 0755 -o root -g root "$dir"
    fi
    # Idempotent — setfacl is a write but the kernel collapses no-op
    # changes. Capture before/after just for the log line.
    setfacl -m u:saas:rwx "$dir"
    setfacl -m default:u:saas:rwx "$dir"
    echo "  + setfacl u:saas:rwx (and default) on $dir"
done

# 6. nginx test + reload to pick up the new snippet directory. We only
#    reload if `nginx -t` passes — never reload a broken config.
nginx -t >/dev/null
if systemctl is-active nginx >/dev/null 2>&1; then
    systemctl reload nginx
    echo "  + reloaded nginx (systemctl)"
else
    nginx -s reload || true
    echo "  + reloaded nginx (-s reload; systemd unit not active)"
fi

echo
echo "saas nginx adapter setup complete."
echo "Next: verify the rules with"
echo "  sudo -l -U saas | grep -E 'nginx|certbot'"
echo "  getfacl /etc/nginx/sites-available | grep -A1 saas"
echo
echo "Then run the CP-5 smoke deployment per docs/runbooks/control-plane-host-trust.md."
