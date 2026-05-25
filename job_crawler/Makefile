# job_crawler — Makefile
#
# Conventions:
#   * `make help` prints every target with its description.
#   * All Python tools run via uv inside .venv.
#   * Anything that mutates the host (db-bootstrap, db-allow-k3s, deploy-nginx)
#     prints its sudo commands so you can see what's about to run.
#   * Cluster deploy targets use the user's existing kubeconfig at
#     /etc/rancher/k3s/k3s.yaml (read via sudo).

KUBECONFIG ?= /etc/rancher/k3s/k3s.yaml
IMAGE      ?= localhost/job-crawler:latest
TAG        ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)

# -- helpers --------------------------------------------------------------
# Source the local .env into a sub-make's environment so SQL/k8s targets can
# pick up the password without it leaking onto argv.
ENV_FILE := $(CURDIR)/.env
define _load_env
	@if [ ! -f "$(ENV_FILE)" ]; then echo "ERROR: $(ENV_FILE) missing. Run 'make db-bootstrap' first." >&2; exit 1; fi
endef

.PHONY: help install test lint format typecheck check clean \
        schema-check \
        db-bootstrap db-apply db-shell db-backup db-restore db-allow-k3s db-rotate-password \
        build-image load-image \
        deploy deploy-nginx deploy-secret deploy-restart \
        k8s-secret k8s-namespace k8s-status k8s-logs \
        run-api

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:  ## List available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Dev
# ---------------------------------------------------------------------------
install:  ## Create venv + install dev/api/crawler extras
	uv venv --python 3.12
	uv pip install -e ".[dev,api,crawler]"

test:  ## Run the full pytest suite (needs Docker for testcontainers)
	uv run pytest

lint:  ## ruff check
	uv run ruff check src tests

format:  ## ruff format
	uv run ruff format src tests

typecheck:  ## mypy --strict
	uv run mypy src tests

check: lint typecheck test  ## Lint + typecheck + tests

clean:  ## Remove caches + build artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

schema-check:  ## Validate db_schema.sql against a throwaway postgres:18-alpine
	@docker run --rm -d --name jc_schema_check \
		-e POSTGRES_PASSWORD=x -e POSTGRES_DB=jc postgres:18-alpine >/dev/null
	@for i in 1 2 3 4 5; do \
		docker exec jc_schema_check pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; \
	done
	@docker cp db_schema.sql jc_schema_check:/tmp/db_schema.sql >/dev/null
	@docker exec jc_schema_check psql -U postgres -d jc -v ON_ERROR_STOP=1 \
		-f /tmp/db_schema.sql >/dev/null && echo "schema OK" || \
		(docker exec jc_schema_check psql -U postgres -d jc -v ON_ERROR_STOP=1 \
			-f /tmp/db_schema.sql; false)
	@docker rm -f jc_schema_check >/dev/null

# ---------------------------------------------------------------------------
# Local API (development)
# ---------------------------------------------------------------------------
run-api:  ## Run FastAPI locally on :8080 with the host DB (reads .env)
	$(call _load_env)
	@set -a; . ./.env; set +a; \
		uv run uvicorn job_crawler_api.app:app --reload --port 8080

