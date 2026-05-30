"""Cross-source cluster deduplication.

The crawler ingests every posting as its own 1-row cluster (see
`runner.py`). This module finds *the same job* posted on multiple sources
and merges them into a single cluster via the existing
`db.jobs.merge()` machinery + `posting_duplicate_edges` evidence rows.

Signals (in priority order — first hit wins per pair)
-----------------------------------------------------
1. **exact content_hash** — identical normalised description body. The
   strongest signal (e.g. one human pasted the same blurb into Bayt and
   LinkedIn). similarity=1.0.
2. **title trigram + company + city (both resolved & matching)** — the
   conservative workhorse. Title sim ≥ 0.60 and the candidates share
   the resolved `company_id` and `city_id`. similarity = title sim.
3. **title trigram + company + city loose** — same shape as stage 2
   but the city filter is relaxed: city must either match OR be NULL
   on one side. Title threshold is raised to ≥ 0.85 to compensate
   for the looser geo signal. Catches the common "recycled" pattern
   where the same role is reposted on a second source that didn't
   resolve the city (e.g. ATS posting with location="Remote" + Bayt
   repost with location="Riyadh, Saudi Arabia"), AND the pattern
   where the same role is reposted weeks later with minor title
   rewording ("Senior Python Engineer" → "Sr. Python Engineer").

For every pair that fires, we:
  * insert a `posting_duplicate_edges` row (with the reason + similarity)
  * pick the canonical cluster (the one belonging to the highest-trust
    source's posting) and merge the other(s) into it via `db.jobs.merge`.

Run via:
    python -m job_crawler.cli.intelligence --dedup
    make intelligence-dedup
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import UUID

from psycopg.rows import dict_row

from job_crawler_db import DuplicateReason, JobCrawlerDB

from .title_norm import normalize_title

_LOG: Final = logging.getLogger("job_crawler.intelligence.dedup")


# ---------------------------------------------------------------------------
# Content-token guard — defends against trigram over-merging
# ---------------------------------------------------------------------------
#
# Trigram title similarity alone CANNOT separate true duplicates from
# distinct-but-templated roles (measured on live data: false merges land
# 0.64-0.78, true rewordings 0.68-0.92 — fully overlapping). Boilerplate-
# heavy titles like "Service Associate - Carpenter" vs
# "Service Associate - Service Center" (sim 0.77), or
# "Associate Accountant - Builders Program" vs
# "Compliance Associate - Builders Program" (sim 0.67), clear the 0.60
# floor and get wrongly merged — hiding genuinely distinct jobs from
# search and the Telegram feed.
#
# The fix: trigram stays as a cheap candidate generator, but the actual
# merge decision compares the *core content tokens* of the two titles.
# Two titles are the same role only when their content-token SETS are
# equal. Seniority words are kept (and canonicalised via normalize_title,
# so "Sr" == "Senior"), because "Sales Executive" and "Senior Sales
# Executive" are different roles. Pure noise — connective stopwords,
# level markers (roman numerals / "Level N"), and internal job codes
# (alphanumeric tokens containing a digit, e.g. "B2B011") — is dropped so
# it never blocks a genuine duplicate.

# Connectives + structural words that carry no role meaning.
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {"and", "or", "of", "the", "to", "for", "in", "at", "a", "an", "with", "&"}
)

# Level markers stripped so "Engineer II" == "Engineer". Roman numerals
# i-v plus "level"; ordinals like "2nd" are dropped by the digit rule below.
_LEVEL_TOKENS: Final[frozenset[str]] = frozenset(
    {"i", "ii", "iii", "iv", "v", "level", "l1", "l2", "l3", "l4", "l5"}
)

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


def _core_role_tokens(title: str | None) -> frozenset[str]:
    """Reduce a title to its set of meaningful role tokens.

    Pipeline: seniority-abbreviation expansion (via `normalize_title`,
    so "Sr" → "Senior"), lowercase, tokenise on alphanumerics, then drop
    stopwords, level markers, and internal job codes (tokens containing a
    digit). Returns a frozenset — order and repetition don't matter for
    "is this the same role?".
    """
    normalised = normalize_title(title) or (title or "")
    tokens: set[str] = set()
    for tok in _WORD_RE.findall(normalised.lower()):
        if tok in _STOPWORDS or tok in _LEVEL_TOKENS:
            continue
        if any(ch.isdigit() for ch in tok):
            # Internal req codes ("b2b011"), ordinals ("2nd"), etc.
            continue
        tokens.add(tok)
    return frozenset(tokens)


def _same_core_role(title_a: str | None, title_b: str | None) -> bool:
    """True when two titles describe the same role.

    Same role iff their core-token sets are equal AND non-empty. An empty
    set on either side (e.g. a title that was nothing but a job code)
    cannot be confidently matched, so we refuse the merge — biasing
    towards keeping distinct postings separate (zero tolerance for hiding
    a real job).
    """
    a = _core_role_tokens(title_a)
    b = _core_role_tokens(title_b)
    return bool(a) and a == b


@dataclass(slots=True)
class DedupSummary:
    pairs_considered: int = 0
    edges_recorded: int = 0
    clusters_merged: int = 0


# ---------------------------------------------------------------------------
# Stage 1: exact content_hash matches
# ---------------------------------------------------------------------------


async def _dedupe_by_content_hash(db: JobCrawlerDB, summary: DedupSummary) -> None:
    """Every set of postings sharing a content_hash → all merge into one cluster."""
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            WITH grp AS (
                SELECT content_hash,
                       array_agg(id ORDER BY first_seen_at) AS posting_ids,
                       COUNT(*) AS n
                FROM   job_postings
                WHERE  content_hash IS NOT NULL
                  AND  cluster_job_id IS NOT NULL
                GROUP  BY content_hash
                HAVING COUNT(*) >= 2
            )
            SELECT posting_ids FROM grp;
            """
        )
        groups = [row["posting_ids"] for row in await cur.fetchall()]

    for ids in groups:
        await _merge_postings(
            db, ids, reason=DuplicateReason.exact_content_hash, similarity=Decimal("1.000"),
            summary=summary,
        )


