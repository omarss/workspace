"""End-to-end dataset builder: open anchors + anchored synthetic observations.

Outputs a single Parquet snapshot under ``data/processed/`` plus a manifest JSON with
hashes and source provenance. Training reads only the snapshot, so retraining is
reproducible.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from salary_model.config import get_logger, get_settings
from salary_model.data import sources, synthetic
from salary_model.data.anchors import SOURCE_TRUST

log = get_logger("salary_model.data.build")


def _hash_dataframe(df: pd.DataFrame) -> str:
    raw = pd.util.hash_pandas_object(df, index=True).values.tobytes()
    return hashlib.sha256(raw).hexdigest()


def build_dataset(
    *,
    n_rows: int,
    seed: int,
    out_dir: Path | None = None,
    run_id: str | None = None,
) -> Path:
    """Build a versioned dataset snapshot. Returns the path of the written Parquet."""
    settings = get_settings()
    out_dir = out_dir or settings.processed_dir
    run_id = run_id or datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. anchors / external sources ─────────────────────────────────────────
    log.info("dataset_build_start", n_rows=n_rows, seed=seed, run_id=run_id)
    wage_df, wage_manifest = sources.fetch_gastat_wage_index()
    sama_df, sama_manifest = sources.fetch_sama_indicators()
    wb_df, wb_manifest = sources.fetch_worldbank_macro()
    macro_df, macro_manifest = sources.fetch_macro_series()
    # Live KAPSARC OpenDataSoft pulls; tagged is_estimate=False when they succeed.
    # Each is best-effort: a 404 / network outage just leaves the slot as a stub.
    kapsarc_results: dict[str, tuple[pd.DataFrame, Any]] = {
        "main_labor": sources.fetch_kapsarc_main_labor(),
        "emp_comp": sources.fetch_kapsarc_employees_compensation(),
        "emp_demog": sources.fetch_kapsarc_employees_demographics(),
        "public_emp": sources.fetch_kapsarc_public_sector_employment(),
        "cpi_mom": sources.fetch_kapsarc_cpi_mom(),
        "population": sources.fetch_kapsarc_population(),
    }
    # Derived live wage index from main_labor; first real authoritative wage series
    # in the project. Used by the fairness audit to compare model gap vs GASTAT gap.
    wage_index_df, wage_index_manifest = sources.build_wage_index()

    # ── 2. synthetic observations anchored to the public tables ───────────────
    spec = synthetic.default_spec(n_rows=n_rows, seed=seed)
    obs_raw = synthetic.generate(spec)

    # ── 2a. calibration to live GASTAT wage anchors ──────────────────────────
    # Pins the dataset mean, Saudi premium, and gender gap to the published
    # values when the live wage index is available. Preserves sector × level ×
    # region structure.
    from salary_model.data.calibrate import calibrate_to_live
    from salary_model.data.calibrate import write_report as write_calibration_report
    obs_calibrated, calibration_report = calibrate_to_live(obs_raw, wage_index_df)
    calibration_dir = settings.reports_dir / "calibration" / run_id
    write_calibration_report(calibration_report, calibration_dir)
    log.info(
        "dataset_calibration_done",
        steps=[s.name for s in calibration_report.steps],
        skipped=calibration_report.skipped,
    )

    # ── 2b. cleanup (§16 rules) ──────────────────────────────────────────────
    from salary_model.data.cleanup import clean_observations, write_report
    obs, cleanup_report = clean_observations(obs_calibrated, drop_outliers=False)
    cleanup_dir = settings.reports_dir / "cleanup" / run_id
    write_report(cleanup_report, cleanup_dir)
    log.info(
        "dataset_cleanup_done",
        rows_in=cleanup_report.rows_in,
        rows_out=cleanup_report.rows_out,
        rows_dropped=cleanup_report.rows_dropped,
    )

    # ── 3. write snapshot ─────────────────────────────────────────────────────
    snapshot_path = out_dir / f"observations_{run_id}.parquet"
    obs.to_parquet(snapshot_path, index=False, compression="zstd")

    anchors_path = out_dir / f"anchors_{run_id}.parquet"
    wage_df.to_parquet(anchors_path, index=False)
    macro_path = out_dir / f"macro_{run_id}.parquet"
    wb_df.to_parquet(macro_path, index=False)
    sama_path = out_dir / f"sama_{run_id}.parquet"
    sama_df.to_parquet(sama_path, index=False)
    macro_series_path = out_dir / f"macro_series_{run_id}.parquet"
    macro_df.to_parquet(macro_series_path, index=False)
    macro_series_latest = out_dir / "macro_series_latest.parquet"
    macro_df.to_parquet(macro_series_latest, index=False)
    # KAPSARC live datasets — only write when the fetch returned rows.
    kapsarc_paths: dict[str, str] = {}
    for key, (df_k, _m_k) in kapsarc_results.items():
        if len(df_k) > 0:
            p = out_dir / f"kapsarc_{key}_{run_id}.parquet"
            df_k.to_parquet(p, index=False)
            kapsarc_paths[f"kapsarc_{key}"] = str(p.relative_to(settings.repo_root))
    # Live wage index (always written when non-empty so the iteration runner finds it)
    wage_index_path: str | None = None
    if len(wage_index_df) > 0:
        wp = out_dir / f"wage_index_live_{run_id}.parquet"
        wage_index_df.to_parquet(wp, index=False)
        wage_index_latest = out_dir / "wage_index_live_latest.parquet"
        wage_index_df.to_parquet(wage_index_latest, index=False)
        wage_index_path = str(wp.relative_to(settings.repo_root))

    # ── 4. manifest ───────────────────────────────────────────────────────────
    source_manifests = {
        "gastat_wage_index": asdict(wage_manifest),
        "sama_indicators": asdict(sama_manifest),
        "worldbank_macro": asdict(wb_manifest),
        "ksa_monthly_macro": asdict(macro_manifest),
    }
    for key, (_df_k, m_k) in kapsarc_results.items():
        source_manifests[f"kapsarc_{key}"] = asdict(m_k)
    source_manifests["wage_index_live"] = asdict(wage_index_manifest)
    live_sources = [k for k, v in source_manifests.items() if not v.get("is_estimate", True)]
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "built_at": datetime.now(tz=UTC).isoformat(),
        "n_rows": len(obs),
        "seed": seed,
        "snapshot": str(snapshot_path.relative_to(settings.repo_root)),
        "anchors": str(anchors_path.relative_to(settings.repo_root)),
        "macro": str(macro_path.relative_to(settings.repo_root)),
        "sama": str(sama_path.relative_to(settings.repo_root)),
        "macro_series": str(macro_series_path.relative_to(settings.repo_root)),
        "kapsarc": kapsarc_paths,
        "wage_index_live": wage_index_path,
        "calibration_report": str(
            (calibration_dir / "calibration.md").relative_to(settings.repo_root)
        ),
        "calibration": calibration_report.to_dict(),
        "cleanup_report": str((cleanup_dir / "cleanup.md").relative_to(settings.repo_root)),
        "cleanup": cleanup_report.to_dict(),
        "snapshot_sha256": _hash_dataframe(obs),
        "sources": source_manifests,
        "live_sources": live_sources,
        "source_trust": {
            k: {"name": v.name, "url": v.url, "trust": v.trust, "last_seen": v.last_seen}
            for k, v in SOURCE_TRUST.items()
        },
    }
    manifest_path = out_dir / f"manifest_{run_id}.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )

    latest = out_dir / "manifest_latest.json"
    latest.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    log.info("dataset_build_done", path=str(snapshot_path), rows=len(obs))
    return snapshot_path


def load_latest_snapshot() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Load the most recent dataset snapshot and its manifest."""
    settings = get_settings()
    manifest_path = settings.processed_dir / "manifest_latest.json"
    if not manifest_path.exists():
        msg = (
            f"No dataset snapshot found at {manifest_path}. "
            "Run `make data` to build one."
        )
        raise FileNotFoundError(msg)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot_path = settings.repo_root / manifest["snapshot"]
    df = pd.read_parquet(snapshot_path)
    return df, manifest


def load_latest_macro_series() -> pd.DataFrame:
    """Load the macro time-series written alongside the latest snapshot."""
    settings = get_settings()
    path = settings.processed_dir / "macro_series_latest.parquet"
    if not path.exists():
        # Fallback: rebuild from bundled values without touching disk.
        from salary_model.data.sources.macro_series import fetch_macro_series
        df, _ = fetch_macro_series()
        return df
    return pd.read_parquet(path)


def load_latest_wage_index() -> pd.DataFrame:
    """Load the live GASTAT wage index written alongside the latest snapshot.

    Returns an empty DataFrame if no snapshot exists yet — callers handle that.
    """
    settings = get_settings()
    path = settings.processed_dir / "wage_index_live_latest.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)
