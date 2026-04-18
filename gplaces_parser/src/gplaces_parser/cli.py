"""gplaces — CLI entry point."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import pipeline, repo
from .db import connection

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()


@app.command("serve")
def serve() -> None:
    """Run the FastAPI /v1/nearby service (see FEEDBACK.md)."""
    from .api.main import run

    run()


@app.command("scrape-places")
def scrape_places() -> None:
    """Fetch places for every (category × Riyadh tile) not yet scraped."""
    pipeline.run_places()


@app.command("scrape-reviews")
def scrape_reviews() -> None:
    """Fetch reviews for every place that hasn't been processed yet."""
    pipeline.run_reviews()


@app.command("status")
def status() -> None:
    """Show totals and scrape_jobs breakdown."""
    with connection() as conn:
        tallies = repo.counts(conn)
        rows = repo.status_summary(conn)

    t1 = Table(title="totals", show_header=True, header_style="bold")
    t1.add_column("table")
    t1.add_column("rows", justify="right")
    for k, v in tallies.items():
        t1.add_row(k, f"{v:,}")
    console.print(t1)

    t2 = Table(title="scrape_jobs", show_header=True, header_style="bold")
    t2.add_column("kind")
    t2.add_column("status")
    t2.add_column("jobs", justify="right")
    t2.add_column("results", justify="right")
    for r in rows:
        t2.add_row(r["kind"], r["status"], f"{r['n']:,}", f"{r['results']:,}")
    console.print(t2)


@app.command("seed-places-jobs")
def seed_places_jobs() -> None:
    """Seed (without running) the places job queue."""
    pipeline.seed_places_jobs()


@app.command("seed-reviews-jobs")
def seed_reviews_jobs() -> None:
    """Seed (without running) the reviews job queue."""
    pipeline.seed_reviews_jobs()


if __name__ == "__main__":
    app()
