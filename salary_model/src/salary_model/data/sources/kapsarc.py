"""KAPSARC Data Portal adapter — live OpenDataSoft REST API.

KAPSARC (King Abdullah Petroleum Studies and Research Center) maintains a public open
data portal at https://datasource.kapsarc.org with quarterly KSA labor-force survey
extracts, "Main Labor Market Indicators", and other authoritative datasets. The portal
is powered by OpenDataSoft and exposes a stable REST API; no authentication needed for
public datasets.

This is one of the **real** fetchers — when the network is reachable, returned data
carries ``is_estimate=False`` because the values are an authoritative live pull, not
my-best-effort recall.

API reference: https://help.opendatasoft.com/apis/ods-explore-v2/

Two datasets are wired today; the OpenDataSoft API is uniform so adding more is a one
line change.
"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from salary_model.config import get_logger
from salary_model.data.sources._common import FetchManifest, fetched_now, safe_get_json

log = get_logger("salary_model.data.sources.kapsarc")

KAPSARC_BASE: str = "https://datasource.kapsarc.org/api/explore/v2.1/catalog"

# KAPSARC dataset slugs (verified live via
# https://datasource.kapsarc.org/api/explore/v2.1/catalog/datasets).
# Add new slugs here as they become useful — the OpenDataSoft API is uniform so each
# new entry is a one-line addition + a wrapper fetcher below.
DATASET_MAIN_LABOR: str = "main-labor-market-indicators"
DATASET_EMP_COMP: str = "employees-compensation-by-establishment-size-and-economic-activity"
DATASET_EMP_DEMOG: str = (
    "saudi-arabia-employees-15-and-over-by-education-status-nationality-and-sex-2007-"
)
DATASET_PUBLIC_EMP: str = "public-sector-employment-by-gender-and-nationality"
DATASET_CPI_MOM: str = "change-of-consumer-price-index-cpi-inflation-month-to-month"
DATASET_POPULATION: str = "population-by-detailed-age-gender-governorate-nationality-and-region"
# Retained for API compatibility; LFS slug was never published under that name and
# falls back gracefully via the manifest.
DATASET_LFS: str = "saudi-labor-force-survey-data"

DEFAULT_LIMIT: int = 100  # OpenDataSoft caps at 100 per page; paginate via offset
MAX_PAGES: int = 50       # 5k rows per dataset is enough for v0


def _records_endpoint(dataset_id: str) -> str:
    return f"{KAPSARC_BASE}/datasets/{dataset_id}/records"


def _fetch_dataset(
    dataset_id: str,
    *,
    select: str | None = None,
    where: str | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Paginate through an OpenDataSoft dataset and return a flat dataframe.

    Returns ``(df, live)`` — ``live`` is True if at least one page was fetched.
    """
    rows: list[dict[str, Any]] = []
    live = False
    url = _records_endpoint(dataset_id)
    for page in range(MAX_PAGES):
        params: dict[str, str | int] = {
            "limit": DEFAULT_LIMIT,
            "offset": page * DEFAULT_LIMIT,
        }
        if select:
            params["select"] = select
        if where:
            params["where"] = where
        payload = safe_get_json(url, timeout_s=12.0, params=params)
        if payload is None:
            break
        live = True
        records = cast("list[dict[str, Any]]", payload.get("results", []))
        if not records:
            break
        rows.extend(records)
        # Stop when we've drained the dataset
        if len(records) < DEFAULT_LIMIT:
            break
    return pd.DataFrame.from_records(rows), live


def fetch_kapsarc_main_labor() -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch the 'Main Labor Market Indicators' dataset.

    Columns are determined by KAPSARC's schema and may vary; the consumer should treat
    this as a wide tidy frame and project the columns it needs.
    """
    df, live = _fetch_dataset(DATASET_MAIN_LABOR)
    manifest = FetchManifest(
        source="kapsarc_main_labor",
        url=_records_endpoint(DATASET_MAIN_LABOR),
        fetched_at=fetched_now(),
        ok=bool(live),
        rows=len(df),
        fallback=not live,
        is_estimate=not live,
        notes=(
            "live KAPSARC OpenDataSoft fetch" if live
            else "network unavailable; returning empty frame"
        ),
        extra={"dataset_id": DATASET_MAIN_LABOR, "max_pages": MAX_PAGES},
    )
    if not live:
        log.warning("kapsarc_main_labor_unavailable")
    return df, manifest


def _wrap(source: str, dataset_id: str) -> tuple[pd.DataFrame, FetchManifest]:
    df, live = _fetch_dataset(dataset_id)
    manifest = FetchManifest(
        source=source,
        url=_records_endpoint(dataset_id),
        fetched_at=fetched_now(),
        ok=bool(live),
        rows=len(df),
        fallback=not live,
        is_estimate=not live,
        notes=(
            "live KAPSARC OpenDataSoft fetch" if live
            else "network unavailable or dataset slug invalid; returning empty frame"
        ),
        extra={"dataset_id": dataset_id, "max_pages": MAX_PAGES},
    )
    if not live:
        log.warning("kapsarc_dataset_unavailable", dataset_id=dataset_id)
    return df, manifest


def fetch_kapsarc_lfs() -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch the LFS-equivalent dataset. Slug is not yet published; falls back."""
    return _wrap("kapsarc_lfs", DATASET_LFS)


def fetch_kapsarc_employees_compensation() -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch 'Employees Compensation by Establishment Size and Economic Activity'.

    This is the most directly useful dataset for the salary model: GASTAT's published
    compensation totals broken down by establishment size and ISIC economic activity.
    """
    return _wrap("kapsarc_employees_compensation", DATASET_EMP_COMP)


def fetch_kapsarc_employees_demographics() -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch employees 15+ by education status, nationality, sex."""
    return _wrap("kapsarc_employees_demographics", DATASET_EMP_DEMOG)


def fetch_kapsarc_public_sector_employment() -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch public-sector employment by gender and nationality."""
    return _wrap("kapsarc_public_sector_employment", DATASET_PUBLIC_EMP)


def fetch_kapsarc_cpi_mom() -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch month-over-month CPI / inflation change."""
    return _wrap("kapsarc_cpi_mom", DATASET_CPI_MOM)


def fetch_kapsarc_population() -> tuple[pd.DataFrame, FetchManifest]:
    """Fetch detailed population by age x gender x governorate x nationality x region."""
    return _wrap("kapsarc_population", DATASET_POPULATION)


__all__ = [
    "DATASET_CPI_MOM",
    "DATASET_EMP_COMP",
    "DATASET_EMP_DEMOG",
    "DATASET_LFS",
    "DATASET_MAIN_LABOR",
    "DATASET_POPULATION",
    "DATASET_PUBLIC_EMP",
    "KAPSARC_BASE",
    "fetch_kapsarc_cpi_mom",
    "fetch_kapsarc_employees_compensation",
    "fetch_kapsarc_employees_demographics",
    "fetch_kapsarc_lfs",
    "fetch_kapsarc_main_labor",
    "fetch_kapsarc_population",
    "fetch_kapsarc_public_sector_employment",
]
