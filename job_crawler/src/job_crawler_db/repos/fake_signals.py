"""Fake-signal repo + cluster verdict recomputation."""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any
from uuid import UUID

from ..enums import ClusterVerdict, FakeSignalKind
from ..models import FakeSignal, Job
from .base import Repo


class FakeSignalsRepo(Repo):
    async def add(
        self,
        job_id: UUID,
        kind: FakeSignalKind,
        *,
        weight: Decimal | float,
        posting_id: UUID | None = None,
        details: dict[str, Any] | None = None,
        detector_version: str = "v1",
    ) -> FakeSignal:
        row = await self._fetchone(
            """
            INSERT INTO job_fake_signals
              (job_id, posting_id, kind, weight, details, detector_version)
            VALUES (%(j)s, %(p)s, %(k)s, %(w)s, %(d)s::jsonb, %(v)s)
            RETURNING *;
            """,
            {
                "j": job_id,
                "p": posting_id,
                "k": kind.value,
                "w": Decimal(str(weight)),
                "d": json.dumps(details or {}, ensure_ascii=False),
                "v": detector_version,
            },
        )
        assert row is not None
        return FakeSignal.model_validate(row)

    async def list_for_job(self, job_id: UUID) -> list[FakeSignal]:
        rows = await self._fetchall(
            "SELECT * FROM job_fake_signals WHERE job_id = %(j)s ORDER BY detected_at",
            {"j": job_id},
        )
        return self._to_models(FakeSignal, rows)

    async def recompute_score(
        self,
        job_id: UUID,
        *,
        fake_threshold: float = 0.30,
        suspicious_threshold: float = 0.55,
        legit_threshold: float = 0.70,
    ) -> Job:
        """Recompute legit_score + verdict from the signal evidence.

        Algorithm:
          * Sum signed weights of every signal (negative = fake).
          * Squash via sigmoid to a [0,1] legit-score (1 = legit, 0 = fake).
          * Pick a verdict by threshold:
              score < fake_threshold       → fake
              score < suspicious_threshold → suspicious
              score < legit_threshold      → pending
              else                         → legit
          * If any `reposted_within_30d` signal fired, override to `recycled`
            (unless overall verdict is `fake`).
        """
        rows = await self._fetchall(
            "SELECT kind, weight FROM job_fake_signals WHERE job_id = %(j)s",
            {"j": job_id},
        )
        if not rows:
            score = 0.85  # gentle "no evidence either way" default
            verdict = ClusterVerdict.pending
        else:
            net_weight = sum(float(r["weight"]) for r in rows)
            score = 1.0 / (1.0 + math.exp(-net_weight))  # sigmoid: 0 weight → 0.5
            if score < fake_threshold:
                verdict = ClusterVerdict.fake
            elif score < suspicious_threshold:
                verdict = ClusterVerdict.suspicious
            elif score < legit_threshold:
                verdict = ClusterVerdict.pending
            else:
                verdict = ClusterVerdict.legit
            if verdict is not ClusterVerdict.fake and any(
                r["kind"] == FakeSignalKind.reposted_within_30d.value for r in rows
            ):
                verdict = ClusterVerdict.recycled

        row = await self._fetchone(
            """
            UPDATE jobs SET verdict = %(v)s, legit_score = %(s)s
            WHERE id = %(id)s
            RETURNING *;
            """,
            {"id": job_id, "v": verdict.value, "s": Decimal(str(round(score, 3)))},
        )
        if row is None:
            raise KeyError(f"Job {job_id} not found")
        return Job.model_validate(row)
