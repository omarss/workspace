"""Local practice history stored in ~/.swet/history.json.

Tracks past questions and scores without requiring a database.
Capped at 100 entries to prevent file bloat.
"""

import json
from datetime import UTC, datetime

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from src.cli.config import CONFIG_DIR, ensure_config_dir

HISTORY_FILE = CONFIG_DIR / "history.json"
MAX_ENTRIES = 100

console = Console()


class HistoryEntry(BaseModel):
    """A single practice session record."""

    timestamp: str
    competency: str
    question_format: str
    difficulty: int
    title: str
    score: float
    max_score: float


def load_history() -> list[HistoryEntry]:
    """Load practice history from disk."""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return [HistoryEntry.model_validate(item) for item in data]
    except (json.JSONDecodeError, ValueError):
        return []


def append_history(entry: HistoryEntry) -> None:
    """Append a new entry and cap at MAX_ENTRIES."""
    ensure_config_dir()
    entries = load_history()
    entries.append(entry)
    # Keep only the most recent entries
    entries = entries[-MAX_ENTRIES:]
    data = [e.model_dump() for e in entries]
    HISTORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_entry(
    competency: str,
    question_format: str,
    difficulty: int,
    title: str,
    score: float,
    max_score: float,
) -> HistoryEntry:
    """Create a history entry with the current timestamp."""
    return HistoryEntry(
        timestamp=datetime.now(UTC).isoformat(),
        competency=competency,
        question_format=question_format,
        difficulty=difficulty,
        title=title,
        score=score,
        max_score=max_score,
    )


def display_history() -> None:
    """Render practice history as a rich table."""
    entries = load_history()

    if not entries:
        console.print("[dim]No practice history yet. Run 'swet' to start practicing![/dim]")
        return

    table = Table(title=f"Practice History (last {len(entries)} sessions)", show_lines=True)
    table.add_column("Date", style="dim")
    table.add_column("Competency", style="cyan")
    table.add_column("Format")
    table.add_column("Difficulty", justify="center")
    table.add_column("Title")
    table.add_column("Score", justify="center")

    # Show most recent first
    for entry in reversed(entries):
        # Parse and format timestamp
        try:
            dt = datetime.fromisoformat(entry.timestamp)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            date_str = entry.timestamp[:16]

        pct = (entry.score / entry.max_score * 100) if entry.max_score > 0 else 0
        color = "green" if pct >= 70 else "yellow" if pct >= 40 else "red"
        score_str = f"[{color}]{entry.score:.0f}/{entry.max_score:.0f} ({pct:.0f}%)[/{color}]"

        # Truncate long titles
        title = entry.title if len(entry.title) <= 50 else entry.title[:47] + "..."

        table.add_row(
            date_str,
            entry.competency.replace("_", " ").title(),
            entry.question_format.replace("_", " ").title(),
            f"L{entry.difficulty}",
            title,
            score_str,
        )

    console.print(table)
