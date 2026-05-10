#!/usr/bin/env bash
# load-images.sh — import qudrat container images into the host k3s
# containerd. Run as root.
#
# By default loads the api + importer images from /tmp. Pass tar paths to
# override.
#
# Run: sudo bash scripts/load-images.sh

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

TARS=("$@")
if [[ ${#TARS[@]} -eq 0 ]]; then
    TARS=(/tmp/qudrat-api.tar /tmp/qudrat-importer.tar)
fi

for tar in "${TARS[@]}"; do
    if [[ ! -f "${tar}" ]]; then
        echo "missing: ${tar}" >&2
        exit 1
    fi
    echo "==> importing ${tar}"
    k3s ctr images import "${tar}"
done

echo "done."
