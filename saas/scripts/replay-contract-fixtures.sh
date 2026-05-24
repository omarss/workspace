#!/usr/bin/env bash
# Replay HTTP fixtures against a running Prism proxy and the local data-plane
# binary. Phase-2 wiring (ADR — pending) — minimal version: each .http file
# under test/fixtures/<resource>/ is parsed and replayed as a curl call;
# we assert the status line falls in 2xx. Future phases add response-shape
# assertions against the Prism mock.
#
# Usage:
#   scripts/replay-contract-fixtures.sh <base-url>
# Default base-url is the local prism-mock-dp on port 4011.
set -euo pipefail

BASE="${1:-http://localhost:4011}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

shopt -s nullglob
fixtures=( "${ROOT}"/test/fixtures/*/*.http )
if [[ ${#fixtures[@]} -eq 0 ]]; then
  echo "no fixtures found under test/fixtures/"
  exit 0
fi

failures=0
for f in "${fixtures[@]}"; do
  echo "==> replaying ${f#${ROOT}/}"
  # Parse "METHOD path HTTP/1.1" — Prism rewrites the path under BASE.
  method=$(head -n1 "$f" | awk '{print $1}')
  path=$(head -n1 "$f" | awk '{print $2}')
  # Pull headers (between line 2 and the blank line).
  headers=$(awk 'NR>1 && /^$/{exit}NR>1{print "-H";print $0}' "$f")
  # Pull body (after the blank line).
  body=$(awk 'BEGIN{p=0}p{print}/^$/{p=1}' "$f")

  args=( -sS -o /tmp/saas-fixture-body -w '%{http_code}' -X "$method" )
  while IFS= read -r line; do
    [[ -n "$line" ]] && args+=( "$line" )
  done <<<"$headers"
  if [[ -n "$body" ]]; then
    args+=( --data-binary "$body" )
  fi

  status=$(curl "${args[@]}" "${BASE}${path}") || status="000"
  echo "    status=${status}"
  if [[ "$status" =~ ^2 ]]; then
    continue
  fi
  echo "    FAIL — body:"
  sed 's/^/      /' /tmp/saas-fixture-body || true
  failures=$((failures+1))
done

if [[ $failures -gt 0 ]]; then
  echo "${failures} fixture(s) failed"
  exit 1
fi
echo "all fixtures replayed"
