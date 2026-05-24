"""World Bank WDI adapter via the public REST API.

Cheap, stable, and authoritative for macro background. We pull a handful of indicators
for Saudi Arabia (SAU) over the last 20 years. If the network is unavailable the
function returns the bundled SAMA-derived single-row fallback.
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from salary_model.data import anchors
from salary_model.data.sources._common import FetchManifest, fetched_now, safe_get_json

WORLDBANK_URL = (
    "https://api.worldbank.org/v2/country/SAU/indicator/"
    "{code}?date=2005:2025&format=json&per_page=200"
)

INDICATORS: dict[str, str] = {
    "gdp_per_capita_usd": "NY.GDP.PCAP.CD",
    "inflation_cpi_yoy": "FP.CPI.TOTL.ZG",
    "labor_force_participation": "SL.TLF.CACT.ZS",
    "unemployment_total": "SL.UEM.TOTL.ZS",
    "unemployment_female": "SL.UEM.TOTL.FE.ZS",
    "population_total": "SP.POP.TOTL",
}


def _parse_indicator(payload: Any, key: str) -> list[dict[str, object]]:
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    rows_raw = payload[1] or []
    out: list[dict[str, object]] = []
    for item in cast("list[dict[str, Any]]", rows_raw):
        year_raw = item.get("date")
        val = item.get("value")
        if year_raw is None or val is None:
            continue
        try:
            year = int(year_raw)
        except (TypeError, ValueError):
            continue
        out.append({"year": year, key: float(val)})
    return out


def fetch_worldbank_macro() -> tuple[pd.DataFrame, FetchManifest]:
    """Return a year-indexed dataframe of KSA macro indicators."""
    frames: list[pd.DataFrame] = []
    failures = 0
    for key, code in INDICATORS.items():
        url = WORLDBANK_URL.format(code=code)
        payload = safe_get_json(url)
        if payload is None:
            failures += 1
            continue
        parsed = _parse_indicator(payload, key)
        if not parsed:
            failures += 1
            continue
        frames.append(pd.DataFrame.from_records(parsed))

    if not frames:
        df = pd.DataFrame(
            [{"year": 2024, "inflation_cpi_yoy": anchors.NATIONAL_CPI_YOY * 100.0}]
        )
        manifest = FetchManifest(
            source="worldbank_wdi",
            url=WORLDBANK_URL.format(code="*"),
            fetched_at=fetched_now(),
            ok=True,
            rows=len(df),
            fallback=True,
            notes="offline fallback to bundled CPI anchor",
        )
        return df, manifest

    merged = frames[0]
    for f in frames[1:]:
        merged = merged.merge(f, on="year", how="outer")
    merged = merged.sort_values("year").reset_index(drop=True)
    manifest = FetchManifest(
        source="worldbank_wdi",
        url=WORLDBANK_URL.format(code="*"),
        fetched_at=fetched_now(),
        ok=True,
        rows=len(merged),
        fallback=failures > 0,
        notes=f"fetched live; {failures} indicator fetch(es) failed",
        extra={"indicators": list(INDICATORS.keys())},
    )
    return merged, manifest
