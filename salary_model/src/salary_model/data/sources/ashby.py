"""Ashby Job Board API adapter.

Ashby exposes ``https://api.ashbyhq.com/posting-api/job-board/{org}`` with no auth.
Each company has an ``org`` token (often the company name lowercased). Salary fields
are present in ``compensation`` for many tech roles.
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

log = get_logger("salary_model.data.sources.ashby")

ASHBY_BOARD_URL: str = "https://api.ashbyhq.com/posting-api/job-board/{org}"

KSA_HIRING_TOKENS: tuple[str, ...] = (
    "ramp",          # Ramp — has occasional ME hires
    "rippling",      # Rippling — same
    "vercel",        # Vercel — global remote
    "linear",        # Linear — global remote
)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _parse_posting(p: dict[str, Any], token: str) -> PostingRow | None:
    posting_id = str(p.get("id") or "").strip()
    title = str(p.get("title") or "").strip()
    if not posting_id or not title:
        return None
    location_raw = str(p.get("location") or "")
    comp = cast("dict[str, Any] | None", p.get("compensation"))
    smin = float(comp["minValue"]) if comp and comp.get("minValue") is not None else None
    smax = float(comp["maxValue"]) if comp and comp.get("maxValue") is not None else None
    currency = str(comp["currencyCode"]) if comp and comp.get("currencyCode") else None
    interval = str((comp or {}).get("interval", "")).lower() if comp else ""
    period_map = {"yearly": "annual", "monthly": "monthly", "hourly": "hourly"}
    period = period_map.get(interval)
    return PostingRow(
        posting_id=posting_id,
        source="ashby",
        company_token=token,
        title_raw=title,
        location_raw=location_raw,
        is_ksa_hint=is_ksa_posting(location_raw),
        posted_at=_parse_iso(p.get("publishedAt")),
        url=str(p.get("jobUrl") or "") or None,
        department=str(p.get("department") or "") or None,
        team=str(p.get("team") or "") or None,
        employment_type=str(p.get("employmentType") or "") or None,
        description_snippet=str(p.get("descriptionPlain", ""))[:240] or None,
        salary_min=smin,
        salary_max=smax,
        salary_currency=currency,
        salary_period=cast("Any", period),
    )


def fetch_ashby_postings(
    tokens: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, FetchManifest]:
    use_tokens = tokens if tokens is not None else KSA_HIRING_TOKENS
    rows: list[PostingRow] = []
    failures: list[str] = []
    for token in use_tokens:
        url = ASHBY_BOARD_URL.format(org=token)
        payload = safe_get_json_paged(url)
        if payload is None:
            failures.append(token)
            continue
        postings = cast("list[dict[str, Any]]", (payload or {}).get("jobs", []))
        for posting in postings:
            parsed = _parse_posting(posting, token)
            if parsed is not None:
                rows.append(parsed)

    df = rows_to_dataframe(rows)
    live = len(use_tokens) > 0 and len(failures) < len(use_tokens)
    manifest = FetchManifest(
        source="ashby_postings",
        url=ASHBY_BOARD_URL.format(org="*"),
        fetched_at=fetched_now(),
        ok=bool(live),
        rows=len(df),
        fallback=not live,
        is_estimate=not live,
        notes=(
            f"live Ashby fetch across {len(use_tokens) - len(failures)}/"
            f"{len(use_tokens)} tokens; {len(failures)} failed"
        ),
        extra={"tokens": list(use_tokens), "failed_tokens": failures},
    )
    if failures:
        log.warning("ashby_tokens_failed", failed=failures)
    return df, manifest


__all__ = [
    "ASHBY_BOARD_URL",
    "KSA_HIRING_TOKENS",
    "fetch_ashby_postings",
]
