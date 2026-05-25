#!/usr/bin/env bash
# Idempotent setup for tweets.omarss.net (browser-hybrid scraper).
# Run as root: sudo bash homelab/scripts/setup-tweets-host.sh
#
# Layout after this script:
#   /srv/tweets/                       (mode 700, owned by omar)
#     ├── browser-profile/             Chrome profile w/ the X session
#     ├── refresh-venv/                Python venv for the CDP refresher
#     ├── refresh-template.py          CDP script (from tweets/scripts/)
#     ├── cookies.json                 captured by refresh-template.py
#     ├── search-template.json         captured by refresh-template.py
#     └── tweets.sqlite                feed cache (created by tweetsd)
#
#   /usr/local/bin/tweetsd             the Go binary
#   /etc/systemd/system/
#     ├── tweets-browser.service       headless Chrome
#     └── tweets.service               the Go scraper, depends on browser
#   /etc/nginx/sites-{available,enabled}/tweets.omarss.net  TLS terminator
#   /etc/nginx/snippets/tweets-security-headers.conf
#
# Re-run after `git pull` to rebuild + restart with the new binary.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root (it writes to /srv, /etc, /usr/local/bin)." >&2
    echo "Re-run with: sudo bash $0" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TWEETS_SOURCE="${REPO_ROOT}/tweets"
NGINX_AVAIL=/etc/nginx/sites-available/tweets.omarss.net
NGINX_ENABLED=/etc/nginx/sites-enabled/tweets.omarss.net
NGINX_SNIPPETS=/etc/nginx/snippets
CONF_SOURCE="${REPO_ROOT}/homelab/nginx/tweets.omarss.net.conf"
SNIPPET_SOURCE="${REPO_ROOT}/homelab/nginx/snippets/tweets-security-headers.conf"
SYSTEMD_TWEETS_SOURCE="${REPO_ROOT}/homelab/systemd/tweets.service"
SYSTEMD_BROWSER_SOURCE="${REPO_ROOT}/homelab/systemd/tweets-browser.service"
REFRESH_SCRIPT_SOURCE="${TWEETS_SOURCE}/scripts/refresh-template.py"
SYSTEMD_TARGET_TWEETS=/etc/systemd/system/tweets.service
SYSTEMD_TARGET_BROWSER=/etc/systemd/system/tweets-browser.service
BINARY_TARGET=/usr/local/bin/tweetsd
DATA_DIR=/srv/tweets
DOMAIN=tweets.omarss.net
TARGET_USER=omar
TARGET_GROUP=omar

for f in "$CONF_SOURCE" "$SNIPPET_SOURCE" "$SYSTEMD_TWEETS_SOURCE" \
         "$SYSTEMD_BROWSER_SOURCE" "$REFRESH_SCRIPT_SOURCE" \
         "$TWEETS_SOURCE/go.mod" "$TWEETS_SOURCE/cmd/tweetsd/main.go"; do
    if [[ ! -f "$f" ]]; then
        echo "Missing source file: $f" >&2
        exit 1
    fi
done
for c in go google-chrome python3; do
    if ! command -v "$c" >/dev/null 2>&1; then
        echo "$c not on PATH — install before re-running." >&2
        exit 1
    fi
done

echo "==> Building tweetsd from ${TWEETS_SOURCE}"
sudo -u "$TARGET_USER" bash -c "cd '$TWEETS_SOURCE' && go build -o /tmp/tweetsd ./cmd/tweetsd"
install -m 755 -o root -g root /tmp/tweetsd "$BINARY_TARGET"
rm -f /tmp/tweetsd

echo "==> Ensuring data dir ${DATA_DIR}"
install -d -m 700 -o "$TARGET_USER" -g "$TARGET_GROUP" "$DATA_DIR"
install -d -m 700 -o "$TARGET_USER" -g "$TARGET_GROUP" "$DATA_DIR/browser-profile"

echo "==> Installing refresh-template.py"
install -m 750 -o "$TARGET_USER" -g "$TARGET_GROUP" \
    "$REFRESH_SCRIPT_SOURCE" "$DATA_DIR/refresh-template.py"

echo "==> Ensuring python venv for the refresher"
if [[ ! -d "$DATA_DIR/refresh-venv" ]]; then
    sudo -u "$TARGET_USER" python3 -m venv "$DATA_DIR/refresh-venv"
