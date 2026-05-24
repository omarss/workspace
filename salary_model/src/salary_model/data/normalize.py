"""Canonical compensation normalization rules.

Heterogeneous inputs (annual vs monthly, gross vs net, SAR vs other, with/without
housing) are reduced to the canonical :class:`CompensationComponents` tuple. See §4 of
the design document.

The functions here are deliberately small and pure; complex business judgments
(e.g. when to gross-up an unspecified net) require explicit caller-side context.
"""

from __future__ import annotations

from dataclasses import dataclass

from salary_model.data.anchors import (
    HOUSING_FRACTION_DEFAULT,
    TRANSPORT_FRACTION_DEFAULT,
)
from salary_model.data.types import CompensationComponents

GOSI_EMPLOYEE_RATE: float = 0.0975  # Saudi employee + employer share, approximate
WORKING_DAYS_PER_MONTH: float = 22.0
CONTRACTOR_EMPLOYEE_EQUIVALENT_FACTOR: float = 0.78
MAX_VARIABLE_FRAC_DEFAULT: float = 1.0
MAX_VARIABLE_FRAC_SALES: float = 3.0


@dataclass(frozen=True)
class RawCompInput:
    """Loose, source-shaped compensation input. Optional fields are NaN-tolerant.

    Convention: monetary fields are SAR unless ``currency`` says otherwise.
    """

    amount: float
    period: str           # 'monthly' | 'annual' | 'hourly' | 'daily'
    gross_or_net: str     # 'gross' | 'net' | 'unknown'
    is_saudi: bool
    is_sales_family: bool
    currency: str = "SAR"
    fx_to_sar: float = 1.0
    weekly_hours: float | None = None
    housing: float | None = None
    transport: float | None = None
    other_fixed: float | None = None
    variable_monthly_eq: float | None = None
    equity_annual_ev: float | None = None
    employment_type: str = "ft"   # 'ft' | 'pt' | 'contract' | 'intern'


def _to_monthly(amount: float, period: str, weekly_hours: float | None) -> float:
    if period == "monthly":
        return amount
    if period == "annual":
        return amount / 12.0
    if period == "daily":
        return amount * WORKING_DAYS_PER_MONTH
    if period == "hourly":
        if weekly_hours is None or weekly_hours <= 0:
            msg = "weekly_hours required for hourly amounts"
            raise ValueError(msg)
        return amount * weekly_hours * 52.0 / 12.0
    msg = f"unsupported period: {period!r}"
    raise ValueError(msg)


def _gross_up(net_monthly: float, *, is_saudi: bool) -> float:
    if not is_saudi:
        return net_monthly
    return net_monthly / (1.0 - GOSI_EMPLOYEE_RATE)


def _contractor_equiv(base_monthly: float) -> float:
    return base_monthly * CONTRACTOR_EMPLOYEE_EQUIVALENT_FACTOR


def normalize_raw(raw: RawCompInput) -> tuple[CompensationComponents, list[str]]:
    """Normalize a raw input to canonical components plus emitted quality flags."""
    flags: list[str] = []
    if raw.amount <= 0:
        msg = "amount must be positive"
        raise ValueError(msg)

    amount_sar = raw.amount * raw.fx_to_sar
    base_monthly = _to_monthly(amount_sar, raw.period, raw.weekly_hours)

    if raw.gross_or_net == "net":
        base_monthly = _gross_up(base_monthly, is_saudi=raw.is_saudi)
        flags.append("gross_estimated_from_net")
    elif raw.gross_or_net == "unknown":
        flags.append("gross_net_unknown")

    if raw.employment_type == "contract":
        base_monthly = _contractor_equiv(base_monthly)
        flags.append("contractor_to_employee_equiv")

    housing = raw.housing
    if housing is None:
        flags.append("housing_imputed_null")
    housing_monthly = float(housing) if housing is not None else 0.0

    transport = raw.transport
    if transport is None:
        flags.append("transport_imputed_null")
    transport_monthly = float(transport) if transport is not None else 0.0

    other = float(raw.other_fixed) if raw.other_fixed is not None else 0.0

    # cap variable
    var = float(raw.variable_monthly_eq) if raw.variable_monthly_eq is not None else 0.0
    cap = MAX_VARIABLE_FRAC_SALES if raw.is_sales_family else MAX_VARIABLE_FRAC_DEFAULT
    if var > cap * base_monthly:
        var = cap * base_monthly
        flags.append("variable_capped")

    equity = float(raw.equity_annual_ev) if raw.equity_annual_ev is not None else 0.0

    comp = CompensationComponents(
        base_monthly=float(base_monthly),
        housing_monthly=float(housing_monthly),
        transport_monthly=float(transport_monthly),
        other_fixed_monthly=float(other),
        variable_monthly_eq=float(var),
        equity_annual_ev=float(equity),
    )
    return comp, flags


def impute_housing_transport_if_missing(
    comp: CompensationComponents, *, conservative: bool = True
) -> CompensationComponents:
    """If housing/transport are zero and caller asks, impute the KSA convention.

    Conservative (default): leave zero. Set ``conservative=False`` only when the source
    is known to omit allowances rather than report zero explicitly.
    """
    if conservative:
        return comp
    housing = (
        comp.housing_monthly
        if comp.housing_monthly > 0
        else comp.base_monthly * HOUSING_FRACTION_DEFAULT
    )
    transport = (
        comp.transport_monthly
        if comp.transport_monthly > 0
        else comp.base_monthly * TRANSPORT_FRACTION_DEFAULT
    )
    return comp.model_copy(
        update={"housing_monthly": housing, "transport_monthly": transport}
    )
