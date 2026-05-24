"""ATS postings aggregator: merges all four sources into one normalized table.

Provides a single entry point :func:`fetch_all_postings` that consumers can call
without caring which ATS each posting came from. Tags every row with `source` so
downstream code can weight by trust prior.
"""

from __future__ import annotations

import pandas as pd

from salary_model.config import get_logger
from salary_model.data.sources._common import FetchManifest, fetched_now
from salary_model.data.sources.ashby import fetch_ashby_postings
from salary_model.data.sources.greenhouse import fetch_greenhouse_postings
from salary_model.data.sources.lever import fetch_lever_postings
from salary_model.data.sources.workable import fetch_workable_postings

log = get_logger("salary_model.data.sources.postings")


def fetch_all_postings() -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch every ATS source and return the union of normalized postings."""
    frames: list[pd.DataFrame] = []
    sub_manifests: dict[str, FetchManifest] = {}
    total_failed_tokens = 0
    for name, fn in (
        ("greenhouse", fetch_greenhouse_postings),
        ("lever", fetch_lever_postings),
        ("ashby", fetch_ashby_postings),
        ("workable", fetch_workable_postings),
    ):
        df, m = fn()
        sub_manifests[name] = m
        if not df.empty:
            frames.append(df)
        failed = m.extra.get("failed_tokens", []) if isinstance(m.extra, dict) else []
        total_failed_tokens += len(failed)

    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    live_sources = [name for name, m in sub_manifests.items() if m.ok and not m.is_estimate]
    manifest = FetchManifest(
        source="ats_postings_union",
        url="aggregator: greenhouse + lever + ashby + workable",
        fetched_at=fetched_now(),
        ok=bool(live_sources),
        rows=len(merged),
        fallback=not live_sources,
        is_estimate=not live_sources,
        notes=(
            f"merged ATS postings from {len(live_sources)} live source(s); "
            f"{total_failed_tokens} token(s) failed"
        ),
        extra={
            "per_source": {
                name: {"rows": m.rows, "ok": m.ok, "is_estimate": m.is_estimate}
                for name, m in sub_manifests.items()
            },
            "live_sources": live_sources,
        },
    )
    log.info(
        "ats_postings_aggregated",
        total_rows=len(merged),
        ksa_hint_rows=int(merged.get("is_ksa_hint", pd.Series(dtype=bool)).sum()),
        live_sources=live_sources,
    )
    return merged, manifest


__all__ = ["fetch_all_postings"]
