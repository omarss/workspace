"""GOSI (General Organization for Social Insurance, KSA) microdata adapter — stub.

GOSI is the highest-trust source we know of: every private-sector employer in KSA is
legally required to register insured employees and report contribution-base wages
monthly. Access to row-level data requires a formal research agreement; aggregates are
sometimes published.

This module is a **scaffold**. When access is granted, replace :func:`fetch_gosi_microdata`
with the real loader; the rest of the pipeline (canonical normalization, feature build,
training) will accept the output unchanged so long as the schema below is respected.

Schema expected from upstream:

| field                | type    | notes                                        |
|----------------------|---------|----------------------------------------------|
| insured_id_hash      | str     | salted hash of national ID; never raw        |
| employer_cr_number   | str     | MCI commercial registration                   |
| observation_month    | date    | first-of-month, YYYY-MM-01                   |
| contribution_base    | float   | SAR / month, gross                           |
| occupation_isco_4    | str     | ISCO-08 4-digit                              |
| region_code          | str     | KSA region code                              |
| sector_isic_4        | str     | ISIC4                                        |
| is_saudi             | bool    | nationality flag                             |
| gender               | str     | 'M' / 'F'                                    |
| age_bucket           | str     | five-year bracket                            |
| employment_status    | str     | active / suspended / terminated              |
| nitaqat_color        | str     | platinum / green / yellow / red              |

Access path (when ready):
- Formal request via https://www.gosi.gov.sa
- DPIA + data-sharing agreement; PDPL controller is the requesting party
- Bulk extracts via SFTP; row-level data stays inside a controlled enclave
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat

from salary_model.config import get_logger
from salary_model.data.sources._common import FetchManifest  # re-exported for callers

log = get_logger("salary_model.data.sources.gosi")
_ = FetchManifest  # keep imported for future loader implementation

GOSI_ACCESS_DOC_URL: Final[str] = "https://www.gosi.gov.sa/GOSIOnline/Open_Data"


class GOSIRow(BaseModel):
    """Typed shape of one GOSI microdata record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    insured_id_hash: str = Field(min_length=8)
    employer_cr_number: str
    observation_month: datetime
    contribution_base: NonNegativeFloat
    occupation_isco_4: str = Field(min_length=4, max_length=4)
    region_code: str
    sector_isic_4: str
    is_saudi: bool
    gender: str = Field(pattern="^[MF]$")
    age_bucket: str
    employment_status: str
    nitaqat_color: str | None = None


def fetch_gosi_microdata(*, path: str | None = None) -> tuple[pd.DataFrame, FetchManifest]:
    """Load GOSI microdata from a local enclave extract.

    Not implemented in v0. When the research agreement is in place, point ``path`` at the
    received Parquet/CSV extract and parse via :class:`GOSIRow`. The output dataframe
    must conform to the columns listed in the module docstring.

    Raises:
        NotImplementedError: always, until real-access path is wired.
    """
    log.warning("gosi_loader_not_implemented", path=path, see=GOSI_ACCESS_DOC_URL)
    msg = (
        "GOSI microdata loader is a scaffold. Request access at "
        f"{GOSI_ACCESS_DOC_URL} then implement the parser against GOSIRow and return "
        "(DataFrame, FetchManifest)."
    )
    raise NotImplementedError(msg)


__all__ = ["GOSI_ACCESS_DOC_URL", "GOSIRow", "fetch_gosi_microdata"]
