"""CLI entry point: `swet` runs the question flow by default."""

import csv
import io
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner

from swet_cli.data import (
    COMPETENCY_BY_SLUG,
    COMPETENCY_SLUGS,
    QUESTION_FORMATS,
    ROLES,
    get_frameworks_for_roles,
    get_languages_for_roles,
)
from swet_cli.db import (
    get_attempts_for_question,
    get_bookmarks,
    get_history,
    get_preferences,
    get_question,
    get_queued_question,
    get_recent_question_topics,
    get_state,
    get_stats,
    is_bookmarked,
    remove_bookmark,
    resolve_question_id,
    save_attempt,
    save_bookmark,
    save_preferences,
    save_question,
    update_format_performance,
    update_streak,
)
from swet_cli.display import (
    display_assessment_results,
    display_bookmarks,
    display_difficulty_adjustment,
    display_grade,
    display_history,
    display_level_progress,
    display_preferences,
    display_question,
    display_review,
    display_session_summary,
    display_stats,
    display_streak,
)
from swet_cli.generator import (
    adapt_difficulty,
    generate_questions,
    pick_competency,
    pick_format,
    should_generate_new,
    update_adaptive_level,
)
from swet_cli.grader import grade_mcq, grade_open_ended

app = typer.Typer(
    name="swet",
    help="Terminal-based software engineering assessment tool. Run with no args to get a question.",
    invoke_without_command=True,
)
config_app = typer.Typer(help="View and update preferences.")
app.add_typer(config_app, name="config")

console = Console()


# --- Default command: `swet` with no subcommand runs the question flow ---


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    question_format: Annotated[str | None, typer.Option("--format", "-f", help="Question format")] = None,
    difficulty: Annotated[int | None, typer.Option("--difficulty", "-d", help="Difficulty 1-5")] = None,
    competency: Annotated[str | None, typer.Option("--competency", "-c", help="Competency slug")] = None,
    timed: Annotated[bool, typer.Option("--timed", "-t", help="Track time to answer")] = False,
) -> None:
    """Run with no subcommand to get a random question."""
    if ctx.invoked_subcommand is not None:
        return
    _run_question_flow(question_format=question_format, difficulty=difficulty, competency=competency, timed=timed)


# --- Subcommands ---


@app.command()
def setup() -> None:
    """Interactive setup: configure your role, languages, and frameworks, then assess your level."""
    console.print("\n[bold blue]SWET CLI Setup[/bold blue]\n")

    # Roles — show human-readable names
    role_choices = [questionary.Choice(r.replace("_", " ").title(), value=r) for r in ROLES]
    roles = questionary.checkbox(
        "Select your roles (space to toggle, enter to confirm):",
        choices=role_choices,
    ).ask()
    if roles is None or len(roles) == 0:
        console.print("[red]At least one role is required.[/red]")
        raise typer.Abort()

    # Languages — filtered by selected roles
    role_languages = sorted(set(get_languages_for_roles(roles)))
    languages = questionary.checkbox(
        "Select your languages (space to toggle, enter to confirm):",
        choices=role_languages,
    ).ask()
    if languages is None:
        raise typer.Abort()

    # Frameworks — filtered by selected roles AND languages
    role_frameworks = sorted(set(get_frameworks_for_roles(roles, languages=languages)))
    frameworks = questionary.checkbox(
        "Select your frameworks/tools (space to toggle, enter to confirm):",
        choices=role_frameworks,
    ).ask()
    if frameworks is None:
        raise typer.Abort()

    # Question format preferences
    format_display = {
        "mcq": "Multiple Choice",
        "code_review": "Code Review",
        "debugging": "Debugging",
        "short_answer": "Short Answer",
        "design_prompt": "System Design",
    }
    format_choices = [questionary.Choice(format_display[f], value=f, checked=True) for f in QUESTION_FORMATS]
    preferred_formats = questionary.checkbox(
        "Select question types you prefer (all selected = no preference):",
        choices=format_choices,
    ).ask()
    if preferred_formats is None:
        raise typer.Abort()
    # If all selected or none selected, treat as no preference
    if len(preferred_formats) == len(QUESTION_FORMATS) or len(preferred_formats) == 0:
        preferred_formats = None

    # Question length preference
    length_choices = [
        questionary.Choice("Concise — brief, focused, straight to the point", value="concise"),
        questionary.Choice("Standard — balanced length with enough context", value="standard", checked=True),
        questionary.Choice("Detailed — rich context, background scenarios, thorough", value="detailed"),
    ]
    question_length = questionary.select(
        "Preferred question length:",
        choices=length_choices,
    ).ask()
    if question_length is None:
        raise typer.Abort()

    # Save preferences with default difficulty (will be overridden by assessment)
    save_preferences(
        roles=roles,
        languages=languages,
        frameworks=frameworks,
        difficulty=3,
        preferred_formats=preferred_formats,
        question_length=question_length,
    )
    console.print("\n[green]Preferences saved.[/green]")

    # Run the level assessment
    console.print("\n[bold blue]Now let's determine your level...[/bold blue]")
    console.print("[dim]You'll answer a few adaptive questions per competency.[/dim]\n")
    _run_assessment(roles=roles, languages=languages, frameworks=frameworks)


