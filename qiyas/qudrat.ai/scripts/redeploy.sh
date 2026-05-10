#!/usr/bin/env bash
# redeploy.sh — full host-side redeploy for qudrat after a code change.
#
# Idempotent. Steps:
#   1. Import every /tmp/qudrat-*.tar into k3s containerd.
#   2. Reapply host nginx vhosts (homelab apply-nginx).
#   3. Re-issue TLS for qudrat.omarss.net (apply-nginx clobbers certbot).
#
# Run as root: sudo bash scripts/redeploy.sh

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOMELAB="$(cd "${REPO_ROOT}/../../homelab" && pwd)"

echo "==> [1/3] importing image tars into k3s"
shopt -s nullglob
TARS=(/tmp/qudrat-*.tar)
shopt -u nullglob
if [[ ${#TARS[@]} -eq 0 ]]; then
    echo "no /tmp/qudrat-*.tar found — skipping image import"
else
    for tar in "${TARS[@]}"; do
        echo "    ${tar}"
        k3s ctr images import "${tar}"
    done
fi

echo "==> [2/3] applying host nginx vhosts"
make -C "${HOMELAB}" apply-nginx

echo "==> [3/3] reissuing TLS for qudrat.omarss.net"
bash "${REPO_ROOT}/scripts/issue-tls.sh" qudrat.omarss.net

echo "done."
