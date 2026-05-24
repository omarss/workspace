"""Skill extraction from posting descriptions.

How it works
------------
1. On startup we load every (id, slug, name, aliases) tuple from `skills`
   and `skill_aliases` into a single trie of normalised tokens.
2. For each posting we lower + unaccent the description, walk the token
   stream, and emit a hit whenever a node terminates a known skill.
3. For each hit we insert a `posting_skills_raw` row and a corresponding
   `job_skills` link (when the posting belongs to a cluster), defaulting
   to `requirement=preferred` and `confidence=0.85`.

Pure-Python, no spaCy / no model downloads. Catches the vast majority of
explicit skill mentions ("Python", "كوبرنيتيس", "k8s") with zero deps.
A model-based extractor can replace `_scan_tokens` later without changing
the public API.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from psycopg.rows import dict_row

from job_crawler_db import JobCrawlerDB, SkillRequirement

_LOG: Final = logging.getLogger("job_crawler.intelligence.skills")


@dataclass(slots=True)
class _TrieNode:
    """One node in the skill trie. `skill_id` is set on terminal nodes."""

    children: dict[str, _TrieNode] = field(default_factory=dict)
    skill_id: UUID | None = None
    skill_slug: str | None = None
    surface: str | None = None  # the surface form that terminates here


@dataclass(slots=True, frozen=True)
class SkillHit:
    skill_id: UUID
    skill_slug: str
    raw_phrase: str
    confidence: float


@dataclass(slots=True)
class ExtractionResult:
    posting_id: UUID
    cluster_job_id: UUID | None
    hits: list[SkillHit]


_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[\w]+|\S", re.UNICODE)


def _normalise(text: str) -> str:
    """Lowercase + strip Latin diacritics. Arabic untouched (the DB
    normalize_ar already handles it; we mirror that intent here)."""
    folded = unicodedata.normalize("NFKD", text)
    out = []
    for c in folded:
        if unicodedata.category(c) == "Mn":
            continue
        out.append(c)
    return "".join(out).lower()


def _tokenize(text: str) -> list[str]:
    return [_normalise(t) for t in _TOKEN_RE.findall(text) if t.strip()]


class SkillExtractor:
    """Loads the skill taxonomy once, then scans posting bodies on demand."""

    __slots__ = ("_root", "_size")

    def __init__(self) -> None:
        self._root = _TrieNode()
        self._size = 0

    async def load(self, db: JobCrawlerDB) -> None:
        """Populate the trie from `skills` + `skill_aliases`."""
        async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT s.id::text  AS skill_id,
                       s.slug      AS slug,
                       s.name_en   AS surface
                FROM   skills s
                WHERE  s.is_active
                UNION ALL
                SELECT s.id::text, s.slug, sa.alias
                FROM   skills s JOIN skill_aliases sa ON sa.skill_id = s.id
                WHERE  s.is_active
                """
            )
            for row in await cur.fetchall():
                self._add(UUID(row["skill_id"]), row["slug"], row["surface"])
        _LOG.info("skill extractor loaded %d surface forms", self._size)

    def _add(self, skill_id: UUID, slug: str, surface: str) -> None:
        toks = _tokenize(surface)
        if not toks:
            return
        node = self._root
        for tok in toks:
            node = node.children.setdefault(tok, _TrieNode())
        # If two skills collide on the same surface, last one wins; this is
        # extremely rare and not worth a conflict-resolution dance.
        node.skill_id = skill_id
        node.skill_slug = slug
        node.surface = surface
        self._size += 1

    def scan(self, text: str | None) -> list[SkillHit]:
        if not text or self._size == 0:
            return []
        toks = _tokenize(text)
        hits: list[SkillHit] = []
        seen: set[UUID] = set()
        i = 0
        while i < len(toks):
            node = self._root.children.get(toks[i])
            if node is None:
                i += 1
                continue
            longest_match: tuple[int, _TrieNode] | None = None
            if node.skill_id is not None:
                longest_match = (i + 1, node)
            j = i + 1
            while j < len(toks) and toks[j] in node.children:
                node = node.children[toks[j]]
                j += 1
                if node.skill_id is not None:
                    longest_match = (j, node)
            if longest_match is not None:
                end, matched = longest_match
                assert matched.skill_id is not None
                assert matched.skill_slug is not None
                if matched.skill_id not in seen:
                    seen.add(matched.skill_id)
                    hits.append(SkillHit(
                        skill_id=matched.skill_id,
                        skill_slug=matched.skill_slug,
                        raw_phrase=matched.surface or "",
                        confidence=0.85,
                    ))
                i = end
            else:
                i += 1
        return hits

    async def apply_to_posting(
        self,
        db: JobCrawlerDB,
        posting_id: UUID,
        body: str | None,
        *,
        cluster_job_id: UUID | None,
    ) -> list[SkillHit]:
        """Scan one posting + persist hits to posting_skills_raw + job_skills."""
        hits = self.scan(body)
        if not hits:
            return []
        for hit in hits:
            try:
                await db.postings.add_raw_skill(
                    posting_id, hit.raw_phrase,
                    skill_id=hit.skill_id, confidence=hit.confidence,
                )
                if cluster_job_id is not None:
                    await db.jobs.link_skill(
                        cluster_job_id, hit.skill_id,
                        requirement=SkillRequirement.preferred,
                        confidence=hit.confidence,
                    )
            except Exception:
                _LOG.exception("failed to record skill %s for posting %s",
                               hit.skill_slug, posting_id)
        return hits


# ---------------------------------------------------------------------------
# Batch helper for the CLI
# ---------------------------------------------------------------------------


async def backfill_all(
    db: JobCrawlerDB,
    *,
    batch_size: int = 500,
    only_unscanned: bool = True,
    limit: int | None = None,
) -> int:
    """Run the extractor across every posting (or only those without
    `posting_skills_raw` rows yet). Returns the count of hits inserted.
    """
    extractor = SkillExtractor()
    await extractor.load(db)
    if extractor._size == 0:
        _LOG.info("skill taxonomy is empty; nothing to extract")
        return 0
    total_hits = 0
    processed = 0
    seen_postings = 0
    sql = (
        "SELECT id, description, cluster_job_id "
        "FROM   job_postings p "
        + ("WHERE NOT EXISTS (SELECT 1 FROM posting_skills_raw r WHERE r.posting_id = p.id) "
           if only_unscanned else "")
        + "ORDER BY first_seen_at DESC"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"

    async with db.pool.connection() as conn, conn.cursor(row_factory=dict_row, name="skills_scan") as cur:
        await cur.execute(sql)
        while batch := await cur.fetchmany(batch_size):
            for row in batch:
                seen_postings += 1
                hits = await extractor.apply_to_posting(
                    db, row["id"], row["description"],
                    cluster_job_id=row["cluster_job_id"],
                )
                if hits:
                    processed += 1
                    total_hits += len(hits)
    _LOG.info(
        "skill extractor: scanned=%d, postings_with_hits=%d, total_hits=%d",
        seen_postings, processed, total_hits,
    )
    return total_hits


_ = asyncio  # keep the import alive for future helpers