@config_app.command("show")
def config_show() -> None:
    """Show current preferences."""
    prefs = get_preferences()
    if prefs is None:
        console.print("[yellow]No preferences set. Run [bold]swet setup[/bold] first.[/yellow]")
        raise typer.Exit(1)
    display_preferences(prefs)


@config_app.command("set")
def config_set(
    roles: Annotated[str | None, typer.Option("--roles", help="Comma-separated roles")] = None,
    languages: Annotated[str | None, typer.Option(help="Comma-separated languages")] = None,
    frameworks: Annotated[str | None, typer.Option(help="Comma-separated frameworks")] = None,
    formats: Annotated[str | None, typer.Option("--formats", help="Comma-separated formats")] = None,
    length: Annotated[str | None, typer.Option("--length", help="Question length: concise, standard, detailed")] = None,
) -> None:
    """Update specific preferences at any time.

    Examples:
        swet config set --roles backend_engineer,ai_engineer
        swet config set --languages Python,Go,TypeScript
        swet config set --formats mcq,debugging,code_review
        swet config set --length concise
    """
    prefs = get_preferences()
    if prefs is None:
        console.print("[yellow]No preferences set. Run [bold]swet setup[/bold] first.[/yellow]")
        raise typer.Exit(1)

    if roles is not None:
        role_list = [r.strip() for r in roles.split(",") if r.strip()]
        for r in role_list:
            if r not in ROLES:
                valid = ", ".join(ROLES)
                console.print(f"[red]Invalid role '{r}'. Choose from: {valid}[/red]")
                raise typer.Exit(1)
        if not role_list:
            console.print("[red]At least one role is required.[/red]")
            raise typer.Exit(1)
        prefs["roles"] = role_list

    if languages is not None:
        lang_list = [lang.strip() for lang in languages.split(",") if lang.strip()]
        prefs["languages"] = lang_list

    if frameworks is not None:
        fw_list = [f.strip() for f in frameworks.split(",") if f.strip()]
        prefs["frameworks"] = fw_list

    if formats is not None:
        fmt_list = [f.strip() for f in formats.split(",") if f.strip()]
        for f in fmt_list:
            if f not in QUESTION_FORMATS:
                valid = ", ".join(QUESTION_FORMATS)
                console.print(f"[red]Invalid format '{f}'. Choose from: {valid}[/red]")
                raise typer.Exit(1)
        prefs["preferred_formats"] = fmt_list if fmt_list else None

    if length is not None:
        valid_lengths = ("concise", "standard", "detailed")
        if length not in valid_lengths:
            console.print(f"[red]Invalid length '{length}'. Choose from: {', '.join(valid_lengths)}[/red]")
            raise typer.Exit(1)
        prefs["question_length"] = length

    save_preferences(**prefs)
    console.print("[green]Preferences updated.[/green]")
    display_preferences(prefs)


