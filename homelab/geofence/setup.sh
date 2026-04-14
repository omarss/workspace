#!/usr/bin/env bash
# One-time installer for the SA geofence.
#
# What this does:
#   1. apt-get install ipset + curl (no-op if already present)
#   2. install scripts to /usr/local/sbin/
#   3. install systemd units, reload, enable boot apply + daily refresh
#   4. download SA IPv4/IPv6 zone files into /var/lib/geofence/
#   5. run geofence-apply once (which itself pre-flights against the
#      current public IP and aborts if it would lock you out)
#
# Safe to re-run: every step is idempotent.
#
# Disable at any time:
#   sudo geofence-disable          # flush rules, keep ipset sets
#   sudo systemctl stop geofence.service
#
# Re-enable:
#   sudo geofence-apply            # or `sudo systemctl start geofence.service`
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root." >&2
    echo "Re-run with: sudo bash $0" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GEOFENCE_DIR="${REPO_ROOT}/geofence"
SYSTEMD_DIR="${REPO_ROOT}/systemd"

for f in apply.sh refresh.sh disable.sh status.sh; do
    if [[ ! -f "$GEOFENCE_DIR/$f" ]]; then
        echo "Missing: $GEOFENCE_DIR/$f" >&2
        exit 1
    fi
done

for f in geofence.service geofence-refresh.service geofence-refresh.timer; do
    if [[ ! -f "$SYSTEMD_DIR/$f" ]]; then
        echo "Missing: $SYSTEMD_DIR/$f" >&2
        exit 1
    fi
done

if ! command -v ipset >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
    echo "==> Installing ipset + curl"
    apt-get update -qq
    apt-get install -y -qq ipset curl
fi

echo "==> Installing scripts to /usr/local/sbin"
install -m 755 "$GEOFENCE_DIR/apply.sh"   /usr/local/sbin/geofence-apply
install -m 755 "$GEOFENCE_DIR/refresh.sh" /usr/local/sbin/geofence-refresh
install -m 755 "$GEOFENCE_DIR/disable.sh" /usr/local/sbin/geofence-disable
install -m 755 "$GEOFENCE_DIR/status.sh"  /usr/local/sbin/geofence-status

echo "==> Installing systemd units"
install -m 644 "$SYSTEMD_DIR/geofence.service"          /etc/systemd/system/geofence.service
install -m 644 "$SYSTEMD_DIR/geofence-refresh.service"  /etc/systemd/system/geofence-refresh.service
install -m 644 "$SYSTEMD_DIR/geofence-refresh.timer"    /etc/systemd/system/geofence-refresh.timer
systemctl daemon-reload

echo "==> Creating /var/lib/geofence"
install -d -m 755 /var/lib/geofence

# Always refresh the zone files before the first apply so we have current
# data and can pre-flight against it. geofence-refresh exec's into
# geofence-apply at the end, which does the install + pre-flight check.
echo "==> First-time refresh + apply"
/usr/local/sbin/geofence-refresh

echo "==> Enabling boot apply + daily refresh timer"
systemctl enable geofence.service
systemctl enable --now geofence-refresh.timer

echo
echo "==> Done."
echo
echo "  Status:    sudo geofence-status"
echo "  Disable:   sudo geofence-disable"
echo "  Re-enable: sudo geofence-apply"
echo "  Logs:      journalctl -u geofence.service -u geofence-refresh.service"
