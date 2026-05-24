"""Dedupe repo — pairwise similarity evidence between postings."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from ..enums import DuplicateReason
from ..models import DuplicateEdge
from .base import Repo


class DedupeRepo(Repo):
    async def add_edge(
        self,
        posting_a: UUID,
        posting_b: UUID,
        *,
        reason: DuplicateReason,
        similarity: Decimal | float,
        detector_version: str = "v1",
    ) -> DuplicateEdge:
        """Record a similarity edge between two postings.

        Canonicalises the (a,b) order to satisfy the schema's `a < b`
        CHECK constraint, so callers can pass them in any order.
        """
        a, b = sorted((str(posting_a), str(posting_b)))
        row = await self._fetchone(
            """
            INSERT INTO posting_duplicate_edges
              (posting_a_id, posting_b_id, reason, similarity, detector_version)
            VALUES (%(a)s, %(b)s, %(r)s, %(s)s, %(v)s)
            ON CONFLICT (posting_a_id, posting_b_id, reason) DO UPDATE SET
                similarity      = EXCLUDED.similarity,
                detector_version= EXCLUDED.detector_version,
                detected_at     = now()
            RETURNING *;
            """,
            {
                "a": a,
                "b": b,
                "r": reason.value,
                "s": Decimal(str(similarity)),
                "v": detector_version,
            },
        )
        assert row is not None
        return DuplicateEdge.model_validate(row)

    async def list_edges_for(self, posting_id: UUID) -> list[DuplicateEdge]:
        rows = await self._fetchall(
            """
            SELECT * FROM posting_duplicate_edges
            WHERE posting_a_id = %(p)s OR posting_b_id = %(p)s
            ORDER BY similarity DESC;
            """,
            {"p": posting_id},
        )
        return self._to_models(DuplicateEdge, rows)

    async def find_cluster_candidates(
        self,
        posting_id: UUID,
        *,
        min_similarity: float = 0.7,
    ) -> list[UUID]:
        """Return ids of postings linked to `posting_id` strongly enough to
        merge into the same cluster. Used by the clustering job."""
        rows = await self._fetchall(
            """
            SELECT CASE WHEN posting_a_id = %(p)s
                        THEN posting_b_id
                        ELSE posting_a_id END AS other_id
            FROM posting_duplicate_edges
            WHERE (%(p)s IN (posting_a_id, posting_b_id))
              AND similarity >= %(min_s)s;
            """,
            {"p": posting_id, "min_s": min_similarity},
        )
        return [row["other_id"] for row in rows]
