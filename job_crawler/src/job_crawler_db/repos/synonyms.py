"""Synonyms repo — query-expansion thesaurus.

The expansion API is the single most important method here; it's what the
search layer calls before building a tsquery. Returns the *normalized*
forms of every sibling term so the app can OR them into the final query.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from ..enums import SynonymKind, SynonymRelation
from ..models import SynonymGroup, SynonymTerm
from .base import Repo


class SynonymsRepo(Repo):
    # -- group + term writes --------------------------------------------

    async def create_group(
        self,
        *,
        canonical_term: str,
        kind: SynonymKind = SynonymKind.general,
        canonical_locale: str | None = None,
        terms: Iterable[tuple[str, str | None]] | None = None,
        skill_id: UUID | None = None,
        company_id: UUID | None = None,
        category_code: str | None = None,
        notes: str | None = None,
    ) -> SynonymGroup:
        """Create a group plus (optionally) its initial member terms.

        `terms` is an iterable of `(term, locale_or_None)` pairs.
        """
        row = await self._fetchone(
            """
            INSERT INTO synonym_groups
              (canonical_term, canonical_locale, kind, notes,
               skill_id, company_id, category_code)
            VALUES (%(t)s, %(loc)s, %(k)s, %(n)s, %(sid)s, %(cid)s, %(cat)s)
            RETURNING *;
            """,
            {
                "t": canonical_term,
                "loc": canonical_locale,
                "k": kind.value,
                "n": notes,
                "sid": skill_id,
                "cid": company_id,
                "cat": category_code,
            },
        )
        assert row is not None
        group = SynonymGroup.model_validate(row)

        if terms:
            for term, locale in terms:
                await self.add_term(group.id, term, locale=locale)
        return group

    async def add_term(
        self,
        group_id: UUID,
        term: str,
        *,
        locale: str | None = None,
        relation: SynonymRelation = SynonymRelation.synonym,
        weight: Decimal | float = Decimal("1.000"),
    ) -> SynonymTerm:
        row = await self._fetchone(
            """
            INSERT INTO synonym_terms (group_id, term, locale, relation, weight)
            VALUES (%(g)s, %(t)s, %(loc)s, %(r)s, %(w)s)
            ON CONFLICT (group_id, term) DO UPDATE SET
                locale   = COALESCE(EXCLUDED.locale, synonym_terms.locale),
                relation = EXCLUDED.relation,
                weight   = EXCLUDED.weight
            RETURNING *;
            """,
            {
                "g": group_id,
                "t": term,
                "loc": locale,
                "r": relation.value,
                "w": Decimal(str(weight)),
            },
        )
        assert row is not None
        return SynonymTerm.model_validate(row)

    async def get_group(self, group_id: UUID) -> SynonymGroup | None:
        row = await self._fetchone(
            "SELECT * FROM synonym_groups WHERE id = %(g)s",
            {"g": group_id},
        )
        return self._to_model(SynonymGroup, row)

    async def list_terms(self, group_id: UUID) -> list[SynonymTerm]:
        rows = await self._fetchall(
            "SELECT * FROM synonym_terms WHERE group_id = %(g)s ORDER BY term",
            {"g": group_id},
        )
        return self._to_models(SynonymTerm, rows)

    # -- the expansion query --------------------------------------------

    async def expand(
        self,
        term: str,
        *,
        kind: SynonymKind | None = None,
        locale: str | None = None,
        include_query: bool = True,
        min_weight: float = 0.0,
    ) -> list[tuple[str, str | None, float]]:
        """Return sibling terms in the same group as `term`.

        Each result is `(term, locale, weight)`. When `include_query` is
        True the input term is included in position 0 (with weight 1.0)
        so the caller can use the result directly as an OR-set without a
        merge step.

        Matching is exact-after-normalization plus trigram-similar (so
        misspelled inputs still find their group).
        """
        rows = await self._fetchall(
            """
            WITH q AS (SELECT normalize_text(%(q)s) AS nq),
            matched_groups AS (
                SELECT DISTINCT group_id
                FROM synonym_terms t1, q
                WHERE (normalize_text(t1.term) = q.nq
                       OR normalize_text(t1.term) %% q.nq)
            )
            SELECT t2.term, t2.locale, t2.weight,
                   g.kind AS group_kind
            FROM matched_groups mg
            JOIN synonym_groups g  ON g.id = mg.group_id AND g.is_active
            JOIN synonym_terms  t2 ON t2.group_id = mg.group_id
            WHERE (%(kind)s::synonym_kind IS NULL OR g.kind = %(kind)s::synonym_kind)
              AND (%(loc)s::text IS NULL OR t2.locale IS NULL OR t2.locale = %(loc)s)
              AND t2.weight >= %(min_w)s
            ORDER BY t2.weight DESC, t2.term;
            """,
            {
                "q": term,
                "kind": kind.value if kind else None,
                "loc": locale,
                "min_w": min_weight,
            },
        )
        results: list[tuple[str, str | None, float]] = [
            (r["term"], r["locale"], float(r["weight"])) for r in rows
        ]

        if include_query:
            # Put the user's exact input first; dedupe is by normalized term.
            normalized_input = await self._normalize_text(term)
            seen = {normalized_input}
            keep: list[tuple[str, str | None, float]] = [(term, None, 1.0)]
            for t, loc, w in results:
                n = await self._normalize_text(t)
                if n in seen:
                    continue
                seen.add(n)
                keep.append((t, loc, w))
            return keep
        return results

    async def _normalize_text(self, raw: str) -> str:
        row = await self._fetchone(
            "SELECT normalize_text(%(q)s) AS n",
            {"q": raw},
        )
        assert row is not None
        return str(row["n"])
