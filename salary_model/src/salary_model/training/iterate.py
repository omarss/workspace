"""End-to-end iteration runner: builds the model ladder and records metrics per step.

Each iteration adds one ingredient and re-evaluates on the same temporal test split.
The output is a folder under ``reports/runs/<RUN_ID>/`` containing:

* ``summary.md`` — Markdown scorecard
* ``metrics.json`` — machine-readable metrics, one record per iteration step
* ``fairness.md`` — counterfactual fairness audit
* ``slice_scorecard.csv`` — per-slice errors
* ``model_bundle.joblib`` — frozen final bundle ready for inference
* ``manifest.json`` — data snapshot hash + seed for reproducibility
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import optuna
import pandas as pd

from salary_model.config import get_logger, get_settings
from salary_model.data.build import load_latest_snapshot
from salary_model.features.build import (
    BuiltFeatures,
    build_feature_frame,
    feature_columns_blind,
    feature_columns_full,
    split_indices,
)
from salary_model.models import (
    baseline,
    bayes,
    conformal,
    ensemble,
    explain,
    fairness,
    quantile,
    retrieval,
)
from salary_model.training.evaluate import (
    evaluate_quantiles,
    interval_coverage,
    mae,
    mape,
    pinball,
    slice_scorecard,
    smape,
)

log = get_logger("salary_model.training.iterate")


optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass
class IterationStep:
    step: int
    name: str
    metrics: dict[str, float]
    elapsed_s: float
    notes: str = ""


@dataclass
class IterationReport:
    run_id: str
    seed: int
    n_rows: int
    steps: list[IterationStep] = field(default_factory=list)
    snapshot_hash: str = ""

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# Iteration run `{self.run_id}`\n")
        lines.append(
            f"- seed: `{self.seed}`\n- rows: `{self.n_rows}`\n"
            f"- snapshot sha256: `{self.snapshot_hash[:12]}...`\n"
        )
        lines.append("\n## Headline metrics per step (base_monthly)\n")
        cols = sorted({k for s in self.steps for k in s.metrics})
        prefer = [
            "mae_p50", "mape_p50", "smape_p50", "rmse_p50",
            "pinball_q10", "pinball_q25", "pinball_q50", "pinball_q75", "pinball_q90",
            "coverage_80", "coverage_90", "width_80", "width_90",
        ]
        ordered = [c for c in prefer if c in cols] + [c for c in cols if c not in prefer]
        header = "| step | name | elapsed_s | " + " | ".join(ordered) + " |"
        sep = "|" + "|".join(["---"] * (3 + len(ordered))) + "|"
        lines.append(header)
        lines.append(sep)
        for s in self.steps:
            row = [str(s.step), s.name, f"{s.elapsed_s:.2f}"]
            for c in ordered:
                v = s.metrics.get(c)
                row.append(f"{v:.4f}" if isinstance(v, (int, float)) else "—")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
        return "\n".join(lines)


def _huber_predict(booster: Any, X: pd.DataFrame, cols: list[str]) -> np.ndarray:
    return np.asarray(booster.predict(X[cols]), dtype=float)


def _slice_warnings(df: pd.DataFrame, scorecard: pd.DataFrame) -> list[str]:
    global_mae = float((df["abs_err"]).mean())
    threshold = 1.5 * global_mae
    bad = scorecard[scorecard["mae"] > threshold]
    return [f"{int(row['n'])} rows in slice with mae={row['mae']:.0f}" for _, row in bad.iterrows()]


def _optuna_objective(
    trial: optuna.Trial,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    weights: pd.Series,
    feature_cols: list[str],
    categorical_cols: list[str],
    seed: int,
) -> float:
    params: dict[str, object] = {
        "num_leaves": trial.suggest_int("num_leaves", 31, 255),
        "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.12, log=True),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 20, 200),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.6, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.6, 1.0),
        "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
    }
    bundle = quantile.train_quantile_bundle(
        X_train, y_train, X_val, y_val,
        feature_columns=feature_cols,
        categorical_columns=categorical_cols,
        target="base_monthly",
        quantiles=(0.1, 0.5, 0.9),
        weights=weights,
        params=params,
        num_boost_round=500,
        early_stopping_rounds=40,
        seed=seed,
    )
    preds = bundle.predict_quantiles(X_val)
    return sum(
        pinball(y_val.to_numpy(dtype=float), preds[q], quantile=q) for q in (0.1, 0.5, 0.9)
    )


def _maybe_mlflow_start(run_id: str, seed: int) -> object | None:
    """Start an MLflow run if mlflow is installed and not disabled via env."""
    try:
        import mlflow
    except ImportError:
        return None
    settings = get_settings()
    mlflow.set_tracking_uri(f"file:{settings.mlruns_dir}")
    mlflow.set_experiment("salary-model")
    active = mlflow.start_run(run_name=run_id)
    mlflow.log_params({"run_id": run_id, "seed": seed})
    return active


def _maybe_mlflow_log_step(step: IterationStep) -> None:
    try:
        import mlflow
    except ImportError:
        return
    import math
    for name, val in step.metrics.items():
        if isinstance(val, (int, float)) and math.isfinite(float(val)):
            mlflow.log_metric(f"step{step.step}_{name}", float(val))
    mlflow.log_metric(f"step{step.step}_elapsed_s", float(step.elapsed_s))


def _maybe_mlflow_end(active: object | None, run_dir: Path) -> None:
    if active is None:
        return
    try:
        import mlflow
    except ImportError:
        return
    for fname in ("summary.md", "metrics.json", "fairness.md", "slice_scorecard.csv"):
        p = run_dir / fname
        if p.exists():
            mlflow.log_artifact(str(p))
    mlflow.end_run()


def run_iteration(
    *,
    run_id: str,
    seed: int,
    optuna_trials: int = 12,
) -> IterationReport:
    settings = get_settings()
    settings.ensure_dirs()
    run_dir = settings.reports_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    obs, manifest = load_latest_snapshot()
    log.info("iter_start", run_id=run_id, rows=len(obs), seed=seed)
    mlflow_run = _maybe_mlflow_start(run_id, seed)

    feats: BuiltFeatures = build_feature_frame(obs)
    train_idx, val_idx, test_idx = split_indices(
        obs,
        val_fraction=settings.val_fraction,
        test_fraction=settings.test_fraction,
    )

    feature_cols_full = feature_columns_full()
    feature_cols_blind = feature_columns_blind()
    categorical_cols = list(feats.categorical)

    X_train = feats.X.loc[train_idx, feature_cols_full]
    y_train_base = feats.y_base.loc[train_idx]
    w_train = feats.weights.loc[train_idx]

    X_val = feats.X.loc[val_idx, feature_cols_full]
    y_val_base = feats.y_base.loc[val_idx]

    X_test = feats.X.loc[test_idx, feature_cols_full]
    y_test_base = feats.y_base.loc[test_idx]
    obs_test = obs.loc[test_idx]

    report = IterationReport(
        run_id=run_id, seed=seed, n_rows=len(obs),
        snapshot_hash=manifest.get("snapshot_sha256", ""),
    )
    target_quantiles = settings.quantiles
    coverage_targets = settings.coverage_targets

    # ── Step 0: Ridge baseline on log(target) ─────────────────────────────────
    t0 = time.perf_counter()
    base = baseline.train_baseline(
        X_train, y_train_base,
        feature_columns=feature_cols_full,
        categorical_columns=categorical_cols,
        target="base_monthly",
        weights=w_train,
    )
    pred_base = base.predict(X_test)
    metrics_0 = {
        "mae_p50": mae(y_test_base.to_numpy(), pred_base),
        "mape_p50": mape(y_test_base.to_numpy(), pred_base),
        "smape_p50": smape(y_test_base.to_numpy(), pred_base),
    }
    report.steps.append(IterationStep(
        step=0, name="ridge_baseline",
        metrics=metrics_0, elapsed_s=time.perf_counter() - t0,
        notes="log-target ridge with one-hot + scaler",
    ))
    log.info("iter_step_done", step=0, **metrics_0)

    # ── Step 1: LightGBM single-point Huber ────────────────────────────────────
    t0 = time.perf_counter()
    huber_booster = quantile.train_lightgbm_point(
        X_train, y_train_base, X_val, y_val_base,
        feature_columns=feature_cols_full,
        categorical_columns=categorical_cols,
        weights=w_train, seed=seed,
    )
    pred_huber = _huber_predict(huber_booster, X_test, feature_cols_full)
    metrics_1 = {
        "mae_p50": mae(y_test_base.to_numpy(), pred_huber),
        "mape_p50": mape(y_test_base.to_numpy(), pred_huber),
        "smape_p50": smape(y_test_base.to_numpy(), pred_huber),
    }
    report.steps.append(IterationStep(
        step=1, name="lightgbm_huber",
        metrics=metrics_1, elapsed_s=time.perf_counter() - t0,
        notes="LightGBM with monotone constraints on yoe/level/ownership",
    ))
    log.info("iter_step_done", step=1, **metrics_1)

    # ── Step 2: LightGBM quantile bundle ───────────────────────────────────────
    t0 = time.perf_counter()
    bundle = quantile.train_quantile_bundle(
        X_train, y_train_base, X_val, y_val_base,
        feature_columns=feature_cols_full,
        categorical_columns=categorical_cols,
        target="base_monthly",
        quantiles=target_quantiles,
        weights=w_train, seed=seed,
    )
    preds_quant = bundle.predict_quantiles(X_test)
    metrics_2 = evaluate_quantiles(
        y_test_base.to_numpy(), preds_quant, coverage_targets,
    )
    report.steps.append(IterationStep(
        step=2, name="lightgbm_quantile",
        metrics=metrics_2, elapsed_s=time.perf_counter() - t0,
        notes="Five quantile boosters; crossings repaired by sorting",
    ))
    log.info("iter_step_done", step=2, **metrics_2)

    # ── Step 3: Conformal calibration on val (split CP) ────────────────────────
    t0 = time.perf_counter()
    adjustments = conformal.calibrate(
        bundle, X_val, y_val_base, coverage_targets=coverage_targets,
    )
    preds_calibrated = adjustments.widen(preds_quant)
    metrics_3 = evaluate_quantiles(
        y_test_base.to_numpy(), preds_calibrated, coverage_targets,
    )
    report.steps.append(IterationStep(
        step=3, name="conformal_calibrated",
        metrics=metrics_3, elapsed_s=time.perf_counter() - t0,
        notes="Split-conformal symmetric widening per coverage target",
    ))
    log.info("iter_step_done", step=3, **metrics_3)

    # ── Step 4: feature group ablation - quantify lift of macro+scarcity ──────
    # Train a "lean" quantile bundle without the macro / sector-anchor features
    # and report the marginal lift from the full feature set.
    t0 = time.perf_counter()
    lean_cols = [
        c for c in feature_cols_full
        if c not in {
            "national_cpi_yoy", "policy_rate", "brent_3m_avg_usd",
            "region_base_multiplier", "sector_base_median",
            "ownership_lift", "family_premium", "size_lift", "log_sigma_sector",
        }
    ]
    lean_bundle = quantile.train_quantile_bundle(
        X_train, y_train_base, X_val, y_val_base,
        feature_columns=lean_cols,
        categorical_columns=categorical_cols,
        target="base_monthly",
        quantiles=target_quantiles,
        weights=w_train, seed=seed,
        num_boost_round=800, early_stopping_rounds=60,
    )
    preds_lean = lean_bundle.predict_quantiles(X_test[lean_cols])
    lean_metrics = evaluate_quantiles(
        y_test_base.to_numpy(), preds_lean, coverage_targets,
    )
    lift = {f"lift_{k}": metrics_3[k] - lean_metrics[k] for k in metrics_3 if k in lean_metrics}
    report.steps.append(IterationStep(
        step=4, name="feature_ablation_lean_vs_full",
        metrics={**lean_metrics, **lift}, elapsed_s=time.perf_counter() - t0,
        notes="Trains a lean bundle without macro & anchor features for marginal-lift comparison",
    ))
    log.info("iter_step_done", step=4)

    # ── Step 5: Optuna hyperparameter sweep ────────────────────────────────────
    t0 = time.perf_counter()
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.optimize(
        lambda trial: _optuna_objective(
            trial, X_train, y_train_base, X_val, y_val_base, w_train,
            feature_cols_full, categorical_cols, seed,
        ),
        n_trials=optuna_trials,
        show_progress_bar=False,
    )
    best_params = study.best_params
    tuned_bundle = quantile.train_quantile_bundle(
        X_train, y_train_base, X_val, y_val_base,
        feature_columns=feature_cols_full,
        categorical_columns=categorical_cols,
        target="base_monthly",
        quantiles=target_quantiles,
        weights=w_train, seed=seed,
        params=best_params,
    )
    preds_tuned = tuned_bundle.predict_quantiles(X_test)
    tuned_adjust = conformal.calibrate(
        tuned_bundle, X_val, y_val_base, coverage_targets=coverage_targets,
    )
    preds_tuned_cal = tuned_adjust.widen(preds_tuned)
    metrics_5 = evaluate_quantiles(
        y_test_base.to_numpy(), preds_tuned_cal, coverage_targets,
    )
    report.steps.append(IterationStep(
        step=5, name="optuna_tuned_conformal",
        metrics=metrics_5, elapsed_s=time.perf_counter() - t0,
        notes=f"Optuna {optuna_trials} trials; best params {best_params}",
    ))
    log.info("iter_step_done", step=5, **metrics_5)

    # ── Step 6: Retrieval blend ────────────────────────────────────────────────
    t0 = time.perf_counter()
    region_codes = feats.X["region_code"]
    obs_local = obs.copy()
    idx_proj = retrieval.build_index(
        feats.X.loc[train_idx],
        feats.y_base.loc[train_idx],
        feats.y_tcc.loc[train_idx],
        region_codes=region_codes.loc[train_idx],
        confidences=feats.weights.loc[train_idx],
        observed_at=obs_local.loc[train_idx, "observed_at"],
    )

    # Retrieval is a *sparse-segment fallback*. We compute it for every row so the API
    # always has a comparables block, but we only let it override the parametric quantiles
    # when the (family, level, region) cell has truly few training observations
    # (n_cell < `sparse_cell_threshold`). On synthetic data the cell partition is fine
    # enough that the parametric model dominates in dense cells; we found via iteration
    # that even modest blending in dense cells regresses MAE because the retrieval
    # estimate has higher variance than the LightGBM point.
    sparse_cell_threshold = 5
    cell_counts_train = (
        obs.loc[train_idx].groupby(["family", "level", "region"]).size()
        .rename("n_cell").reset_index()
    )
    obs_test_n_cell = obs.loc[test_idx].merge(
        cell_counts_train, on=["family", "level", "region"], how="left",
    )["n_cell"].fillna(0).to_numpy(dtype=float)

    blended_p50 = []
    blended_p10 = []
    blended_p90 = []
    n_comparables_arr = []
    batch_k = 200
    batch = retrieval.search(idx_proj, X_test, k=batch_k, query_region_code=None)
    for i, (_, nb) in enumerate(zip(X_test.index, batch, strict=True)):
        target_region = int(region_codes.loc[X_test.index[i]])
        mask = idx_proj.region_codes[nb["indices"]] == target_region
        if mask.sum() >= 20:
            nb_f = {k: (v[mask] if hasattr(v, "__getitem__") else v) for k, v in nb.items()}
        else:
            nb_f = nb
        param_q = {q: float(preds_tuned_cal[q][i]) for q in target_quantiles}
        n_cell_here = int(obs_test_n_cell[i])
        if n_cell_here < sparse_cell_threshold:
            ret_q = retrieval.retrieval_quantiles(
                nb_f, quantiles=target_quantiles, target="base",
            )
            blend = ensemble.blend_quantiles(
                param_q, ret_q, n_comparables=int(nb_f["base"].size),
            )
            blended_p10.append(blend.quantiles[0.1])
            blended_p50.append(blend.quantiles[0.5])
            blended_p90.append(blend.quantiles[0.9])
            n_comparables_arr.append(blend.n_comparables)
        else:
            blended_p10.append(param_q[0.1])
            blended_p50.append(param_q[0.5])
            blended_p90.append(param_q[0.9])
            n_comparables_arr.append(int(nb_f["base"].size))

    preds_blend = {
        0.1: np.asarray(blended_p10),
        0.5: np.asarray(blended_p50),
        0.9: np.asarray(blended_p90),
        0.25: preds_tuned_cal[0.25],
        0.75: preds_tuned_cal[0.75],
    }
    metrics_6 = evaluate_quantiles(
        y_test_base.to_numpy(), preds_blend, coverage_targets,
    )
    metrics_6["mean_n_comparables"] = float(np.mean(n_comparables_arr))
    report.steps.append(IterationStep(
        step=6, name="retrieval_blended",
        metrics=metrics_6, elapsed_s=time.perf_counter() - t0,
        notes="Recency- and confidence-weighted neighbor blending policy from §10",
    ))
    log_metrics_6 = {k: v for k, v in metrics_6.items() if k != "mean_n_comparables"}
    log.info("iter_step_done", step=6, **log_metrics_6)

    # ── Step 7: Fairness debiasing (recommendation head) ───────────────────────
    t0 = time.perf_counter()
    weights_rec = fairness.reweight_sensitive(obs.loc[train_idx])
    X_train_blind = X_train[feature_cols_blind]
    X_val_blind = X_val[feature_cols_blind]
    X_test_blind = X_test[feature_cols_blind]
    rec_bundle = quantile.train_quantile_bundle(
        X_train_blind, y_train_base, X_val_blind, y_val_base,
        feature_columns=feature_cols_blind,
        categorical_columns=categorical_cols,
        target="base_monthly",
        quantiles=target_quantiles,
        weights=pd.Series(weights_rec.to_numpy(), index=X_train_blind.index),
        seed=seed,
    )
    rec_adjust = conformal.calibrate(
        rec_bundle, X_val_blind, y_val_base, coverage_targets=coverage_targets,
    )
    rec_preds = rec_adjust.widen(rec_bundle.predict_quantiles(X_test_blind))
    metrics_7 = evaluate_quantiles(
        y_test_base.to_numpy(), rec_preds, coverage_targets,
    )

    # Counterfactual audit: flip gender and is_saudi on the descriptive head and measure drift
    X_test_flip_g = X_test.copy()
    X_test_flip_g["gender_code"] = 1 - X_test_flip_g["gender_code"]
    X_test_flip_n = X_test.copy()
    X_test_flip_n["is_saudi"] = 1 - X_test_flip_n["is_saudi"]
    p50_base = tuned_bundle.predict_quantiles(X_test)[0.5]
    p50_flip_g = tuned_bundle.predict_quantiles(X_test_flip_g)[0.5]
    p50_flip_n = tuned_bundle.predict_quantiles(X_test_flip_n)[0.5]
    fairness_descriptive = fairness.counterfactual_audit(
        pd.Series(p50_base),
        pd.Series(p50_flip_g),
        pd.Series(p50_flip_n),
        family=obs.loc[test_idx, "family"].reset_index(drop=True),
        level=obs.loc[test_idx, "level"].reset_index(drop=True),
    )
    p50_rec = rec_preds[0.5]
    p50_rec_flip_g = rec_adjust.widen(
        rec_bundle.predict_quantiles(X_test_flip_g[feature_cols_blind])
    )[0.5]
    p50_rec_flip_n = rec_adjust.widen(
        rec_bundle.predict_quantiles(X_test_flip_n[feature_cols_blind])
    )[0.5]
    fairness_recommend = fairness.counterfactual_audit(
        pd.Series(p50_rec),
        pd.Series(p50_rec_flip_g),
        pd.Series(p50_rec_flip_n),
        family=obs.loc[test_idx, "family"].reset_index(drop=True),
        level=obs.loc[test_idx, "level"].reset_index(drop=True),
    )
    # Truth-check against live GASTAT data — our model's gender gap should not be
    # wildly inconsistent with the published gap (off by > 2x is a yellow flag).
    truth_block = ""
    try:
        from salary_model.data.build import load_latest_wage_index
        from salary_model.data.sources.wage_index_live import gender_gap_pct, saudi_gap_pct
        wage_idx = load_latest_wage_index()
        if not wage_idx.empty:
            published_all = gender_gap_pct(wage_idx)
            published_saudi = gender_gap_pct(wage_idx, saudi_only=True)
            published_nat = saudi_gap_pct(wage_idx)
            model_gender = fairness_descriptive.median_abs_gap_pct_gender
            model_nat = fairness_descriptive.median_abs_gap_pct_nationality
            published_year = int(wage_idx["year"].max())
            lines = [
                "\n\n## Truth-check vs live GASTAT data (KAPSARC)\n",
                f"Reference year: **{published_year}**\n",
            ]
            if published_all is not None:
                lines.append(
                    f"- Published gender gap, all employees: "
                    f"**{published_all:+.2%}** (vs model |gap| {model_gender:.2%})"
                )
            if published_saudi is not None:
                lines.append(
                    f"- Published gender gap, Saudi-only: **{published_saudi:+.2%}**"
                )
            if published_nat is not None:
                lines.append(
                    f"- Published Saudi-vs-all wage premium: "
                    f"**{published_nat:+.2%}** (vs model |nat gap| {model_nat:.2%})"
                )
            lines.append("")
            lines.append(
                "Reading: large positive Saudi-vs-all premium reflects expat labor "
                "concentrated at the floor; the larger Saudi-only gender gap is the "
                "residual real gap once the high-education female cohort is removed."
            )
            truth_block = "\n".join(lines)
    except Exception as exc:
        log.warning("wage_index_truth_check_failed", error=str(exc))
        truth_block = ""

    fairness_md = (
        "# Fairness audit\n\n"
        "## Descriptive head\n\n"
        + fairness_descriptive.to_markdown()
        + "\n\n## Recommendation head (blinded + reweighted)\n\n"
        + fairness_recommend.to_markdown()
        + truth_block
        + "\n"
    )
    (run_dir / "fairness.md").write_text(fairness_md, encoding="utf-8")

    metrics_7.update(
        {
            "fair_gender_median_descriptive": fairness_descriptive.median_abs_gap_pct_gender,
            "fair_gender_median_recommend": fairness_recommend.median_abs_gap_pct_gender,
            "fair_nat_median_descriptive": fairness_descriptive.median_abs_gap_pct_nationality,
            "fair_nat_median_recommend": fairness_recommend.median_abs_gap_pct_nationality,
        }
    )
    report.steps.append(IterationStep(
        step=7, name="recommendation_blinded_reweighted",
        metrics=metrics_7, elapsed_s=time.perf_counter() - t0,
        notes="Recommendation head: blinded features + reweighted samples; audit attached.",
    ))
    log.info("iter_step_done", step=7)

    # ── Step 8: Hierarchical Bayesian shrinkage stabilizes sparse cells ───────
    t0 = time.perf_counter()
    train_obs = obs.loc[train_idx]
    shrink = bayes.fit_shrinkage(train_obs, target="base_monthly", seed=seed)
    shrink_pred = obs.loc[test_idx].apply(
        lambda r: shrink.predict(r["family"], r["level"], r["region"]),
        axis=1,
    ).to_numpy(dtype=float)
    # Blend shrinkage with parametric p50 inversely proportional to local sample density.
    cell_counts = (
        train_obs.groupby(["family", "level", "region"]).size().rename("n_cell").reset_index()
    )
    obs_test_with_n = obs.loc[test_idx].merge(
        cell_counts, on=["family", "level", "region"], how="left"
    )
    # v2 production prediction: the parametric model (with retrieval fallback for very
    # sparse cells) is the production output. The Bayes shrinkage is *retained* as a
    # diagnostic on the bundle and reported alongside, but is not blended into the
    # headline prediction because iteration on synthetic data showed that the coarse
    # (family, level, region) cell mean throws away conditioning information already
    # captured by the parametric estimator. When real microdata replaces the synthetic
    # generator, revisit by enabling the SVI fit and a small blend weight.
    n_cell = obs_test_with_n["n_cell"].fillna(0).to_numpy(dtype=float)
    w_shrink = np.zeros_like(n_cell)
    p50_param = preds_blend[0.5]
    p50_v2 = (1.0 - w_shrink) * p50_param + w_shrink * shrink_pred
    shrink_only_mae = float(mae(y_test_base.to_numpy(), shrink_pred))
    log.info("bayes_shrinkage_diagnostic_mae", value=shrink_only_mae)
    metrics_8 = {
        "mae_p50": mae(y_test_base.to_numpy(), p50_v2),
        "mape_p50": mape(y_test_base.to_numpy(), p50_v2),
        "smape_p50": smape(y_test_base.to_numpy(), p50_v2),
        "coverage_80": interval_coverage(
            y_test_base.to_numpy(), preds_blend[0.1], preds_blend[0.9],
        ),
        "shrinkage_only_mae_diagnostic": shrink_only_mae,
    }
    report.steps.append(IterationStep(
        step=8, name="v2_final",
        metrics=metrics_8, elapsed_s=time.perf_counter() - t0,
        notes=(
            "v2 = parametric (Optuna+conformal) + retrieval sparse fallback. "
            "Bayes shrinkage retained on the bundle as a diagnostic only (see notes)."
        ),
    ))
    log.info("iter_step_done", step=8, **metrics_8)

    # ── Slice scorecard (final step only) ──────────────────────────────────────
    abs_err = np.abs(y_test_base.to_numpy() - p50_v2)
    sc_df = obs_test.copy().reset_index(drop=True)
    sc_df["abs_err"] = abs_err
    scorecard = slice_scorecard(
        sc_df,
        y_true=y_test_base.reset_index(drop=True),
        p50=pd.Series(p50_v2),
        slice_cols=["family", "region", "level", "ownership", "gender", "is_saudi"],
    )
    scorecard.to_csv(run_dir / "slice_scorecard.csv", index=False)

    # ── Persist final v2 bundle for inference ──────────────────────────────────
    p50_booster = tuned_bundle.boosters[0.5]
    shap_explainer = explain.build_explainer(p50_booster, feature_cols_full)
    # Persist the macro series alongside the bundle so the API can do an `as_of`
    # lookup without depending on data/ being mounted in the inference container.
    from salary_model.data.build import load_latest_macro_series  # local to avoid cycle
    macro_series = load_latest_macro_series()

    # Provenance: which observations came from which source, for the API to surface.
    src_counts = obs.get("source", pd.Series(dtype=str)).value_counts().to_dict()
    training_mix = {str(k): int(v) for k, v in src_counts.items()}

    final_bundle: dict[str, Any] = {
        "descriptive_bundle": tuned_bundle,
        "descriptive_conformal": tuned_adjust,
        "recommendation_bundle": rec_bundle,
        "recommendation_conformal": rec_adjust,
        "retrieval_index": idx_proj,
        "bayes_shrinkage": shrink,
        "shap_explainer": shap_explainer,
        "macro_series": macro_series,
        "feature_columns_full": feature_cols_full,
        "feature_columns_blind": feature_cols_blind,
        "categorical_columns": categorical_cols,
        "category_codes": feats.category_codes,
        "seed": seed,
        "snapshot_hash": manifest.get("snapshot_sha256", ""),
        "training_mix": training_mix,
        "trained_on_real_data": not all(
            k == "synthetic_anchored" for k in training_mix
        ),
    }
    joblib.dump(final_bundle, run_dir / "model_bundle.joblib")
    # Also publish "latest" pointer for the API
    artifacts_latest = settings.artifacts_dir / "model_bundle_latest.joblib"
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(final_bundle, artifacts_latest)

    # ── Reports ───────────────────────────────────────────────────────────────
    (run_dir / "summary.md").write_text(report.to_markdown(), encoding="utf-8")
    (run_dir / "metrics.json").write_text(
        json.dumps([asdict(s) for s in report.steps], indent=2, default=str),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "seed": seed,
                "snapshot": manifest.get("snapshot"),
                "snapshot_sha256": manifest.get("snapshot_sha256"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Stream every step's metrics into MLflow now that all files exist on disk.
    for step in report.steps:
        _maybe_mlflow_log_step(step)
    _maybe_mlflow_end(mlflow_run, run_dir)
    log.info("iter_done", run_id=run_id, steps=len(report.steps))
    return report
