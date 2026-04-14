#!/usr/bin/env bash
# Panic button — flush the PRE_GEOFENCE chain and remove its jump from
# INPUT. Reverts the host to its pre-geofence state. Safe to run at any
# time. ipset sets stay on disk so re-enabling is fast (just run
# `sudo geofence-apply`).
#
# Installed at /usr/local/sbin/geofence-disable by setup.sh.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root." >&2
    exit 1
fi

echo "==> Removing iptables jump from INPUT"
iptables  -D INPUT -j PRE_GEOFENCE 2>/dev/null || true
ip6tables -D INPUT -j PRE_GEOFENCE 2>/dev/null || true

echo "==> Flushing + removing PRE_GEOFENCE chain"
iptables  -F PRE_GEOFENCE 2>/dev/null || true
iptables  -X PRE_GEOFENCE 2>/dev/null || true
ip6tables -F PRE_GEOFENCE 2>/dev/null || true
ip6tables -X PRE_GEOFENCE 2>/dev/null || true

echo "==> Stopping geofence.service so it doesn't re-apply on next boot"
systemctl disable geofence.service 2>/dev/null || true

echo
echo "Geofence disabled."
echo "  ipset sets sa-v4 / sa-v6 left intact for fast re-enable."
echo "  Run 'sudo geofence-apply' to bring it back."
echo "  Run 'ipset destroy sa-v4 sa-v6' afterwards if you want them fully gone."
