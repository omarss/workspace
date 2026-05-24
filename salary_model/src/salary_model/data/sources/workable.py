"""Workable Public Jobs API adapter.

Workable exposes per-company endpoints like
``https://apply.workable.com/api/v3/accounts/{subdomain}/jobs?limit=100&offset=0``
without auth. Each company has a ``subdomain`` (often the company name lowercased).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import pandas as pd

from salary_model.config import get_logger
from salary_model.data.sources._ats_common import (
    PostingRow,
    is_ksa_posting,
    rows_to_dataframe,
    safe_get_json_paged,
)
from salary_model.data.sources._common import FetchManifest, fetched_now

log = get_logger("salary_model.data.sources.workable")

WORKABLE_JOBS_URL: str = (
    "https://apply.workable.com/api/v3/accounts/{subdomain}/jobs"
)

KSA_HIRING_TOKENS: tuple[str, ...] = (
    # Workable adoption in KSA is patchy; populate as you verify each subdomain.
    # Defaults are conservative — empty rather than wrong. Add via env override
    # or a future YAML config.
)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _parse_job(j: dict[str, Any], token: str) -> PostingRow | None:
    posting_id = str(j.get("id") or j.get("shortcode") or "").strip()
    title = str(j.get("title") or "").strip()
    if not posting_id or not title:
        return None
    loc = cast("dict[str, Any] | None", j.get("location"))
    parts = []
    if loc:
        for key in ("city", "region", "country"):
            v = loc.get(key)
            if v:
                parts.append(str(v))
    location_raw = ", ".join(parts)
    return PostingRow(
        posting_id=posting_id,
        source="workable",
        company_token=token,
        title_raw=title,
        location_raw=location_raw,
        is_ksa_hint=is_ksa_posting(location_raw),
        posted_at=_parse_iso(j.get("published_on") or j.get("created_at")),
        url=str(j.get("application_url") or "") or None,
        department=str(j.get("department") or "") or None,
        team=None,
        employment_type=str(j.get("employment_type") or "") or None,
        description_snippet=str(j.get("description", ""))[:240] or None,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_period=None,
    )


def fetch_workable_postings(
    tokens: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, FetchManifest]:
    use_tokens = tokens if tokens is not None else KSA_HIRING_TOKENS
    rows: list[PostingRow] = []
    failures: list[str] = []
    for token in use_tokens:
        url = WORKABLE_JOBS_URL.format(subdomain=token)
        payload = safe_get_json_paged(url, params={"limit": 100, "offset": 0})
        if payload is None:
            failures.append(token)
            continue
        results = cast("list[dict[str, Any]]", (payload or {}).get("results", []))
        for job in results:
            parsed = _parse_job(job, token)
            if parsed is not None:
                rows.append(parsed)

    df = rows_to_dataframe(rows)
    live = bool(use_tokens) and len(failures) < len(use_tokens)
    manifest = FetchManifest(
        source="workable_postings",
        url=WORKABLE_JOBS_URL.format(subdomain="*"),
        fetched_at=fetched_now(),
        ok=bool(live or not use_tokens),  # OK even when empty tokens list
        rows=len(df),
        fallback=not live,
        is_estimate=not live,
        notes=(
            "no tokens configured yet" if not use_tokens
            else f"live Workable fetch across {len(use_tokens) - len(failures)}/"
                 f"{len(use_tokens)} tokens; {len(failures)} failed"
        ),
        extra={"tokens": list(use_tokens), "failed_tokens": failures},
    )
    if failures:
        log.warning("workable_tokens_failed", failed=failures)
    return df, manifest


__all__ = [
    "KSA_HIRING_TOKENS",
    "WORKABLE_JOBS_URL",
    "fetch_workable_postings",
]
