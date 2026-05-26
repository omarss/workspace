"""`python -m job_crawler.cli.intelligence [--skills] [--enrich] [--dedup] [--all]`

Runs the post-processing intelligence layer over the existing data:
  --skills   extract skills from descriptions, fill job_skills
  --enrich   recover salary/experience/education from free-text, normalize titles
  --dedup    find cross-source duplicates, record edges, merge clusters
  --all      shorthand for everything
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from job_crawler_db import JobCrawlerDB

from ..intelligence import pipeline


async def _main(*, skills: bool, enrich: bool, do_dedup: bool, limit: int | None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    async with JobCrawlerDB.from_env() as db:
        summary = await pipeline.run_all(
            db,
            run_skills=skills, run_enrich=enrich, run_dedup=do_dedup,
            skill_limit=limit,
        )
    print(
        f"[intelligence] skill_hits={summary.skill_hits} "
        f"salary_recovered={summary.salary_recovered} "
        f"experience_recovered={summary.experience_recovered} "
        f"education_recovered={summary.education_recovered} "
        f"restrictions_recovered={summary.restrictions_recovered} "
        f"centroids_filled={summary.centroids_filled} "
        f"legit_scored={summary.legit_scored} "
        f"industries_classified={summary.industries_classified} "
        f"titles_normalized={summary.titles_normalized} "
        f"titles_depolluted={summary.titles_depolluted} "
        f"cities_resolved={summary.cities_resolved} "
        f"titles_decoded={summary.titles_decoded} "
        f"dedup_edges={summary.dedup_edges} "
        f"dedup_clusters_merged={summary.dedup_clusters_merged}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="job_crawler.cli.intelligence")
    parser.add_argument("--skills", action="store_true",
                        help="extract skills + fill job_skills")
    parser.add_argument("--enrich", action="store_true",
                        help="recover salary/experience/education + normalize titles")
    parser.add_argument("--dedup", action="store_true",
                        help="cross-source dedup + cluster merge")
    parser.add_argument("--all", action="store_true",
                        help="run every intelligence step")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of postings processed by --skills")
    args = parser.parse_args()
    skills = args.skills or args.all
    enrich = args.enrich or args.all
    do_dedup = args.dedup or args.all
    if not (skills or enrich or do_dedup):
        parser.error("specify at least one of --skills / --enrich / --dedup / --all")
    sys.exit(asyncio.run(_main(
        skills=skills, enrich=enrich, do_dedup=do_dedup, limit=args.limit,
    )))


if __name__ == "__main__":
    main()
