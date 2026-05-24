"""Mercer Total Remuneration Survey (KSA) adapter — stub.

Mercer TRS is the closest commercial proxy to GOSI for white-collar compensation. It is
delivered annually as a paid PDF + XLSX bundle. There is no API; we parse the XLSX
sheets ourselves.

Schema expected from upstream (per Mercer TRS data dictionary):

| field                | type    | notes                                       |
|----------------------|---------|---------------------------------------------|
| survey_year          | int     | publication year                            |
| job_family           | str     | Mercer job family code (mapped to ours)     |
| level                | str     | Mercer PG level (mapped to our IC/M)        |
| n_participants       | int     | number of contributors at this cell         |
| base_p25             | float   | 25th percentile SAR / month                 |
| base_p50             | float   | median                                      |
| base_p75             | float   | 75th percentile                             |
| target_total_cash_p50| float   | base + target variable                      |
| sector_focus         | str     | broad sector                                |
| region               | str     | KSA region                                  |

This module is a scaffold; replace the body when a licensed XLSX is on disk.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat

from salary_model.config import get_logger
from salary_model.data.sources._common import FetchManifest

log = get_logger("salary_model.data.sources.mercer")
_ = FetchManifest


class MercerCell(BaseModel):
    """Aggregated cell from a Mercer TRS sheet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    survey_year: int = Field(ge=2015, le=2100)
    job_family: str
    level: str
    n_participants: int = Field(ge=1)
    base_p25: NonNegativeFloat
    base_p50: NonNegativeFloat
    base_p75: NonNegativeFloat
    target_total_cash_p50: NonNegativeFloat
    sector_focus: str
    region: str


def fetch_mercer_trs(*, xlsx_path: Path | None = None) -> tuple[pd.DataFrame, FetchManifest]:
    """Load a Mercer TRS XLSX extract.

    Args:
        xlsx_path: path to the licensed Mercer TRS XLSX bundle (gitignored).

    Raises:
        NotImplementedError: until the licensed file path is wired and the sheet
            parsing rules are confirmed against the current TRS data dictionary.
    """
    log.warning("mercer_loader_not_implemented", path=str(xlsx_path) if xlsx_path else None)
    msg = (
        "Mercer TRS loader is a scaffold. Acquire the licensed XLSX, then parse each "
        "sheet against MercerCell and return (DataFrame, FetchManifest). Map "
        "job_family + level into our taxonomy via data.taxonomy."
    )
    raise NotImplementedError(msg)


__all__ = ["MercerCell", "fetch_mercer_trs"]
