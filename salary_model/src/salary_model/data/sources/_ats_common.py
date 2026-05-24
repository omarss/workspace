"""Shared schema + helpers for ATS (applicant tracking system) job-board fetchers.

The four adapters (Greenhouse, Lever, Ashby, Workable) all expose free public JSON
APIs that return a list of active postings per company. Each one has a different
field layout, but they normalize cleanly to the :class:`PostingRow` shape below so
downstream code is source-agnostic.

Per the project policy: never scrape ToS-protected sites. These APIs are the
companies' own public job-board endpoints — explicitly intended for indexing by job
search engines — so calling them is allowed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat

from salary_model.data.sources._common import safe_get_json

KSA_HINTS: tuple[str, ...] = (
    "saudi", "ksa", "riyadh", "jeddah", "dammam", "khobar", "neom", "alula",
    "makkah", "medina", "eastern province", "dhahran",
)


class PostingRow(BaseModel):
    """Normalized posting record. One row per active job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    posting_id: str = Field(min_length=1)
    source: Literal["greenhouse", "lever", "ashby", "workable"]
    company_token: str
    title_raw: str
    location_raw: str
    is_ksa_hint: bool
    posted_at: datetime | None = None
    url: str | None = None
    department: str | None = None
    team: str | None = None
    employment_type: str | None = None
    description_snippet: str | None = None
    salary_min: NonNegativeFloat | None = None
    salary_max: NonNegativeFloat | None = None
    salary_currency: str | None = None
    salary_period: Literal["annual", "monthly", "hourly", "daily"] | None = None


def is_ksa_posting(location: str | None) -> bool:
    """Lower-bound heuristic — return True if any KSA hint appears in the location."""
    if not location:
        return False
    low = location.lower()
    return any(h in low for h in KSA_HINTS)


def safe_get_json_paged(
    url: str,
    *,
    timeout_s: float = 12.0,
    params: dict[str, str | int] | None = None,
) -> object | None:
    """Single GET wrapper kept thin so adapters can paginate however they need to."""
    return safe_get_json(url, timeout_s=timeout_s, params=params)


def rows_to_dataframe(rows: list[PostingRow]) -> pd.DataFrame:
    """Convert a list of PostingRow to a tidy DataFrame matching the schema."""
    if not rows:
        return pd.DataFrame(columns=list(PostingRow.model_fields.keys()))
    return pd.DataFrame([r.model_dump() for r in rows])