# ---------------------------------------------------------------------------
# Stage 2: title trigram + company + city
# ---------------------------------------------------------------------------


async def _dedupe_by_title_company_loc(
    db: JobCrawlerDB,
    summary: DedupSummary,
    *,
    min_title_similarity: float = 0.6,
) -> None:
    """For every posting, find peers sharing (company_id, city_id) whose
    title's trigram similarity ≥ threshold. Each match becomes an edge +
    a candidate merge. Runs in O(N) over postings; the pg_trgm index on
    job_postings(normalize_text(title)) makes the per-posting lookup fast.
    """
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            WITH pairs AS (
                SELECT a.id              AS a_id,
                       b.id              AS b_id,
                       a.cluster_job_id  AS a_cluster,
                       b.cluster_job_id  AS b_cluster,
                       a.title           AS a_title,
                       b.title           AS b_title,
                       similarity(normalize_text(a.title), normalize_text(b.title)) AS sim
                FROM   job_postings a
                JOIN   job_postings b
                  ON   b.id > a.id                          -- canonical ordering
                  AND  b.company_id IS NOT DISTINCT FROM a.company_id
                  AND  b.city_id    IS NOT DISTINCT FROM a.city_id
                  AND  a.company_id IS NOT NULL             -- skip "no company" matches
                  AND  a.cluster_job_id <> b.cluster_job_id -- already same cluster?
                WHERE  a.cluster_job_id IS NOT NULL
                  AND  b.cluster_job_id IS NOT NULL
                  AND  normalize_text(a.title) %% normalize_text(b.title)
            )
            SELECT a_id, b_id, a_cluster, b_cluster, a_title, b_title, sim
            FROM   pairs
            WHERE  sim >= %(thr)s
            ORDER  BY sim DESC;
            """,
            {"thr": min_title_similarity},
        )
        pairs = list(await cur.fetchall())

    for row in pairs:
        summary.pairs_considered += 1
        # Trigram cleared the cheap pre-filter; the content-token guard is
        # the authoritative decision. Distinct-but-templated titles
        # (e.g. "Service Associate - Carpenter" vs "...- Service Center")
        # are rejected here so they stay separate jobs.
        if not _same_core_role(row["a_title"], row["b_title"]):
            _LOG.debug(
                "dedup: skip over-merge %r ↔ %r (sim=%.2f, core tokens differ)",
                row["a_title"], row["b_title"], row["sim"],
            )
            continue
        # Record the edge regardless of whether merging is possible.
        try:
            await db.dedupe.add_edge(
                row["a_id"], row["b_id"],
                reason=DuplicateReason.title_company_loc,
                similarity=Decimal(str(row["sim"])).quantize(Decimal("0.001")),
            )
            summary.edges_recorded += 1
        except Exception:
            _LOG.exception("could not record edge for %s ↔ %s",
                           row["a_id"], row["b_id"])
        # Merge clusters, picking the higher-trust cluster as the survivor.
        await _merge_clusters_for_pair(db, row["a_cluster"], row["b_cluster"], summary)


# ---------------------------------------------------------------------------
# Stage 3: title trigram + company + city LOOSE
# ---------------------------------------------------------------------------


async def _dedupe_by_title_company_city_loose(
    db: JobCrawlerDB,
    summary: DedupSummary,
    *,
    min_title_similarity: float = 0.85,
) -> None:
    """Same shape as stage 2 but the city filter is relaxed: city must
    either match OR be NULL on one side. The title threshold is raised
    to 0.85 (vs stage 2's 0.60) to compensate for the looser geo signal.

    Catches the two main recycled-job patterns:
      * same role on direct ATS + aggregator, only one resolved the city
      * same company reposting the same role weeks later with minor
        title rewording ("Senior Python Engineer" → "Sr. Python Engineer")

    Stage 2 runs first; pairs it already merged share a `cluster_job_id`
    and are filtered out here by the `a.cluster_job_id <> b.cluster_job_id`
    clause, so this stage only sees the residual.
    """
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            WITH pairs AS (
                SELECT a.id              AS a_id,
                       b.id              AS b_id,
                       a.cluster_job_id  AS a_cluster,
                       b.cluster_job_id  AS b_cluster,
                       a.title           AS a_title,
                       b.title           AS b_title,
                       similarity(normalize_text(a.title), normalize_text(b.title)) AS sim
                FROM   job_postings a
                JOIN   job_postings b
                  ON   b.id > a.id                          -- canonical ordering
                  AND  b.company_id IS NOT DISTINCT FROM a.company_id
                  AND  a.company_id IS NOT NULL             -- skip "no company" matches
                  AND  a.cluster_job_id <> b.cluster_job_id
                  -- City loose: equal, or either side NULL.
                  AND  (a.city_id IS NOT DISTINCT FROM b.city_id
                        OR a.city_id IS NULL
                        OR b.city_id IS NULL)
                WHERE  a.cluster_job_id IS NOT NULL
                  AND  b.cluster_job_id IS NOT NULL
                  AND  normalize_text(a.title) %% normalize_text(b.title)
            )
            SELECT a_id, b_id, a_cluster, b_cluster, a_title, b_title, sim
            FROM   pairs
            WHERE  sim >= %(thr)s
            ORDER  BY sim DESC;
            """,
            {"thr": min_title_similarity},
        )
        pairs = list(await cur.fetchall())

    for row in pairs:
        summary.pairs_considered += 1
        # Same content-token guard as stage 2 — the looser geo filter here
        # makes over-merge protection even more important.
        if not _same_core_role(row["a_title"], row["b_title"]):
            _LOG.debug(
                "dedup(loose): skip over-merge %r ↔ %r (sim=%.2f, core tokens differ)",
                row["a_title"], row["b_title"], row["sim"],
            )
            continue
        try:
            await db.dedupe.add_edge(
                row["a_id"], row["b_id"],
                reason=DuplicateReason.title_company_loc,
                similarity=Decimal(str(row["sim"])).quantize(Decimal("0.001")),
            )
            summary.edges_recorded += 1
        except Exception:
            _LOG.exception("could not record edge for %s ↔ %s",
                           row["a_id"], row["b_id"])
        await _merge_clusters_for_pair(db, row["a_cluster"], row["b_cluster"], summary)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _merge_postings(
    db: JobCrawlerDB,
    posting_ids: list[UUID],
    *,
    reason: DuplicateReason,
    similarity: Decimal,
    summary: DedupSummary,
) -> None:
    """Treat all `posting_ids` as the same job: record pairwise edges,
    then merge their clusters down to one."""
    if len(posting_ids) < 2:
        return
    # Edges (canonical ordering enforced by add_edge).
    head = posting_ids[0]
    for other in posting_ids[1:]:
        summary.pairs_considered += 1
        try:
            await db.dedupe.add_edge(
                head, other, reason=reason, similarity=similarity,
            )
            summary.edges_recorded += 1
        except Exception:
            _LOG.exception("could not record %s edge", reason.value)

    # Clusters
    clusters: list[UUID] = []
    for pid in posting_ids:
        p = await db.postings.get(pid)
        if p and p.cluster_job_id and p.cluster_job_id not in clusters:
            clusters.append(p.cluster_job_id)
    if len(clusters) < 2:
        return
    target = await _pick_target_cluster(db, clusters)
    for c in clusters:
        if c == target:
            continue
        try:
            await db.jobs.merge(target=target, source=c)
            summary.clusters_merged += 1
        except Exception:
            _LOG.exception("merge %s → %s failed", c, target)


