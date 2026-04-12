#!/bin/bash
# Sign NVIDIA kernel modules for Secure Boot.
# Run after kernel or driver updates:
#   sudo bash scripts/sign-nvidia.sh
set -e

KVER=$(uname -r)
SIGN=/usr/src/linux-headers-${KVER}/scripts/sign-file
KEY=/var/lib/shim-signed/mok/MOK.priv
CERT=/var/lib/shim-signed/mok/MOK.der
MODDIR=/lib/modules/${KVER}/updates/dkms

for mod in nvidia nvidia-modeset nvidia-drm nvidia-uvm nvidia-peermem; do
    echo "Signing ${mod}..."
    zstd -d "${MODDIR}/${mod}.ko.zst" -o "/tmp/${mod}.ko" --force
    ${SIGN} sha256 "${KEY}" "${CERT}" "/tmp/${mod}.ko"
    zstd "/tmp/${mod}.ko" -o "${MODDIR}/${mod}.ko.zst" --force
    rm "/tmp/${mod}.ko"
done

depmod
modprobe nvidia
echo "Done! Verify with: nvidia-smi"
