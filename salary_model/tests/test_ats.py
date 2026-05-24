"""Tests for the four ATS adapters and the aggregator."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from salary_model.data.sources import (
    ashby,
    greenhouse,
    lever,
    postings,
    workable,
)
from salary_model.data.sources._ats_common import is_ksa_posting


def test_is_ksa_posting_detects_keywords() -> None:
    assert is_ksa_posting("Riyadh, Saudi Arabia") is True
    assert is_ksa_posting("Jeddah") is True
    assert is_ksa_posting("Dubai, UAE") is False
    assert is_ksa_posting(None) is False


# ── Greenhouse ──────────────────────────────────────────────────────────────


def _gh_payload(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"jobs": jobs}


def test_greenhouse_parses_minimal_payload() -> None:
    payload = _gh_payload([
        {"id": 1, "title": "Backend Engineer", "location": {"name": "Riyadh, Saudi Arabia"},
         "absolute_url": "https://x/y/1", "updated_at": "2026-05-01T00:00:00Z"},
        {"id": 2, "title": "Designer", "location": {"name": "Berlin, Germany"},
         "absolute_url": "https://x/y/2"},
    ])
    with patch.object(greenhouse, "safe_get_json_paged", return_value=payload):
        df, m = greenhouse.fetch_greenhouse_postings(tokens=("acme",))
    assert m.ok is True
    assert m.is_estimate is False
    assert len(df) == 2
    ksa_rows = df.loc[df["is_ksa_hint"]]
    assert len(ksa_rows) == 1
    assert ksa_rows.iloc[0]["title_raw"] == "Backend Engineer"


def test_greenhouse_fallback_on_failure() -> None:
    with patch.object(greenhouse, "safe_get_json_paged", return_value=None):
        df, m = greenhouse.fetch_greenhouse_postings(tokens=("missing",))
    assert df.empty
    assert m.ok is False
    assert m.is_estimate is True


# ── Lever ───────────────────────────────────────────────────────────────────


def test_lever_parses_salary_range() -> None:
    payload = [
        {
            "id": "abc", "text": "Senior SWE",
            "categories": {"location": "Remote, KSA", "department": "Engineering"},
            "salaryRange": {"min": 80000, "max": 120000, "currency": "USD",
                            "interval": "annual"},
            "hostedUrl": "https://jobs.lever.co/x/abc",
            "createdAt": 1714521600000,
        }
    ]
    with patch.object(lever, "safe_get_json_paged", return_value=payload):
        df, m = lever.fetch_lever_postings(tokens=("acme",))
    assert m.ok is True
    assert len(df) == 1
    row = df.iloc[0]
    assert row["salary_min"] == 80000.0
    assert row["salary_max"] == 120000.0
    assert row["salary_period"] == "annual"
    assert bool(row["is_ksa_hint"]) is True


# ── Ashby ───────────────────────────────────────────────────────────────────


def test_ashby_parses_compensation_yearly_to_annual() -> None:
    payload = {
        "jobs": [
            {
                "id": "j1", "title": "Staff Engineer",
                "location": "Riyadh", "publishedAt": "2026-04-01T00:00:00Z",
                "jobUrl": "https://jobs.ashbyhq.com/x/j1",
                "compensation": {"minValue": 200000, "maxValue": 250000,
                                 "currencyCode": "USD", "interval": "yearly"},
            }
        ]
    }
    with patch.object(ashby, "safe_get_json_paged", return_value=payload):
        df, _ = ashby.fetch_ashby_postings(tokens=("acme",))
    assert len(df) == 1
    assert df.iloc[0]["salary_period"] == "annual"


# ── Workable ────────────────────────────────────────────────────────────────


def test_workable_empty_tokens_returns_empty_but_ok() -> None:
    df, m = workable.fetch_workable_postings(tokens=())
    assert df.empty
    # No tokens configured is a valid state, not a failure
    assert m.ok is True
    assert "no tokens configured" in m.notes


def test_workable_parses_location_struct() -> None:
    payload = {
        "results": [
            {
                "id": "w1", "title": "DevOps",
                "location": {"city": "Jeddah", "region": "Makkah", "country": "Saudi Arabia"},
                "application_url": "https://apply.workable.com/x/j/w1",
                "published_on": "2026-03-15T12:00:00Z",
                "employment_type": "Full-time",
            }
        ]
    }
    with patch.object(workable, "safe_get_json_paged", return_value=payload):
        df, m = workable.fetch_workable_postings(tokens=("acme",))
    assert m.ok is True
    assert len(df) == 1
    assert "Jeddah" in df.iloc[0]["location_raw"]
    assert bool(df.iloc[0]["is_ksa_hint"]) is True


# ── Aggregator ──────────────────────────────────────────────────────────────


def test_aggregator_merges_all_four() -> None:
    gh = _gh_payload([{"id": "g1", "title": "A", "location": {"name": "Riyadh"}}])
    lv = [{"id": "l1", "text": "B", "categories": {"location": "Jeddah"}}]
    ab = {"jobs": [{"id": "a1", "title": "C", "location": "Dammam"}]}
    wk = {"results": [{"id": "w1", "title": "D",
                       "location": {"city": "Khobar", "country": "Saudi Arabia"}}]}
    with (
        patch.object(greenhouse, "safe_get_json_paged", return_value=gh),
        patch.object(lever, "safe_get_json_paged", return_value=lv),
        patch.object(ashby, "safe_get_json_paged", return_value=ab),
        patch.object(workable, "safe_get_json_paged", return_value=wk),
        # Limit each source to one token so each mocked payload is fetched exactly once
        patch.object(greenhouse, "KSA_HIRING_TOKENS", ("acme",)),
        patch.object(lever, "KSA_HIRING_TOKENS", ("acme",)),
        patch.object(ashby, "KSA_HIRING_TOKENS", ("acme",)),
        patch.object(workable, "KSA_HIRING_TOKENS", ("acme",)),
    ):
        df, m = postings.fetch_all_postings()
    assert m.ok is True
    assert m.rows == 4
    assert set(df["source"].unique()) == {"greenhouse", "lever", "ashby", "workable"}
    assert int(df["is_ksa_hint"].sum()) == 4


@pytest.mark.network
def test_live_greenhouse_returns_dataframe() -> None:
    """Live call to one Greenhouse board. Skipped unless `-m network`."""
    df, m = greenhouse.fetch_greenhouse_postings(tokens=("stripe",))
    assert isinstance(df, pd.DataFrame)
    assert m.source == "greenhouse_postings"
