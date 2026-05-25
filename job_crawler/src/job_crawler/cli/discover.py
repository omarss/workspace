"""`python -m job_crawler.cli.discover [--seed] [--wikidata] [--ats] [--all]`

Discovery sub-commands:
  --seed       reload the curated CSV into companies
  --wikidata   pull all SA-headquartered orgs from Wikidata SPARQL
  --ats        auto-detect each company's hosting ATS
  --all        run every available discovery step
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Final

from psycopg.rows import dict_row

from job_crawler_db import Company, JobCrawlerDB

from ..alerts.email import send_alert
from ..company_sites import ats_detector
from ..discover import manual_seed, wikidata
from ..discover.wikidata import WikidataFetchError

_LOG: Final = logging.getLogger("job_crawler.cli.discover")


async def _main(seed: bool, wd: bool, ats: bool, limit: int | None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    exit_code = 0
    async with JobCrawlerDB.from_env() as db:
        if seed:
            r = await manual_seed.load(db)
            print(
                f"[seed] total={r.total} created={r.created} "
                f"matched={r.matched_existing} career_profiles={r.career_profiles}"
            )
        if wd:
            # Wikidata used to swallow fetch failures and return a (0, 0, 0)
            # result that the CronJob recorded as success (Finding 4). Now we
            # let WikidataFetchError surface to the exit code and still run
            # the remaining discovery steps so a transient SPARQL hiccup
            # doesn't block --seed / --ats. An alert email goes out so the
            # weekly-cron failure isn't silent even when k8s shows green.
            try:
                r2 = await wikidata.fetch_and_load(db)
                print(
                    f"[wikidata] fetched={r2.fetched} inserted={r2.inserted} "
                    f"skipped={r2.skipped}"
                )
            except WikidataFetchError as exc:
                _LOG.error("wikidata pull failed: %s", exc)
                print(f"[wikidata] FAILED: {exc}", file=sys.stderr)
                exit_code = 1
                await send_alert(
                    subject="[job_crawler] wikidata discovery failed",
                    body=(
                        f"Wikidata SPARQL pull failed:\n  {exc}\n\n"
                        "The weekly company-discovery job has stale data. "
                        "The crawler keeps running — only the Wikidata enrichment is missing."
                    ),
                )
        if ats:
            cap = limit or 1000
            async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT * FROM companies WHERE deleted_at IS NULL "
                    "ORDER BY created_at LIMIT %(lim)s",
                    {"lim": cap},
                )
                companies = [Company.model_validate(r) for r in await cur.fetchall()]
            res = await ats_detector.detect_for_companies(db, companies)
            print(f"[ats-detect] scanned={res.companies_scanned} hits={res.hits} "
                  f"by_source={res.by_source}")
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(prog="job_crawler.cli.discover")
    parser.add_argument("--seed", action="store_true", help="reload the curated CSV")
    parser.add_argument("--wikidata", action="store_true", help="run the Wikidata SPARQL pull")
    parser.add_argument("--ats", action="store_true",
                        help="auto-detect each company's ATS hosting")
    parser.add_argument("--all", action="store_true", help="run every discovery step")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of companies scanned by --ats")
    args = parser.parse_args()
    seed = args.seed or args.all
    wd = args.wikidata or args.all
    ats = args.ats or args.all
    if not (seed or wd or ats):
        parser.error("specify --seed, --wikidata, --ats, or --all")
    sys.exit(asyncio.run(_main(seed, wd, ats, args.limit)))


if __name__ == "__main__":
    main()