# ---------------------------------------------------------------------------
# Database (host Postgres 18, accessed as omar via peer auth)
# ---------------------------------------------------------------------------
db-bootstrap:  ## One-shot: create role + db + extensions + write .env (idempotent)
	@if [ -f .env ]; then echo ".env already exists; refusing to overwrite. Use db-rotate-password to regenerate." >&2; exit 1; fi
	@JC_DB_PASSWORD=$$(python3 -c "import secrets; print(secrets.token_urlsafe(24))"); \
		psql -U omar -d postgres -v ON_ERROR_STOP=1 <<-SQL >/dev/null && \
		psql -U omar -d job_crawler -v ON_ERROR_STOP=1 <<-EXT >/dev/null && \
		umask 077 && \
		printf 'JCDB_DSN=postgresql://job_crawler:%s@127.0.0.1:5432/job_crawler\nJCDB_POOL_MIN_SIZE=2\nJCDB_POOL_MAX_SIZE=20\nJCDB_APPLICATION_NAME=job_crawler_local\nJC_DB_PASSWORD=%s\n' "$$JC_DB_PASSWORD" "$$JC_DB_PASSWORD" > .env && \
		chmod 600 .env && \
		echo "OK. Password written to .env (chmod 600)."
		CREATE ROLE job_crawler WITH LOGIN PASSWORD '$$JC_DB_PASSWORD' NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT;
		CREATE DATABASE job_crawler OWNER job_crawler ENCODING 'UTF8' LOCALE 'en_US.UTF-8' TEMPLATE template0;
		SQL
		CREATE EXTENSION IF NOT EXISTS pgcrypto;
		CREATE EXTENSION IF NOT EXISTS pg_trgm;
		CREATE EXTENSION IF NOT EXISTS unaccent;
		CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
		CREATE EXTENSION IF NOT EXISTS btree_gin;
		CREATE EXTENSION IF NOT EXISTS btree_gist;
		GRANT ALL ON SCHEMA public TO job_crawler;
		GRANT CREATE ON DATABASE job_crawler TO job_crawler;
		EXT

db-apply:  ## Apply db_schema.sql to the host DB
	$(call _load_env)
	@set -a; . ./.env; set +a; \
		PGPASSWORD=$$JC_DB_PASSWORD psql -U job_crawler -h 127.0.0.1 -d job_crawler \
		-v ON_ERROR_STOP=1 -f db_schema.sql

db-shell:  ## psql shell as job_crawler against the host DB
	$(call _load_env)
	@set -a; . ./.env; set +a; \
		PGPASSWORD=$$JC_DB_PASSWORD psql -U job_crawler -h 127.0.0.1 -d job_crawler

db-backup:  ## pg_dump custom format to ./backups/YYYYMMDD-HHMM.dump
	$(call _load_env)
	@mkdir -p backups
	@set -a; . ./.env; set +a; \
		ts=$$(date +%Y%m%d-%H%M); \
		PGPASSWORD=$$JC_DB_PASSWORD pg_dump -U job_crawler -h 127.0.0.1 -d job_crawler \
			-Fc -f backups/$$ts.dump && \
		echo "wrote backups/$$ts.dump"

db-restore:  ## pg_restore from FILE=backups/...  (DROPS existing schema!)
	@if [ -z "$(FILE)" ]; then echo "usage: make db-restore FILE=backups/<file>.dump" >&2; exit 1; fi
	$(call _load_env)
	@set -a; . ./.env; set +a; \
		PGPASSWORD=$$JC_DB_PASSWORD pg_restore -U job_crawler -h 127.0.0.1 -d job_crawler \
			--clean --if-exists --no-owner --no-acl --exit-on-error "$(FILE)"

db-clear:  ## Dry-run: print rows that would be wiped (postings/clusters/runs). Add CONFIRM=1 to execute.
	@bash scripts/db_clear.sh crawl $(if $(CONFIRM),--confirm,)

db-clear-all:  ## Dry-run: print rows for FULL wipe (also companies+recruiters). Add CONFIRM=1 to execute.
	@bash scripts/db_clear.sh all $(if $(CONFIRM),--confirm,)

db-allow-k3s:  ## Append a pg_hba entry letting the 10.42.0.0/16 pod CIDR connect (NEEDS SUDO)
	@# `omar` is a superuser on the local socket via peer auth, so no sudo
	@# needed to ask for the hba_file path.
	@PG_HBA=$$(psql -U omar -d postgres -tAc "SHOW hba_file"); \
	if [ -z "$$PG_HBA" ]; then echo "could not determine pg_hba.conf path" >&2; exit 1; fi; \
	echo "pg_hba.conf at: $$PG_HBA"; \
	if sudo grep -Pq '^host\s+job_crawler\s+job_crawler\s+10\.42\.0\.0/16\s+scram-sha-256' "$$PG_HBA"; then \
		echo "entry already present — nothing to do"; \
	else \
		echo "host  job_crawler  job_crawler  10.42.0.0/16  scram-sha-256" | sudo tee -a "$$PG_HBA" >/dev/null; \
		sudo systemctl reload postgresql && echo "appended + postgresql reloaded"; \
	fi
	@# Postgres also needs to listen on the host-gateway interface, not just
	@# 127.0.0.1, for pods on 10.42.0.0/16 to reach it. Check + warn (no auto-edit).
	@LISTEN=$$(psql -U omar -d postgres -tAc "SHOW listen_addresses"); \
	echo "listen_addresses = $$LISTEN"; \
	case "$$LISTEN" in \
	  *\*|*0.0.0.0*) echo "  OK — already listening on all interfaces.";; \
	  *) echo "  NOTE: postgres is not listening on the host-gateway. Add" \
	     "10.42.0.1 (or '*') to listen_addresses in postgresql.conf and reload" \
	     "before pods can reach it.";; \
	esac

