#!/bin/bash
# Initialize CouchDB for Obsidian Livesync after deployment.
# Usage: bash scripts/init-couchdb.sh
set -e

COUCH_USER=$(kubectl get secret couchdb-credentials -n obsidian-sync -o jsonpath='{.data.COUCHDB_USER}' | base64 -d)
COUCH_PASS=$(kubectl get secret couchdb-credentials -n obsidian-sync -o jsonpath='{.data.COUCHDB_PASSWORD}' | base64 -d)
POD=$(kubectl get pods -n obsidian-sync -l app=couchdb -o jsonpath='{.items[0].metadata.name}')

kubectl exec -n obsidian-sync "$POD" -- bash -c "
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_users
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_replicator
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_global_changes
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/chttpd/require_valid_user -d '\"true\"'
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/chttpd_auth/require_valid_user -d '\"true\"'
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/httpd/WWW-Authenticate -d '\"Basic realm=\\\"couchdb\\\"\"'
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/httpd/enable_cors -d '\"true\"'
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/chttpd/enable_cors -d '\"true\"'
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/cors/credentials -d '\"true\"'
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/cors/origins -d '\"app://obsidian.md,capacitor://localhost,http://localhost\"'
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/chttpd/max_http_request_size -d '\"4294967296\"'
curl -s -u '${COUCH_USER}:${COUCH_PASS}' -X PUT http://localhost:5984/_node/_local/_config/couchdb/max_document_size -d '\"50000000\"'
"

echo "CouchDB initialized for Obsidian Livesync."
