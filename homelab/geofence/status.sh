#!/usr/bin/env bash
# Show current geofence state: chain installed?, ipset sizes, last
# refresh time, packet counters on the chain.
#
# Installed at /usr/local/sbin/geofence-status by setup.sh.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root (iptables -L requires it)." >&2
    exit 1
fi

print_section() {
    echo
    echo "=== $1 ==="
}

print_section "Chain installed?"
if iptables -L INPUT -n --line-numbers 2>/dev/null | grep -q PRE_GEOFENCE; then
    echo "iptables INPUT → PRE_GEOFENCE  ✓"
else
    echo "iptables INPUT → PRE_GEOFENCE  ✗  (geofence is OFF)"
fi
if ip6tables -L INPUT -n --line-numbers 2>/dev/null | grep -q PRE_GEOFENCE; then
    echo "ip6tables INPUT → PRE_GEOFENCE ✓"
else
    echo "ip6tables INPUT → PRE_GEOFENCE ✗  (IPv6 geofence is OFF)"
fi

print_section "ipset sa-v4"
ipset list sa-v4 -terse 2>/dev/null || echo "(set does not exist)"

print_section "ipset sa-v6"
ipset list sa-v6 -terse 2>/dev/null || echo "(set does not exist)"

print_section "PRE_GEOFENCE chain (iptables, with counters)"
iptables -L PRE_GEOFENCE -n -v 2>/dev/null || echo "(chain not installed)"

print_section "PRE_GEOFENCE chain (ip6tables, with counters)"
ip6tables -L PRE_GEOFENCE -n -v 2>/dev/null || echo "(chain not installed)"

print_section "Timestamps"
if [[ -f /var/lib/geofence/last-refresh ]]; then
    echo "Last zone refresh: $(cat /var/lib/geofence/last-refresh)"
fi
if [[ -f /var/lib/geofence/last-applied ]]; then
    echo "Last apply:        $(cat /var/lib/geofence/last-applied)"
fi

print_section "systemd units"
systemctl is-enabled geofence.service 2>&1 | sed 's/^/geofence.service:        /'
systemctl is-enabled geofence-refresh.timer 2>&1 | sed 's/^/geofence-refresh.timer:  /'
systemctl is-active geofence-refresh.timer 2>&1 | sed 's/^/geofence-refresh.timer (active): /'
