"""External data source adapters.

Each module exposes a single ``fetch()`` function that returns a typed dataframe and a
manifest dict with provenance. Network calls go through ``httpx`` with conservative
timeouts and graceful fallback to bundled anchors when offline.
"""

from __future__ import annotations

from salary_model.data.sources.gastat import fetch_gastat_wage_index
from salary_model.data.sources.macro_series import fetch_macro_series, lookup_at
from salary_model.data.sources.sama import fetch_sama_indicators
from salary_model.data.sources.worldbank import fetch_worldbank_macro

__all__ = [
    "fetch_gastat_wage_index",
    "fetch_macro_series",
    "fetch_sama_indicators",
    "fetch_worldbank_macro",
    "lookup_at",
]
