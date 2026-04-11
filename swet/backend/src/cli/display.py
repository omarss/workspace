"""Terminal rendering for CLI practice mode.

Uses rich (bundled with typer) for syntax highlighting, panels, and tables.
"""

import os
import subprocess
import tempfile

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from src.questions.schemas import GeneratedQuestion

console = Console()


def display_question(question: GeneratedQuestion) -> None:
    """Render a question to the terminal based on its format."""
    # Header with competency context
    fmt_label = question.format.replace("_", " ").title()
    difficulty_label = (
        f"L{question.metadata.estimated_time_minutes}min" if question.metadata else ""
    )
    header = f"[bold cyan]{fmt_label}[/bold cyan]"
    if difficulty_label:
        header += f"  [dim]{difficulty_label} estimated[/dim]"

    console.print()
    console.print(Panel(f"[bold]{question.title}[/bold]", title=header, border_style="blue"))
    console.print()
    console.print(Markdown(question.body))

    # Code snippet for code-based formats
    if question.code_snippet and question.language:
        console.print()
        console.print(
            Syntax(
                question.code_snippet,
                question.language,
                theme="monokai",
                line_numbers=True,
                padding=1,
            )
        )

    # MCQ options
    if question.format == "mcq" and question.options:
        console.print()
        for key in sorted(question.options.keys()):
            console.print(f"  [bold yellow]{key})[/bold yellow] {question.options[key]}")

    console.print()


def collect_answer(question: GeneratedQuestion) -> str:
    """Collect the user's answer based on question format.

    MCQ: single letter A-D.
    Others: opens $EDITOR for long-form input, falls back to multi-line stdin.
    """
    if question.format == "mcq":
        return _collect_mcq_answer()
    return _collect_long_answer()


def _collect_mcq_answer() -> str:
    """Prompt for a single A/B/C/D selection."""
    while True:
        answer = console.input("[bold green]Your answer (A/B/C/D): [/bold green]").strip().upper()
        if answer in ("A", "B", "C", "D"):
            return answer
        console.print("[red]Please enter A, B, C, or D.[/red]")


def _collect_long_answer() -> str:
    """Collect a long-form answer via $EDITOR or multi-line stdin."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")

    if editor:
        return _collect_via_editor(editor)
    return _collect_via_stdin()


def _collect_via_editor(editor: str) -> str:
    """Open the user's preferred editor with a temp file, return contents."""
    console.print("[dim]Opening your editor... Save and close when done.[/dim]")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Write your answer below this line, then save and close.\n\n")
        tmppath = f.name

    try:
        subprocess.run([editor, tmppath], check=True)
        with open(tmppath, encoding="utf-8") as f:
            lines = f.readlines()

        # Strip the instruction comment
        content_lines = [line for line in lines if not line.startswith("# Write your answer")]
        return "".join(content_lines).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        console.print("[yellow]Editor failed, falling back to inline input.[/yellow]")
        return _collect_via_stdin()
    finally:
        os.unlink(tmppath)


def _collect_via_stdin() -> str:
    """Collect multi-line input terminated by an empty line."""
    console.print("[dim]Type your answer. Press Enter twice (empty line) to submit.[/dim]")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "" and lines:
            break
        lines.append(line)
    return "\n".join(lines).strip()


def display_mcq_result(selected: str, correct: str, explanation: str) -> None:
    """Show MCQ grading result with color coding."""
    is_correct = selected.upper() == correct.upper()

    console.print()
    if is_correct:
        console.print(
            Panel(
                f"[bold green]Correct! The answer is {correct}.[/bold green]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]Incorrect. You chose {selected}, the correct answer is {correct}.[/bold red]",
                border_style="red",
            )
        )

    console.print()
    console.print("[bold]Explanation:[/bold]")
    console.print(Markdown(explanation))
    console.print()


def display_grade_result(
    grade_result: object,
    explanation: str,
) -> None:
    """Show AI grading result with per-criterion scores.

    Args:
        grade_result: A GradeResult instance from src.scoring.grader.
        explanation: The question's built-in explanation text.
    """
    # Import here to avoid circular/early import issues with settings patching
    from src.scoring.grader import GradeResult

    if not isinstance(grade_result, GradeResult):
        console.print("[red]Unexpected grade result format.[/red]")
        return

    console.print()

    # Score summary
    pct = grade_result.normalized_score * 100
    color = "green" if pct >= 70 else "yellow" if pct >= 40 else "red"
    console.print(
        Panel(
            f"[bold {color}]Score: {grade_result.total_score}/{grade_result.max_score} "
            f"({pct:.0f}%)[/bold {color}]",
            border_style=color,
        )
    )

    # Per-criterion breakdown table
    table = Table(title="Criteria Breakdown", show_lines=True)
    table.add_column("Criterion", style="bold")
    table.add_column("Score", justify="center")
    table.add_column("Feedback")

    for cs in grade_result.criteria_scores:
        score_color = (
            "green"
            if cs.score >= cs.max_points * 0.7
            else "yellow"
            if cs.score >= cs.max_points * 0.4
            else "red"
        )
        table.add_row(
            cs.name,
            Text(f"{cs.score}/{cs.max_points}", style=score_color),
            cs.feedback,
        )

    console.print(table)

    # Overall feedback
    console.print()
    console.print("[bold]Grader feedback:[/bold]")
    console.print(grade_result.overall_feedback)

    # Question explanation
    console.print()
    console.print("[bold]Explanation:[/bold]")
    console.print(Markdown(explanation))
    console.print()


def display_profile(config: object) -> None:
    """Pretty-print the user's current profile."""
    from src.cli.config import CLIConfig

    if not isinstance(config, CLIConfig):
        return

    profile = config.profile
    console.print()
    console.print(Panel("[bold]Your SWET Profile[/bold]", border_style="blue"))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Role", profile.primary_role or "[dim]not set[/dim]")
    table.add_row(
        "Languages", ", ".join(profile.languages) if profile.languages else "[dim]not set[/dim]"
    )
    table.add_row(
        "Frameworks", ", ".join(profile.frameworks) if profile.frameworks else "[dim]not set[/dim]"
    )
    table.add_row(
        "Experience",
        f"{profile.experience_years} years" if profile.experience_years else "[dim]not set[/dim]",
    )
    table.add_row(
        "Interests", ", ".join(profile.interests) if profile.interests else "[dim]not set[/dim]"
    )
    table.add_row(
        "API Key", "[green]configured[/green]" if config.has_api_key() else "[red]not set[/red]"
    )
    table.add_row("Generation Model", config.llm_generation_model)
    table.add_row("Grading Model", config.llm_grading_model)

    console.print(table)
    console.print()
