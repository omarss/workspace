"""`python -m job_crawler.cli.proxies {refresh,stats,clear-blacklist}`

Manage the rotating proxy pool used by `use_proxy_pool=True` crawlers.

Commands:
    refresh           — pull fresh lists from the default sources, persist state
    stats             — print pool size / blacklist count / hit rate
    clear-blacklist   — remove every proxy currently blacklisted (fresh start)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from ..core.proxy import DEFAULT_SOURCES, ProxyPool, build_default_pool

_STATE = Path(__file__).resolve().parents[3] / ".cache" / "proxy_pool.json"


async def _refresh() -> int:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    pool = await build_default_pool(state_file=_STATE)
    print(await pool.stats())
    await pool.save_state(_STATE)
    return 0


async def _validate(max_to_test: int | None) -> int:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    pool = ProxyPool()
    if _STATE.is_file():
        await pool.load_state(_STATE)
    res = await pool.validate(max_to_test=max_to_test)
    print(res)
    print(await pool.stats())
    await pool.save_state(_STATE)
    return 0


async def _stats() -> int:
    pool = ProxyPool()
    if _STATE.is_file():
        n = await pool.load_state(_STATE)
        print(f"loaded {n} proxies from {_STATE}")
    else:
        print(f"no state file at {_STATE} — run `proxies refresh` first")
    print(await pool.stats())
    return 0


async def _clear_blacklist() -> int:
    if not _STATE.is_file():
        print(f"no state at {_STATE}")
        return 0
    import json

    snapshot = json.loads(_STATE.read_text("utf-8"))
    cleared = 0
    for meta in snapshot.values():
        if meta.get("blacklisted_at") is not None:
            meta["blacklisted_at"] = None
            meta["blacklist_reason"] = None
            meta["failures_consec"] = 0
            cleared += 1
    _STATE.write_text(json.dumps(snapshot, indent=2))
    print(f"cleared blacklist on {cleared} proxies")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="job_crawler.cli.proxies")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh", help=f"pull fresh lists from {len(DEFAULT_SOURCES)} sources")
    sub.add_parser("stats", help="print pool stats")
    sub.add_parser("clear-blacklist", help="unblacklist every proxy")
    validate_p = sub.add_parser(
        "validate",
        help="probe each non-blacklisted proxy and cull the dead ones",
    )
    validate_p.add_argument(
        "--max", type=int, default=None,
        help="cap the number of proxies to probe in this pass",
    )
    args = p.parse_args()
    if args.cmd == "validate":
        sys.exit(asyncio.run(_validate(args.max)))
    sys.exit(asyncio.run({
        "refresh": _refresh,
        "stats": _stats,
        "clear-blacklist": _clear_blacklist,
    }[args.cmd]()))


if __name__ == "__main__":
    main()