db-rotate-password:  ## Generate a new password, ALTER ROLE, rewrite .env, recreate k8s secret
	@NEW_PW=$$(python3 -c "import secrets; print(secrets.token_urlsafe(24))"); \
	psql -U omar -d postgres -v ON_ERROR_STOP=1 -c "ALTER ROLE job_crawler WITH PASSWORD '$$NEW_PW'"; \
	umask 077; \
	sed -E "s|^JCDB_DSN=postgresql://job_crawler:[^@]+@(.+)|JCDB_DSN=postgresql://job_crawler:$$NEW_PW@\1|; s|^JC_DB_PASSWORD=.*|JC_DB_PASSWORD=$$NEW_PW|" .env > .env.new && mv .env.new .env; \
	chmod 600 .env; \
	echo "rotated. Run 'make deploy-secret' to push the new value to the cluster."

# ---------------------------------------------------------------------------
# Container image
# ---------------------------------------------------------------------------
build-image:  ## docker build the runtime image
	docker build -t $(IMAGE) -t localhost/job-crawler:$(TAG) -f Dockerfile .

load-image:  ## Import the built image into k3s containerd via ctr
	@docker save $(IMAGE) | sudo k3s ctr -n=k8s.io images import -
	@sudo k3s ctr -n=k8s.io images ls | grep "job-crawler" | head -3

# ---------------------------------------------------------------------------
# Cluster deploy
# ---------------------------------------------------------------------------
k8s-namespace:  ## Ensure the namespace exists
	@sudo kubectl --kubeconfig=$(KUBECONFIG) apply -f homelab/apps/job-crawler/namespace.yaml

k8s-secret deploy-secret:  ## Create/replace job-crawler-secrets from .env (DSN + SMTP)
	$(call _load_env)
	@set -a; . ./.env; set +a; \
	if [ -z "$$JC_DB_PASSWORD" ]; then echo "JC_DB_PASSWORD missing in .env" >&2; exit 1; fi; \
	DSN="postgresql://job_crawler:$$JC_DB_PASSWORD@10.42.0.1:5432/job_crawler"; \
	sudo kubectl --kubeconfig=$(KUBECONFIG) apply -f homelab/apps/job-crawler/namespace.yaml; \
	sudo kubectl --kubeconfig=$(KUBECONFIG) -n job-crawler create secret generic job-crawler-secrets \
		--from-literal=JCDB_DSN="$$DSN" \
		--from-literal=SMTP_HOST="$${SMTP_HOST:-}" \
		--from-literal=SMTP_PORT="$${SMTP_PORT:-587}" \
		--from-literal=SMTP_USERNAME="$${SMTP_USERNAME:-}" \
		--from-literal=SMTP_PASSWORD="$${SMTP_PASSWORD:-}" \
		--from-literal=SMTP_STARTTLS="$${SMTP_STARTTLS:-true}" \
		--from-literal=SMTP_USE_SSL="$${SMTP_USE_SSL:-false}" \
		--from-literal=ALERT_EMAIL_FROM="$${ALERT_EMAIL_FROM:-job-crawler <alerts@jobs.omarss.net>}" \
		--from-literal=ALERT_EMAIL_TO="$${ALERT_EMAIL_TO:-omar.s.shaaban@gmail.com}" \
		--dry-run=client -o yaml | sudo kubectl --kubeconfig=$(KUBECONFIG) apply -f -