async def _merge_clusters_for_pair(
    db: JobCrawlerDB,
    a_cluster: UUID | None,
    b_cluster: UUID | None,
    summary: DedupSummary,
) -> None:
    if a_cluster is None or b_cluster is None or a_cluster == b_cluster:
        return
    # In a dedup batch, earlier merges may have deleted one or both of these
    # clusters. Skip cleanly if either is gone — the trigram pass picks up
    # the surviving cluster on its next iteration.
    a_alive = await db.jobs.get(a_cluster) is not None
    b_alive = await db.jobs.get(b_cluster) is not None
    if not (a_alive and b_alive):
        return
    target = await _pick_target_cluster(db, [a_cluster, b_cluster])
    source = b_cluster if target == a_cluster else a_cluster
    try:
        await db.jobs.merge(target=target, source=source)
        summary.clusters_merged += 1
    except KeyError:
        # Cluster vanished between alive-check and merge; harmless.
        return
    except Exception:
        _LOG.exception("merge %s → %s failed", source, target)


async def _pick_target_cluster(
    db: JobCrawlerDB,
    cluster_ids: list[UUID],
) -> UUID:
    """Pick the survivor when merging clusters.

    Tiering (highest wins):
      1. **directness tier** — `source.kind`. Government portals + ATSes
         + company-owned career pages are the canonical "apply directly"
         path; aggregators / regional / local boards are intermediates
         that repost what's elsewhere. Choosing the direct tier means
         the Telegram link a subscriber taps goes to the company's own
         application form, not to a Bayt/LinkedIn middleman that may
         require an aggregator account to apply.
      2. **trust_weight** — finer tiebreaker inside a tier (e.g. two
         ATSes; Greenhouse 0.95 wins over Workday 0.92).
      3. **posting_count** — bigger clusters absorb smaller ones so we
         preserve the most evidence.
      4. **first_seen_at** — oldest first as a deterministic last resort.
    """
    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT j.id,
                   CASE s.kind
                       WHEN 'gov_board'    THEN 3
                       WHEN 'ats'          THEN 2
                       WHEN 'company_site' THEN 2
                       ELSE 0
                   END                                  AS directness,
                   COALESCE(s.trust_weight, 0)::float   AS trust,
                   j.posting_count,
                   j.first_seen_at
            FROM   jobs j
            LEFT   JOIN job_postings p ON p.id = j.canonical_posting_id
            LEFT   JOIN sources s ON s.id = p.source_id
            WHERE  j.id = ANY(%(ids)s)
            ORDER  BY directness DESC, trust DESC, j.posting_count DESC, j.first_seen_at;
            """,
            {"ids": cluster_ids},
        )
        rows = await cur.fetchall()
    return rows[0]["id"] if rows else cluster_ids[0]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run(db: JobCrawlerDB) -> DedupSummary:
    summary = DedupSummary()
    _LOG.info("dedup: stage 1 — exact content_hash")
    await _dedupe_by_content_hash(db, summary)
    _LOG.info("dedup: stage 2 — title trigram + company + city")
    await _dedupe_by_title_company_loc(db, summary)
    _LOG.info("dedup: stage 3 — title trigram + company + city loose")
    await _dedupe_by_title_company_city_loose(db, summary)
    _LOG.info(
        "dedup done: pairs=%d edges=%d cluster_merges=%d",
        summary.pairs_considered, summary.edges_recorded, summary.clusters_merged,
    )
    return summary