@config_app.command("edit")
def config_edit() -> None:
    """Interactively edit preferences (same as setup but preserves existing choices)."""
    prefs = get_preferences()
    if prefs is None:
        console.print("[yellow]No preferences set. Running setup...[/yellow]")
        setup()
        return

    console.print("\n[bold blue]Edit Preferences[/bold blue]\n")
    console.print("[dim]Press enter to keep current values, or select new ones.[/dim]\n")

    # Roles
    current_roles = set(prefs.get("roles", []))
    role_choices = [
        questionary.Choice(
            r.replace("_", " ").title(),
            value=r,
            checked=r in current_roles,
        )
        for r in ROLES
    ]
    roles = questionary.checkbox(
        "Select your roles:",
        choices=role_choices,
    ).ask()
    if roles is None:
        raise typer.Abort()
    if not roles:
        console.print("[red]At least one role is required.[/red]")
        raise typer.Abort()

    # Languages — filtered by newly selected roles
    current_langs = set(prefs.get("languages", []))
    role_languages = sorted(set(get_languages_for_roles(roles)))
    lang_ui_choices = [questionary.Choice(lang, checked=lang in current_langs) for lang in role_languages]
    languages = questionary.checkbox(
        "Select your languages:",
        choices=lang_ui_choices,
    ).ask()
    if languages is None:
        raise typer.Abort()

    # Frameworks — filtered by newly selected roles AND languages
    current_fws = set(prefs.get("frameworks", []))
    role_frameworks = sorted(set(get_frameworks_for_roles(roles, languages=languages)))
    fw_ui_choices = [questionary.Choice(f, checked=f in current_fws) for f in role_frameworks]
    frameworks = questionary.checkbox(
        "Select your frameworks/tools:",
        choices=fw_ui_choices,
    ).ask()
    if frameworks is None:
        raise typer.Abort()

    # Question format preferences
    format_display = {
        "mcq": "Multiple Choice",
        "code_review": "Code Review",
        "debugging": "Debugging",
        "short_answer": "Short Answer",
        "design_prompt": "System Design",
    }
    current_formats = set(prefs.get("preferred_formats") or [])
    # If no preference was set, default to all checked
    all_checked = len(current_formats) == 0
    format_choices = [
        questionary.Choice(format_display[f], value=f, checked=all_checked or f in current_formats)
        for f in QUESTION_FORMATS
    ]
    preferred_formats = questionary.checkbox(
        "Select question types you prefer (all selected = no preference):",
        choices=format_choices,
    ).ask()
    if preferred_formats is None:
        raise typer.Abort()
    if len(preferred_formats) == len(QUESTION_FORMATS) or len(preferred_formats) == 0:
        preferred_formats = None

    # Question length preference
    current_length = prefs.get("question_length", "standard")
    length_choices = [
        questionary.Choice(
            "Concise — brief, focused, straight to the point",
            value="concise",
            checked=current_length == "concise",
        ),
        questionary.Choice(
            "Standard — balanced length with enough context",
            value="standard",
            checked=current_length == "standard",
        ),
        questionary.Choice(
            "Detailed — rich context, background scenarios, thorough",
            value="detailed",
            checked=current_length == "detailed",
        ),
    ]
    question_length = questionary.select(
        "Preferred question length:",
        choices=length_choices,
        default=current_length,
    ).ask()
    if question_length is None:
        raise typer.Abort()

    save_preferences(
        roles=roles,
        languages=languages,
        frameworks=frameworks,
        difficulty=prefs["difficulty"],
        preferred_formats=preferred_formats,
        question_length=question_length,
    )
    console.print("\n[green]Preferences updated.[/green]")
    display_preferences(
        {
            "roles": roles,
            "languages": languages,
            "frameworks": frameworks,
            "preferred_formats": preferred_formats,
            "question_length": question_length,
        }
    )


@app.command()
def history(
    last: Annotated[int, typer.Option("--last", "-n", help="Number of attempts to show")] = 20,
) -> None:
    """Show recent attempt history."""
    attempts = get_history(limit=last)
    display_history(attempts)


@app.command()
def stats() -> None:
    """Show aggregate stats by competency."""
    data = get_stats()
    streak_str = get_state("current_streak")
    longest_str = get_state("longest_streak")
    streak = int(streak_str) if streak_str else None
    longest = int(longest_str) if longest_str else None
    display_stats(data, streak=streak, longest_streak=longest)


