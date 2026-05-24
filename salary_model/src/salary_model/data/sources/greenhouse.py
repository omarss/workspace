"""Greenhouse Job Board API adapter.

Greenhouse exposes a free, no-auth public job board API at
``https://boards-api.greenhouse.io/v1/boards/{token}/jobs``. Each company that uses
Greenhouse has a ``token`` (e.g. ``stripe``, ``datadog``). We pull every active
posting per token, normalize to :class:`~salary_model.data.sources._ats_common.PostingRow`,
and flag KSA-relevant rows.

Add company tokens to ``KSA_HIRING_TOKENS`` as new employers adopt Greenhouse. Tokens
are public; find them by clicking 'See open positions' on a company's career site
and reading the resulting boards.greenhouse.io URL.
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

log = get_logger("salary_model.data.sources.greenhouse")

GREENHOUSE_BOARD_URL: str = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

# Verified Greenhouse board tokens for KSA-hiring companies.
# Tokens are checked manually by visiting boards.greenhouse.io/<token>; only confirmed
# entries land here. The list is intentionally short and curated rather than scraped
# from a third-party directory.
KSA_HIRING_TOKENS: tuple[str, ...] = (
    "stripe",        # Stripe — has KSA-remote roles + ME expansion
    "datadog",       # Datadog — EMEA hiring incl. ME
    "gitlab",        # GitLab — fully remote, KSA candidates
    "hashicorp",     # HashiCorp — same
    "anthropic",     # Anthropic — selective ME remote
    "openai",        # OpenAI — selective ME remote
)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _parse_job(job: dict[str, Any], token: str) -> PostingRow | None:
    posting_id = str(job.get("id") or "").strip()
    title = str(job.get("title") or "").strip()
    if not posting_id or not title:
        return None
    location_raw = str((job.get("location") or {}).get("name") or "").strip()
    return PostingRow(
        posting_id=posting_id,
        source="greenhouse",
        company_token=token,
        title_raw=title,
        location_raw=location_raw,
        is_ksa_hint=is_ksa_posting(location_raw),
        posted_at=_parse_iso(job.get("updated_at") or job.get("first_published")),
        url=str(job.get("absolute_url") or "") or None,
        department=None,
        team=None,
        employment_type=None,
        description_snippet=None,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_period=None,
    )


def fetch_greenhouse_postings(
    tokens: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch postings for the given Greenhouse tokens.

    Defaults to :data:`KSA_HIRING_TOKENS`. Each token is one HTTP call.
    """
    use_tokens = tokens if tokens is not None else KSA_HIRING_TOKENS
    rows: list[PostingRow] = []
    failures: list[str] = []
    for token in use_tokens:
        url = GREENHOUSE_BOARD_URL.format(token=token)
        payload = safe_get_json_paged(url)
        if payload is None:
            failures.append(token)
            continue
        jobs = cast("list[dict[str, Any]]", (payload or {}).get("jobs", []))
        for job in jobs:
            parsed = _parse_job(job, token)
            if parsed is not None:
                rows.append(parsed)

    df = rows_to_dataframe(rows)
    live = len(use_tokens) > 0 and len(failures) < len(use_tokens)
    manifest = FetchManifest(
        source="greenhouse_postings",
        url=GREENHOUSE_BOARD_URL.format(token="*"),  # noqa: S106 (kw is GH board id, not a secret)
        fetched_at=fetched_now(),
        ok=bool(live),
        rows=len(df),
        fallback=not live,
        is_estimate=not live,
        notes=(
            f"live Greenhouse fetch across {len(use_tokens) - len(failures)}/"
            f"{len(use_tokens)} tokens; {len(failures)} failed"
        ),
        extra={"tokens": list(use_tokens), "failed_tokens": failures},
    )
    if failures:
        log.warning("greenhouse_tokens_failed", failed=failures)
    return df, manifest


__all__ = [
    "GREENHOUSE_BOARD_URL",
    "KSA_HIRING_TOKENS",
    "fetch_greenhouse_postings",
]
