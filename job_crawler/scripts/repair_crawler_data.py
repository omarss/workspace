"""One-shot repair for the two correctness defects found in the 2026-05-30
data audit. Dry-run by default; pass --apply to mutate.

    uv run python -m scripts.repair_crawler_data          # dry-run (read-only)
    uv run python -m scripts.repair_crawler_data --apply  # execute

IMPORTANT — run order
---------------------
This MUST run AFTER the fixed code is deployed to the live crawler. The
hourly crawl tail-runs `intelligence.run_all`, which re-runs the
(previously buggy) dedup + title normalization every cycle. Repairing
before deploy means the next hourly run re-corrupts the same rows within
the hour.

What it repairs
---------------
1. Title corruption — clusters whose `title_en` was mangled by the old
   `normalize_title` ("Chef De Cuisine" -> "Chef Data Engineer Cuisine").
   Re-derives the cluster title from its canonical posting's raw title
   and re-applies the FIXED normalizer.

2. Over-merge — clusters that hold postings spanning more than one
   distinct role (by `_core_role_tokens`). The largest role-group keeps
   the original cluster; every other role-group is split into its own
   cluster so the distinct jobs reappear in search / the feed.

Both passes are idempotent: a clean DB yields zero changes.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from uuid import UUID

from psycopg.rows import dict_row

from job_crawler.intelligence.dedup import _core_role_tokens
from job_crawler.intelligence.title_norm import normalize_title
from job_crawler_db import JobCrawlerDB, Settings


async def _repair_titles(db: JobCrawlerDB, *, apply: bool) -> int:
    """Re-derive cluster title_en from the canonical posting's raw title
    (which was never corrupted) and re-apply the fixed normalizer.
    Returns the number of clusters whose title changed."""
    changed = 0
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT j.id, j.title_en, p.title AS raw_title
            FROM   jobs j
            JOIN   job_postings p ON p.id = j.canonical_posting_id
            WHERE  j.title_en IS NOT NULL
              AND  p.title IS NOT NULL
            """,
        )
        rows = await cur.fetchall()

    for row in rows:
        raw = row["raw_title"]
        fixed = normalize_title(raw) or raw
        if fixed == row["title_en"]:
            continue
        changed += 1
        print(f"  title: {row['title_en']!r} -> {fixed!r}")
        if apply:
            async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE jobs SET title_en = %(t)s WHERE id = %(j)s",
                    {"t": fixed, "j": row["id"]},
                )
    return changed


async def _over_merged_clusters(db: JobCrawlerDB) -> dict[UUID, dict[frozenset[str], list[UUID]]]:
    """Return {cluster_id: {core_role_tokens: [posting_id, ...]}} for every
    cluster whose postings span more than one distinct role."""
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT cluster_job_id, id AS posting_id, title
            FROM   job_postings
            WHERE  cluster_job_id IS NOT NULL
            ORDER  BY first_seen_at
            """,
        )
        rows = await cur.fetchall()

    by_cluster: dict[UUID, dict[frozenset[str], list[UUID]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        tokens = _core_role_tokens(row["title"])
        by_cluster[row["cluster_job_id"]][tokens].append(row["posting_id"])

    # Keep only clusters with >1 distinct role group.
    return {cid: groups for cid, groups in by_cluster.items() if len(groups) > 1}


async def _repair_over_merges(db: JobCrawlerDB, *, apply: bool) -> int:
    """Split over-merged clusters: largest role-group keeps the cluster,
    each other group is detached into its own cluster. Returns the number
    of new clusters created (== number of role-groups split off)."""
    over = await _over_merged_clusters(db)
    split_count = 0

    for cluster_id, groups in over.items():
        # Largest group stays; order the rest deterministically.
        ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), sorted(kv[0])))
        keep_tokens, keep_ids = ordered[0]
        split_groups = ordered[1:]
        print(
            f"  over-merge: cluster {cluster_id} has {len(groups)} roles; "
            f"keeping {sorted(keep_tokens)} ({len(keep_ids)} postings), "
            f"splitting {len(split_groups)} group(s)"
        )
        for tokens, posting_ids in split_groups:
            print(f"      -> split {sorted(tokens)}: {len(posting_ids)} posting(s)")
            if not apply:
                split_count += 1
                continue
            seed, *rest = posting_ids
            # Detach the whole group, then bootstrap a fresh cluster from
            # the seed and re-attach the rest to it.
            async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE job_postings SET cluster_job_id = NULL "
                    "WHERE id = ANY(%(ids)s)",
                    {"ids": posting_ids},
                )
            new_cluster = await db.jobs.create_from_posting(seed)
            if rest:
                async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "UPDATE job_postings SET cluster_job_id = %(c)s "
                        "WHERE id = ANY(%(ids)s)",
                        {"c": new_cluster.id, "ids": rest},
                    )
            await db.jobs.recompute_canonical(new_cluster.id)
            split_count += 1
        # Re-derive the surviving cluster's canonical fields.
        if apply:
            await db.jobs.recompute_canonical(cluster_id)

    return split_count


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== repair_crawler_data ({mode}) ===")

    async with JobCrawlerDB(Settings.from_env()) as db:
        print("\n[1] Title corruption repair")
        titles = await _repair_titles(db, apply=args.apply)
        print(f"    {titles} cluster title(s) {'fixed' if args.apply else 'would be fixed'}")

        print("\n[2] Over-merge split")
        splits = await _repair_over_merges(db, apply=args.apply)
        print(f"    {splits} new cluster(s) {'created' if args.apply else 'would be created'}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply AFTER the fix is deployed.")


if __name__ == "__main__":
    asyncio.run(main())
