#!/usr/bin/env bash
# bootstrap-host.sh — full host-side provisioning for qudrat.
#
# Idempotent. Runs three steps:
#   1. provision Postgres role+db and pg_hba (delegates to bootstrap-pg.sh)
#   2. copy and reload host nginx vhosts (homelab apply-nginx)
#   3. issue/refresh TLS for qudrat.omarss.net AND every other vhost the
#      apply-nginx step touches (the apply clobbers existing 443 blocks)
#
# Run as root: sudo bash scripts/bootstrap-host.sh

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOMELAB="$(cd "${REPO_ROOT}/../../homelab" && pwd)"
EMAIL="${QUDRAT_LE_EMAIL:-omar.s.shaaban@gmail.com}"

echo "==> [1/3] provisioning postgres"
bash "${REPO_ROOT}/scripts/bootstrap-pg.sh"

echo "==> [2/3] applying host nginx vhosts"
make -C "${HOMELAB}" apply-nginx

echo "==> [3/3] issuing/refreshing TLS"
# qudrat is the new vhost; the others were touched by apply-nginx and need
# a re-run so certbot re-injects their 443 blocks (this is a known gotcha
# in homelab/CLAUDE.md — apply-nginx wipes certbot's edits).
for d in qudrat.omarss.net claw.omarss.net swet.omarss.net sync.omarss.net apps.omarss.net api.omarss.net; do
    if ! certbot --nginx -d "${d}" --non-interactive --agree-tos -m "${EMAIL}" --redirect 2>&1 \
        | grep -E "Successfully (received|deployed)|Certificate not yet due|no action|did nothing" -q; then
        echo "  -- certbot warning for ${d} (continuing; re-run manually if needed)"
    fi
done

echo "done."
