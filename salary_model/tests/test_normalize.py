from __future__ import annotations

import pytest

from salary_model.data.normalize import RawCompInput, normalize_raw


def test_annual_to_monthly_gross() -> None:
    raw = RawCompInput(
        amount=240_000.0, period="annual", gross_or_net="gross",
        is_saudi=True, is_sales_family=False,
    )
    comp, flags = normalize_raw(raw)
    assert comp.base_monthly == pytest.approx(20_000.0)
    assert "variable_capped" not in flags


def test_net_grossed_up_for_saudi_only() -> None:
    raw_saudi = RawCompInput(
        amount=10_000.0, period="monthly", gross_or_net="net",
        is_saudi=True, is_sales_family=False,
    )
    comp_saudi, flags_saudi = normalize_raw(raw_saudi)
    assert comp_saudi.base_monthly > 10_000.0
    assert "gross_estimated_from_net" in flags_saudi

    raw_expat = RawCompInput(
        amount=10_000.0, period="monthly", gross_or_net="net",
        is_saudi=False, is_sales_family=False,
    )
    comp_expat, _ = normalize_raw(raw_expat)
    assert comp_expat.base_monthly == pytest.approx(10_000.0)


def test_variable_capped_non_sales() -> None:
    raw = RawCompInput(
        amount=10_000.0, period="monthly", gross_or_net="gross",
        is_saudi=True, is_sales_family=False, variable_monthly_eq=99_999.0,
    )
    comp, flags = normalize_raw(raw)
    assert comp.variable_monthly_eq == pytest.approx(10_000.0)
    assert "variable_capped" in flags


def test_contractor_employee_equiv() -> None:
    raw = RawCompInput(
        amount=20_000.0, period="monthly", gross_or_net="gross",
        is_saudi=True, is_sales_family=False, employment_type="contract",
    )
    comp, flags = normalize_raw(raw)
    assert comp.base_monthly < 20_000.0
    assert "contractor_to_employee_equiv" in flags


def test_invalid_amount_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        normalize_raw(
            RawCompInput(
                amount=0.0, period="monthly", gross_or_net="gross",
                is_saudi=True, is_sales_family=False,
            )
        )