deploy-api:  ## Apply API-side manifests only (namespace/configmap/deployment/service)
	@sudo kubectl --kubeconfig=$(KUBECONFIG) apply \
		-f homelab/apps/job-crawler/namespace.yaml \
		-f homelab/apps/job-crawler/configmap.yaml \
		-f homelab/apps/job-crawler/deployment.yaml \
		-f homelab/apps/job-crawler/service.yaml

deploy-cronjobs:  ## Apply per-source CronJobs (requires phase 1 crawler code in the image)
	@sudo kubectl --kubeconfig=$(KUBECONFIG) apply \
		-f homelab/apps/job-crawler/cronjobs.yaml

deploy: deploy-api deploy-cronjobs  ## Apply ALL k3s manifests (API + cronjobs)

deploy-restart:  ## Roll the API deployment
	@sudo kubectl --kubeconfig=$(KUBECONFIG) -n job-crawler rollout restart deploy/job-crawler-api
	@sudo kubectl --kubeconfig=$(KUBECONFIG) -n job-crawler rollout status deploy/job-crawler-api

deploy-nginx:  ## Install jobs.omarss.net vhost + reload nginx (NEEDS SUDO + certbot re-run)
	@sudo install -m 644 homelab/nginx/jobs.omarss.net.conf /etc/nginx/sites-available/jobs.omarss.net.conf
	@sudo ln -sf /etc/nginx/sites-available/jobs.omarss.net.conf /etc/nginx/sites-enabled/jobs.omarss.net.conf
	@sudo nginx -t && sudo systemctl reload nginx
	@echo
	@echo "Now run (once): sudo certbot --nginx -d jobs.omarss.net"
	@echo "After that, jobs.omarss.net will serve TLS via the certbot-managed 443 block."

# ---------------------------------------------------------------------------
# Cluster ops
# ---------------------------------------------------------------------------
k8s-status:  ## Quick status: pods, recent jobs, services
	@sudo kubectl --kubeconfig=$(KUBECONFIG) -n job-crawler get pods,svc,cronjobs
	@echo
	@sudo kubectl --kubeconfig=$(KUBECONFIG) -n job-crawler get jobs --sort-by=.metadata.creationTimestamp | tail -10

k8s-logs:  ## Tail API logs (override with POD=...)
	@POD=$${POD:-$$(sudo kubectl --kubeconfig=$(KUBECONFIG) -n job-crawler get pod -l app.kubernetes.io/name=job-crawler-api -o jsonpath='{.items[0].metadata.name}')}; \
	sudo kubectl --kubeconfig=$(KUBECONFIG) -n job-crawler logs -f $$POD

# ===========================================================================
# Crawler runs (local — uses host DB via .env)
# ===========================================================================
# Generic:
#     make crawl SOURCE=greenhouse                  # one
#     make crawl SOURCE=greenhouse,bayt             # several
#     make crawl SOURCE=all                         # every implemented
#     make crawl-list                               # what's registered
#
# Per-source convenience targets with their well-known env knobs:
#
#   ATS:
#     make crawl-greenhouse        JC_GREENHOUSE_BOARDS=neom,tabby,...
#     make crawl-lever             JC_LEVER_BOARDS=...           (stub)
#     make crawl-workday           JC_WORKDAY_TENANTS=...        (stub)
#     make crawl-workable          JC_WORKABLE_BOARDS=...        (stub)
#     make crawl-smartrecruiters   JC_SR_COMPANIES=...           (stub)
#     make crawl-recruitee         JC_RECRUITEE_BOARDS=...       (stub)
#     make crawl-personio          JC_PERSONIO_BOARDS=...        (stub)
#   Boards:
#     make crawl-bayt              JC_BAYT_QUERY=... JC_BAYT_MAX_PAGES=5
#     make crawl-naukrigulf        JC_NAUKRI_QUERY=...           (stub)
#     make crawl-wuzzuf            JC_WUZZUF_QUERY=...           (stub)
#     make crawl-tanqeeb           JC_TANQEEB_QUERY=...          (stub)
#     make crawl-mihnati           JC_MIHNATI_QUERY=...          (stub)
#     make crawl-jadarat                                         (stub)
#   Aggregators (phase 3+ — bot-hostile):
#     make crawl-linkedin          JC_LINKEDIN_KEYWORDS=... JC_LINKEDIN_LOCATION=...
#     make crawl-indeed            JC_INDEED_QUERY=... JC_INDEED_LOCATION=...
#     make crawl-glassdoor                                       (stub)
#
# All targets honour:
#   JC_LOOKBACK_DAYS=30     # window the crawler filters to
#   JC_FETCH_TIMEOUT_S=20   # per-request timeout
#   JC_FETCH_MAX_CONCURRENCY=3
#   RESEND_API_KEY=...      # alerts (optional)
# ===========================================================================
.PHONY: crawl crawl-list canary canary-list discover discover-seed discover-wikidata \
        crawl-greenhouse crawl-lever crawl-workday crawl-workable \
        crawl-smartrecruiters crawl-successfactors crawl-recruitee crawl-personio \
        crawl-bayt crawl-naukrigulf crawl-wuzzuf crawl-tanqeeb crawl-mihnati \
        crawl-jadarat crawl-linkedin crawl-indeed crawl-glassdoor \
        crawl-ats crawl-boards crawl-all

