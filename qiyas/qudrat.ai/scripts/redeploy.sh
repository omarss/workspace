#!/usr/bin/env bash
# redeploy.sh — host-side (sudo-required) redeploy steps for qudrat.
#
# Scope: only the parts that need root. The kubectl pod-replace step lives
# in the Makefile so it runs under the invoking user's kubeconfig (this
# script is exec'd via sudo, and `sudo -u $SUDO_USER kubectl` was unreliable
# in practice — silent failures left pods on the old image).
#
# Idempotent. Steps:
#   1. Import every /tmp/qudrat-*.tar into k3s containerd, removing any
#      cached :dev tag first so containerd actually picks up the new digest.
#   2. Reapply host nginx vhosts (homelab apply-nginx) and snippets.
#   3. Re-issue TLS for qudrat.omarss.net (apply-nginx clobbers certbot).
#
# Run as root: sudo bash scripts/redeploy.sh
# (or invoke `make redeploy` / `make redeploy-quick` from the repo root,
#  which also runs the kubectl pod-replace afterward)

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
        # Derive the image name from the tar filename: qudrat-web.tar →
        # localhost/qudrat/web:dev. Then explicitly remove the old tag
        # from containerd before re-importing — `k3s ctr images import`
        # does NOT repoint an existing tag at a new digest, so pods would
        # otherwise keep resolving to the cached old image even after a
        # pod delete.
        base=$(basename "${tar}" .tar)            # qudrat-web
        svc=${base#qudrat-}                       # web
        ref="localhost/qudrat/${svc}:dev"
        echo "    ${tar} → ${ref}"
        k3s ctr images rm "${ref}" >/dev/null 2>&1 || true
        k3s ctr images import "${tar}"
    done
fi

echo "==> [2/3] applying host nginx vhosts"
make -C "${HOMELAB}" apply-nginx

echo "==> [3/3] reissuing TLS for qudrat.omarss.net"
bash "${REPO_ROOT}/scripts/issue-tls.sh" qudrat.omarss.net

echo "done. (pod replacement handled by the calling Makefile target)"
