"""SAMA (Saudi Central Bank) monthly bulletin adapter.

SAMA publishes monthly tables for the policy rate, money supply, sector credit, FX, and
banking employment. The published files are XLSX behind a portal — there is no public
JSON API at the time of writing. This adapter returns the bundled most-recent anchors;
when SAMA exposes a JSON feed, replace the body.
"""

from __future__ import annotations

import pandas as pd

from salary_model.data import anchors
from salary_model.data.sources._common import FetchManifest, fetched_now

SAMA_MONTHLY_STATS_URL = (
    "https://www.sama.gov.sa/en-US/EconomicReports/Pages/MonthlyStatistics.aspx"
)


def fetch_sama_indicators() -> tuple[pd.DataFrame, FetchManifest]:
    """Return current macro indicators with a single-row dataframe.

    Columns: ``policy_rate``, ``cpi_yoy``, ``sar_to_usd``, ``brent_3m_avg_usd``.
    """
    df = pd.DataFrame(
        [
            {
                "policy_rate": anchors.SAMA_POLICY_RATE,
                "cpi_yoy": anchors.NATIONAL_CPI_YOY,
                "sar_to_usd": anchors.SAR_TO_USD,
                "brent_3m_avg_usd": anchors.BRENT_3M_AVG_USD,
            }
        ]
    )
    manifest = FetchManifest(
        source="sama",
        url=SAMA_MONTHLY_STATS_URL,
        fetched_at=fetched_now(),
        ok=True,
        rows=len(df),
        fallback=True,
        is_estimate=True,
        notes="bundled SAMA Monthly Bulletin 2025 Q1 anchors",
    )
    return df, manifest
