#!/bin/bash
# Backup PostgreSQL, MongoDB, and CouchDB to Dropbox.
# Keeps the last 7 daily backups.
# Usage: bash scripts/backup-databases.sh
#   or via cron: 0 3 * * * /home/omar/workspace_personal/homelab/scripts/backup-databases.sh
set -euo pipefail

BACKUP_DIR="$HOME/Dropbox/Backups/databases"
DATE=$(date +%Y-%m-%d_%H%M)
RETAIN_DAYS=7

mkdir -p "$BACKUP_DIR"

# PostgreSQL — dump all databases
echo "[$(date)] Backing up PostgreSQL..."
sudo -u postgres pg_dumpall | gzip > "$BACKUP_DIR/postgres_${DATE}.sql.gz"

# MongoDB — dump all databases (with auth)
echo "[$(date)] Backing up MongoDB..."
mongodump --uri="mongodb://localhost:27017" --gzip --archive="$BACKUP_DIR/mongo_${DATE}.archive.gz"

# CouchDB — dump all databases via k8s
echo "[$(date)] Backing up CouchDB..."
COUCH_USER=$(kubectl get secret couchdb-credentials -n obsidian-sync -o jsonpath='{.data.COUCHDB_USER}' | base64 -d)
COUCH_PASS=$(kubectl get secret couchdb-credentials -n obsidian-sync -o jsonpath='{.data.COUCHDB_PASSWORD}' | base64 -d)
COUCH_URL="https://sync.omarss.net"
# Get all database names
DBS=$(curl -s -u "${COUCH_USER}:${COUCH_PASS}" "${COUCH_URL}/_all_dbs" | python3 -c "import sys,json; [print(db) for db in json.load(sys.stdin) if not db.startswith('_')]")
COUCH_BACKUP_DIR="$BACKUP_DIR/couchdb_${DATE}"
mkdir -p "$COUCH_BACKUP_DIR"
for db in $DBS; do
    curl -s -u "${COUCH_USER}:${COUCH_PASS}" "${COUCH_URL}/${db}/_all_docs?include_docs=true" | gzip > "$COUCH_BACKUP_DIR/${db}.json.gz"
    echo "  backed up: $db"
done
tar -czf "$BACKUP_DIR/couchdb_${DATE}.tar.gz" -C "$BACKUP_DIR" "couchdb_${DATE}" && rm -rf "$COUCH_BACKUP_DIR"

# Cleanup old backups
echo "[$(date)] Cleaning up backups older than ${RETAIN_DAYS} days..."
find "$BACKUP_DIR" -name "postgres_*.sql.gz" -mtime +$RETAIN_DAYS -delete
find "$BACKUP_DIR" -name "mongo_*.archive.gz" -mtime +$RETAIN_DAYS -delete
find "$BACKUP_DIR" -name "couchdb_*.tar.gz" -mtime +$RETAIN_DAYS -delete

echo "[$(date)] Backup complete."
ls -lh "$BACKUP_DIR"/*_${DATE}*
