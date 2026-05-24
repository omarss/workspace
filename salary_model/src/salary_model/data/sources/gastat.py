"""GASTAT (General Authority for Statistics, KSA) adapters.

GASTAT publishes the Labor Market Bulletin quarterly with wage quantiles by sector and
region. There is no stable open JSON endpoint at the time of writing, so this module
falls back to the bundled anchor values in :mod:`salary_model.data.anchors` and exposes
the same shape consumers would receive from a live fetch.

If/when GASTAT exposes a stable open API, swap the body of :func:`fetch_gastat_wage_index`
without changing the return type.
"""

from __future__ import annotations

import pandas as pd

from salary_model.data import anchors
from salary_model.data.sources._common import FetchManifest, fetched_now

GASTAT_WAGE_BULLETIN_URL = "https://www.stats.gov.sa/en/814"


def fetch_gastat_wage_index() -> tuple[pd.DataFrame, FetchManifest]:
    """Return per-(region, sector) median monthly base wage anchors.

    Columns: ``region``, ``sector``, ``base_median``, ``log_sigma``.
    The bundled values are derived from GASTAT's most recent publicly available
    bulletin and are coarse but authoritative-anchored.
    """
    rows: list[dict[str, object]] = []
    for region, region_mult in anchors.REGION_BASE_MULTIPLIER.items():
        for sector, sector_med in anchors.SECTOR_BASE_MEDIAN.items():
            rows.append(
                {
                    "region": region.value,
                    "sector": sector.value,
                    "base_median": float(sector_med * region_mult),
                    "log_sigma": float(anchors.SECTOR_LOG_SIGMA[sector]),
                }
            )
    df = pd.DataFrame.from_records(rows)
    manifest = FetchManifest(
        source="gastat_lmb",
        url=GASTAT_WAGE_BULLETIN_URL,
        fetched_at=fetched_now(),
        ok=True,
        rows=len(df),
        fallback=True,
        is_estimate=True,
        notes="bundled anchors derived from GASTAT Labor Market Bulletin 2024",
    )
    return df, manifest
