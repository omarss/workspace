"""Integration-contract tests for the real-data loader stubs.

These tests verify that the pydantic schemas are well-formed and that the stubs raise
NotImplementedError until access is wired. When a real loader replaces a stub, drop the
`NotImplementedError` assertion and add a positive-path test against a tiny fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from salary_model.data.sources.gosi import GOSIRow, fetch_gosi_microdata
from salary_model.data.sources.lightcast import LightcastPosting, fetch_lightcast_postings
from salary_model.data.sources.mercer import MercerCell, fetch_mercer_trs
from salary_model.data.sources.mudad import MudadAggregate, fetch_mudad_aggregates


def test_gosi_row_schema_valid() -> None:
    row = GOSIRow(
        insured_id_hash="abc12345xyz",
        employer_cr_number="1010101010",
        observation_month=datetime(2026, 1, 1, tzinfo=UTC),
        contribution_base=15_500.0,
        occupation_isco_4="2511",
        region_code="RUH",
        sector_isic_4="J62",
        is_saudi=True,
        gender="M",
        age_bucket="30-34",
        employment_status="active",
        nitaqat_color="green",
    )
    assert row.contribution_base == 15_500.0


def test_gosi_row_rejects_bad_gender() -> None:
    with pytest.raises(ValueError, match="gender"):
        GOSIRow(
            insured_id_hash="abc12345xyz",
            employer_cr_number="1010101010",
            observation_month=datetime(2026, 1, 1, tzinfo=UTC),
            contribution_base=15_500.0,
            occupation_isco_4="2511",
            region_code="RUH",
            sector_isic_4="J62",
            is_saudi=True,
            gender="X",  # invalid
            age_bucket="30-34",
            employment_status="active",
        )


def test_mercer_cell_schema_valid() -> None:
    cell = MercerCell(
        survey_year=2024,
        job_family="SWE",
        level="IC4",
        n_participants=42,
        base_p25=18_000.0,
        base_p50=24_000.0,
        base_p75=31_000.0,
        target_total_cash_p50=30_000.0,
        sector_focus="ICT",
        region="RUH",
    )
    assert cell.base_p50 == 24_000.0


def test_mudad_aggregate_schema_valid() -> None:
    agg = MudadAggregate(
        month=datetime(2026, 1, 1, tzinfo=UTC),
        region_code="RUH",
        sector_isic_4="J62",
        size_bucket="250-999",
        n_workers=500,
        avg_monthly_wage=13_500.0,
        share_saudi=0.6,
    )
    assert agg.share_saudi == 0.6


def test_lightcast_posting_schema_valid() -> None:
    p = LightcastPosting(
        posting_id="LC-9281",
        posted_at=datetime(2026, 5, 1, tzinfo=UTC),
        company_name="Example Co",
        company_cr=None,
        title_raw="Sr. Backend Eng",
        title_clean="Senior Backend Engineer",
        onet_soc="15-1252.00",
        location_region="RUH",
        sector_naics="518210",
        skills=("python", "kubernetes"),
        salary_low=None,
        salary_high=None,
        salary_period=None,
    )
    assert p.title_clean.startswith("Senior")


@pytest.mark.parametrize("loader", [
    fetch_gosi_microdata, fetch_mercer_trs, fetch_mudad_aggregates, fetch_lightcast_postings,
])
def test_loaders_are_scaffolds_until_access_wired(loader: object) -> None:
    """Until real data access is wired, each loader must raise NotImplementedError.

    This test exists to catch a regression where a future change accidentally returns
    a placeholder dataframe — which would silently corrupt the training pipeline.
    """
    with pytest.raises(NotImplementedError, match="scaffold"):
        loader()  # type: ignore[operator]
