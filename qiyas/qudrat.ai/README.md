# qudrat

Assessment-content platform for Saudi Qudurat (Qiyas) and Tahsili practice.
Hosted at `qudrat.omarss.net` (and later `qudrat.ai`), fronted by host
nginx, served out of k3s. Postgres runs on the host (matches the
api-mcqs / api-places / prompter pattern).

See `CLAUDE.md` for stack, conventions, build flow, and known gotchas.

## Quickstart

```sh
make builder    # build the local builder image (one-time)
make test       # unit tests inside the builder
make lint       # static analysis
make build      # build all service binaries to bin/

make db-up      # start a dev Postgres 18 container on :55433
make migrate-up # apply migrations to the dev database
make sqlc-gen   # regenerate internal/store from db/queries

make run-importer  # seed dev DB from ../questions/*.json
make run-api       # run the api locally on :8080
```

No Go is required on the host — everything runs inside the builder
container via podman.

## Bootstrap on this machine (Phase 1)

One-time, with sudo:

```sh
# 1. Postgres role + db on the host instance.
sudo -u postgres psql <<'SQL'
CREATE ROLE qudrat LOGIN PASSWORD :'pw';
CREATE DATABASE qudrat OWNER qudrat
  ENCODING 'UTF8' LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8'
  TEMPLATE template0;
SQL

# 2. Allow the k3s pod CIDR to reach the host Postgres.
#    Add to /etc/postgresql/*/main/pg_hba.conf if missing:
#      host  qudrat  qudrat  10.42.0.0/16  scram-sha-256
sudo systemctl reload postgresql

# 3. nginx vhost + TLS.
sudo make -C ../../homelab apply-nginx
sudo certbot --nginx -d qudrat.omarss.net

# 4. Create the live k8s secret (DB password from ~/.config/qudrat/db-password).
DB_PASS=$(cat ~/.config/qudrat/db-password)
kubectl create namespace qudrat --dry-run=client -o yaml | kubectl apply -f -
kubectl -n qudrat create secret generic qudrat-secrets \
  --from-literal=QUDRAT_DATABASE_DSN="postgresql://qudrat:${DB_PASS}@10.42.0.1:5432/qudrat?sslmode=disable" \
  --from-literal=QUDRAT_TWILIO_ACCOUNT_SID=REPLACE_ME \
  --from-literal=QUDRAT_TWILIO_AUTH_TOKEN=REPLACE_ME \
  --from-literal=QUDRAT_TWILIO_VERIFY_SERVICE_SID=REPLACE_ME \
  --from-literal=QUDRAT_RESEND_API_KEY=REPLACE_ME \
  --from-literal=QUDRAT_RESEND_FROM=REPLACE_ME \
  --dry-run=client -o yaml | kubectl apply -f -

# 5. Build, load, deploy.
make image-load-api
make k8s-apply

# 6. Run migrations + seed against the live DB.
export PROD_DB_DSN="postgres://qudrat:${DB_PASS}@127.0.0.1:5432/qudrat?sslmode=disable"
make migrate-up-prod
make image-load-importer
make import-prod

# 7. Verify.
curl -s https://qudrat.omarss.net/healthz
curl -s https://qudrat.omarss.net/readyz
psql -h localhost -U qudrat -d qudrat -c "select count(*) from items"
```
