#!/usr/bin/env bash
# Re-download the Saudi Arabia IPv4/IPv6 zone files and re-apply the
# geofence (atomic ipset swap inside apply.sh).
#
# Source: ipdeny.com — daily-updated, free, no auth.
# Installed at /usr/local/sbin/geofence-refresh by setup.sh and run on a
# daily systemd timer.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root." >&2
    exit 1
fi

DATA_DIR=/var/lib/geofence
V4_URL="https://www.ipdeny.com/ipblocks/data/countries/sa.zone"
V6_URL="https://www.ipdeny.com/ipblocks/data/ipv6/countries/sa.zone"

install -d -m 755 "$DATA_DIR"

echo "==> Fetching SA IPv4 ranges"
curl -fsSL --max-time 30 "$V4_URL" -o "$DATA_DIR/sa-v4.zone.new"
if [[ ! -s "$DATA_DIR/sa-v4.zone.new" ]]; then
    echo "Empty IPv4 zone download — aborting." >&2
    rm -f "$DATA_DIR/sa-v4.zone.new"
    exit 1
fi

echo "==> Fetching SA IPv6 ranges"
if curl -fsSL --max-time 30 "$V6_URL" -o "$DATA_DIR/sa-v6.zone.new"; then
    if [[ ! -s "$DATA_DIR/sa-v6.zone.new" ]]; then
        echo "    Empty IPv6 zone — keeping previous." >&2
        rm -f "$DATA_DIR/sa-v6.zone.new"
    else
        mv "$DATA_DIR/sa-v6.zone.new" "$DATA_DIR/sa-v6.zone"
    fi
else
    echo "    IPv6 fetch failed — keeping previous." >&2
    rm -f "$DATA_DIR/sa-v6.zone.new"
fi

mv "$DATA_DIR/sa-v4.zone.new" "$DATA_DIR/sa-v4.zone"
date -u -Iseconds | sed 's/+00:00/Z/' > "$DATA_DIR/last-refresh"

echo "==> Re-applying geofence"
exec /usr/local/sbin/geofence-apply
