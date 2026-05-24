"""Skills repo — canonical taxonomy + aliases."""

from __future__ import annotations

from uuid import UUID

from ..enums import SkillKind
from ..models import Skill, SkillAlias
from .base import Repo


class SkillsRepo(Repo):
    async def create(
        self,
        *,
        slug: str,
        name_en: str,
        kind: SkillKind,
        name_ar: str | None = None,
        description: str | None = None,
        esco_uri: str | None = None,
        onet_code: str | None = None,
        parent_id: UUID | None = None,
    ) -> Skill:
        row = await self._fetchone(
            """
            INSERT INTO skills (slug, name_en, name_ar, kind, description,
                                esco_uri, onet_code, parent_id)
            VALUES (%(slug)s, %(en)s, %(ar)s, %(kind)s, %(d)s,
                    %(esco)s, %(onet)s, %(pid)s)
            ON CONFLICT (slug) DO UPDATE SET
                name_en = EXCLUDED.name_en,
                name_ar = EXCLUDED.name_ar,
                kind    = EXCLUDED.kind
            RETURNING *;
            """,
            {
                "slug": slug,
                "en": name_en,
                "ar": name_ar,
                "kind": kind.value,
                "d": description,
                "esco": esco_uri,
                "onet": onet_code,
                "pid": parent_id,
            },
        )
        assert row is not None
        return Skill.model_validate(row)

    async def get(self, skill_id: UUID) -> Skill | None:
        row = await self._fetchone("SELECT * FROM skills WHERE id = %(id)s", {"id": skill_id})
        return self._to_model(Skill, row)

    async def get_by_slug(self, slug: str) -> Skill | None:
        row = await self._fetchone("SELECT * FROM skills WHERE slug = %(s)s", {"s": slug})
        return self._to_model(Skill, row)

    async def find(
        self,
        query: str,
        *,
        kind: SkillKind | None = None,
        limit: int = 10,
        min_similarity: float = 0.4,
        max_edit_distance: int = 2,
    ) -> list[tuple[Skill, float]]:
        """Fuzzy search across name_en, name_ar, and aliases.

        Combines three signals — each contributes to the score and any one
        of them can cause the row to be recalled:

          * `word_similarity` (trigram, substring-aware) — great for short
            queries like "lead" → "Leadership".
          * `similarity`      (trigram, whole-string) — tie-breaker.
          * `levenshtein`     (edit distance) — catches single-letter typos
            and transpositions that share too few trigrams to match (e.g.
            "Pyhton" vs "python").

        `max_edit_distance` bounds the levenshtein search (default 2 = up
        to two single-char edits, which is the right ceiling for skill names).

        Restricts to a specific `kind` when given.
        """
        rows = await self._fetchall(
            """
            WITH q AS (SELECT normalize_text(%(q)s) AS nq),
            candidates AS (
                SELECT s.id,
                       GREATEST(
                         COALESCE(word_similarity(q.nq, normalize_en(s.name_en)), 0),
                         COALESCE(word_similarity(q.nq, normalize_ar(s.name_ar)), 0),
                         COALESCE((
                             SELECT MAX(word_similarity(q.nq, normalize_text(sa.alias)))
                             FROM skill_aliases sa WHERE sa.skill_id = s.id
                         ), 0),
                         COALESCE(similarity(normalize_en(s.name_en), q.nq), 0),
                         COALESCE(similarity(normalize_ar(s.name_ar), q.nq), 0),
                         -- Levenshtein-derived similarity: 1 - editdist/max_len.
                         -- Guarded by length(...) > 0 to avoid divide-by-zero.
                         CASE WHEN length(q.nq) > 0 AND length(normalize_en(s.name_en)) > 0
                              THEN 1.0
                                   - levenshtein_less_equal(
                                       q.nq, normalize_en(s.name_en), %(max_ed)s
                                     )::float
                                   / GREATEST(length(q.nq), length(normalize_en(s.name_en)))::float
                              ELSE 0 END
                       ) AS sim
                FROM skills s, q
                WHERE s.is_active
                  AND (%(kind)s::text IS NULL OR s.kind = %(kind)s::skill_kind)
                  AND (
                       q.nq <%% normalize_en(s.name_en)
                    OR q.nq <%% normalize_ar(s.name_ar)
                    OR normalize_en(s.name_en) %% q.nq
                    OR normalize_ar(s.name_ar) %% q.nq
                    OR EXISTS (
                         SELECT 1 FROM skill_aliases sa
                         WHERE sa.skill_id = s.id
                           AND (q.nq <%% normalize_text(sa.alias)
                                OR normalize_text(sa.alias) %% q.nq)
                       )
                    -- Length pre-filter avoids running levenshtein on
                    -- obviously-different strings.
                    OR (
                        length(q.nq) > 0
                        AND abs(length(q.nq) - length(normalize_en(s.name_en))) <= %(max_ed)s
                        AND levenshtein_less_equal(
                              q.nq, normalize_en(s.name_en), %(max_ed)s
                            ) <= %(max_ed)s
                    )
                  )
            )
            SELECT s.*, cand.sim
            FROM candidates cand JOIN skills s ON s.id = cand.id
            WHERE cand.sim >= %(min_sim)s
            ORDER BY cand.sim DESC LIMIT %(lim)s;
            """,
            {
                "q": query,
                "kind": kind.value if kind else None,
                "min_sim": min_similarity,
                "max_ed": max_edit_distance,
                "lim": limit,
            },
        )
        out: list[tuple[Skill, float]] = []
        for row in rows:
            sim = float(row.pop("sim"))
            out.append((Skill.model_validate(row), sim))
        return out

    async def add_alias(
        self,
        skill_id: UUID,
        alias: str,
        *,
        locale: str | None = None,
    ) -> SkillAlias:
        row = await self._fetchone(
            """
            INSERT INTO skill_aliases (skill_id, alias, locale)
            VALUES (%(sid)s, %(a)s, %(loc)s)
            ON CONFLICT (skill_id, alias) DO UPDATE SET
                locale = COALESCE(EXCLUDED.locale, skill_aliases.locale)
            RETURNING *;
            """,
            {"sid": skill_id, "a": alias, "loc": locale},
        )
        assert row is not None
        return SkillAlias.model_validate(row)

    async def list_aliases(self, skill_id: UUID) -> list[SkillAlias]:
        rows = await self._fetchall(
            "SELECT * FROM skill_aliases WHERE skill_id = %(s)s ORDER BY created_at",
            {"s": skill_id},
        )
        return self._to_models(SkillAlias, rows)

    async def list_children(self, parent_id: UUID) -> list[Skill]:
        rows = await self._fetchall(
            "SELECT * FROM skills WHERE parent_id = %(p)s ORDER BY name_en",
            {"p": parent_id},
        )
        return self._to_models(Skill, rows)