# Helper that loads .env and runs `python -m job_crawler.cli.run <selector>`.
# Used by every crawl target.
define _run_crawler
	$(call _load_env)
	@set -a; . ./.env; set +a; uv run python -m job_crawler.cli.run $(1)
endef
define _run_canary
	$(call _load_env)
	@set -a; . ./.env; set +a; uv run python -m job_crawler.cli.canary $(1)
endef
define _run_discover
	$(call _load_env)
	@set -a; . ./.env; set +a; uv run python -m job_crawler.cli.discover $(1)
endef

crawl-list:  ## List every registered source (✓ implemented, · stub)
	@uv run python -m job_crawler.cli.run --list

crawl:  ## Run one or many crawlers (SOURCE=greenhouse | all | bayt,linkedin | ats | boards)
	@if [ -z "$(SOURCE)" ]; then echo "usage: make crawl SOURCE=greenhouse | all | ats | boards | <csv>" >&2; exit 2; fi
	$(call _run_crawler,$(SOURCE))

crawl-all:           ## Run every implemented crawler
	$(call _run_crawler,all)
crawl-ats:           ## Run every implemented ATS crawler
	$(call _run_crawler,ats)
crawl-boards:        ## Run every implemented board crawler
	$(call _run_crawler,boards)

# ---- ATS family ----------------------------------------------------------
crawl-greenhouse:    ## ATS: Greenhouse Boards (set JC_GREENHOUSE_BOARDS=slug1,slug2,...)
	$(call _run_crawler,greenhouse)
crawl-lever:         ## ATS: Lever (set JC_LEVER_BOARDS=site1,site2,...)
	$(call _run_crawler,lever)
crawl-workday:       ## ATS: Workday (set JC_WORKDAY_TENANTS=tenant:wdN:site,...)
	$(call _run_crawler,workday)
crawl-workable:      ## ATS: Workable (set JC_WORKABLE_BOARDS=slug1,slug2,...)
	$(call _run_crawler,workable)
crawl-smartrecruiters: ## ATS: SmartRecruiters (set JC_SR_COMPANIES=co1,co2,...)
	$(call _run_crawler,smartrecruiters)
crawl-successfactors: ## ATS: SAP SuccessFactors (set JC_SUCCESSFACTORS_TENANTS=aramco:career5,sabic:performancemanager4,...)
	$(call _run_crawler,successfactors)
crawl-recruitee:     ## ATS: Recruitee (set JC_RECRUITEE_BOARDS=slug1,slug2,...)
	$(call _run_crawler,recruitee)
crawl-personio:      ## ATS: Personio (set JC_PERSONIO_BOARDS=slug1,slug2,...)
	$(call _run_crawler,personio)

# ---- Boards --------------------------------------------------------------
crawl-bayt:          ## Board: Bayt (default 18-keyword multi-query; override JC_BAYT_QUERIES, JC_BAYT_MAX_PAGES)
	$(call _run_crawler,bayt)
crawl-naukrigulf:    ## Board: Naukrigulf (SPA — yields ~0 without app-id)
	$(call _run_crawler,naukrigulf)