@app.command()
def export(
    fmt: Annotated[str, typer.Option("--format", "-f", help="Export format: json or csv")] = "json",
    output: Annotated[str | None, typer.Option("--output", "-o", help="Output file path")] = None,
    last: Annotated[int, typer.Option("--last", "-n", help="Number of attempts to export")] = 100,
) -> None:
    """Export attempt history to JSON or CSV."""
    attempts = get_history(limit=last)
    if not attempts:
        console.print("[dim]No attempts to export.[/dim]")
        raise typer.Exit()

    if fmt == "json":
        content = json.dumps(attempts, indent=2, default=str)
    elif fmt == "csv":
        buf = io.StringIO()
        fieldnames = list(attempts[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(attempts)
        content = buf.getvalue()
    else:
        console.print(f"[red]Unknown format '{fmt}'. Use 'json' or 'csv'.[/red]")
        raise typer.Exit(1)

    if output:
        Path(output).write_text(content)
        console.print(f"[green]Exported {len(attempts)} attempts to {output}[/green]")
    else:
        console.print(content)


@app.command()
def review(
    question_id: Annotated[str, typer.Argument(help="Question ID (or prefix)")],
) -> None:
    """Review a past question and its attempts."""
    full_id = resolve_question_id(question_id)
    if full_id is None:
        console.print(f"[red]Question not found or ambiguous ID: {question_id}[/red]")
        raise typer.Exit(1)

    question = get_question(full_id)
    if question is None:
        console.print(f"[red]Question not found: {full_id}[/red]")
        raise typer.Exit(1)

    attempts = get_attempts_for_question(full_id)
    display_review(question, attempts)


@app.command(name="retry")
def retry_question(
    question_id: Annotated[str, typer.Argument(help="Question ID (or prefix)")],
    timed: Annotated[bool, typer.Option("--timed", "-t", help="Track time to answer")] = False,
) -> None:
    """Re-attempt a past question."""
    full_id = resolve_question_id(question_id)
    if full_id is None:
        console.print(f"[red]Question not found or ambiguous ID: {question_id}[/red]")
        raise typer.Exit(1)

    question = get_question(full_id)
    if question is None:
        console.print(f"[red]Question not found: {full_id}[/red]")
        raise typer.Exit(1)

    display_question(question)
    _answer_and_grade(question, timed=timed)


@app.command()
def bookmark(
    question_id: Annotated[str, typer.Argument(help="Question ID (or prefix)")],
) -> None:
    """Bookmark a question for later review."""
    full_id = resolve_question_id(question_id)
    if full_id is None:
        console.print(f"[red]Question not found or ambiguous ID: {question_id}[/red]")
        raise typer.Exit(1)

    if is_bookmarked(full_id):
        console.print("[dim]Already bookmarked.[/dim]")
        return

    save_bookmark(full_id)
    console.print("[green]Bookmarked.[/green]")


@app.command(name="bookmarks")
def list_bookmarks(
    last: Annotated[int, typer.Option("--last", "-n", help="Number to show")] = 50,
) -> None:
    """List bookmarked questions."""
    bmarks = get_bookmarks(limit=last)
    display_bookmarks(bmarks)


@app.command()
def unbookmark(
    question_id: Annotated[str, typer.Argument(help="Question ID (or prefix)")],
) -> None:
    """Remove a bookmark."""
    full_id = resolve_question_id(question_id)
    if full_id is None:
        console.print(f"[red]Question not found or ambiguous ID: {question_id}[/red]")
        raise typer.Exit(1)

    remove_bookmark(full_id)
    console.print("[green]Bookmark removed.[/green]")


@app.command()
def session(
    count: Annotated[int, typer.Option("--count", "-n", help="Number of questions")] = 5,
    timed: Annotated[bool, typer.Option("--timed", "-t", help="Track time to answer")] = False,
    question_format: Annotated[str | None, typer.Option("--format", "-f", help="Question format")] = None,
    difficulty: Annotated[int | None, typer.Option("--difficulty", "-d", help="Difficulty 1-5")] = None,
    competency: Annotated[str | None, typer.Option("--competency", "-c", help="Competency slug")] = None,
) -> None:
    """Run a session of multiple questions with a summary at the end."""
    prefs = _require_preferences()

    results: list[dict] = []
    try:
        for i in range(count):
            console.print(f"\n[bold blue]--- Question {i + 1}/{count} ---[/bold blue]")
            result = _run_single_question(
                prefs=prefs,
                question_format=question_format,
                difficulty=difficulty,
                competency=competency,
                timed=timed,
            )
            if result is not None:
                results.append(result)
    except KeyboardInterrupt:
        console.print("\n[dim]Session ended early.[/dim]")

    display_session_summary(results)


@app.command()
def competencies() -> None:
    """List all available competency areas."""
    from swet_cli.db import get_all_competency_levels

    levels = get_all_competency_levels()

    from rich.table import Table

    table = Table(title="Competency Areas", show_header=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Slug")
    table.add_column("Name")
    table.add_column("Level", justify="center")
    table.add_column("Attempts", justify="center")

    for i, slug in enumerate(COMPETENCY_SLUGS, 1):
        comp = COMPETENCY_BY_SLUG[slug]
        level_data = levels.get(slug)
        if level_data:
            level_str = f"L{level_data['estimated_level']}"
            attempts_str = str(level_data["total_attempts"])
        else:
            level_str = "[dim]-[/dim]"
            attempts_str = "[dim]0[/dim]"

        table.add_row(str(i), slug, comp.name, level_str, attempts_str)

    console.print()
    console.print(table)
    console.print()


@app.command()
def roles() -> None:
    """List all available roles."""
    from rich.table import Table

    table = Table(title="Available Roles", show_header=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Role ID")
    table.add_column("Display Name")

    for i, role in enumerate(ROLES, 1):
        table.add_row(str(i), role, role.replace("_", " ").title())

    console.print()
    console.print(table)
    console.print()


@app.command(name="test")
def level_test() -> None:
    """Run an adaptive level assessment to determine your competency levels.

    Uses Computerized Adaptive Testing (CAT) with Bayesian estimation to
    efficiently determine your level across your role-relevant competencies.
    Questions adapt in difficulty based on your responses.
    """
    prefs = _require_preferences()
    _run_assessment(
        roles=prefs["roles"],
        languages=prefs["languages"],
        frameworks=prefs["frameworks"],
    )


def _run_assessment(
    roles: list[str],
    languages: list[str],
    frameworks: list[str],
) -> None:
    """Run the adaptive level assessment flow.

    For each key competency:
    1. Generate a question at the current best difficulty estimate
    2. Grade the answer
    3. Update the Bayesian posterior
    4. Pick the next difficulty that maximizes information gain
    5. Repeat for QUESTIONS_PER_COMPETENCY questions

    At the end, stores the estimated levels and displays results.
    """
    from swet_cli.assessment import (
        QUESTIONS_PER_COMPETENCY,
        BayesianLevelEstimator,
        finalize_assessment,
        select_assessment_competencies,
    )

    comp_slugs = select_assessment_competencies(roles)
    if not comp_slugs:
        console.print("[red]No competencies found for your roles.[/red]")
        raise typer.Exit(1)

    total_questions = len(comp_slugs) * QUESTIONS_PER_COMPETENCY
    console.print(
        f"[bold blue]Level Assessment[/bold blue] — {len(comp_slugs)} competencies, {total_questions} questions\n"
    )

    results: dict[str, dict] = {}
    question_num = 0

    try:
        for slug in comp_slugs:
            comp = COMPETENCY_BY_SLUG[slug]
            estimator = BayesianLevelEstimator()

            console.print(f"\n[bold]{comp.name}[/bold]")

            for q_idx in range(QUESTIONS_PER_COMPETENCY):
                question_num += 1
                difficulty = estimator.best_next_difficulty()

                console.print(f"[dim]Question {question_num}/{total_questions} (L{difficulty})[/dim]")

                # Generate a single MCQ for speed during assessment
                spinner = Spinner("dots", text="Generating question...")
                with Live(spinner, console=console, transient=True):
                    question_models = generate_questions(
                        competency=comp,
                        difficulty=difficulty,
                        question_format="mcq",
                        roles=roles,
                        languages=languages,
                        frameworks=frameworks,
                        count=1,
                    )

                if not question_models:
                    console.print("[red]Failed to generate question. Skipping.[/red]")
                    continue

                # Save and serve the question
                q_data = {
                    "competency_slug": slug,
                    "format": "mcq",
                    "difficulty": difficulty,
                    **question_models[0].model_dump(),
                }
                q_id = save_question(q_data)
                question_data = get_question(q_id)
                if question_data is None:
                    continue

                display_question(question_data)

                # Collect answer
                answer = _collect_mcq_answer(question_data)
                if answer is None:
                    console.print("[dim]Skipped.[/dim]")
                    continue

                # Grade
                from swet_cli.grader import grade_mcq

                grade = grade_mcq(answer, question_data["correct_answer"])

                # Save attempt
                save_attempt(
                    question_id=q_id,
                    answer_text=answer,
                    score=grade.normalized_score,
                    max_score=grade.max_score,
                    total_score=grade.total_score,
                    grade_details=grade.model_dump(),
                    feedback=grade.overall_feedback,
                )

                # Show result inline
                result_text = "[green]Correct[/green]" if grade.normalized_score == 1.0 else "[red]Incorrect[/red]"
                console.print(f"  {result_text}")
                if question_data.get("explanation"):
                    console.print(f"  [dim]{question_data['explanation'][:120]}[/dim]")

                # Update Bayesian estimator
                estimator.update(difficulty, grade.normalized_score)

            # Finalize this competency
            level = finalize_assessment(slug, estimator)
            results[slug] = {
                "level": level,
                "confidence": estimator.confidence(),
                "distribution": estimator.distribution_str(),
            }

    except KeyboardInterrupt:
        console.print("\n[dim]Assessment interrupted. Partial results saved.[/dim]")

    if results:
        display_assessment_results(results)
    else:
        console.print("[dim]No competencies assessed.[/dim]")


# --- Core question flow ---


def _require_preferences() -> dict:
    """Load preferences or exit with a helpful message."""
    prefs = get_preferences()
    if prefs is None:
        console.print("[yellow]No preferences set. Run [bold]swet setup[/bold] first.[/yellow]")
        raise typer.Exit(1)
    return prefs


def _run_question_flow(
    question_format: str | None = None,
    difficulty: int | None = None,
    competency: str | None = None,
    timed: bool = False,
) -> None:
    """Generate a question, collect an answer, grade it, and display results."""
    prefs = _require_preferences()
    _run_single_question(
        prefs=prefs,
        question_format=question_format,
        difficulty=difficulty,
        competency=competency,
        timed=timed,
    )


def _run_single_question(
    prefs: dict,
    question_format: str | None = None,
    difficulty: int | None = None,
    competency: str | None = None,
    timed: bool = False,
) -> dict | None:
    """Run a single question cycle. Returns result dict or None if skipped.

    The algorithm:
    1. Pick competency (multi-signal weighted selection)
    2. Pick format (adaptive based on level and format performance)
    3. Adapt difficulty (per-competency ELO-like tracking)
    4. Smart DB check: serve from queue or generate new
    5. After grading: update adaptive levels and format performance
    """
    # 1. Pick competency
    base_diff = difficulty or prefs["difficulty"]
    if competency:
        comp = COMPETENCY_BY_SLUG.get(competency)
        if comp is None:
            console.print("[red]Unknown competency. Run [bold]swet competencies[/bold] for the full list.[/red]")
            raise typer.Exit(1)
    else:
        comp = pick_competency(prefs["roles"], base_diff)

    # 2. Pick format (adaptive, respects user preferences)
    q_format = question_format or pick_format(
        comp.slug,
        base_diff,
        preferred_formats=prefs.get("preferred_formats"),
    )
    if q_format not in QUESTION_FORMATS:
        console.print(f"[red]Invalid format. Choose from: {', '.join(QUESTION_FORMATS)}[/red]")
        raise typer.Exit(1)

    # 3. Adapt difficulty (per-competency)
    if base_diff < 1 or base_diff > 5:
        console.print("[red]Difficulty must be 1-5.[/red]")
        raise typer.Exit(1)

    diff = adapt_difficulty(comp.slug, base_diff)
    if diff != base_diff and difficulty is None:
        # Only show adjustment message if user didn't explicitly set difficulty
        display_difficulty_adjustment(base_diff, diff, comp.name)

    # 4. Smart DB vs LLM decision
    needs_generation = should_generate_new(comp.slug, q_format, diff)

    if not needs_generation:
        # Serve from DB queue
        question_data = get_queued_question(
            competency_slug=comp.slug,
            question_format=q_format,
            difficulty=diff,
        )
    else:
        question_data = None

    if question_data is None:
        # Generate new questions
        console.print(f"[dim]Generating questions for {comp.name} at L{diff}...[/dim]")

        # Gather recent topics for diversity
        recent_topics = get_recent_question_topics(n=20)

        spinner = Spinner("dots", text="Generating questions (this may take a moment)...")
        with Live(spinner, console=console, transient=True):
            question_models = generate_questions(
                competency=comp,
                difficulty=diff,
                question_format=q_format,
                roles=prefs["roles"],
                languages=prefs["languages"],
                frameworks=prefs["frameworks"],
                recent_topics=recent_topics,
                question_length=prefs.get("question_length", "standard"),
            )

        # Save all generated questions to DB
        for qm in question_models:
            q_data = {
                "competency_slug": comp.slug,
                "format": q_format,
                "difficulty": diff,
                **qm.model_dump(),
            }
            save_question(q_data)

        console.print(f"[dim]Queued {len(question_models)} new questions.[/dim]")

        # Grab the first queued one
        question_data = get_queued_question(
            competency_slug=comp.slug,
            question_format=q_format,
            difficulty=diff,
        )
        if question_data is None:
            console.print("[red]Failed to generate questions. Please try again.[/red]")
            raise typer.Exit(1)

    display_question(question_data)

    # 5. Collect answer, grade, save, and update adaptive levels
    return _answer_and_grade(question_data, timed=timed)


def _answer_and_grade(question_data: dict, timed: bool = False) -> dict | None:
    """Collect an answer, grade it, save, update adaptive levels, and display."""
    q_format = question_data["format"]
    question_id = question_data["id"]
    competency_slug = question_data["competency_slug"]

    # Collect answer (with optional timing)
    start_time = time.monotonic() if timed else None

    if q_format == "mcq":
        answer = _collect_mcq_answer(question_data)
    else:
        answer = _collect_text_answer(question_data)

    elapsed = (time.monotonic() - start_time) if start_time is not None else None

    if answer is None:
        console.print("[dim]Skipped.[/dim]")
        return None

    # Grade
    with Live(Spinner("dots", text="Grading..."), console=console, transient=True):
        if q_format == "mcq":
            grade = grade_mcq(answer, question_data["correct_answer"])
        else:
            grade = grade_open_ended(
                question_title=question_data["title"],
                question_body=question_data["body"],
                question_format=q_format,
                rubric=question_data["grading_rubric"],
                answer_text=answer,
                code_snippet=question_data.get("code_snippet"),
            )

    # Save attempt
    save_attempt(
        question_id=question_id,
        answer_text=answer,
        score=grade.normalized_score,
        max_score=grade.max_score,
        total_score=grade.total_score,
        grade_details=grade.model_dump(),
        feedback=grade.overall_feedback,
        time_seconds=elapsed,
    )

    # Get the user's level BEFORE updating (for progress display)
    from swet_cli.db import get_competency_level

    prev_level_data = get_competency_level(competency_slug)
    old_level = prev_level_data["estimated_level"] if prev_level_data else question_data["difficulty"]

    # Update adaptive level tracking (ELO + consecutive scores)
    new_level = update_adaptive_level(
        competency_slug=competency_slug,
        score=grade.normalized_score,
        difficulty=question_data["difficulty"],
    )

    # Update per-competency format performance
    update_format_performance(competency_slug, q_format, grade.normalized_score)

    # Update streak
    streak_count, is_new_day = update_streak()

    # Display results
    display_grade(grade, question_data, time_seconds=elapsed)
    display_streak(streak_count, is_new_day)
    if new_level != old_level:
        display_level_progress(competency_slug, old_level, new_level)

    return {"question": question_data, "grade": grade, "time_seconds": elapsed}


# --- Answer collection helpers ---


def _collect_mcq_answer(question: dict) -> str | None:
    """Collect MCQ answer via interactive selection."""
    options = question.get("options", {})
    if not options:
        return None

    choices = [questionary.Choice(f"{key}. {options[key]}", value=key) for key in sorted(options.keys())]
    return questionary.select("Your answer:", choices=choices).ask()


def _collect_text_answer(question: dict) -> str | None:
    """Collect a text answer via $EDITOR or multiline input."""
    header_lines = [
        f"# {question['title']}",
        f"# Format: {question['format']} | Competency: {question['competency_slug']}",
        "#",
        "# Write your answer below this line. Lines starting with # are ignored.",
        "# Save and close the editor to submit. Leave empty to skip.",
        "",
    ]
    initial_content = "\n".join(header_lines)

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))

    if editor:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(initial_content)
            f.flush()
            tmp_path = f.name

        try:
            subprocess.run([editor, tmp_path], check=True)
            with open(tmp_path) as f:
                content = f.read()
        finally:
            os.unlink(tmp_path)

        lines = [line for line in content.split("\n") if not line.startswith("#")]
        answer = "\n".join(lines).strip()
        return answer if answer else None
    else:
        console.print("[dim]Type your answer (press Esc then Enter to submit):[/dim]")
        answer = questionary.text("Your answer:", multiline=True).ask()
        return answer if answer and answer.strip() else None


if __name__ == "__main__":
    app()
