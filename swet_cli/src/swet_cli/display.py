"""Rich-based terminal rendering for questions, grades, and history."""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from swet_cli.data import COMPETENCY_BY_SLUG
from swet_cli.models import GradeResult
from swet_cli.prompts import DIFFICULTY_LABELS

console = Console()

# Difficulty level colors
DIFFICULTY_COLORS = {1: "green", 2: "cyan", 3: "yellow", 4: "red", 5: "magenta"}


def _competency_display_name(slug: str) -> str:
    """Get human-readable name for a competency slug."""
    comp = COMPETENCY_BY_SLUG.get(slug)
    if comp:
        return comp.name
    return slug.replace("_", " ").title()


def display_question(question: dict) -> None:
    """Render a question with Rich panels and syntax highlighting."""
    competency_name = _competency_display_name(question["competency_slug"])
    difficulty = question["difficulty"]
    diff_label = DIFFICULTY_LABELS.get(difficulty, f"L{difficulty}")
    diff_color = DIFFICULTY_COLORS.get(difficulty, "white")
    fmt = question["format"].replace("_", " ").title()

    # Estimated time from metadata
    est_time = ""
    if question.get("metadata") and question["metadata"].get("estimated_time_minutes"):
        est_time = f"  ~{question['metadata']['estimated_time_minutes']} min"

    # Header with competency, difficulty, format
    header = f"[bold]{competency_name}[/bold]  [{diff_color}]{diff_label}[/{diff_color}]  [dim]{fmt}{est_time}[/dim]"

    console.print()
    console.print(Panel(header, title="[bold blue]SWET Question[/bold blue]", border_style="blue"))

    # Question title
    console.print(f"\n[bold]{question['title']}[/bold]\n")

    # Question body as markdown
    console.print(Markdown(question["body"]))

    # Code snippet with syntax highlighting
    if question.get("code_snippet"):
        lang = question.get("language", "text") or "text"
        console.print()
        console.print(
            Panel(
                Syntax(question["code_snippet"], lang, theme="monokai", line_numbers=True),
                title=f"[bold]{lang}[/bold]",
                border_style="dim",
            )
        )

    # MCQ options
    if question.get("options"):
        console.print()
        for key in sorted(question["options"].keys()):
            console.print(f"  [bold]{key}.[/bold] {question['options'][key]}")

    console.print()


def display_grade(grade: GradeResult, question: dict, time_seconds: float | None = None) -> None:
    """Render the grading result with score breakdown."""
    is_mcq = question["format"] == "mcq"

    # Score header
    if is_mcq:
        emoji = "[green]Correct[/green]" if grade.normalized_score == 1.0 else "[red]Incorrect[/red]"
        console.print(Panel(emoji, title="[bold]Result[/bold]", border_style="yellow"))
    else:
        pct = grade.normalized_score * 100
        color = "green" if pct >= 70 else "yellow" if pct >= 40 else "red"
        score_text = f"[{color}]{grade.total_score}/{grade.max_score} ({pct:.0f}%)[/{color}]"
        console.print(Panel(score_text, title="[bold]Score[/bold]", border_style="yellow"))

        # Per-criterion breakdown table
        table = Table(title="Criterion Breakdown", show_header=True)
        table.add_column("Criterion", style="bold")
        table.add_column("Score", justify="center")
        table.add_column("Feedback")

        for cs in grade.criteria_scores:
            ratio = cs.score / cs.max_points if cs.max_points else 0
            score_color = "green" if ratio >= 0.7 else "yellow" if ratio >= 0.4 else "red"
            table.add_row(
                cs.name,
                f"[{score_color}]{cs.score}/{cs.max_points}[/{score_color}]",
                cs.feedback,
            )
        console.print(table)

    # Time taken (if timed mode)
    if time_seconds is not None:
        display_time_taken(time_seconds, question)

    # Overall feedback
    console.print(Panel(grade.overall_feedback, title="[bold]Feedback[/bold]", border_style="cyan"))

    # Show explanation if available
    if question.get("explanation"):
        console.print(
            Panel(
                Markdown(question["explanation"]),
                title="[bold]Explanation[/bold]",
                border_style="green",
            )
        )

    console.print()