crawl-wuzzuf:        ## Board: Wuzzuf (set JC_WUZZUF_QUERY, JC_WUZZUF_MAX_PAGES)
	$(call _run_crawler,wuzzuf)
crawl-tanqeeb:       ## Board: Tanqeeb SA (homepage + regional landing pages)
	$(call _run_crawler,tanqeeb)
crawl-mihnati:       ## Board: Mihnati (set JC_MIHNATI_QUERY, JC_MIHNATI_MAX_PAGES)
	$(call _run_crawler,mihnati)
crawl-jadarat:       ## Board: Jadarat (KSA gov — Playwright sits through Queue-It)
	$(call _run_crawler,jadarat)
crawl-company-careers: ## Boards: per-company careers pages (Playwright JSON-LD scrape)
	$(call _run_crawler,company_careers)
crawl-linkedin:      ## Aggregator: LinkedIn (curl_cffi+proxy pool; IP-throttled)
	$(call _run_crawler,linkedin)
crawl-indeed:        ## Aggregator: Indeed (bot-walled; set JC_INDEED_COOKIE for yield)
	$(call _run_crawler,indeed)
crawl-glassdoor:     ## Aggregator: Glassdoor (SPA; set JC_GLASSDOOR_COOKIE for yield)
	$(call _run_crawler,glassdoor)

# ---- Canary + discovery --------------------------------------------------
canary:              ## Run canary checks (SELECTOR=all | greenhouse,bayt | ...)
	$(call _run_canary,$${SELECTOR:-all})
canary-list:         ## Show which sources expose canary URLs
	@uv run python -m job_crawler.cli.run --list

discover:            ## Run all discovery steps (curated seed + Wikidata + ATS auto-detect)
	$(call _run_discover,--all)
discover-seed:       ## Reload only the curated SA companies CSV
	$(call _run_discover,--seed)
discover-wikidata:   ## Pull SA-headquartered orgs from Wikidata
	$(call _run_discover,--wikidata)
discover-ats:        ## Auto-detect every company's ATS (Greenhouse/Lever/Workable/SF)
	$(call _run_discover,--ats)

# ---- Post-processing intelligence ----------------------------------------
define _run_intelligence
	$(call _load_env)
	@set -a; . ./.env; set +a; uv run python -m job_crawler.cli.intelligence $(1)
endef
intelligence:         ## Run every intelligence pass (skills + enrich + dedup)
	$(call _run_intelligence,--all)
intelligence-skills:  ## Extract skills from descriptions + fill job_skills
	$(call _run_intelligence,--skills)
intelligence-enrich:  ## Recover salary/experience/education + normalize titles
	$(call _run_intelligence,--enrich)
intelligence-dedup:   ## Cross-source duplicate detection + cluster merging
	$(call _run_intelligence,--dedup)

# ---- Proxy pool ----------------------------------------------------------
proxies-refresh:      ## Pull fresh proxy lists from monosans / proxifly / TheSpeedX
	@uv run python -m job_crawler.cli.proxies refresh
proxies-stats:        ## Print the current proxy pool stats (alive / blacklisted / hit rate)
	@uv run python -m job_crawler.cli.proxies stats
proxies-clear-blacklist: ## Unblacklist every proxy in the saved state
	@uv run python -m job_crawler.cli.proxies clear-blacklist
proxies-validate:     ## Probe every live proxy, blacklist the dead ones (long-running)
	@uv run python -m job_crawler.cli.proxies validate

# ---- One-button daily cycle ---------------------------------------------
# Full end-to-end loop you can run from cron or kick off manually.
#   1. Refresh the auto-detected ATS profiles (so new SA companies on
#      Greenhouse/Lever/Workable/SF get picked up automatically).
#   2. Crawl every implemented source (ATS + boards).
#   3. Run the intelligence layer: extract skills, recover salary/
#      experience/education, backfill city resolution, strip HTML entities
#      from titles (idempotent), cross-source dedup.
#
# Every step is idempotent. Safe to interrupt and re-run.
#
# Defaults can be overridden per-invocation:
#   JC_LOOKBACK_DAYS=60 make cycle      # widen the window
#   JC_BAYT_MAX_PAGES=10 make cycle     # shorter Bayt sweep
.PHONY: cycle cycle-light cycle-heavy

