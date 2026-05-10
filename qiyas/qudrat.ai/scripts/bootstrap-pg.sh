#!/usr/bin/env bash
# bootstrap-pg.sh — provision the host Postgres for qudrat.
#
# Idempotent: safe to re-run. Reads the DB password from the file passed
# as $1 (default: ~/.config/qudrat/db-password), creates the role + db
# if missing, ensures pg_hba.conf allows pods on 10.42.0.0/16, and
# reloads Postgres if pg_hba changed.
#
# Run as root: sudo bash scripts/bootstrap-pg.sh
#
# Output goes to stdout/stderr; nothing is echoed that would leak the
# password.

set -euo pipefail

PASS_FILE="${1:-/home/omar/.config/qudrat/db-password}"
PG_HBA="/etc/postgresql/18/main/pg_hba.conf"

if [[ "${EUID}" -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi
if [[ ! -f "${PASS_FILE}" ]]; then
    echo "password file not found: ${PASS_FILE}" >&2
    exit 1
fi
if [[ ! -f "${PG_HBA}" ]]; then
    echo "pg_hba.conf not found at ${PG_HBA}" >&2
    exit 1
fi

DB_PASS="$(cat "${PASS_FILE}")"

echo "==> ensuring role qudrat exists"
sudo -u postgres psql -v ON_ERROR_STOP=1 -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname='qudrat'" \
    | grep -q 1 || sudo -u postgres psql -v ON_ERROR_STOP=1 \
        -c "CREATE ROLE qudrat LOGIN PASSWORD '${DB_PASS}'"

echo "==> ensuring role password matches the on-disk password file"
sudo -u postgres psql -v ON_ERROR_STOP=1 \
    -c "ALTER ROLE qudrat WITH PASSWORD '${DB_PASS}'"

echo "==> ensuring database qudrat exists"
sudo -u postgres psql -v ON_ERROR_STOP=1 -tAc \
    "SELECT 1 FROM pg_database WHERE datname='qudrat'" \
    | grep -q 1 || sudo -u postgres psql -v ON_ERROR_STOP=1 \
        -c "CREATE DATABASE qudrat OWNER qudrat ENCODING 'UTF8' LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8' TEMPLATE template0"

echo "==> ensuring pg_hba.conf allows the k3s pod CIDR"
HBA_LINE='host    qudrat          qudrat          10.42.0.0/16            scram-sha-256'
if grep -qF "${HBA_LINE}" "${PG_HBA}"; then
    echo "    already present"
else
    cp "${PG_HBA}" "${PG_HBA}.bak.$(date +%s)"
    printf '\n# qudrat — k3s pods on cni0 reach Postgres via the host gateway 10.42.0.1\n%s\n' \
        "${HBA_LINE}" >> "${PG_HBA}"
    echo "    appended; reloading postgres"
    systemctl reload postgresql
fi

echo "==> verifying connection from the host"
PGPASSWORD="${DB_PASS}" psql -h 127.0.0.1 -U qudrat -d qudrat -c "SELECT 'ok' AS status" >/dev/null
echo "    OK"

echo "done."
