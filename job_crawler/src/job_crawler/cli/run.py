"""`python -m job_crawler.cli.run <slug>[,<slug>...]`

Runs one (or many) crawler(s) end-to-end against the host DB pointed to
by `JCDB_DSN`. Used by both the Makefile and the k3s CronJobs.

    python -m job_crawler.cli.run greenhouse
    python -m job_crawler.cli.run greenhouse,bayt
    python -m job_crawler.cli.run all                # every implemented crawler
    python -m job_crawler.cli.run --list             # show the registry
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Final

from job_crawler_db import JobCrawlerDB

from ..alerts.email import send_alert
from ..core.http import HttpClient
from ..core.proxy import ProxyPool, build_default_pool
from ..core.runner import CrawlerRunner
from ..intelligence import pipeline as intelligence
from ..registry import REGISTRY, NotImplementedCrawler, get, resolve_slugs

# Shared proxy state lives under .cache/ so survives runs but stays local.
_PROXY_STATE_FILE = Path(__file__).resolve().parents[3] / ".cache" / "proxy_pool.json"
_PROXY_POOL_SINGLETON: ProxyPool | None = None


async def _get_proxy_pool() -> ProxyPool:
    """Build (or reuse) the shared proxy pool for this CLI invocation."""
    global _PROXY_POOL_SINGLETON
    if _PROXY_POOL_SINGLETON is None:
        _PROXY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PROXY_POOL_SINGLETON = await build_default_pool(state_file=_PROXY_STATE_FILE)
    return _PROXY_POOL_SINGLETON

_LOG: Final = logging.getLogger("job_crawler.cli.run")


async def _run_one(db: JobCrawlerDB, slug: str) -> int:
    """Run a single crawler. Returns the process-exit code for it."""
    cls = get(slug)
    if issubclass(cls, NotImplementedCrawler):
        print(f"[{slug}] not implemented yet — skipping", file=sys.stderr)
        return 0
    proxy_pool = await _get_proxy_pool() if cls.use_proxy_pool else None
    http = HttpClient(
        cls.rate,
        respect_robots=cls.respect_robots,
        http2=not cls.prefer_http_1_1,
        impersonate=cls.impersonate_browser,
        proxy_pool=proxy_pool,
    )
    crawler = cls(http, db=db)
    try:
        runner = CrawlerRunner(db, crawler)
        summary = await runner.run()
        print(
            f"[{slug}] {summary.status.value}: "
            f"fetched={summary.fetched} parsed={summary.parsed} "
            f"new={summary.new_postings} updated={summary.updated_postings} "
            f"errors={summary.errors}",
        )
        if summary.status.value == "failed":
            await send_alert(
                subject=f"[job_crawler] {slug} run failed",
                body=f"Run {summary.run_id} for source {slug} ended in 'failed'.\n"
                f"Counters: {summary}",
            )
            return 1
        return 0
    finally:
        await http.aclose()


async def _main(slugs: tuple[str, ...]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    exit_code = 0
    async with JobCrawlerDB.from_env() as db:
        for slug in slugs:
            try:
                code = await _run_one(db, slug)
                exit_code = max(exit_code, code)
            except Exception:
                _LOG.exception("crawler %s crashed", slug)
                await send_alert(
                    subject=f"[job_crawler] {slug} crashed",
                    body=f"Uncaught exception while running source {slug}. Check logs.",
                )
                exit_code = 2
        # Persist proxy-pool state so the next CLI invocation inherits
        # the blacklist + success counters.
        if _PROXY_POOL_SINGLETON is not None:
            try:
                stats = await _PROXY_POOL_SINGLETON.stats()
                print(
                    f"[proxy_pool] alive={stats['alive']} blacklisted={stats['blacklisted']} "
                    f"hits={stats['successes']} fails={stats['failures']} "
                    f"success_rate={stats['success_rate']}"
                )
                await _PROXY_POOL_SINGLETON.save_state(_PROXY_STATE_FILE)
            except Exception:
                _LOG.exception("could not save proxy pool state (non-fatal)")
        # Tail-run intelligence so newly-ingested postings get skills
        # extraction, salary/experience recovery + cross-source dedup
        # applied immediately. Failures here are non-fatal.
        try:
            summary = await intelligence.run_all(db)
            print(
                f"[intelligence] skill_hits={summary.skill_hits} "
                f"salary={summary.salary_recovered} "
                f"exp={summary.experience_recovered} "
                f"edu={summary.education_recovered} "
                f"titles={summary.titles_normalized} "
                f"dedup_edges={summary.dedup_edges} "
                f"merged={summary.dedup_clusters_merged}"
            )
        except Exception:
            _LOG.exception("intelligence pass failed (non-fatal)")
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="job_crawler.cli.run",
        description="Run one or more crawlers end-to-end.",
    )
    parser.add_argument(
        "selector",
        nargs="?",
        default=None,
        help="Slug, comma-separated list, or one of: all, all-stubs, ats, boards",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the registry and exit.",
    )
    args = parser.parse_args()

    if args.list or not args.selector:
        for slug, cls in REGISTRY.items():
            mark = "✓" if not issubclass(cls, NotImplementedCrawler) else "·"
            print(f"  {mark} {slug:<18s} {cls.source_display_name}")
        return

    slugs = tuple(resolve_slugs(args.selector))
    if not slugs:
        parser.error(f"no slugs resolved from selector '{args.selector}'")
    sys.exit(asyncio.run(_main(slugs)))


if __name__ == "__main__":
    main()
