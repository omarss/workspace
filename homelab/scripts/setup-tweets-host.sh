#!/usr/bin/env bash
# Idempotent setup for tweets.omarss.net.
# Run as root: sudo bash homelab/scripts/setup-tweets-host.sh
#
# Steps:
#   1. Build the tweetsd binary from source (the repo is already on
#      this machine; this script doesn't try to fetch it).
#   2. Install /srv/tweets owned by omar (mode 700 — holds X cookies).
#   3. Install /usr/local/bin/tweetsd + systemd unit, enable + start.
#   4. Install nginx vhost + security-headers snippet, reload nginx.
#   5. Print the certbot command for the operator to run by hand.
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
SYSTEMD_SOURCE="${REPO_ROOT}/homelab/systemd/tweets.service"
SYSTEMD_TARGET=/etc/systemd/system/tweets.service
BINARY_TARGET=/usr/local/bin/tweetsd
DATA_DIR=/srv/tweets
DOMAIN=tweets.omarss.net
TARGET_USER=omar
TARGET_GROUP=omar

for f in "$CONF_SOURCE" "$SNIPPET_SOURCE" "$SYSTEMD_SOURCE" \
         "$TWEETS_SOURCE/go.mod" "$TWEETS_SOURCE/cmd/tweetsd/main.go"; do
    if [[ ! -f "$f" ]]; then
        echo "Missing source file: $f" >&2
        exit 1
    fi
done

if ! command -v go >/dev/null 2>&1; then
    echo "Go toolchain not on PATH — install Go before re-running." >&2
    exit 1
fi

echo "==> Building tweetsd from ${TWEETS_SOURCE}"
# Build as the owning user so go's module cache stays in $HOME/.cache
# instead of polluting /root/.cache.
sudo -u "$TARGET_USER" bash -c "cd '$TWEETS_SOURCE' && go build -o /tmp/tweetsd ./cmd/tweetsd"
install -m 755 -o root -g root /tmp/tweetsd "$BINARY_TARGET"
rm -f /tmp/tweetsd

echo "==> Ensuring data dir ${DATA_DIR}"
# Mode 700 — the cookies file inside is highly sensitive. systemd's
# ReadWritePaths needs read+exec on the dir to enter; 700 against the
# omar user is sufficient because the service runs as omar.
install -d -m 700 -o "$TARGET_USER" -g "$TARGET_GROUP" "$DATA_DIR"

if [[ ! -f "$DATA_DIR/cookies.json" ]]; then
    echo "==> Seeding cookies.json placeholder"
    install -m 600 -o "$TARGET_USER" -g "$TARGET_GROUP" /dev/null "$DATA_DIR/cookies.json"
    cat >"$DATA_DIR/cookies.json" <<'EOF'
{
  "auth_token": "",
  "ct0": ""
}
EOF
    chown "${TARGET_USER}:${TARGET_GROUP}" "$DATA_DIR/cookies.json"
    chmod 600 "$DATA_DIR/cookies.json"
    SEEDED_COOKIES=1
fi

echo "==> Installing systemd unit"
install -m 644 -o root -g root "$SYSTEMD_SOURCE" "$SYSTEMD_TARGET"

echo "==> Reloading systemd"
systemctl daemon-reload

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

echo
echo "==> Done."
systemctl --no-pager status tweets.service | head -8 || true
echo
echo "Next steps:"
if [[ "${SEEDED_COOKIES:-0}" == "1" ]]; then
    echo "  1. Edit ${DATA_DIR}/cookies.json — paste your X auth_token and ct0"
    echo "     cookies (DevTools → Application → Cookies on x.com)."
    echo "     Then: sudo systemctl restart tweets.service"
fi
echo "  $( [[ "${SEEDED_COOKIES:-0}" == "1" ]] && echo 2 || echo 1 ). Re-run certbot to inject the TLS server block:"
echo "       sudo certbot --nginx -d ${DOMAIN}"
echo
echo "  Logs: sudo journalctl -u tweets.service -f"
