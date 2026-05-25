"""`python -m job_crawler.cli.canary <slug>|all`

Fetches each crawler's `canary_urls`, runs `.parse()` on the response, and
records the outcome in `crawler_health`. Two consecutive failures auto-
disable the source + send an email.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Final

from job_crawler_db import JobCrawlerDB

from ..alerts.email import send_alert
from ..core.health import record_canary
from ..core.http import HttpClient
from ..registry import get, resolve_slugs

_LOG: Final = logging.getLogger("job_crawler.cli.canary")


async def _check(db: JobCrawlerDB, slug: str) -> bool:
    """Run the canary for one source. Returns True on success."""
    cls = get(slug)
    if not cls.canary_urls:
        _LOG.info("[%s] no canary URLs configured — skipping", slug)
        return True

    source = await db.sources.get(slug=slug)
    if source is None:
        _LOG.info("[%s] not yet registered in sources — skipping", slug)
        return True

    # Canary deliberately skips the proxy pool — we want to know whether
    # the source itself is reachable from our own egress, not whether a
    # random shared proxy still works.
    http = HttpClient(
        cls.rate,
        respect_robots=cls.respect_robots,
        http2=not cls.prefer_http_1_1,
        impersonate=cls.impersonate_browser,
    )
    crawler = cls(http)
    ok = True
    last_err: str | None = None
    try:
        for url in cls.canary_urls:
            from ..core.types import Listing

            listing = Listing(source_job_external_id="canary", detail_url=url)
            try:
                raw = await crawler.fetch_detail(listing)
                if raw is None:
                    raise RuntimeError("fetch_detail returned None")
                parsed = crawler.parse(raw)
                if parsed is None:
                    raise RuntimeError("parse returned None on canary URL")
            except Exception as exc:
                ok = False
                last_err = f"{type(exc).__name__}: {exc}"
                _LOG.warning("[%s] canary failed on %s: %s", slug, url, last_err)
                break
    finally:
        await http.aclose()

    await record_canary(db, source.id, ok=ok, error=last_err)
    if not ok:
        # The health code only marks-broken on 2 consecutive failures, so
        # we send an "early warning" mail every time the canary trips.
        await send_alert(
            subject=f"[job_crawler] canary failed for {slug}",
            body=(
                f"Canary for {slug} failed: {last_err}\n"
                f"Two consecutive failures will auto-disable the source."
            ),
        )
    return ok


async def _main(slugs: tuple[str, ...]) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s"
    )
    bad = 0
    async with JobCrawlerDB.from_env() as db:
        for slug in slugs:
            ok = await _check(db, slug)
            print(f"[{slug}] canary {'ok' if ok else 'FAIL'}")
            if not ok:
                bad += 1
    return 1 if bad else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="job_crawler.cli.canary")
    parser.add_argument(
        "selector",
        nargs="?",
        default="all",
        help="slug, list, or one of: all, all-stubs, ats, boards",
    )
    args = parser.parse_args()
    slugs = tuple(resolve_slugs(args.selector))
    sys.exit(asyncio.run(_main(slugs)))


if __name__ == "__main__":
    main()
