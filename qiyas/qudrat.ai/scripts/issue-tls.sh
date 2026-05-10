#!/usr/bin/env bash
# issue-tls.sh — request/refresh a Let's Encrypt cert for one or more
# domains via certbot's nginx plugin. Run as root.
#
# Usage:
#   sudo bash scripts/issue-tls.sh                       # default: qudrat.omarss.net
#   sudo bash scripts/issue-tls.sh qudrat.ai             # any other domain
#   sudo bash scripts/issue-tls.sh d1.example d2.example # multiple
#
# Fails loudly on any single domain failure.

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

EMAIL="${QUDRAT_LE_EMAIL:-omar.s.shaaban@gmail.com}"
DOMAINS=("$@")
if [[ ${#DOMAINS[@]} -eq 0 ]]; then
    DOMAINS=(qudrat.omarss.net)
fi

for d in "${DOMAINS[@]}"; do
    echo "==> issuing/refreshing TLS for ${d}"
    certbot --nginx -d "${d}" --non-interactive --agree-tos -m "${EMAIL}" --redirect
done

echo "done."
