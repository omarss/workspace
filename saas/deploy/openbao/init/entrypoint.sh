#!/bin/sh
# OpenBao container entrypoint for the local-dev / homelab MVP.
#
# Responsibilities:
#   1. Launch `bao server` against the file backend.
#   2. On first boot, initialise the cluster (Shamir 5-of-3) and store the
#      generated shares + root token under /openbao/secrets (tmpfs, mode 0700).
#   3. Unseal using the first 3 shares.
#   4. Hand control to `bao server` in the foreground.
#
# Idempotency:
#   - If /openbao/secrets/init.json already exists, the init step is skipped.
#   - The unseal step is skipped when `bao status` reports Sealed=false.
#   - The script is safe to re-run on a restarted container, but note that the
#     tmpfs share file is destroyed on container shutdown — a cold boot of an
#     existing data volume requires manual share entry (operator runbook). See
#     ADR 006 for the trade-off.
#
# Production:
#   This script is DEV-ONLY. The production stack uses cloud KMS auto-unseal
#   and never touches a tmpfs share file.
set -eu

CONFIG_PATH="/openbao/config/openbao.hcl"
SECRETS_DIR="/openbao/secrets"
INIT_FILE="${SECRETS_DIR}/init.json"
LOGS_DIR="/openbao/logs"

# Ensure target directories exist + are writable by the bao user.
mkdir -p "${SECRETS_DIR}" "${LOGS_DIR}"

# Launch bao in the background; the parent shell handles bootstrap.
bao server -config="${CONFIG_PATH}" &
BAO_PID=$!

export BAO_ADDR="http://127.0.0.1:8200"

# Wait until the API is reachable. The health endpoint returns:
#   200 — initialised + unsealed
#   429 — standby (we standby-ok)
#   472 — disaster recovery mode (unused locally)
#   501 — not initialised
#   503 — sealed
# Any non-curl error means the listener isn't up yet.
wait_for_api() {
  i=0
  while [ "$i" -lt 60 ]; do
    if wget -qO- "${BAO_ADDR}/v1/sys/health?standbyok=true&uninitcode=200&sealedcode=200" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  echo "openbao: listener never came up" >&2
  return 1
}

wait_for_api

# --- Initialise ----------------------------------------------------------------
# `bao operator init` returns 200 with the unseal keys + root token the first
# time and 400 on subsequent runs. We only write the share file if init
# actually returned new shares; otherwise we assume an earlier boot did it.
if ! [ -f "${INIT_FILE}" ]; then
  if bao status -format=json 2>/dev/null | grep -q '"initialized":[[:space:]]*true'; then
    echo "openbao: already initialised but no share file present — this is a stuck state."
    echo "openbao: refusing to init a second time (would lose existing data)."
    echo "openbao: drop the openbao-data volume to start fresh, or restore the share file."
    # We do NOT exit so the operator can attach and recover.
  else
    echo "openbao: running first-time init (key-shares=5, key-threshold=3)"
    bao operator init -format=json -key-shares=5 -key-threshold=3 > "${INIT_FILE}.tmp"
    mv "${INIT_FILE}.tmp" "${INIT_FILE}"
    chmod 0400 "${INIT_FILE}"
  fi
fi

# --- Unseal --------------------------------------------------------------------
# Read 3 shares from the JSON. The image ships only awk/sed/grep (no jq), so
# we use a flat regex extractor: pull every base64 share from the
# "unseal_keys_b64" array. The array is emitted on a single line by `bao
# operator init -format=json` so this approach is robust regardless of
# external pretty-printing.
extract_shares() {
  # bao operator init -format=json emits a pretty-printed file (one key per
  # line), so we flatten newlines to spaces first. Then:
  # 1. grep the unseal_keys_b64 array.
  # 2. strip everything up to the array open bracket and after the close.
  # 3. translate commas to newlines (busybox sed doesn't expand \n, so tr).
  # 4. trim quotes / whitespace, drop empty lines.
  tr '\n' ' ' < "${INIT_FILE}" \
    | grep -o '"unseal_keys_b64"[[:space:]]*:[[:space:]]*\[[^]]*\]' \
    | sed -e 's/.*\[//' -e 's/\].*//' \
    | tr ',' '\n' \
    | sed -e 's/["[:space:]]//g' \
    | grep -v '^$'
}

unseal_if_sealed() {
  if ! [ -f "${INIT_FILE}" ]; then
    echo "openbao: no init file; cannot unseal automatically"
    return 0
  fi
  if bao status -format=json 2>/dev/null | grep -q '"sealed":[[:space:]]*false'; then
    return 0
  fi
  echo "openbao: unsealing with 3 shares"
  # Use a tempfile rather than a subshell pipe so the while loop's counter
  # persists in the parent shell.
  tmp=$(mktemp)
  extract_shares > "$tmp"
  i=0
  while IFS= read -r key; do
    if [ -z "$key" ]; then continue; fi
    if [ "$i" -ge 3 ]; then break; fi
    bao operator unseal "$key" >/dev/null
    i=$((i + 1))
  done < "$tmp"
  rm -f "$tmp"
}

unseal_if_sealed

# Re-check we made it out of the sealed state. If we didn't, bail loudly so
# Docker restarts the container.
if bao status -format=json 2>/dev/null | grep -q '"sealed":[[:space:]]*true'; then
  echo "openbao: still sealed after unseal attempt; aborting" >&2
  kill "${BAO_PID}" 2>/dev/null || true
  exit 1
fi

echo "openbao: ready"

# Hand off to bao server (it's running as PID ${BAO_PID}). `wait` blocks until
# bao exits, which is the signal Docker uses to recycle the container.
wait "${BAO_PID}"
