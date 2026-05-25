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
from typing import Final, Literal

from job_crawler_db import JobCrawlerDB

from ..alerts.email import send_alert
from ..core.health import record_canary
from ..core.http import HttpClient
from ..registry import get, resolve_slugs

_LOG: Final = logging.getLogger("job_crawler.cli.canary")

# A canary run has three terminal states, not two (Finding 17):
#   * "ok"               — fetch + parse succeeded on every canary URL.
#   * "fail"             — at least one canary URL didn't fetch or parse.
#   * "skipped_no_canary"— the crawler is implemented but ships no
#                          canary_urls. Counts as a non-ok health signal
#                          so it's visible on the dashboard, but doesn't
#                          send the failure alert (it's a code gap, not
#                          a site outage).
CanaryStatus = Literal["ok", "fail", "skipped_no_canary"]


async def _check(db: JobCrawlerDB, slug: str) -> CanaryStatus:
    """Run the canary for one source.

    Returns the terminal state for the run. The CLI sums these into an
    exit code (any "fail" → exit 1; any "skipped_no_canary" prints a
    warning but doesn't fail the run).
    """
    cls = get(slug)
    if not cls.canary_urls:
        # Previously returned True ("ok") here — that hid the fact that
        # workday / successfactors / linkedin etc. were implemented but
        # never actually proved they could fetch + parse anything. Now
        # surface it both to the operator (log + stdout) and to the
        # health table (record_canary with ok=False + a marker error).
        _LOG.warning("[%s] no canary URLs configured — recording skipped state", slug)
        source = await db.sources.get(slug=slug)
        if source is not None:
            await record_canary(
                db, source.id, ok=False, error="skipped_no_canary",
            )
        return "skipped_no_canary"

    source = await db.sources.get(slug=slug)
    if source is None:
        _LOG.info("[%s] not yet registered in sources — skipping", slug)
        return "ok"

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
    return "ok" if ok else "fail"


async def _main(slugs: tuple[str, ...]) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s"
    )
    failed = 0
    skipped = 0
    async with JobCrawlerDB.from_env() as db:
        for slug in slugs:
            status = await _check(db, slug)
            print(f"[{slug}] canary {status}")
            if status == "fail":
                failed += 1
            elif status == "skipped_no_canary":
                skipped += 1
    if failed:
        return 1
    if skipped:
        # Implemented crawlers WITHOUT canary URLs are a code gap, not a
        # site outage. Exit nonzero so CI / cron status reflects the gap;
        # operator can either add canary URLs or accept the WARN.
        print(f"[canary] {skipped} source(s) had no canary URLs configured", file=sys.stderr)
        return 2
    return 0


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
