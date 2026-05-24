"""Lightcast (Burning Glass) MENA postings adapter — stub.

Lightcast normalizes job postings from hundreds of sources into a clean schema with
ESCO/O*NET-aligned skills and (sometimes) salary ranges. Paid feed delivered as daily
Parquet via S3.

Expected per-posting schema:

| field            | type   | notes                                          |
|------------------|--------|------------------------------------------------|
| posting_id       | str    | Lightcast unique id                            |
| posted_at        | date   |                                                |
| company_name     | str    | normalized                                     |
| company_cr       | str?   | optional CR linkage                            |
| title_raw        | str    |                                                |
| title_clean      | str    | Lightcast-normalized                           |
| onet_soc         | str    |                                                |
| location_region  | str    |                                                |
| sector_naics     | str    |                                                |
| skills           | list   | of normalized skill labels                     |
| salary_low       | float? | SAR / year if disclosed                        |
| salary_high      | float? |                                                |
| salary_period    | str?   | 'annual' / 'monthly' / 'hourly'                |

Scaffold-only in v0.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat

from salary_model.config import get_logger
from salary_model.data.sources._common import FetchManifest

log = get_logger("salary_model.data.sources.lightcast")
_ = FetchManifest


class LightcastPosting(BaseModel):
    """Typed shape of one Lightcast job-posting record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    posting_id: str = Field(min_length=1)
    posted_at: datetime
    company_name: str
    company_cr: str | None = None
    title_raw: str
    title_clean: str
    onet_soc: str
    location_region: str
    sector_naics: str
    skills: tuple[str, ...] = ()
    salary_low: NonNegativeFloat | None = None
    salary_high: NonNegativeFloat | None = None
    salary_period: str | None = None


def fetch_lightcast_postings(
    *, parquet_path: Path | None = None,
) -> tuple[pd.DataFrame, FetchManifest]:
    """Load a Lightcast daily Parquet drop. Not implemented in v0."""
    path_str = str(parquet_path) if parquet_path else None
    log.warning("lightcast_loader_not_implemented", path=path_str)
    msg = (
        "Lightcast postings loader is a scaffold. Wire the S3-delivered Parquet path "
        "and parse against LightcastPosting; map onto our taxonomy via data.taxonomy."
    )
    raise NotImplementedError(msg)


__all__ = ["LightcastPosting", "fetch_lightcast_postings"]
