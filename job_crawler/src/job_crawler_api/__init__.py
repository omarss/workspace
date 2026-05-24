"""job_crawler_api — the FastAPI service served at jobs.omarss.net.

A thin facade in front of the `job_crawler_db` library. Read-only by design:
the crawlers (deployed as separate k3s CronJobs) write to the DB; this
service only reads.

Endpoints
---------
* GET /             — static HTML dashboard (under static/index.html)
* GET /v1/health    — overall health, db reachable, last-run summary
* GET /v1/health/sources    — per-source crawler health rollup
* GET /v1/search    — ranked job search (proxies db.search.find_jobs)
* GET /v1/companies — fuzzy company lookup
* GET /v1/jobs/{id} — full cluster details, including locations + skills
"""

from .app import create_app

__all__ = ["create_app"]
