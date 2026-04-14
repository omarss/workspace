#!/usr/bin/env bash
# Idempotent setup for apps.omarss.net static APK host.
# Run as root: sudo bash homelab/scripts/setup-apps-host.sh
#
# Steps:
#   1. Ensure /srv/apps exists with the right owner + mode (nginx must
#      be able to traverse it).
#   2. Install the static index.html that any browser sees at /.
#   3. Seed an empty manifest.json so the index page renders cleanly
#      before the first publish.
#   4. Install update-apps-manifest to /usr/local/bin so any project's
#      publish flow can call it without depending on this repo.
#   5. Install the nginx vhost into /etc/nginx/sites-{available,enabled}.
#   6. Validate nginx config and reload.
#   7. Print the certbot command (does NOT run it — Let's Encrypt
#      rate-limits failed challenges).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root (it touches /srv, /etc/nginx, /usr/local/bin)." >&2
    echo "Re-run with: sudo bash $0" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOC_ROOT=/srv/apps
NGINX_AVAIL=/etc/nginx/sites-available/apps.omarss.net
NGINX_ENABLED=/etc/nginx/sites-enabled/apps.omarss.net
CONF_SOURCE="${REPO_ROOT}/nginx/apps.omarss.net.conf"
INDEX_SOURCE="${REPO_ROOT}/static/apps/index.html"
MANIFEST_HELPER_SOURCE="${REPO_ROOT}/scripts/update-apps-manifest.sh"
MANIFEST_HELPER_TARGET=/usr/local/bin/update-apps-manifest
DOMAIN=apps.omarss.net
TARGET_USER=omar
TARGET_GROUP=omar

for f in "$CONF_SOURCE" "$INDEX_SOURCE" "$MANIFEST_HELPER_SOURCE"; do
    if [[ ! -f "$f" ]]; then
        echo "Missing source file: $f" >&2
        exit 1
    fi
done

if ! command -v jq >/dev/null 2>&1; then
    echo "==> jq not found — installing"
    apt-get update -qq
    apt-get install -y -qq jq
fi

echo "==> Ensuring document root $DOC_ROOT exists"
# `install -d` is atomic over mkdir + chown + chmod and ignores the
# inherited umask, which on some sudo setups is 077 and produces a
# 700 directory that nginx (www-data) can't traverse — exactly the
# kind of silent failure that gives us a 403 with no logs.
install -d -m 755 -o "$TARGET_USER" -g "$TARGET_GROUP" "$DOC_ROOT"
# Belt-and-braces: re-assert mode on an existing dir too.
chmod 755 "$DOC_ROOT"
chown "${TARGET_USER}:${TARGET_GROUP}" "$DOC_ROOT"

echo "==> Installing index.html"
install -m 644 -o "$TARGET_USER" -g "$TARGET_GROUP" "$INDEX_SOURCE" "$DOC_ROOT/index.html"

echo "==> Seeding manifest.json (only if missing)"
if [[ ! -f "$DOC_ROOT/manifest.json" ]]; then
    install -m 644 -o "$TARGET_USER" -g "$TARGET_GROUP" /dev/null "$DOC_ROOT/manifest.json"
    NOW=$(date -u -Iseconds | sed 's/+00:00/Z/')
    printf '{"generated_at":"%s","apps":{}}\n' "$NOW" > "$DOC_ROOT/manifest.json"
    chown "${TARGET_USER}:${TARGET_GROUP}" "$DOC_ROOT/manifest.json"
fi

echo "==> Installing update-apps-manifest helper"
install -m 755 "$MANIFEST_HELPER_SOURCE" "$MANIFEST_HELPER_TARGET"

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
echo "  3. From the omono project: make release"
echo "     The APK + changelog will land at https://${DOMAIN}/"
