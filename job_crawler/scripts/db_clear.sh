#!/usr/bin/env bash
# Wipe crawler data from the live database. Two tiers:
#
#   crawl       (default)  Truncate all posting / cluster / crawl-run data.
#                          Preserves: companies, source_profiles, sources,
#                          skills, synonyms, regions, cities,
#                          countries, industries, job_categories, crawler_health.
#
#   all                    Also wipes companies + source_profiles +
#                          recruiters. Keeps the reference taxonomies
#                          (countries / cities / industries / skills /
#                          synonyms) so reseeding stays fast.
#
# Schema is never dropped; rerun is idempotent.
#
# Usage:
#     scripts/db_clear.sh crawl --confirm
#     scripts/db_clear.sh all --confirm
#
# Without --confirm prints the row counts that would be wiped and exits.
set -euo pipefail

MODE="${1:-crawl}"
CONFIRM="${2:-}"

if [[ "$MODE" != "crawl" && "$MODE" != "all" ]]; then
    echo "usage: $0 {crawl|all} [--confirm]" >&2
    exit 2
fi

cd "$(dirname "$0")/.."
if [[ -f .env ]]; then
    set -a
    . ./.env
    set +a
fi
if [[ -z "${JC_DB_PASSWORD:-}" ]]; then
    echo "JC_DB_PASSWORD not set — run from the project root with .env present" >&2
    exit 3
fi

PSQL=(env PGPASSWORD="$JC_DB_PASSWORD" psql
      -U job_crawler -h 127.0.0.1 -d job_crawler
      -v ON_ERROR_STOP=1 -X -tA)

if [[ "$MODE" == "crawl" ]]; then
    TABLES=(
        # posting-level + cluster + linkage
        job_skills
        posting_skills_raw
        posting_snapshots
        application_channels
        posting_duplicate_edges
        job_fake_signals
        job_locations
        # clusters first then postings so FK cascade is well-defined
        jobs
        job_postings
        # crawl trail
        crawl_fetches
        crawl_runs
        # source-health flags (regenerated on next run)
        crawler_health
    )
else
    TABLES=(
        # Everything in `crawl` PLUS:
        job_skills
        posting_skills_raw
        posting_snapshots
        application_channels
        posting_duplicate_edges
        job_fake_signals
        job_locations
        jobs
        job_postings
        crawl_fetches
        crawl_runs
        crawler_health
        # Entity layer
        company_aliases
        company_source_profiles
        recruiters
        companies
    )
fi

echo "=== rows to wipe in mode='$MODE' ==="
for tbl in "${TABLES[@]}"; do
    n=$("${PSQL[@]}" -c "SELECT COUNT(*) FROM ${tbl};") || n="?"
    printf "  %-28s %s\n" "$tbl" "$n"
done

if [[ "$CONFIRM" != "--confirm" ]]; then
    echo
    echo "DRY-RUN — pass --confirm to actually truncate."
    exit 0
fi

echo
echo "TRUNCATING (cascade, restart identity)..."
# Single statement with CASCADE so we don't fight FK order. RESTART IDENTITY
# resets any sequences (irrelevant for uuidv7 but harmless).
TBL_LIST=$(IFS=,; echo "${TABLES[*]}")
"${PSQL[@]}" -c "TRUNCATE ${TBL_LIST} RESTART IDENTITY CASCADE;"
echo "done. verifying:"
for tbl in "${TABLES[@]}"; do
    n=$("${PSQL[@]}" -c "SELECT COUNT(*) FROM ${tbl};")
    if [[ "$n" != "0" ]]; then
        echo "  WARNING: $tbl still has $n rows" >&2
    fi
done
echo "all clear."
