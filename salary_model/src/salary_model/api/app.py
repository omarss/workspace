"""FastAPI inference application.

Loads the latest model bundle once at startup and serves quantile + recommendation +
retrieval-blended predictions. The bundle artifact path is fixed at
``artifacts/model_bundle_latest.joblib``; re-run ``make iterate`` to refresh it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, cast

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException

from salary_model.api.schemas import (
    ComparablesBlock,
    ConfidenceBlock,
    DataProvenanceBlock,
    DescriptiveBlock,
    ExplanationFactor,
    FairnessBlock,
    PredictRequest,
    PredictResponse,
    QuantileBlock,
    RecommendationBlock,
)
from salary_model.config import get_logger, get_settings
from salary_model.data.types import EDUCATION_RANK, LEVEL_RANK
from salary_model.features.build import (
    feature_columns_blind,
    feature_columns_full,
)
from salary_model.models import retrieval as retrieval_mod
from salary_model.models.conformal import ConformalAdjustments
from salary_model.models.ensemble import blend_quantiles
from salary_model.models.quantile import QuantileBundle
from salary_model.models.retrieval import RetrievalIndex

log = get_logger("salary_model.api")

app = FastAPI(title="Saudi Salary Model", version="0.1.0")


@lru_cache(maxsize=1)
def _load_bundle() -> dict[str, Any]:
    settings = get_settings()
    path = settings.artifacts_dir / "model_bundle_latest.joblib"
    if not path.exists():
        msg = f"model bundle not found at {path}; run `make iterate` first"
        raise FileNotFoundError(msg)
    obj = joblib.load(path)
    if not isinstance(obj, dict):
        msg = f"unexpected bundle type: {type(obj).__name__}"
        raise TypeError(msg)
    return obj


_MACRO_FALLBACK_COLS: tuple[str, ...] = (
    "cpi_yoy", "cpi_yoy_lag1", "cpi_yoy_lag3", "cpi_yoy_lag6", "cpi_yoy_lag12",
    "policy_rate", "policy_rate_lag1", "policy_rate_lag3",
    "policy_rate_lag6", "policy_rate_lag12",
    "brent_usd", "brent_3m_avg_usd", "brent_yoy", "sar_to_usd",
)


def _macro_lookup(
    as_of: datetime, macro_series: pd.DataFrame | None,
) -> dict[str, float]:
    """Return the macro snapshot at ``as_of``; fall back to bundled anchors if missing."""
    from salary_model.data import anchors as _anchors  # local

    if macro_series is None or macro_series.empty:
        return {c: 0.0 for c in _MACRO_FALLBACK_COLS} | {
            "cpi_yoy": _anchors.NATIONAL_CPI_YOY,
            "policy_rate": _anchors.SAMA_POLICY_RATE,
            "brent_3m_avg_usd": _anchors.BRENT_3M_AVG_USD,
            "sar_to_usd": _anchors.SAR_TO_USD,
        }
    series = macro_series.sort_values("month")
    ts = pd.Timestamp(as_of).tz_convert("UTC")
    target = ts.tz_localize(None).to_period("M").to_timestamp(how="start").tz_localize("UTC")
    matched = series.loc[series["month"] <= target]
    if matched.empty:
        matched = series.iloc[[0]]
    row = matched.iloc[-1]
    return {c: float(row[c]) for c in _MACRO_FALLBACK_COLS if c in row.index}


def _build_inference_row(
    req: PredictRequest,
    category_codes: dict[str, dict[str, int]],
    macro_series: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Encode a single request into the canonical feature row layout.

    Categorical columns are mapped to integer codes via the per-feature mapping
    serialized into the model bundle at training time. Unknown values map to -1, which
    LightGBM treats as a missing category.
    """
    from salary_model.data import anchors  # local to keep startup cheap

    now = req.as_of or datetime.now(tz=UTC)
    raw: dict[str, object] = {
        "family": req.family.value,
        "level": req.level.value,
        "sector": req.sector.value,
        "region": req.region.value,
        "ownership": req.company_ownership.value,
        "size_bucket": req.size_bucket,
        "employment_type": req.employment_type.value,
        "work_mode": req.work_mode.value,
        "education": req.education.value,
    }
    raw_to_code_col: dict[str, str] = {
        "family": "family_code",
        "level": "level_code",
        "sector": "sector_code",
        "region": "region_code",
        "ownership": "ownership_code",
        "size_bucket": "size_code",
        "employment_type": "employment_code",
        "work_mode": "workmode_code",
        "education": "education_code",
    }
    coded: dict[str, int] = {}
    for src, code_col in raw_to_code_col.items():
        mapping = category_codes.get(code_col, {})
        coded[code_col] = int(mapping.get(str(raw[src]), -1))

    row: dict[str, object] = {
        **coded,
        "yoe": float(req.yoe),
        "yoe_sq": float(req.yoe) ** 2,
        "level_rank": int(LEVEL_RANK[req.level]),
        "education_rank": int(EDUCATION_RANK[req.education]),
        "region_base_multiplier": float(anchors.REGION_BASE_MULTIPLIER[req.region]),
        "sector_base_median": float(anchors.SECTOR_BASE_MEDIAN[req.sector]),
        "ownership_lift": float(anchors.OWNERSHIP_LIFT[req.company_ownership]),
        "family_premium": float(anchors.FAMILY_PREMIUM[req.family]),
        "size_lift": float(anchors.SIZE_LIFT[req.size_bucket]),
        "log_sigma_sector": float(anchors.SECTOR_LOG_SIGMA[req.sector]),
        "month_sin": float(np.sin(2.0 * np.pi * now.month / 12.0)),
        "month_cos": float(np.cos(2.0 * np.pi * now.month / 12.0)),
        "year_ord": int(now.year),
        "vision_phase": 3 if now.year >= 2026 else 2,
        # Macro: looked up from the bundled monthly series at the request's `as_of`.
        # Falls back to the bundled anchor constants only if no series is attached.
        **_macro_lookup(now, macro_series),
        "is_metro": int(req.region.value in {"RUH", "JED", "EST"}),
        "is_pif_or_mnc": int(req.company_ownership.value in {"pif_backed", "mnc"}),
        "is_exec": int(req.level.value in {
            "M3", "M4", "M5", "D1", "D2", "D3", "VP", "SVP", "CXO",
        }),
        "is_saudi": int(bool(req.is_saudi)) if req.is_saudi is not None else 1,
        "gender_code": 1 if (req.gender and req.gender.value == "F") else 0,
        "age_bucket_ord": 2,  # default "30-34"; never used by the recommendation head
    }
    return pd.DataFrame([row])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/model")
