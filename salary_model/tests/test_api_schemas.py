from __future__ import annotations

from salary_model.api.schemas import PredictRequest
from salary_model.data.types import JobFamily, Level, Ownership, Region, Sector


def test_predict_request_defaults() -> None:
    req = PredictRequest(
        family=JobFamily.SWE,
        level=Level.IC4,
        yoe=7.0,
        region=Region.RIYADH,
        sector=Sector.ICT,
        company_ownership=Ownership.PIF_BACKED,
    )
    assert req.head == "descriptive"
    assert req.size_bucket == "250-999"


def test_predict_request_yoe_validation() -> None:
    import pytest

    with pytest.raises(ValueError, match="60"):
        PredictRequest(
            family=JobFamily.SWE, level=Level.IC4, yoe=70.0,
            region=Region.RIYADH, sector=Sector.ICT,
        )
