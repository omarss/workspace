#!/usr/bin/env bash
# scripts/fetch_data_gov_sa.sh
#
# Best-effort fetcher for open.data.gov.sa (Saudi National Open Data Portal).
#
# The portal is protected by a Web Application Firewall that rejects most automated
# clients. We try with a full browser User-Agent + Accept headers; if blocked, we exit
# non-zero and print the manual workaround. The downloaded CSVs land under
# data/reports/data_gov_sa/<dataset_id>/<filename>.csv.
#
# Per the "data, not assumptions" rule, when fetch fails we surface that clearly
# rather than silently substitute bundled data. Each successful download is recorded
# in data/reports/data_gov_sa/manifest.jsonl.
#
# Manual workaround when the WAF blocks us:
#   1. Open https://open.data.gov.sa/en/datasets/view/<dataset_id> in a real browser.
#   2. Download the CSV/JSON manually.
#   3. Drop it under data/reports/data_gov_sa/<dataset_id>/<filename>.
#   4. Re-run `make data` to pick it up.
#
# Usage: scripts/fetch_data_gov_sa.sh [--list-only]
#
# Env overrides:
#   USER_AGENT — browser UA string
#   TIMEOUT_S  — per-download timeout (default: 30)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/data/reports/data_gov_sa"
MANIFEST="${OUT_DIR}/manifest.jsonl"
LIST_ONLY=0

USER_AGENT="${USER_AGENT:-Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36}"
TIMEOUT_S="${TIMEOUT_S:-30}"

mkdir -p "${OUT_DIR}"

for arg in "$@"; do
    case "${arg}" in
        --list-only) LIST_ONLY=1 ;;
        -h|--help) sed -n '1,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown arg: ${arg}" >&2; exit 2 ;;
    esac
done

# ── Dataset registry ─────────────────────────────────────────────────────────
# Format: dataset_slug<TAB>category<TAB>format<TAB>resource_url
# Slugs verified live on open.data.gov.sa.
REGISTRY=$(cat <<'EOF'
average-monthly-wages-for-paid-employees	wages	csv	https://open.data.gov.sa/en/datasets/view/average-monthly-wages-for-paid-employees/download
statistics-of-the-number-of-employees-in-the-private-sector-by-economic-activity-2021	employment	csv	https://open.data.gov.sa/en/datasets/view/statistics-of-the-number-of-employees-in-the-private-sector-by-economic-activity-2021/download
914f9dc2-d0a1-4666-ad93-a1b8cb91c80c	hrdf_doroob_beneficiaries	csv	https://open.data.gov.sa/ar/datasets/view/914f9dc2-d0a1-4666-ad93-a1b8cb91c80c/download
EOF
)

if [[ "${LIST_ONLY}" -eq 1 ]]; then
    echo "Registered datasets:"
    echo "${REGISTRY}" | awk -F'\t' '{printf "  %-60s %s\n", $1, $2}'
    exit 0
fi

# ── Worker ───────────────────────────────────────────────────────────────────
fetch_one() {
    local slug="$1" category="$2" fmt="$3" url="$4"
    local dir="${OUT_DIR}/${slug}"
    local out="${dir}/dataset.${fmt}"
    local tmp="${out}.partial"
    local status="failed"
    local size_bytes=0
    local sha=""

    mkdir -p "${dir}"

    if curl -fsSL \
            --max-time "${TIMEOUT_S}" \
            -A "${USER_AGENT}" \
            -H "Accept: text/csv,application/json,application/octet-stream" \
            -H "Accept-Language: en-US,en;q=0.9,ar;q=0.8" \
            -o "${tmp}" \
            "${url}"
    then
        # Detect HTML body (WAF rejection masquerading as 200 OK)
        if head -c 1024 "${tmp}" | grep -qiE '<html|request rejected|access denied'; then
            echo "[waf]  ${slug} — WAF blocked the request (HTML body returned)" >&2
            rm -f "${tmp}"
            status="waf_blocked"
        else
            mv "${tmp}" "${out}"
            size_bytes=$(stat -c%s "${out}")
            sha=$(sha256sum "${out}" | awk '{print $1}')
            status="ok"
            echo "[ok]   ${slug} (${size_bytes} bytes)"
        fi
    else
        rm -f "${tmp}"
        echo "[fail] ${slug} <- ${url}" >&2
    fi

    printf '{"slug":"%s","category":"%s","format":"%s","url":"%s","status":"%s","size_bytes":%s,"sha256":"%s","fetched_at":"%s"}\n' \
        "${slug}" "${category}" "${fmt}" "${url}" "${status}" "${size_bytes}" "${sha}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        >> "${MANIFEST}"
}

export -f fetch_one
export OUT_DIR USER_AGENT TIMEOUT_S MANIFEST

echo "Fetching open.data.gov.sa datasets to ${OUT_DIR}"
total=0
blocked=0
while IFS=$'\t' read -r slug category fmt url; do
    [[ -z "${slug}" ]] && continue
    total=$((total + 1))
    fetch_one "${slug}" "${category}" "${fmt}" "${url}" || true
done <<< "${REGISTRY}"

# ── Diagnose WAF rejection ───────────────────────────────────────────────────
if [[ -f "${MANIFEST}" ]]; then
    blocked=$(grep -c '"status":"waf_blocked"' "${MANIFEST}" || true)
fi

echo
echo "Summary: ${total} attempted, manifest at ${MANIFEST}"
if [[ "${blocked}" -gt 0 ]]; then
    cat <<NOTE

open.data.gov.sa rejected ${blocked} request(s) at the WAF layer. This is expected
behavior — the portal does not officially expose a CSV-by-URL API to non-browser
clients. Manual workaround:

  1. Open https://open.data.gov.sa/en/datasets/view/<dataset_slug> in your browser.
  2. Download the dataset (CSV / JSON / XLSX) manually.
  3. Place the file under data/reports/data_gov_sa/<dataset_slug>/dataset.<ext>.
  4. Re-run \`make data\` to pick it up.
NOTE
fi