def display_time_taken(elapsed_seconds: float, question: dict) -> None:
    """Display how long the user took to answer."""
    minutes = int(elapsed_seconds // 60)
    seconds = int(elapsed_seconds % 60)
    time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    # Compare against estimated time if available
    estimated = None
    if question.get("metadata") and question["metadata"].get("estimated_time_minutes"):
        estimated = question["metadata"]["estimated_time_minutes"]

    if estimated:
        estimated_seconds = estimated * 60
        if elapsed_seconds <= estimated_seconds:
            color = "green"
            note = f"within estimate ({estimated}m)"
        else:
            color = "yellow"
            note = f"over estimate ({estimated}m)"
        text = f"[{color}]{time_str}[/{color}] — {note}"
    else:
        text = f"{time_str}"

    console.print(Panel(text, title="[bold]Time[/bold]", border_style="dim"))


def display_streak(count: int, is_new_day: bool) -> None:
    """Display the current streak count."""
    if is_new_day:
        if count == 1:
            console.print(Panel("[bold green]Streak started! Day 1[/bold green]", border_style="green"))
        else:
            console.print(Panel(f"[bold green]Day {count} streak![/bold green]", border_style="green"))
    else:
        console.print(f"[dim]Current streak: {count} day{'s' if count != 1 else ''}[/dim]")


def display_difficulty_adjustment(original: int, adjusted: int, competency_name: str) -> None:
    """Show a note when difficulty was auto-adjusted."""
    direction = "up" if adjusted > original else "down"
    color = "yellow" if adjusted > original else "cyan"
    console.print(
        f"[{color}]Difficulty adapted {direction} to L{adjusted} "
        f"for {competency_name} based on your performance.[/{color}]"
    )


def display_level_progress(competency_slug: str, old_level: int, new_level: int) -> None:
    """Show a congratulatory message when the user levels up/down in a competency."""
    comp_name = _competency_display_name(competency_slug)
    if new_level > old_level:
        level_label = DIFFICULTY_LABELS.get(new_level, f"L{new_level}")
        console.print(
            Panel(
                f"[bold green]Level up! {comp_name}: L{old_level} -> {level_label}[/bold green]\n"
                f"You're now being assessed at a higher level for this competency.",
                title="[bold]Level Progress[/bold]",
                border_style="green",
            )
        )
    else:
        level_label = DIFFICULTY_LABELS.get(new_level, f"L{new_level}")
        console.print(
            f"[dim]{comp_name} adjusted to {level_label} — building stronger foundations before advancing.[/dim]"
        )


def display_preferences(prefs: dict) -> None:
    """Display current user preferences."""
    table = Table(title="Your Preferences", show_header=False)
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    format_display = {
        "mcq": "Multiple Choice",
        "code_review": "Code Review",
        "debugging": "Debugging",
        "short_answer": "Short Answer",
        "design_prompt": "System Design",
    }

    roles = prefs.get("roles", [prefs["role"]] if "role" in prefs else [])
    role_names = [r.replace("_", " ").title() for r in roles]
    table.add_row("Roles", ", ".join(role_names) if role_names else "none")
    table.add_row("Languages", ", ".join(prefs["languages"]) if prefs["languages"] else "none")
    table.add_row("Frameworks", ", ".join(prefs["frameworks"]) if prefs["frameworks"] else "none")

    pref_formats = prefs.get("preferred_formats")
    if pref_formats:
        fmt_names = [format_display.get(f, f) for f in pref_formats]
        table.add_row("Question Types", ", ".join(fmt_names))
    else:
        table.add_row("Question Types", "all (no preference)")

    question_length = prefs.get("question_length", "standard")
    length_display = {"concise": "Concise", "standard": "Standard", "detailed": "Detailed"}
    table.add_row("Question Length", length_display.get(question_length, question_length.title()))

    console.print()
    console.print(table)
    console.print()


def display_assessment_results(results: dict[str, dict]) -> None:
    """Display level assessment results in a formatted table.

    Args:
        results: Dict of competency_slug -> {"level": int, "confidence": float,
                 "distribution": str}
    """
    console.print()
    console.print(
        Panel(
            "[bold]Level Assessment Complete[/bold]\n"
            "Your competency levels have been determined using adaptive testing.",
            border_style="blue",
        )
    )

    table = Table(title="Your Competency Levels", show_header=True)
    table.add_column("Competency")
    table.add_column("Level", justify="center")
    table.add_column("Confidence", justify="center")
    table.add_column("Distribution", style="dim")

    for slug, data in results.items():
        comp_name = _competency_display_name(slug)
        level = data["level"]
        confidence = data["confidence"]
        distribution = data.get("distribution", "")

        level_label = DIFFICULTY_LABELS.get(level, f"L{level}")
        diff_color = DIFFICULTY_COLORS.get(level, "white")
        conf_color = "green" if confidence >= 0.5 else "yellow" if confidence >= 0.3 else "dim"

        table.add_row(
            comp_name,
            f"[{diff_color}]{level_label}[/{diff_color}]",
            f"[{conf_color}]{confidence:.0%}[/{conf_color}]",
            distribution,
        )

    console.print(table)
    console.print(
        "\n[dim]These levels will adapt as you practice. Run [bold]swet test[/bold] anytime to reassess.[/dim]\n"
    )


def display_history(history: list[dict]) -> None:
    """Display attempt history as a table."""
    if not history:
        console.print("[dim]No attempts yet. Run [bold]swet[/bold] to get started.[/dim]")
        return

    table = Table(title="Recent Attempts", show_header=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Question", max_width=40)
    table.add_column("Competency")
    table.add_column("Format")
    table.add_column("Diff", justify="center")
    table.add_column("Score", justify="center")
    table.add_column("Time", justify="center")
    table.add_column("Date", style="dim")

    for i, attempt in enumerate(history, 1):
        difficulty = attempt["difficulty"]
        diff_color = DIFFICULTY_COLORS.get(difficulty, "white")

        # Format score display
        if attempt["score"] is not None:
            pct = attempt["score"] * 100
            score_color = "green" if pct >= 70 else "yellow" if pct >= 40 else "red"
            score_str = f"[{score_color}]{pct:.0f}%[/{score_color}]"
        else:
            score_str = "[dim]N/A[/dim]"

        # Format time display
        time_secs = attempt.get("time_seconds")
        if time_secs is not None:
            mins = int(time_secs // 60)
            secs = int(time_secs % 60)
            time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        else:
            time_str = "[dim]-[/dim]"

        table.add_row(
            str(i),
            attempt["title"][:40],
            _competency_display_name(attempt["competency_slug"]),
            attempt["format"].replace("_", " ").title(),
            f"[{diff_color}]L{difficulty}[/{diff_color}]",
            score_str,
            time_str,
            attempt["completed_at"][:10] if attempt["completed_at"] else "",
        )

    console.print()
    console.print(table)
    console.print()


def display_stats(stats: list[dict], streak: int | None = None, longest_streak: int | None = None) -> None:
    """Display aggregate stats by competency."""
    # Show streak info if available
    if streak is not None:
        streak_text = f"Current streak: [bold]{streak}[/bold] day{'s' if streak != 1 else ''}"
        if longest_streak is not None and longest_streak > streak:
            streak_text += f"  |  Best: [bold]{longest_streak}[/bold] days"
        console.print(Panel(streak_text, border_style="green"))

    if not stats:
        console.print("[dim]No graded attempts yet.[/dim]")
        return

    table = Table(title="Stats by Competency", show_header=True)
    table.add_column("Competency")
    table.add_column("Attempts", justify="center")
    table.add_column("Avg Score", justify="center")
    table.add_column("Best", justify="center")
    table.add_column("Worst", justify="center")

    for row in stats:
        avg_pct = row["avg_score"] * 100
        avg_color = "green" if avg_pct >= 70 else "yellow" if avg_pct >= 40 else "red"

        table.add_row(
            _competency_display_name(row["competency_slug"]),
            str(row["total_attempts"]),
            f"[{avg_color}]{avg_pct:.0f}%[/{avg_color}]",
            f"{row['max_score'] * 100:.0f}%",
            f"{row['min_score'] * 100:.0f}%",
        )

    console.print()
    console.print(table)
    console.print()


def display_bookmarks(bookmarks: list[dict]) -> None:
    """Display bookmarked questions."""
    if not bookmarks:
        console.print("[dim]No bookmarks yet. Use [bold]swet bookmark <question_id>[/bold] to save one.[/dim]")
        return

    table = Table(title="Bookmarked Questions", show_header=True)
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Question", max_width=40)
    table.add_column("Competency")
    table.add_column("Format")
    table.add_column("Diff", justify="center")
    table.add_column("Saved", style="dim")

    for bm in bookmarks:
        difficulty = bm["difficulty"]
        diff_color = DIFFICULTY_COLORS.get(difficulty, "white")
        table.add_row(
            bm["id"][:8],
            bm["title"][:40],
            _competency_display_name(bm["competency_slug"]),
            bm["format"].replace("_", " ").title(),
            f"[{diff_color}]L{difficulty}[/{diff_color}]",
            bm["bookmarked_at"][:10] if bm.get("bookmarked_at") else "",
        )

    console.print()
    console.print(table)
    console.print()


def display_review(question: dict, attempts: list[dict]) -> None:
    """Display a question and its past attempts for review."""
    display_question(question)

    if not attempts:
        console.print("[dim]No attempts for this question.[/dim]")
        return

    table = Table(title="Past Attempts", show_header=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Score", justify="center")
    table.add_column("Time", justify="center")
    table.add_column("Feedback", max_width=60)
    table.add_column("Date", style="dim")

    for i, attempt in enumerate(attempts, 1):
        if attempt["score"] is not None:
            pct = attempt["score"] * 100
            score_color = "green" if pct >= 70 else "yellow" if pct >= 40 else "red"
            score_str = f"[{score_color}]{pct:.0f}%[/{score_color}]"
        else:
            score_str = "[dim]N/A[/dim]"

        time_secs = attempt.get("time_seconds")
        if time_secs is not None:
            mins = int(time_secs // 60)
            secs = int(time_secs % 60)
            time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        else:
            time_str = "[dim]-[/dim]"

        feedback_text = (attempt["feedback"] or "")[:60]

        table.add_row(
            str(i),
            score_str,
            time_str,
            feedback_text,
            attempt["completed_at"][:10] if attempt.get("completed_at") else "",
        )

    console.print(table)
    console.print()


def display_session_summary(results: list[dict]) -> None:
    """Display a summary after a session of multiple questions."""
    if not results:
        console.print("[dim]No questions completed in this session.[/dim]")
        return

    console.print()
    console.print(Panel("[bold]Session Summary[/bold]", border_style="blue"))

    table = Table(show_header=True)
    table.add_column("#", style="dim", justify="right")
    table.add_column("Question", max_width=40)
    table.add_column("Competency")
    table.add_column("Score", justify="center")
    table.add_column("Time", justify="center")

    total_score = 0.0
    total_time = 0.0
    scored_count = 0

    for i, result in enumerate(results, 1):
        question = result["question"]
        grade = result["grade"]
        time_secs = result.get("time_seconds")

        if grade.normalized_score is not None:
            pct = grade.normalized_score * 100
            score_color = "green" if pct >= 70 else "yellow" if pct >= 40 else "red"
            score_str = f"[{score_color}]{pct:.0f}%[/{score_color}]"
            total_score += grade.normalized_score
            scored_count += 1
        else:
            score_str = "[dim]N/A[/dim]"

        if time_secs is not None:
            mins = int(time_secs // 60)
            secs = int(time_secs % 60)
            time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
            total_time += time_secs
        else:
            time_str = "[dim]-[/dim]"

        table.add_row(
            str(i),
            question["title"][:40],
            _competency_display_name(question["competency_slug"]),
            score_str,
            time_str,
        )

    console.print(table)

    # Totals
    avg_score = (total_score / scored_count * 100) if scored_count > 0 else 0
    avg_color = "green" if avg_score >= 70 else "yellow" if avg_score >= 40 else "red"
    summary_parts = [f"Questions: [bold]{len(results)}[/bold]"]
    summary_parts.append(f"Average: [{avg_color}]{avg_score:.0f}%[/{avg_color}]")
    if total_time > 0:
        total_mins = int(total_time // 60)
        total_secs = int(total_time % 60)
        summary_parts.append(f"Total time: [bold]{total_mins}m {total_secs}s[/bold]")

    console.print(Panel("  |  ".join(summary_parts), border_style="blue"))
    console.print()
