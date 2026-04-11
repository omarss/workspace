"""SWET CLI entry point.

Provides a standalone practice mode that works without PostgreSQL.
Settings must be patched BEFORE importing generator/grader modules.

Usage:
    swet              # practice (default command)
    swet setup        # configure profile and API key
    swet profile      # show current profile
    swet history      # show practice history
"""

import asyncio
from typing import Annotated

import typer
from rich.console import Console

# Load config and patch settings BEFORE any generator/grader imports.
# This is critical because generator.py:26 and grader.py:26 read
# settings at module level (GENERATION_MODEL, GRADING_MODEL).
from src.cli.config import load_config, patch_settings, save_config

_config = load_config()
patch_settings(_config)

from src.cli.data import COMPETENCIES, ONBOARDING_OPTIONS  # noqa: E402
from src.cli.display import display_profile  # noqa: E402
from src.cli.history import display_history  # noqa: E402
from src.cli.practice import FORMATS, run_practice  # noqa: E402

app = typer.Typer(
    name="swet",
    help="SWET - Software Engineering Test (CLI Practice Mode)",
    no_args_is_help=False,
    invoke_without_command=True,
)
console = Console()

# Valid competency slugs for CLI validation
COMPETENCY_SLUGS = [str(c["slug"]) for c in COMPETENCIES]


def _reload_config() -> None:
    """Reload config from disk and re-patch settings."""
    global _config
    _config = load_config()
    patch_settings(_config)


@app.callback()
def main(
    ctx: typer.Context,
    question_format: Annotated[
        str | None,
        typer.Option("--format", "-f", help=f"Question format: {', '.join(FORMATS)}"),
    ] = None,
    difficulty: Annotated[
        int | None,
        typer.Option("--difficulty", "-d", help="Difficulty level 1-5"),
    ] = None,
    competency: Annotated[
        str | None,
        typer.Option("--competency", "-c", help="Competency slug"),
    ] = None,
) -> None:
    """Practice software engineering questions from your terminal."""
    # If a subcommand is invoked, skip the default behavior
    if ctx.invoked_subcommand is not None:
        return

    _reload_config()

    if not _config.has_api_key():
        console.print(
            "[red]No API key found. Run 'swet setup' or set ANTHROPIC_API_KEY env var.[/red]"
        )
        raise typer.Exit(1)

    if not _config.has_profile():
        console.print("[red]No profile configured. Run 'swet setup' first.[/red]")
        raise typer.Exit(1)

    # Validate overrides
    if question_format and question_format not in FORMATS:
        console.print(f"[red]Invalid format '{question_format}'. Valid: {', '.join(FORMATS)}[/red]")
        raise typer.Exit(1)

    if difficulty and not (1 <= difficulty <= 5):
        console.print("[red]Difficulty must be between 1 and 5.[/red]")
        raise typer.Exit(1)

    if competency and competency not in COMPETENCY_SLUGS:
        console.print(
            f"[red]Invalid competency '{competency}'. Valid: {', '.join(COMPETENCY_SLUGS)}[/red]"
        )
        raise typer.Exit(1)

    asyncio.run(
        run_practice(
            config=_config,
            format_override=question_format,
            difficulty_override=difficulty,
            competency_override=competency,
        )
    )


@app.command()
def setup() -> None:
    """Interactive setup: configure your profile and API key."""
    options = ONBOARDING_OPTIONS

    console.print()
    console.print("[bold blue]SWET CLI Setup[/bold blue]")
    console.print("[dim]Configure your engineering profile for targeted questions.[/dim]")
    console.print()

    config = load_config()

    # API key
    current_key = config.get_api_key()
    if current_key:
        console.print(f"[green]API key: configured (ends in ...{current_key[-4:]})[/green]")
        change_key = typer.confirm("Change API key?", default=False)
    else:
        change_key = True

    if change_key:
        console.print("[dim]You can also set ANTHROPIC_API_KEY env var instead.[/dim]")
        key = typer.prompt("Anthropic API key", default="", hide_input=True)
        if key:
            config.anthropic_api_key = key

    # Role selection
    console.print()
    console.print("[bold]Available roles:[/bold]")
    for i, role in enumerate(options["roles"], 1):
        console.print(f"  {i}. {role}")
    role_idx = typer.prompt(
        "Select role (number)",
        type=int,
        default=options["roles"].index(config.profile.primary_role) + 1
        if config.profile.primary_role in options["roles"]
        else 1,
    )
    config.profile.primary_role = options["roles"][
        max(0, min(role_idx - 1, len(options["roles"]) - 1))
    ]

    # Languages (multi-select)
    console.print()
    console.print("[bold]Available languages:[/bold]")
    for i, lang in enumerate(options["languages"], 1):
        marker = "*" if lang in config.profile.languages else " "
        console.print(f"  {i}. [{marker}] {lang}")
    lang_input = typer.prompt(
        "Select languages (comma-separated numbers)",
        default=",".join(
            str(options["languages"].index(lang) + 1)
            for lang in config.profile.languages
            if lang in options["languages"]
        )
        or "1",
    )
    lang_indices = [int(x.strip()) - 1 for x in lang_input.split(",") if x.strip().isdigit()]
    config.profile.languages = [
        options["languages"][i] for i in lang_indices if 0 <= i < len(options["languages"])
    ]

    # Frameworks (multi-select)
    console.print()
    console.print("[bold]Available frameworks:[/bold]")
    for i, fw in enumerate(options["frameworks"], 1):
        marker = "*" if fw in config.profile.frameworks else " "
        console.print(f"  {i}. [{marker}] {fw}")
    fw_input = typer.prompt(
        "Select frameworks (comma-separated numbers, or 'none')",
        default=",".join(
            str(options["frameworks"].index(f) + 1)
            for f in config.profile.frameworks
            if f in options["frameworks"]
        )
        or "none",
    )
    if fw_input.strip().lower() != "none":
        fw_indices = [int(x.strip()) - 1 for x in fw_input.split(",") if x.strip().isdigit()]
        config.profile.frameworks = [
            options["frameworks"][i] for i in fw_indices if 0 <= i < len(options["frameworks"])
        ]
    else:
        config.profile.frameworks = []

    # Experience
    console.print()
    config.profile.experience_years = typer.prompt(
        "Years of experience",
        type=int,
        default=config.profile.experience_years or 3,
    )

    # Save
    save_config(config)
    console.print()
    console.print("[bold green]Profile saved![/bold green]")
    display_profile(config)


@app.command()
def profile(
    edit: Annotated[bool, typer.Option("--edit", "-e", help="Edit profile")] = False,
) -> None:
    """Show or edit your current profile."""
    if edit:
        setup()
        return

    _reload_config()
    if not _config.has_profile():
        console.print("[yellow]No profile configured. Run 'swet setup' first.[/yellow]")
        raise typer.Exit(1)

    display_profile(_config)


@app.command()
def history() -> None:
    """Show your practice history."""
    console.print()
    display_history()
    console.print()


if __name__ == "__main__":
    app()