def model_info() -> dict[str, Any]:
    bundle = _load_bundle()
    return {
        "snapshot_hash": bundle.get("snapshot_hash"),
        "seed": bundle.get("seed"),
        "feature_columns_full_count": len(bundle.get("feature_columns_full", [])),
        "feature_columns_blind_count": len(bundle.get("feature_columns_blind", [])),
    }


@app.post("/v1/predict", response_model=PredictResponse)
def predict(req: PredictRequest) -> PredictResponse:
    try:
        bundle = _load_bundle()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    descriptive: QuantileBundle = bundle["descriptive_bundle"]
    desc_adjust: ConformalAdjustments = bundle["descriptive_conformal"]
    recommend: QuantileBundle = bundle["recommendation_bundle"]
    rec_adjust: ConformalAdjustments = bundle["recommendation_conformal"]
    idx: RetrievalIndex = bundle["retrieval_index"]
    category_codes = bundle.get("category_codes", {})

    X = _build_inference_row(req, category_codes, bundle.get("macro_series"))
    cols_full = feature_columns_full()
    cols_blind = feature_columns_blind()

    raw_desc = descriptive.predict_quantiles(X[cols_full])
    cal_desc = desc_adjust.widen(raw_desc)
    parametric = {q: float(cal_desc[q][0]) for q in cal_desc}

    region_code = int(X["region_code"].iloc[0])
    neighbors = retrieval_mod.search(idx, X, k=50, query_region_code=region_code)[0]
    ret_q = retrieval_mod.retrieval_quantiles(
        neighbors, quantiles=tuple(sorted(parametric.keys())), target="base",
    )
    blended = blend_quantiles(parametric, ret_q, n_comparables=int(neighbors["base"].size))

    rec_block: RecommendationBlock | None = None
    if req.head == "recommendation":
        raw_rec = recommend.predict_quantiles(X[cols_blind])
        cal_rec = rec_adjust.widen(raw_rec)
        rec_p50 = float(cal_rec[0.5][0])
        desc_p50 = float(blended.quantiles.get(0.5, parametric[0.5]))
        rec_block = RecommendationBlock(
            base_p50_fair=rec_p50,
            delta_vs_descriptive_pct=(rec_p50 - desc_p50) / desc_p50 if desc_p50 else 0.0,
            notes="Trained on blinded features with sensitive-group reweighting.",
        )

    confidence_score = min(0.95, 0.55 + 0.005 * blended.n_comparables)
    quant_block = QuantileBlock(
        p10=max(0.0, blended.quantiles.get(0.1, parametric[0.1])),
        p25=max(0.0, blended.quantiles.get(0.25, parametric[0.25])),
        p50=max(0.0, blended.quantiles.get(0.5, parametric[0.5])),
        p75=max(0.0, blended.quantiles.get(0.75, parametric[0.75])),
        p90=max(0.0, blended.quantiles.get(0.9, parametric[0.9])),
    )

    shap_explainer = bundle.get("shap_explainer")
    if shap_explainer is not None:
        contribs = shap_explainer.explain_row(X[cols_full], top_k=5)
        if contribs:
            explanation = [
                ExplanationFactor(
                    feature=f"{c.feature}={c.feature_value}",
                    shap=c.shap_value,
                    human=_humanize(c.feature),
                )
                for c in contribs
            ]
        else:
            explanation = _approx_explanation(req, parametric[0.5])
    else:
        explanation = _approx_explanation(req, parametric[0.5])
    fairness_flag = (
        "sensitive_used_descriptive" if req.head == "descriptive" else "none"
    )

    training_mix = bundle.get("training_mix", {})
    trained_on_real_data = bool(bundle.get("trained_on_real_data", False))
    return PredictResponse(
        model_version=str(bundle.get("snapshot_hash", "unknown"))[:12],
        as_of=req.as_of or datetime.now(tz=UTC),
        head=req.head,
        descriptive=DescriptiveBlock(base=quant_block),
        recommendation=rec_block,
        confidence=ConfidenceBlock(
            score=float(confidence_score),
            drivers=[
                f"n_comparables={blended.n_comparables}",
                f"parametric_weight={blended.parametric_weight:.2f}",
            ],
        ),
        comparables=ComparablesBlock(
            n=blended.n_comparables,
            parametric_weight=blended.parametric_weight,
        ),
        explanation=explanation,
        warnings=list(blended.warnings),
        fairness=FairnessBlock(
            flag=cast("Any", fairness_flag),
            sensitive_features_used=(
                ["is_saudi", "gender_code"] if req.head == "descriptive" else []
            ),
        ),
        data_provenance=DataProvenanceBlock(
            trained_on_real_data=trained_on_real_data,
            training_mix={str(k): int(v) for k, v in training_mix.items()},
            snapshot_hash=str(bundle.get("snapshot_hash", "")),
        ),
    )