fi
sudo -u "$TARGET_USER" "$DATA_DIR/refresh-venv/bin/pip" install --quiet --upgrade pip
sudo -u "$TARGET_USER" "$DATA_DIR/refresh-venv/bin/pip" install --quiet 'websocket-client>=1.7'

# Seed cookies + template so tweetsd's loader sees structurally valid
# files (even if empty) and the operator gets clear "credentials not
# yet captured" messages instead of a stat() failure.
SEEDED_STATE=0
for f in cookies.json search-template.json; do
    if [[ ! -f "$DATA_DIR/$f" ]]; then
        install -m 600 -o "$TARGET_USER" -g "$TARGET_GROUP" /dev/null "$DATA_DIR/$f"
        echo '{}' > "$DATA_DIR/$f"
        chown "$TARGET_USER:$TARGET_GROUP" "$DATA_DIR/$f"
        chmod 600 "$DATA_DIR/$f"
        SEEDED_STATE=1
    fi
done

echo "==> Installing systemd units"
install -m 644 -o root -g root "$SYSTEMD_BROWSER_SOURCE" "$SYSTEMD_TARGET_BROWSER"
install -m 644 -o root -g root "$SYSTEMD_TWEETS_SOURCE" "$SYSTEMD_TARGET_TWEETS"
systemctl daemon-reload

echo "==> Enabling + starting tweets-browser.service (headless Chrome)"
systemctl enable tweets-browser.service >/dev/null
systemctl restart tweets-browser.service

echo "==> Waiting up to 15s for CDP port to listen"
for _ in $(seq 1 30); do
    if curl -sS --max-time 1 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
        echo "    CDP up."
        break
    fi
    sleep 0.5
done

echo "==> Enabling + starting tweets.service"
systemctl enable tweets.service >/dev/null
systemctl restart tweets.service

echo "==> Installing nginx snippet + vhost"
install -d -m 755 "$NGINX_SNIPPETS"
install -m 644 "$SNIPPET_SOURCE" "$NGINX_SNIPPETS/tweets-security-headers.conf"
cp "$CONF_SOURCE" "$NGINX_AVAIL"
ln -sf "$NGINX_AVAIL" "$NGINX_ENABLED"

echo "==> Validating nginx config"
nginx -t

echo "==> Reloading nginx"
systemctl reload nginx

# Idempotent certbot. Copying the vhost from source wipes out the
# `listen 443 ssl;` block certbot previously injected, so every apply
# must re-inject it. certbot reuses the cached cert with no LE API
# call when one already exists for this domain (--reinstall). We only
# do this if certbot is installed AND a cert already exists; first-run
# setups still need the operator to do an interactive certbot to prove
# domain ownership.
if command -v certbot >/dev/null 2>&1 && \
   [[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
    echo "==> Re-injecting TLS via certbot --reinstall"
    if certbot --nginx --reinstall -d "$DOMAIN" --non-interactive; then
        echo "==> Reloading nginx (post-certbot)"
        systemctl reload nginx
    else
        echo "    certbot --reinstall failed — re-run interactively:" >&2
        echo "      sudo certbot --nginx -d $DOMAIN" >&2
    fi
fi

echo
echo "==> Done."
systemctl --no-pager status tweets-browser.service | head -6 || true
echo
systemctl --no-pager status tweets.service | head -6 || true
echo
echo "Next steps:"
if [[ "$SEEDED_STATE" == "1" ]]; then
    echo "  1. ONE-TIME LOGIN — from a graphical session (needs your desktop):"
    echo "       make -C homelab tweets-browser-login"
    echo "     A headed Chrome opens with the same --user-data-dir. Log into x.com (incl. 2FA)."
    echo "     Close the window. systemd's headless Chrome inherits the session."
    echo
    echo "  2. Restart the headless browser to pick up the session,"
    echo "     then prime cookies + template via the CDP refresher:"
    echo "       sudo systemctl restart tweets-browser.service"
    echo "       make -C homelab tweets-refresh"
fi
echo "  $( [[ "$SEEDED_STATE" == "1" ]] && echo 3 || echo 1 ). TLS — first run only (subsequent runs re-use the cached cert):"
echo "       sudo certbot --nginx -d ${DOMAIN}"
echo
echo "  Logs:"
echo "    sudo journalctl -u tweets -f"
echo "    sudo journalctl -u tweets-browser -f"