cycle: discover-ats crawl-all intelligence  ## Full daily flow: discover→crawl→intelligence
	@echo "[cycle] done — see make k8s-status / db-shell for verification"

cycle-light: crawl-all intelligence    ## Skip ATS auto-discovery (faster nightly cycle)
	@echo "[cycle-light] done"

cycle-heavy: proxies-refresh proxies-validate cycle  ## Refresh proxies first (weekly)
	@echo "[cycle-heavy] done"

# ---- Data stats: routine inspection in one shot -------------------------
.PHONY: data-stats data-stats-riyadh

data-stats:  ## Compact summary of cluster + per-source + coverage metrics
	$(call _load_env)
	@set -a; . ./.env; set +a; \
	PGPASSWORD=$$JC_DB_PASSWORD psql -U job_crawler -h 127.0.0.1 -d job_crawler -X -tA -F'|' -c "\
		SELECT 'clusters_total', COUNT(*)::text FROM jobs WHERE deleted_at IS NULL \
		UNION ALL SELECT 'postings_total', COUNT(*)::text FROM job_postings \
		UNION ALL SELECT 'companies', COUNT(*)::text FROM companies \
		UNION ALL SELECT 'dedup_edges', COUNT(*)::text FROM posting_duplicate_edges \
		UNION ALL SELECT 'job_skills', COUNT(*)::text FROM job_skills;"; \
	echo "--- per source ---"; \
	PGPASSWORD=$$JC_DB_PASSWORD psql -U job_crawler -h 127.0.0.1 -d job_crawler -X -tA -F'|' -c "\
		SELECT s.slug, COUNT(p.id) FROM sources s LEFT JOIN job_postings p ON p.source_id=s.id GROUP BY s.slug ORDER BY 2 DESC;"; \
	echo "--- cluster coverage %---"; \
	PGPASSWORD=$$JC_DB_PASSWORD psql -U job_crawler -h 127.0.0.1 -d job_crawler -X -tA -F'|' -c "\
		WITH c AS (SELECT j.* FROM jobs j WHERE j.deleted_at IS NULL) \
		SELECT \
			ROUND(COUNT(*) FILTER (WHERE city_id IS NOT NULL)*100.0/NULLIF(COUNT(*),0),1)::text || '% city', \
			ROUND(COUNT(*) FILTER (WHERE company_id IS NOT NULL)*100.0/NULLIF(COUNT(*),0),1)::text || '% company', \
			ROUND(COUNT(*) FILTER (WHERE salary_min IS NOT NULL)*100.0/NULLIF(COUNT(*),0),1)::text || '% salary', \
			ROUND(COUNT(*) FILTER (WHERE min_experience_years IS NOT NULL)*100.0/NULLIF(COUNT(*),0),1)::text || '% experience', \
			ROUND(COUNT(*) FILTER (WHERE min_education_level IS NOT NULL)*100.0/NULLIF(COUNT(*),0),1)::text || '% education' \
		FROM c;"

data-stats-riyadh:  ## Riyadh postings in the last 30 days, top 20 by title
	$(call _load_env)
	@set -a; . ./.env; set +a; \
	PGPASSWORD=$$JC_DB_PASSWORD psql -U job_crawler -h 127.0.0.1 -d job_crawler -X -tA -F'|' -c "\
		SELECT p.title, COALESCE(comp.name_en, p.raw_company_name, '-') AS company, s.slug, \
		       to_char(p.posted_at, 'YYYY-MM-DD') \
		FROM jobs j \
		JOIN job_postings p ON p.id = j.canonical_posting_id \
		JOIN sa_cities c ON c.id = j.city_id \
		JOIN sources s ON s.id = p.source_id \
		LEFT JOIN companies comp ON comp.id = p.company_id \
		WHERE j.deleted_at IS NULL AND c.name_en = 'Riyadh' \
		  AND (p.posted_at IS NULL OR p.posted_at >= now() - interval '30 days') \
		ORDER BY p.title LIMIT 20;"
