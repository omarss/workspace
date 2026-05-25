"""Sources repo — the websites being crawled."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from ..enums import SourceKind
from ..models import Source
from .base import Repo


class SourcesRepo(Repo):
    """CRUD for the `sources` table. Sources are reference data — created
    once when bootstrapping a new crawl target, rarely updated."""

    async def list(self, *, enabled_only: bool = False) -> list[Source]:
        """Return every known source, optionally filtered to enabled."""
        sql = "SELECT * FROM sources"
        if enabled_only:
            sql += " WHERE crawl_enabled"
        sql += " ORDER BY slug"
        rows = await self._fetchall(sql)
        return self._to_models(Source, rows)

    async def get(self, *, id: UUID | None = None, slug: str | None = None) -> Source | None:
        """Fetch by primary key or slug (exactly one must be provided)."""
        if (id is None) == (slug is None):
            raise ValueError("Provide exactly one of `id` or `slug`.")
        if id is not None:
            row = await self._fetchone("SELECT * FROM sources WHERE id = %(id)s", {"id": id})
        else:
            row = await self._fetchone("SELECT * FROM sources WHERE slug = %(s)s", {"s": slug})
        return self._to_model(Source, row)

    async def upsert(
        self,
        *,
        slug: str,
        display_name: str,
        kind: SourceKind | str,
        base_url: str,
        trust_weight: Decimal | float = Decimal("0.50"),
        crawl_enabled: bool | None = None,
        config: dict[str, Any] | None = None,
    ) -> Source:
        """Create or update a source by slug.

        Use during application bootstrap; safe to re-run on every deploy.
        `crawl_enabled` defaults to None so a source that crawler_health
        marked broken is NOT silently re-enabled by `runner.ensure_source()`
        on the next invocation; explicit True/False from a CLI flip is
        respected. On first insert, None becomes the column default (true).
        """
        row = await self._fetchone(
            """
            INSERT INTO sources (slug, display_name, kind, base_url, trust_weight,
                                 crawl_enabled, config)
            VALUES (%(slug)s, %(display_name)s, %(kind)s, %(base_url)s,
                    %(trust_weight)s, COALESCE(%(crawl_enabled)s, true), %(config)s::jsonb)
            ON CONFLICT (slug) DO UPDATE SET
                display_name  = EXCLUDED.display_name,
                kind          = EXCLUDED.kind,
                base_url      = EXCLUDED.base_url,
                trust_weight  = EXCLUDED.trust_weight,
                crawl_enabled = COALESCE(%(crawl_enabled)s, sources.crawl_enabled),
                config        = EXCLUDED.config
            RETURNING *;
            """,
            {
                "slug": slug,
                "display_name": display_name,
                "kind": kind.value if isinstance(kind, SourceKind) else kind,
                "base_url": base_url,
                "trust_weight": Decimal(str(trust_weight)),
                "crawl_enabled": crawl_enabled,
                "config": _to_json(config or {}),
            },
        )
        assert row is not None
        return Source.model_validate(row)


def _to_json(value: dict[str, Any]) -> str:
    """Tiny helper: dumps to a JSON string. psycopg can adapt dict to jsonb
    directly with Json() wrapper, but a plain string keeps the placeholder
    style consistent across repos."""
    import json

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
