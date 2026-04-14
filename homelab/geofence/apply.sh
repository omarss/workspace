#!/usr/bin/env bash
# Load Saudi Arabia IPv4/IPv6 ranges from disk into ipset, then install
# the PRE_GEOFENCE chain into iptables/ip6tables. Idempotent.
#
# Reads:
#   /var/lib/geofence/sa-v4.zone
#   /var/lib/geofence/sa-v6.zone
#
# Pre-flight: tests the current public IPv4/IPv6 against the new set
# BEFORE inserting the INPUT jump. If the host's own public IP isn't in
# the SA range, the script aborts without modifying any live rules — so
# running this can never lock you out from the IP you're on right now.
#
# Always-allowed (regardless of source country):
#   - loopback (lo)
#   - established / related connections (existing flows survive)
#   - tailscale interface
#   - 100.64.0.0/10 (Tailscale CGNAT range)
#   - RFC1918 private (10/8, 172.16/12, 192.168/16) — LAN access
#   - tcp/80 globally — Let's Encrypt ACME challenge
#   - IPv6: ICMPv6, link-local, multicast destinations
#
# Installed at /usr/local/sbin/geofence-apply by setup.sh.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "This script needs root." >&2
    exit 1
fi

V4_ZONE=/var/lib/geofence/sa-v4.zone
V6_ZONE=/var/lib/geofence/sa-v6.zone

if [[ ! -s "$V4_ZONE" ]]; then
    echo "Missing or empty $V4_ZONE — run geofence-refresh first." >&2
    exit 1
fi

have_v6=true
if [[ ! -s "$V6_ZONE" ]]; then
    echo "Note: $V6_ZONE missing — IPv6 geofence will not be applied." >&2
    have_v6=false
fi

# ── Build new sets ───────────────────────────────────────────────────────
echo "==> Building ipset sa-v4 from $V4_ZONE"
ipset create sa-v4 hash:net family inet maxelem 131072 -exist
ipset create sa-v4-new hash:net family inet maxelem 131072 -exist
ipset flush sa-v4-new
count_v4=0
while IFS= read -r cidr; do
    [[ -z "$cidr" || "$cidr" =~ ^# ]] && continue
    ipset add sa-v4-new "$cidr" -exist
    count_v4=$((count_v4 + 1))
done < "$V4_ZONE"
echo "    loaded $count_v4 IPv4 ranges"

if $have_v6; then
    echo "==> Building ipset sa-v6 from $V6_ZONE"
    ipset create sa-v6 hash:net family inet6 maxelem 131072 -exist
    ipset create sa-v6-new hash:net family inet6 maxelem 131072 -exist
    ipset flush sa-v6-new
    count_v6=0
    while IFS= read -r cidr; do
        [[ -z "$cidr" || "$cidr" =~ ^# ]] && continue
        ipset add sa-v6-new "$cidr" -exist
        count_v6=$((count_v6 + 1))
    done < "$V6_ZONE"
    echo "    loaded $count_v6 IPv6 ranges"
fi

# ── Pre-flight: refuse to lock out the current public IP ────────────────
echo "==> Pre-flight: checking this host's public IP"
PUBLIC_V4=$(curl -s -4 --max-time 8 https://ifconfig.me 2>/dev/null || true)
PUBLIC_V6=$(curl -s -6 --max-time 8 https://ifconfig.me 2>/dev/null || true)

if [[ -n "$PUBLIC_V4" ]]; then
    if ipset test sa-v4-new "$PUBLIC_V4" 2>/dev/null; then
        echo "    IPv4 $PUBLIC_V4 ✓ in SA range"
    else
        echo "REFUSING: public IPv4 $PUBLIC_V4 is NOT in the SA range." >&2
        echo "Applying the geofence right now would lock this host out via clearnet." >&2
        echo "Tailscale would still work, but stopping here is safer." >&2
        ipset destroy sa-v4-new
        $have_v6 && ipset destroy sa-v6-new
        exit 2
    fi
else
    echo "    IPv4: no public address (skipping check)"
fi

if [[ -n "$PUBLIC_V6" ]] && $have_v6; then
    if ipset test sa-v6-new "$PUBLIC_V6" 2>/dev/null; then
        echo "    IPv6 $PUBLIC_V6 ✓ in SA range"
    else
        echo "REFUSING: public IPv6 $PUBLIC_V6 is NOT in the SA range." >&2
        ipset destroy sa-v4-new
        ipset destroy sa-v6-new
        exit 2
    fi
fi

# ── Atomic swap ─────────────────────────────────────────────────────────
echo "==> Swapping ipset contents into live sets"
ipset swap sa-v4-new sa-v4
ipset destroy sa-v4-new
if $have_v6; then
    ipset swap sa-v6-new sa-v6
    ipset destroy sa-v6-new
fi

# ── PRE_GEOFENCE chain (IPv4) ───────────────────────────────────────────
echo "==> Installing PRE_GEOFENCE chain (iptables)"
iptables -N PRE_GEOFENCE 2>/dev/null || iptables -F PRE_GEOFENCE
iptables -A PRE_GEOFENCE -i lo -j RETURN
iptables -A PRE_GEOFENCE -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A PRE_GEOFENCE -i tailscale0 -j RETURN 2>/dev/null || true
iptables -A PRE_GEOFENCE -s 100.64.0.0/10 -j RETURN
iptables -A PRE_GEOFENCE -s 10.0.0.0/8 -j RETURN
iptables -A PRE_GEOFENCE -s 172.16.0.0/12 -j RETURN
iptables -A PRE_GEOFENCE -s 192.168.0.0/16 -j RETURN
iptables -A PRE_GEOFENCE -p tcp --dport 80 -j RETURN
iptables -A PRE_GEOFENCE -m set --match-set sa-v4 src -j RETURN
iptables -A PRE_GEOFENCE -j DROP

# Insert jump at position 1, idempotently.
iptables -D INPUT -j PRE_GEOFENCE 2>/dev/null || true
iptables -I INPUT 1 -j PRE_GEOFENCE

# ── PRE_GEOFENCE chain (IPv6) ───────────────────────────────────────────
if $have_v6; then
    echo "==> Installing PRE_GEOFENCE chain (ip6tables)"
    ip6tables -N PRE_GEOFENCE 2>/dev/null || ip6tables -F PRE_GEOFENCE
    ip6tables -A PRE_GEOFENCE -i lo -j RETURN
    ip6tables -A PRE_GEOFENCE -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
    # ICMPv6 is required for NDP / PMTU; never block.
    ip6tables -A PRE_GEOFENCE -p ipv6-icmp -j RETURN
    # Link-local + multicast destinations stay open.
    ip6tables -A PRE_GEOFENCE -s fe80::/10 -j RETURN
    ip6tables -A PRE_GEOFENCE -d ff00::/8 -j RETURN
    ip6tables -A PRE_GEOFENCE -i tailscale0 -j RETURN 2>/dev/null || true
    ip6tables -A PRE_GEOFENCE -p tcp --dport 80 -j RETURN
    ip6tables -A PRE_GEOFENCE -m set --match-set sa-v6 src -j RETURN
    ip6tables -A PRE_GEOFENCE -j DROP

    ip6tables -D INPUT -j PRE_GEOFENCE 2>/dev/null || true
    ip6tables -I INPUT 1 -j PRE_GEOFENCE
fi

date -u -Iseconds | sed 's/+00:00/Z/' > /var/lib/geofence/last-applied
echo "==> Geofence applied."
