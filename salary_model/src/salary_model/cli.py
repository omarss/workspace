"""Typer CLI: the only supported way to invoke this project, alongside the Makefile."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from salary_model.config import configure_logging, get_logger, get_settings

app = typer.Typer(
    add_completion=False,
    help="Saudi salary intelligence model CLI.",
    no_args_is_help=True,
)
data_app = typer.Typer(help="Build and inspect datasets.", no_args_is_help=True)
fairness_app = typer.Typer(help="Fairness operations.", no_args_is_help=True)
drift_app = typer.Typer(help="Drift detection.", no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(fairness_app, name="fairness")
app.add_typer(drift_app, name="drift")


def _ts() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


@data_app.command("build")
def data_build(
    seed: int = typer.Option(17, help="RNG seed for synthetic generator."),
    run_id: str = typer.Option(_ts(), help="Identifier for this dataset snapshot."),
    n_rows: int = typer.Option(
        25_000, help="Number of synthetic observations to generate.", min=1_000,
    ),
) -> None:
    """Fetch open anchors and build a versioned dataset snapshot."""
    configure_logging()
    log = get_logger("salary_model.cli")
    log.info("data_build_start", seed=seed, run_id=run_id, n_rows=n_rows)
    from salary_model.data.build import build_dataset

    path = build_dataset(n_rows=n_rows, seed=seed, run_id=run_id)
    typer.echo(f"snapshot: {path}")


_CLEAN_INPUT_ARG = typer.Argument(
    ..., help="Path to a raw observations Parquet to clean.",
)
_CLEAN_OUTPUT_OPT = typer.Option(None, help="Where to write the cleaned Parquet.")
_CLEAN_DROP_OUTLIERS_OPT = typer.Option(
    False, help="Drop instead of flag intra-segment outliers.",
)


@data_app.command("clean")
def data_clean(
    input_path: Path = _CLEAN_INPUT_ARG,
    output_path: Path | None = _CLEAN_OUTPUT_OPT,
    drop_outliers: bool = _CLEAN_DROP_OUTLIERS_OPT,
) -> None:
    """Run the §16 cleanup pipeline on a raw observations Parquet."""
    configure_logging()
    settings = get_settings()
    import pandas as pd  # local

    from salary_model.data.cleanup import clean_observations, write_report

    if not input_path.exists():
        typer.echo(f"input not found: {input_path}", err=True)
        raise typer.Exit(code=1)
    raw = pd.read_parquet(input_path)
    cleaned, report = clean_observations(raw, drop_outliers=drop_outliers)
    out = output_path or input_path.with_name(f"{input_path.stem}_clean.parquet")
    cleaned.to_parquet(out, index=False, compression="zstd")
    md_dir = settings.reports_dir / "cleanup" / _ts()
    md_path, _ = write_report(report, md_dir)
    typer.echo(
        f"rows in {report.rows_in} -> out {report.rows_out} "
        f"(dropped {report.rows_dropped})\nreport: {md_path}\ncleaned: {out}"
    )


@data_app.command("fetch-anchors")
def data_fetch_anchors() -> None:
    """Refresh the public anchor tables only (no synthesis)."""
    configure_logging()
    from salary_model.data.sources import (
        fetch_gastat_wage_index,
        fetch_kapsarc_cpi_mom,
        fetch_kapsarc_employees_compensation,
        fetch_kapsarc_employees_demographics,
        fetch_kapsarc_main_labor,
        fetch_kapsarc_population,
        fetch_kapsarc_public_sector_employment,
        fetch_sama_indicators,
        fetch_worldbank_macro,
    )

    fetchers = (
        fetch_gastat_wage_index,
        fetch_sama_indicators,
        fetch_worldbank_macro,
        fetch_kapsarc_main_labor,
        fetch_kapsarc_employees_compensation,
        fetch_kapsarc_employees_demographics,
        fetch_kapsarc_public_sector_employment,
        fetch_kapsarc_cpi_mom,
        fetch_kapsarc_population,
    )
    for fn in fetchers:
        _, m = fn()
        typer.echo(
            f"{m.source}: ok={m.ok} live={not m.is_estimate} rows={m.rows} "
            f"fallback={m.fallback}"
        )


@app.command()
def train(
    seed: int = typer.Option(17),
    run_id: str = typer.Option(_ts()),
    optuna_trials: int = typer.Option(12),
) -> None:
    """Train the full ladder once (alias for ``iterate`` for convenience)."""
    configure_logging()
    from salary_model.training.iterate import run_iteration

    run_iteration(run_id=run_id, seed=seed, optuna_trials=optuna_trials)


@app.command()
def iterate(
    seed: int = typer.Option(17),
    run_id: str = typer.Option(_ts()),
    optuna_trials: int = typer.Option(12),
) -> None:
    """Run the full iteration ladder and write reports/runs/<RUN_ID>/."""
    configure_logging()
    log = get_logger("salary_model.cli")
    log.info("iterate_start", run_id=run_id, seed=seed)
    from salary_model.training.iterate import run_iteration

    report = run_iteration(run_id=run_id, seed=seed, optuna_trials=optuna_trials)
    typer.echo(f"wrote reports/runs/{run_id}/summary.md ({len(report.steps)} steps)")


@app.command()
def evaluate(run_id: str | None = typer.Option(None)) -> None:
    """Print the summary of the most recent (or given) run."""
    settings = get_settings()
    runs_dir = settings.reports_dir / "runs"
    if run_id is None:
        runs = sorted(p.name for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.exists() else []
        if not runs:
            typer.echo("no runs found; run `make iterate` first", err=True)
            raise typer.Exit(code=1)
        run_id = runs[-1]
    summary = runs_dir / run_id / "summary.md"
    if not summary.exists():
        typer.echo(f"no summary at {summary}", err=True)
        raise typer.Exit(code=1)
    typer.echo(summary.read_text(encoding="utf-8"))


@fairness_app.command("audit")
def fairness_audit(run_id: str | None = typer.Option(None)) -> None:
    """Print the fairness audit of the most recent (or given) run."""
    settings = get_settings()
    runs_dir = settings.reports_dir / "runs"
    if run_id is None:
        runs = sorted(p.name for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.exists() else []
        if not runs:
            typer.echo("no runs found", err=True)
            raise typer.Exit(code=1)
        run_id = runs[-1]
    p = runs_dir / run_id / "fairness.md"
    if not p.exists():
        typer.echo(f"no fairness report at {p}", err=True)
        raise typer.Exit(code=1)
    typer.echo(p.read_text(encoding="utf-8"))


_DRIFT_PATH_ARG = typer.Argument(
    ..., help="Path to a current observations Parquet (built like the training snapshot).",
)


@drift_app.command("check")
def drift_check(
    current_snapshot: Path = _DRIFT_PATH_ARG,
    run_id: str = typer.Option(_ts(), help="Identifier for this drift run."),
) -> None:
    """Compare a current snapshot against the latest training snapshot via PSI."""
    configure_logging()
    log = get_logger("salary_model.cli")
    settings = get_settings()
    from salary_model.data.build import load_latest_snapshot
    from salary_model.features.build import build_feature_frame
    from salary_model.monitoring.drift import compute_drift, write_report

    if not current_snapshot.exists():
        typer.echo(f"current snapshot not found: {current_snapshot}", err=True)
        raise typer.Exit(code=1)

    import pandas as pd  # local
    ref_obs, _ = load_latest_snapshot()
    curr_obs = pd.read_parquet(current_snapshot)
    ref_feats = build_feature_frame(ref_obs).X
    curr_feats = build_feature_frame(curr_obs).X

    report = compute_drift(ref_feats, curr_feats)
    out_dir = settings.reports_dir / "drift" / run_id
    md_path, _json_path = write_report(report, out_dir)
    log.info("drift_done", max_psi=report.max_psi, alerts=len(report.alerts), md=str(md_path))
    typer.echo(f"wrote {md_path}\nmax_psi={report.max_psi:.4f}  alerts={len(report.alerts)}")


if __name__ == "__main__":  # pragma: no cover
    app()