_HUMAN_LABELS: dict[str, str] = {
    "yoe": "Years of experience",
    "yoe_sq": "Saturating returns to experience",
    "level_rank": "Seniority level",
    "education_rank": "Education level",
    "region_base_multiplier": "Regional cost-of-labor index",
    "sector_base_median": "Sector median wage anchor",
    "ownership_lift": "Employer ownership type",
    "family_premium": "Job family premium",
    "size_lift": "Company size lift",
    "log_sigma_sector": "Sector wage dispersion",
    "is_metro": "Metro region (Riyadh / Jeddah / Eastern)",
    "is_pif_or_mnc": "PIF-backed or multinational employer",
    "is_exec": "Executive-track level",
    "family_code": "Job family",
    "level_code": "Seniority level",
    "sector_code": "Industry sector",
    "region_code": "Region",
    "ownership_code": "Employer ownership",
    "size_code": "Company size bucket",
    "employment_code": "Employment type",
    "workmode_code": "Work mode",
    "education_code": "Education category",
    "month_sin": "Seasonality (sine)",
    "month_cos": "Seasonality (cosine)",
    "year_ord": "Year",
    "vision_phase": "Vision 2030 phase",
    "national_cpi_yoy": "National CPI YoY",
    "policy_rate": "SAMA policy rate",
    "brent_3m_avg_usd": "Oil price (Brent 3M avg)",
    "is_saudi": "Nationality flag (Saudi)",
    "gender_code": "Gender (encoded)",
    "age_bucket_ord": "Age bucket",
}


def _humanize(feature: str) -> str:
    return _HUMAN_LABELS.get(feature, feature)


def _approx_explanation(req: PredictRequest, p50: float) -> list[ExplanationFactor]:
    """Quick local approximation; replace with SHAP once we serialize a TreeExplainer."""
    from salary_model.data import anchors  # local import

    factors: list[ExplanationFactor] = []
    fam_lift = anchors.FAMILY_PREMIUM[req.family]
    factors.append(ExplanationFactor(
        feature=f"family={req.family.value}",
        shap=float(p50 * (fam_lift - 1.0)),
        human=f"Family premium ({fam_lift:.2f}x sector median)",
    ))
    own_lift = anchors.OWNERSHIP_LIFT[req.company_ownership]
    factors.append(ExplanationFactor(
        feature=f"ownership={req.company_ownership.value}",
        shap=float(p50 * (own_lift - 1.0)),
        human=f"Ownership type ({own_lift:.2f}x baseline)",
    ))
    region_lift = anchors.REGION_BASE_MULTIPLIER[req.region]
    factors.append(ExplanationFactor(
        feature=f"region={req.region.value}",
        shap=float(p50 * (region_lift - 1.0)),
        human=f"Regional cost-of-labor index ({region_lift:.2f})",
    ))
    factors.append(ExplanationFactor(
        feature=f"level={req.level.value}",
        shap=float(p50 * (anchors.LEVEL_MULTIPLIER[req.level] / 1.35 - 1.0)),
        human="Level multiplier relative to IC4",
    ))
    factors.append(ExplanationFactor(
        feature=f"yoe={req.yoe:.0f}",
        shap=float(p50 * 0.01 * (req.yoe - 5.0)),
        human="Approximate experience contribution",
    ))
    return factors
