#!/bin/bash
# license-scan.sh — Walk go.mod (direct + indirect) and classify the LICENSE
# file shipped in each module's pkg/mod cache against the AGENTS.md §3.5 allowlist.
#
# Why this exists: go-licenses and licenseclassifier both require either a
# root LICENSE file (which we don't ship publicly during the MVP) or a Docker
# image (which is no longer published at the expected ghcr path). The
# pkg/mod walk is reliable because module fetches are hash-verified via
# go.sum, so the upstream LICENSE bytes are guaranteed authentic.
#
# Output (stdout): one line per module — "<license-summary> <module> <version>".
# A summary of "UNKNOWN" / "NOLICENSE" / "MISSING" means manual review required.
#
# Exit code: 0 — informational only. Combine with grep on the disallowlist
# for a hard-fail gate (see docs/plans/mvp/_verification/license-scan.md).
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GOMOD="${REPO_ROOT}/go.mod"
CACHE="${GOPATH:-$HOME/go}/pkg/mod"
if [[ -n "${SAAS_GO_PKG_CACHE:-}" ]]; then
  CACHE="${SAAS_GO_PKG_CACHE}"
fi
# Project-local cache used by the Makefile docker runs.
if [[ ! -d "$CACHE" && -d "/home/omar/.cache/saas-go-pkg/mod" ]]; then
  CACHE="/home/omar/.cache/saas-go-pkg/mod"
fi

if [[ ! -f "$GOMOD" ]]; then
  echo "license-scan: go.mod not found at $GOMOD" >&2
  exit 2
fi
if [[ ! -d "$CACHE" ]]; then
  echo "license-scan: module cache not found at $CACHE" >&2
  echo "license-scan: run 'go mod download' first or set SAAS_GO_PKG_CACHE" >&2
  exit 2
fi

grep -E "^\s+[a-z0-9./_-]+\s+v" "$GOMOD" | sed -E 's|//.*||' | awk '{print $1" "$2}' | sort -u | \
while read mod ver; do
  dir="$CACHE/$mod@$ver"
  if [[ ! -d "$dir" ]]; then
    # Module paths with uppercase letters are case-encoded as !<lower>.
    enc=$(echo "$mod" | sed 's/\([A-Z]\)/!\L\1/g')
    dir="$CACHE/$enc@$ver"
  fi
  if [[ ! -d "$dir" ]]; then
    echo "MISSING $mod $ver"
    continue
  fi
  lic=$(ls "$dir" 2>/dev/null | grep -iE '^(LICEN[SC]E|COPYING|NOTICE)' | head -1)
  if [[ -z "$lic" ]]; then
    echo "NOLICENSE $mod $ver"
    continue
  fi
  body=$(head -30 "$dir/$lic" | tr -d '\r')
  summary="UNKNOWN"
  if echo "$body" | grep -qi "Apache License"; then summary="Apache-2.0"
  elif echo "$body" | grep -qi "MIT License"; then summary="MIT"
  elif echo "$body" | grep -qiE "Permission is hereby granted, free of charge"; then summary="MIT"
  elif echo "$body" | grep -qiE "Redistribution and use in source and binary forms" && echo "$body" | grep -qiE "Neither the name"; then summary="BSD-3-Clause"
  elif echo "$body" | grep -qiE "Redistribution and use in source and binary forms"; then summary="BSD-2-Clause"
  elif echo "$body" | grep -qiE "Mozilla Public License"; then summary="MPL-2.0"
  elif echo "$body" | grep -qiE "ISC License"; then summary="ISC"
  elif echo "$body" | grep -qiE "PostgreSQL License"; then summary="PostgreSQL"
  elif echo "$body" | grep -qiE "GNU Lesser General Public License"; then summary="LGPL"
  elif echo "$body" | grep -qiE "GNU General Public License"; then summary="GPL"
  elif echo "$body" | grep -qiE "GNU Affero General Public"; then summary="AGPL"
  elif echo "$body" | grep -qiE "Business Source License"; then summary="BSL"
  elif echo "$body" | grep -qiE "Server Side Public License"; then summary="SSPL"
  elif echo "$body" | grep -qiE "Elastic License"; then summary="Elastic"
  elif echo "$body" | grep -qiE "BlueOak"; then summary="BlueOak-1.0.0"
  elif echo "$body" | grep -qiE "BSD Zero Clause"; then summary="0BSD"
  elif echo "$body" | grep -qiE "Permission is granted to anyone to use this software"; then summary="Zlib"
  fi
  echo "$summary $mod $ver"
done
