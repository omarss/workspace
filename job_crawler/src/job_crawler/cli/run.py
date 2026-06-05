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
import os
import sys
from pathlib import Path
from typing import Any, Final

from job_crawler_db import JobCrawlerDB

from ..alerts.email import send_alert
from ..core.http import HttpClient
from ..core.proxy import ProxyPool, build_default_pool
from ..core.runner import CrawlerRunner
from ..intelligence import pipeline as intelligence
from ..registry import REGISTRY, get, resolve_slugs

# Shared proxy state location:
#   * local dev (no env override): `<repo>/.cache/proxy_pool.json` so a
#     fresh `make crawl` re-uses the previous run's blacklist + counters.
#   * container (env override):    `JC_PROXY_STATE_FILE` set to a
#     writable path on an emptyDir mount, since `readOnlyRootFilesystem`
#     forbids creating `/app/.cache/`. Default for containers is
#     `/tmp/job_crawler/proxy_pool.json` (mounted via emptyDir in
#     `homelab/apps/job-crawler/cronjobs.yaml`).
_PROXY_STATE_FILE = Path(
    os.environ.get(
        "JC_PROXY_STATE_FILE",
        str(Path(__file__).resolve().parents[3] / ".cache" / "proxy_pool.json"),
    )
)
_PROXY_POOL_SINGLETON: ProxyPool | None = None


async def _get_proxy_pool() -> ProxyPool:
    """Build (or reuse) the shared proxy pool for this CLI invocation.

    A write-protected proxy-state path (e.g. mounting issue, RO root FS)
    must not block proxy-backed crawls — the in-memory pool is still
    usable, we just lose persistence. `save_state` failures elsewhere
    in this file are already non-fatal; mirror that for the mkdir.
    """
    global _PROXY_POOL_SINGLETON
    if _PROXY_POOL_SINGLETON is None:
        try:
            _PROXY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _LOG.warning(
                "could not create proxy state dir %s (%s); running without persistence",
                _PROXY_STATE_FILE.parent, exc,
            )
        _PROXY_POOL_SINGLETON = await build_default_pool(state_file=_PROXY_STATE_FILE)
    return _PROXY_POOL_SINGLETON

_LOG: Final = logging.getLogger("job_crawler.cli.run")


async def _run_one(db: JobCrawlerDB, slug: str) -> int:
    """Run a single crawler. Returns the process-exit code for it."""
    cls = get(slug)
    # Pick the right fetcher: Playwright (Chromium) for SPA / bot-walled
    # sites that need behavioural cover, HttpClient (httpx/curl_cffi) for
    # everything else. Both expose the same async `.fetch()` shape so the
    # crawler body is agnostic.
    http: Any
    if cls.use_playwright:
        from ..core.playwright_fetcher import PlaywrightFetcher

        # Per-source cookie env: JC_LINKEDIN_COOKIE, JC_INDEED_COOKIE, etc.
        cookie_env_var = f"JC_{cls.source_slug.upper()}_COOKIE"
        cookie_header = os.environ.get(cookie_env_var, "").strip() or None
        http = PlaywrightFetcher(cls.rate, cookie=cookie_header)
        await http.__aenter__()
    else:
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
            f"fresh_skipped={summary.fresh_skipped} "
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
                f"restrictions={summary.restrictions_recovered} "
                f"centroids={summary.centroids_filled} "
                f"legit_scored={summary.legit_scored} "
                f"industries={summary.industries_classified} "
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
            print(f"  {slug:<18s} {cls.source_display_name}")
        return

    slugs = tuple(resolve_slugs(args.selector))
    if not slugs:
        parser.error(f"no slugs resolved from selector '{args.selector}'")
    valid_slugs, dropped = partition_known_slugs(slugs)
    for slug in dropped:
        print(
            f"warning: source '{slug}' is not in the registry; "
            f"skipping (known: {', '.join(REGISTRY)})",
            file=sys.stderr,
        )
    if not valid_slugs:
        parser.error(
            f"none of the requested slugs ({', '.join(slugs)}) are registered",
        )
    sys.exit(asyncio.run(_main(valid_slugs)))


def partition_known_slugs(
    slugs: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split `slugs` into (known, unknown) based on REGISTRY membership.

    Used to tolerate slugs that no longer exist in the registry — a
    retired source (e.g. mihnati, removed in 2026-06 after its upstream
    went dead) commonly stays in operator-side systemd unit files until
    the next deploy. The caller warns + skips unknowns rather than
    crashing the whole run, which would orphan every other source.
    """
    known = tuple(s for s in slugs if s in REGISTRY)
    unknown = tuple(s for s in slugs if s not in REGISTRY)
    return known, unknown


if __name__ == "__main__":
    main()
