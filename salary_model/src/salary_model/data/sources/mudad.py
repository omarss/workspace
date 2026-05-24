"""MUDAD wage-protection adapter — stub.

MUDAD (https://mudad.com.sa) is the KSA government's wage-protection platform; ~90% of
private-sector salary transfers flow through it. Aggregates are sometimes published by
HRSD; row-level access requires an MoU.

Expected aggregate-table schema (published HRSD reports):

| field            | type  | notes                                  |
|------------------|-------|----------------------------------------|
| month            | date  | YYYY-MM-01                             |
| region_code      | str   |                                        |
| sector_isic_4    | str   |                                        |
| size_bucket      | str   | establishment size band                |
| n_workers        | int   |                                        |
| avg_monthly_wage | float | SAR / month, gross                     |
| share_saudi      | float | 0..1                                   |

This module is a scaffold; replace when aggregate or microdata access is wired.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat

from salary_model.config import get_logger
from salary_model.data.sources._common import FetchManifest

log = get_logger("salary_model.data.sources.mudad")
_ = FetchManifest


class MudadAggregate(BaseModel):
    """Aggregate cell from MUDAD published statistics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    month: datetime
    region_code: str
    sector_isic_4: str
    size_bucket: str
    n_workers: int = Field(ge=1)
    avg_monthly_wage: NonNegativeFloat
    share_saudi: float = Field(ge=0.0, le=1.0)


def fetch_mudad_aggregates() -> tuple[pd.DataFrame, FetchManifest]:
    """Load MUDAD published aggregate tables. Not implemented in v0."""
    log.warning("mudad_loader_not_implemented")
    msg = (
        "MUDAD aggregates loader is a scaffold; implement once HRSD publishes a stable "
        "feed and return (DataFrame, FetchManifest)."
    )
    raise NotImplementedError(msg)


__all__ = ["MudadAggregate", "fetch_mudad_aggregates"]
