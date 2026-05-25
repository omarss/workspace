from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from salary_model.data.sources import wage_index_live
from salary_model.data.sources._common import FetchManifest, fetched_now


def _mock_raw() -> tuple[pd.DataFrame, FetchManifest]:
    df = pd.DataFrame(
        [
            {"time_period": "2020", "quarter": "Q2", "gender": "Males",
             "indicator": "Average Monthly Wages of Paid employees (main job) (+15) years",
             "data_source": "x", "indicator_value": 8500.0},
            {"time_period": "2020", "quarter": "Q2", "gender": "Females",
             "indicator": "Average Monthly Wages of Paid employees (main job) (+15) years",
             "data_source": "x", "indicator_value": 7900.0},
            {"time_period": "2020", "quarter": "Q2", "gender": "Total",
             "indicator": "Average Monthly Wages of Paid employees (main job) (+15) years",
             "data_source": "x", "indicator_value": 8350.0},
            {"time_period": "2020", "quarter": "Q2", "gender": "Total",
             "indicator": "Average Monthly Wages of Paid Saudi employee (main job)(+15) years",
             "data_source": "x", "indicator_value": 11000.0},
            # Unrelated indicator should be ignored
            {"time_period": "2020", "quarter": "Q2", "gender": "Total",
             "indicator": "Saudi Unemployment Rate(15) years and above",
             "data_source": "x", "indicator_value": 11.0},
        ]
    )
    return df, FetchManifest(source="x", url="u", fetched_at=fetched_now(), ok=True, rows=len(df))


def test_build_wage_index_filters_to_wage_indicators_only() -> None:
    with patch.object(wage_index_live, "fetch_kapsarc_main_labor", return_value=_mock_raw()):
        table, manifest = wage_index_live.build_wage_index()
    # 3 total-population (M/F/T) + 1 Saudi-only = 4 rows
    assert len(table) == 4
    assert manifest.is_estimate is False
    assert manifest.ok is True


def test_lookup_wage_returns_value() -> None:
    with patch.object(wage_index_live, "fetch_kapsarc_main_labor", return_value=_mock_raw()):
        table, _ = wage_index_live.build_wage_index()
    male_2020 = wage_index_live.lookup_wage(table, year=2020, gender="Males", is_saudi=False)
    assert male_2020 == 8500.0


def test_gender_gap_pct_is_negative_for_female_lower() -> None:
    with patch.object(wage_index_live, "fetch_kapsarc_main_labor", return_value=_mock_raw()):
        table, _ = wage_index_live.build_wage_index()
    gap = wage_index_live.gender_gap_pct(table, year=2020)
    # female 7900 vs male 8500 -> -7.06%
    assert gap is not None
    assert -0.08 < gap < -0.06


def test_saudi_gap_pct_positive_when_saudi_pays_more() -> None:
    with patch.object(wage_index_live, "fetch_kapsarc_main_labor", return_value=_mock_raw()):
        table, _ = wage_index_live.build_wage_index()
    gap = wage_index_live.saudi_gap_pct(table, year=2020)
    # saudi total 11000 vs all total 8350 -> +31.7%
    assert gap is not None
    assert gap > 0.30


def test_fallback_when_upstream_fails() -> None:
    empty = pd.DataFrame()
    fail_manifest = FetchManifest(
        source="x", url="u", fetched_at=fetched_now(), ok=False, rows=0,
        fallback=True, is_estimate=True,
    )
    mocked = (empty, fail_manifest)
    with patch.object(wage_index_live, "fetch_kapsarc_main_labor", return_value=mocked):
        table, manifest = wage_index_live.build_wage_index()
    assert table.empty
    assert manifest.ok is False
    assert manifest.is_estimate is True
