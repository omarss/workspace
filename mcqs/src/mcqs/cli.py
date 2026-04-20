"""mcqs — CLI entry point."""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
console = Console()


@app.command("serve")
def serve() -> None:
    """Run the FastAPI /v1/mcq service."""
    from .api.main import run

    run()


@app.command("ingest")
def ingest(
    subject: str | None = typer.Option(
        None, "--subject", "-s", help="Only ingest this subject slug (default: all)."
    ),
) -> None:
    """Walk docs-bundle → subjects / source_docs / doc_chunks."""
    from . import ingest as ingest_mod

    ingest_mod.run(subject=subject)


@app.command("plan-round")
def plan_round(
    target: int = typer.Option(
        None, "--target", "-n", help="Target questions per (subject, type). Defaults to config."
    ),
    notes: str = typer.Option("", "--notes", help="Free-text notes attached to the round."),
) -> None:
    """Open a new round and queue pending generation jobs."""
    from . import generate as generate_mod

    generate_mod.plan_round(target=target, notes=notes)


@app.command("generate")
def generate(
    subject: str | None = typer.Option(None, "--subject", "-s"),
    qtype: str | None = typer.Option(
        None, "--type", "-t", help="knowledge | analytical | problem_solving"
    ),
    limit_jobs: int | None = typer.Option(
        None, "--limit-jobs", help="Stop after N jobs completed (for smoke tests)."
    ),
) -> None:
    """Run the generator worker (resumable)."""
    from . import generate as generate_mod

    generate_mod.run_worker(subject=subject, qtype=qtype, limit_jobs=limit_jobs)


@app.command("status")
def status() -> None:
    """Show round/subject/type progress."""
    from . import generate as generate_mod

    generate_mod.print_status()


if __name__ == "__main__":
    app()
