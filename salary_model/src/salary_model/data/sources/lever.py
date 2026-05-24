"""Lever public postings API adapter.

Lever exposes ``https://api.lever.co/v0/postings/{company}?mode=json`` with no auth
required. Each company that uses Lever has a token (e.g. ``netflix``, ``mistralai``).
We pull every active posting per token, normalize, flag KSA-relevant rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
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

log = get_logger("salary_model.data.sources.lever")

LEVER_POSTINGS_URL: str = "https://api.lever.co/v0/postings/{company}?mode=json"

KSA_HIRING_TOKENS: tuple[str, ...] = (
    "netflix",       # Netflix — has ME content team
    "mistralai",     # Mistral AI — ME hires occasionally
    "scaleai",       # Scale AI — has ME hires
    "checkout",      # Checkout.com — KSA payments
)


def _epoch_ms_to_dt(ms: int | float | None) -> datetime | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_posting(p: dict[str, Any], token: str) -> PostingRow | None:
    posting_id = str(p.get("id") or "").strip()
    title = str(p.get("text") or "").strip()
    if not posting_id or not title:
        return None
    cats = cast("dict[str, Any]", p.get("categories") or {})
    location_raw = str(cats.get("location") or "")
    salary = cast("dict[str, Any] | None", p.get("salaryRange"))
    smin = float(salary["min"]) if salary and salary.get("min") is not None else None
    smax = float(salary["max"]) if salary and salary.get("max") is not None else None
    currency = str(salary["currency"]) if salary and salary.get("currency") else None
    period_map = {"annual": "annual", "monthly": "monthly", "hourly": "hourly"}
    period_raw = (salary or {}).get("interval") if salary else None
    period = period_map.get(str(period_raw or "").lower()) if period_raw else None
    return PostingRow(
        posting_id=posting_id,
        source="lever",
        company_token=token,
        title_raw=title,
        location_raw=location_raw,
        is_ksa_hint=is_ksa_posting(location_raw),
        posted_at=_epoch_ms_to_dt(p.get("createdAt")),
        url=str(p.get("hostedUrl") or "") or None,
        department=str(cats.get("department") or "") or None,
        team=str(cats.get("team") or "") or None,
        employment_type=str(cats.get("commitment") or "") or None,
        description_snippet=str(p.get("descriptionPlain", ""))[:240] or None,
        salary_min=smin,
        salary_max=smax,
        salary_currency=currency,
        salary_period=cast("Any", period),
    )


def fetch_lever_postings(
    tokens: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, FetchManifest]:
    use_tokens = tokens if tokens is not None else KSA_HIRING_TOKENS
    rows: list[PostingRow] = []
    failures: list[str] = []
    for token in use_tokens:
        url = LEVER_POSTINGS_URL.format(company=token)
        payload = safe_get_json_paged(url)
        if payload is None:
            failures.append(token)
            continue
        postings = cast("list[dict[str, Any]]", payload or [])
        for posting in postings:
            parsed = _parse_posting(posting, token)
            if parsed is not None:
                rows.append(parsed)

    df = rows_to_dataframe(rows)
    live = len(use_tokens) > 0 and len(failures) < len(use_tokens)
    manifest = FetchManifest(
        source="lever_postings",
        url=LEVER_POSTINGS_URL.format(company="*"),
        fetched_at=fetched_now(),
        ok=bool(live),
        rows=len(df),
        fallback=not live,
        is_estimate=not live,
        notes=(
            f"live Lever fetch across {len(use_tokens) - len(failures)}/"
            f"{len(use_tokens)} tokens; {len(failures)} failed"
        ),
        extra={"tokens": list(use_tokens), "failed_tokens": failures},
    )
    if failures:
        log.warning("lever_tokens_failed", failed=failures)
    return df, manifest


__all__ = [
    "KSA_HIRING_TOKENS",
    "LEVER_POSTINGS_URL",
    "fetch_lever_postings",
]
