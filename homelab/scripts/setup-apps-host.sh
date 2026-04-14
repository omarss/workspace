#!/usr/bin/env bash
# Idempotent setup for apps.omarss.net static APK host.
# Run as root: sudo bash homelab/scripts/setup-apps-host.sh
#
# Steps:
#   1. Create /srv/apps owned by omar so `make publish` can rsync without sudo.
#   2. Install the nginx vhost into /etc/nginx/sites-{available,enabled}.
#   3. Validate nginx config and reload.
#   4. Print the certbot command (does NOT run it — Let's Encrypt rate-limits
#      failed challenges, so the operator confirms DNS resolves first).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root (it touches /srv, /etc/nginx, and reloads nginx)." >&2
    echo "Re-run with: sudo bash $0" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOC_ROOT=/srv/apps
NGINX_AVAIL=/etc/nginx/sites-available/apps.omarss.net
NGINX_ENABLED=/etc/nginx/sites-enabled/apps.omarss.net
CONF_SOURCE="${REPO_ROOT}/nginx/apps.omarss.net.conf"
DOMAIN=apps.omarss.net
TARGET_USER=omar
TARGET_GROUP=omar

if [[ ! -f "$CONF_SOURCE" ]]; then
    echo "Source config not found: $CONF_SOURCE" >&2
    exit 1
fi

echo "==> Ensuring document root $DOC_ROOT exists"
mkdir -p "$DOC_ROOT"
chown "${TARGET_USER}:${TARGET_GROUP}" "$DOC_ROOT"
chmod 755 "$DOC_ROOT"

echo "==> Installing nginx vhost"
cp "$CONF_SOURCE" "$NGINX_AVAIL"
ln -sf "$NGINX_AVAIL" "$NGINX_ENABLED"

echo "==> Validating nginx config"
nginx -t

echo "==> Reloading nginx"
systemctl reload nginx

echo
echo "==> Done."
echo
echo "Next steps (run by hand):"
echo "  1. Confirm DNS resolves: dig +short ${DOMAIN}"
echo "     (must point at this machine's public IP)"
echo
echo "  2. Issue the cert (Let's Encrypt rate-limits failed challenges, so"
echo "     do step 1 first):"
echo "     sudo certbot --nginx -d ${DOMAIN}"
echo
echo "  3. From the omono project: make publish"
echo "     The APK will land at https://${DOMAIN}/omono.latest.apk"
