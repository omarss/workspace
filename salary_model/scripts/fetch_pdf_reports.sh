#!/usr/bin/env bash
# scripts/fetch_pdf_reports.sh
#
# Downloads the latest publicly available PDF reports we know to be useful for the
# salary model. PDFs land under data/reports/<source>/<year>/<filename>.pdf; existing
# files are skipped (idempotent). Per the "data, not assumptions" rule, the report
# manifest written at the end records URL, sha256, fetched_at for each successful
# download. Failed (e.g. gated) downloads also land in the manifest as status="failed"
# so a human can fall back to manual download for those.
#
# Usage: scripts/fetch_pdf_reports.sh [--force]
#
# Env overrides:
#   USER_AGENT  — browser UA string (default: realistic Chrome on Linux)
#   TIMEOUT_S   — per-download timeout in seconds (default: 45)
#   PARALLEL    — number of concurrent downloads (default: 4)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/data/reports"
MANIFEST="${OUT_DIR}/manifest.jsonl"
FORCE=0

USER_AGENT="${USER_AGENT:-Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36}"
TIMEOUT_S="${TIMEOUT_S:-45}"
PARALLEL="${PARALLEL:-4}"

mkdir -p "${OUT_DIR}"

for arg in "$@"; do
    case "${arg}" in
        --force) FORCE=1 ;;
        -h|--help)
            sed -n '1,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown arg: ${arg}" >&2; exit 2 ;;
    esac
done

# ── Source registry ──────────────────────────────────────────────────────────
# Format: source|year|filename|url
# Pipe-separated because tabs were unreliable through xargs; '|' is forbidden in
# URLs so it's safe as a separator.
# Direct PDFs only. Gated/form-download reports (Hays, Cooper Fitch, Robert Walters,
# Michael Page) are NOT here because their URLs return a form page, not a PDF; see
# scripts/manual_download_targets.md for the full curated list of gated sources to
# download manually into data/reports/<source>/.
REGISTRY=$(cat <<'EOF'
hrdf|2019|hrdf_annual_report_2019_en.pdf|https://www.hrdf.org.sa/media/bfuapclq/hrdf_annual_report_2019_-english.pdf
hrdf|2018|hrdf_annual_report_2018_ar.pdf|https://www.hrdf.org.sa/media/Annual%20report/HRDF_Annual_Report_2018_(Arabic).pdf
hrdf|2021|hrdf_quarterly_q1_2021.pdf|https://www.hrdf.org.sa/media/ilznqojn/first-quarterly-report-2021.pdf
hrdf|2020|hrdf_media_report_2020.pdf|https://www.hrdf.org.sa/media/inrppjhy/media-report-2020.pdf
hrdf|2023|hrdf_programs_individuals_2023.pdf|https://www.hrdf.org.sa/media/PDF/program-guide-for-individuals-2023.pdf
hrsd|2023|hrsd_nitaqat_mutawar_e2021.pdf|https://www.hrsd.gov.sa/sites/default/files/2023-06/E20210523.pdf
gastat|2025|gastat_labor_market_q2_2025.pdf|https://www.stats.gov.sa/documents/20117/2435273/LMS+Q2_2025_EN.pdf
gastat|2024|gastat_healthcare_workforce_2024.pdf|https://www.stats.gov.sa/documents/20117/2435273/Healthcare+Establishments+and+Workforce+Statistics+Publication+2024+EN+(1).pdf
mof|2026|mof_budget_statement_2026_en.pdf|https://www.mof.gov.sa/en/budget/2026/BudgetStatementDocs/Eng_2026.pdf
vision2030|2025|vision2030_annual_report_2025_en.pdf|https://www.vision2030.gov.sa/media/ecdjfopq/vision2030_annual_report_2025_en.pdf
worldbank|2026|wb_ksa_decade_of_progress.pdf|https://documents1.worldbank.org/curated/en/099012226144031210/pdf/P179647-b378ec18-7e40-488a-8327-0cc6f6c5dd18.pdf
sabic|2024|sabic_integrated_annual_2024_en.pdf|https://www.sabic.com/en/Images/SABIC-Integrated-Annual-Report-2024-EN_tcm1010-46870.pdf
kornferry|2025|workforce_saudi_2025.pdf|https://www.kornferry.com/content/dam/kornferry-v2/featured-topics/pdf/workforce-saudi-2025.pdf
EOF
)

# ── Worker function (subshell-safe) ──────────────────────────────────────────
fetch_one() {
    local source="$1" year="$2" filename="$3" url="$4"
    local dir="${OUT_DIR}/${source}/${year}"
    local out="${dir}/${filename}"

    mkdir -p "${dir}"

    if [[ "${FORCE}" -ne 1 && -f "${out}" && -s "${out}" ]]; then
        echo "[skip] ${source}/${year}/${filename} (already present)"
        return 0
    fi

    local tmp="${out}.partial"
    local status="failed"
    local size_bytes=0
    local sha=""

    if curl -fsSL \
            --max-time "${TIMEOUT_S}" \
            -A "${USER_AGENT}" \
            -H "Accept: application/pdf,*/*" \
            -o "${tmp}" \
            "${url}"
    then
        mv "${tmp}" "${out}"
        size_bytes=$(stat -c%s "${out}")
        sha=$(sha256sum "${out}" | awk '{print $1}')
        status="ok"
        echo "[ok]   ${source}/${year}/${filename} (${size_bytes} bytes)"
    else
        rm -f "${tmp}"
        echo "[fail] ${source}/${year}/${filename}  <- ${url}" >&2
    fi

    printf '{"source":"%s","year":"%s","filename":"%s","url":"%s","status":"%s","size_bytes":%s,"sha256":"%s","fetched_at":"%s"}\n' \
        "${source}" "${year}" "${filename}" "${url}" "${status}" "${size_bytes}" "${sha}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        >> "${MANIFEST}"
}

# ── Drive the registry sequentially (PARALLEL kept for forward-compat) ──────
# Sequential keeps shell escaping sane; 13 PDFs at curl-default-speed land in < 60s.
# When the list grows past ~50 entries, swap to GNU parallel + a temp-file dispatch.
echo "Fetching report PDFs to ${OUT_DIR}"
echo "${REGISTRY}" | grep -v '^$' | while IFS='|' read -r src yr fn url; do
    fetch_one "${src}" "${yr}" "${fn}" "${url}" || true
done

echo
echo "Manifest: ${MANIFEST}"
if [[ -f "${MANIFEST}" ]]; then
    ok_count=$(grep -c '"status":"ok"' "${MANIFEST}" || true)
    fail_count=$(grep -c '"status":"failed"' "${MANIFEST}" || true)
    echo "Successful downloads recorded: ${ok_count}"
    echo "Failed downloads recorded:     ${fail_count}"
    echo "(See data/reports/manual_download_targets.md for gated reports to fetch by hand.)"
fi
