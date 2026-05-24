"""Tests for the KAPSARC OpenDataSoft adapter.

The unit-test path mocks the network and verifies the manifest contract. The
``@pytest.mark.network`` test actually hits datasource.kapsarc.org and is skipped by
default (run with ``pytest -m network`` to include it).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from salary_model.data.sources import kapsarc


def _mock_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"results": records, "total_count": len(records)}


def test_main_labor_returns_estimate_when_network_unavailable() -> None:
    with patch.object(kapsarc, "safe_get_json", return_value=None):
        df, manifest = kapsarc.fetch_kapsarc_main_labor()
    assert df.empty
    assert manifest.ok is False
    assert manifest.fallback is True
    assert manifest.is_estimate is True
    assert manifest.source == "kapsarc_main_labor"


def test_lfs_returns_estimate_when_network_unavailable() -> None:
    with patch.object(kapsarc, "safe_get_json", return_value=None):
        df, manifest = kapsarc.fetch_kapsarc_lfs()
    assert df.empty
    assert manifest.fallback is True
    assert manifest.is_estimate is True


def test_main_labor_parses_records_when_network_succeeds() -> None:
    rows = [
        {"period": "2024-Q1", "indicator": "participation_rate", "value": 65.3},
        {"period": "2024-Q1", "indicator": "unemployment_rate", "value": 4.6},
    ]
    with patch.object(kapsarc, "safe_get_json", return_value=_mock_payload(rows)):
        df, manifest = kapsarc.fetch_kapsarc_main_labor()
    assert len(df) == 2
    assert manifest.ok is True
    assert manifest.fallback is False
    assert manifest.is_estimate is False
    assert set(df.columns) >= {"period", "indicator", "value"}


def test_pagination_stops_when_short_page_returned() -> None:
    """When a page returns fewer than DEFAULT_LIMIT records, fetch should stop."""
    rows = [{"period": "2024-Q1", "indicator": "x", "value": 1.0}]
    call_count = {"n": 0}

    def fake_get(url: str, **_: Any) -> dict[str, Any]:
        call_count["n"] += 1
        return _mock_payload(rows)

    with patch.object(kapsarc, "safe_get_json", side_effect=fake_get):
        df, _ = kapsarc.fetch_kapsarc_main_labor()
    assert len(df) == 1
    # One page only because we returned < DEFAULT_LIMIT
    assert call_count["n"] == 1


@pytest.mark.network
def test_live_main_labor_returns_some_rows() -> None:
    """Hits the live KAPSARC API. Run with `pytest -m network`."""
    df, manifest = kapsarc.fetch_kapsarc_main_labor()
    assert isinstance(df, pd.DataFrame)
    # We don't assert on row count because the dataset may be empty or schema may shift.
    assert manifest.source == "kapsarc_main_labor"
    if manifest.ok:
        assert manifest.is_estimate is False
