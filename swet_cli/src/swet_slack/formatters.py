"""Slack mrkdwn message formatting for questions, grades, stats, etc.

Uses Slack's mrkdwn format (*bold*, _italic_, `code`, ```code blocks```).
Handles the ~3000-char block text limit by splitting into multiple parts.
"""

from swet_cli.data import COMPETENCY_BY_SLUG
from swet_cli.models import GradeResult
from swet_cli.prompts import DIFFICULTY_LABELS

# Slack block text character limit (conservative to avoid truncation)
MAX_MESSAGE_LENGTH = 3000

# Unicode symbols for visual display
_CHECK = "\u2713"  # checkmark
_CROSS = "\u2717"  # cross
_BULLET = "\u2022"  # bullet

_FORMAT_DISPLAY = {
    "mcq": "Multiple Choice",
    "code_review": "Code Review",
    "debugging": "Debugging",
    "short_answer": "Short Answer",
    "design_prompt": "System Design",
}


def _competency_name(slug: str) -> str:
    """Get human-readable name for a competency slug."""
    comp = COMPETENCY_BY_SLUG.get(slug)
    return comp.name if comp else slug.replace("_", " ").title()


def _escape(text: str) -> str:
    """Escape special characters for Slack mrkdwn.

    Slack requires escaping &, <, > in message text to prevent
    them from being interpreted as HTML entities or link syntax.
    """
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split a long message into parts respecting the character limit.

    Splits on paragraph boundaries (double newline) where possible,
    falling back to single newline, then hard truncation.
    """
    if len(text) <= max_len:
        return [text]

    parts: list[str] = []
    remaining = text

    while len(remaining) > max_len:
        # Try splitting at paragraph boundary
        split_pos = remaining.rfind("\n\n", 0, max_len)
        if split_pos == -1:
            split_pos = remaining.rfind("\n", 0, max_len)
        if split_pos == -1:
            split_pos = max_len

        parts.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()

    if remaining.strip():
        parts.append(remaining)

    return parts


def format_question(question: dict) -> list[str]:
    """Format a question for Slack display.

    Returns a list of message parts (usually 1, may be 2+ for long questions).
    MCQ options are omitted here — they go via Block Kit action buttons.
    """
    comp_name = _competency_name(question["competency_slug"])
    difficulty = question["difficulty"]
    diff_label = DIFFICULTY_LABELS.get(difficulty, f"L{difficulty}")
    fmt_label = _FORMAT_DISPLAY.get(question["format"], question["format"])

    # Estimated time from metadata
    est_time = ""
    if question.get("metadata") and question["metadata"].get("estimated_time_minutes"):
        est_time = f" | ~{question['metadata']['estimated_time_minutes']} min"

    lines = [
        "*SWET Question*",
        f"*{_escape(comp_name)}* | {_escape(diff_label)} | {_escape(fmt_label)}{est_time}",
        "",
        f"*{_escape(question['title'])}*",
        "",
        _escape(question["body"]),
    ]

    # Code snippet
    if question.get("code_snippet"):
        lines.append("")
        lines.append(f"```{_escape(question['code_snippet'])}```")

    # For non-MCQ formats, show answer prompt
    if question["format"] != "mcq":
        lines.append("")
        lines.append("_Type your answer below:_")

    text = "\n".join(lines)
    return _split_message(text)


def format_grade(grade: GradeResult, question: dict, time_seconds: float | None = None) -> str:
    """Format the grading result for Slack display."""
    is_mcq = question["format"] == "mcq"
    lines: list[str] = []

    if is_mcq:
        if grade.normalized_score == 1.0:
            lines.append(f"*{_CHECK} Correct!*")
        else:
            lines.append(f"*{_CROSS} Incorrect*")
            if question.get("correct_answer"):
                lines.append(f"Correct answer: *{_escape(question['correct_answer'])}*")
    else:
        pct = grade.normalized_score * 100
        lines.append(f"*Score: {grade.total_score}/{grade.max_score} ({pct:.0f}%)*")

        # Criterion breakdown
        if grade.criteria_scores:
            lines.append("")
            for cs in grade.criteria_scores:
                lines.append(f"{_BULLET} {_escape(cs.name)}: {cs.score}/{cs.max_points}")
                if cs.feedback:
                    lines.append(f"  _{_escape(cs.feedback)}_")

    # Time taken
    if time_seconds is not None:
        minutes = int(time_seconds // 60)
        seconds = int(time_seconds % 60)
        time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
        lines.append(f"\nTime: {time_str}")

    # Feedback
    if grade.overall_feedback:
        lines.append(f"\n*Feedback:*\n{_escape(grade.overall_feedback)}")

    # Explanation
    if question.get("explanation"):
        lines.append(f"\n*Explanation:*\n{_escape(question['explanation'])}")

    return "\n".join(lines)


def format_streak(count: int, is_new_day: bool) -> str:
    """Format streak info."""
    if is_new_day:
        if count == 1:
            return "Streak started! Day 1"
        return f"Day {count} streak!"
    return f"Current streak: {count} day{'s' if count != 1 else ''}"


def format_level_progress(competency_slug: str, old_level: int, new_level: int) -> str:
    """Format a level change notification."""
    comp_name = _competency_name(competency_slug)
    if new_level > old_level:
        new_label = DIFFICULTY_LABELS.get(new_level, f"L{new_level}")
        return f"*Level up! {_escape(comp_name)}: L{old_level} -> {_escape(new_label)}*"
    new_label = DIFFICULTY_LABELS.get(new_level, f"L{new_level}")
    return f"{_escape(comp_name)} adjusted to {_escape(new_label)}"


def format_stats(stats: list[dict], streak: int | None = None, longest_streak: int | None = None) -> str:
    """Format aggregate stats for Slack display."""
    lines: list[str] = []

    if streak is not None:
        streak_text = f"Current streak: *{streak}* day{'s' if streak != 1 else ''}"
        if longest_streak is not None and longest_streak > streak:
            streak_text += f" | Best: *{longest_streak}* days"
        lines.append(streak_text)
        lines.append("")

    if not stats:
        lines.append("No graded attempts yet.")
        return "\n".join(lines)

    lines.append("*Stats by Competency*")
    lines.append("")

    for row in stats:
        comp_name = _competency_name(row["competency_slug"])
        avg_pct = row["avg_score"] * 100
        lines.append(
            f"{_BULLET} *{_escape(comp_name)}*\n"
            f"  Attempts: {row['total_attempts']} | "
            f"Avg: {avg_pct:.0f}% | "
            f"Best: {row['max_score'] * 100:.0f}% | "
            f"Worst: {row['min_score'] * 100:.0f}%"
        )

    return "\n".join(lines)


def format_history(history: list[dict]) -> str:
    """Format recent attempt history for Slack display."""
    if not history:
        return "No attempts yet. Use `/swet-q` to get started."

    lines = ["*Recent Attempts*", ""]

    for i, attempt in enumerate(history, 1):
        comp_name = _competency_name(attempt["competency_slug"])
        fmt_label = _FORMAT_DISPLAY.get(attempt["format"], attempt["format"])

        score_str = "N/A"
        if attempt["score"] is not None:
            score_str = f"{attempt['score'] * 100:.0f}%"

        time_str = ""
        if attempt.get("time_seconds") is not None:
            mins = int(attempt["time_seconds"] // 60)
            secs = int(attempt["time_seconds"] % 60)
            time_str = f" | {mins}m {secs}s" if mins > 0 else f" | {secs}s"

        date_str = ""
        if attempt.get("completed_at"):
            date_str = f" | {attempt['completed_at'][:10]}"

        title = attempt["title"][:40]
        lines.append(
            f"{i}. *{_escape(title)}*\n"
            f"   {_escape(comp_name)} | {_escape(fmt_label)} | L{attempt['difficulty']} | "
            f"{score_str}{time_str}{date_str}"
        )

    return "\n".join(lines)


def format_preferences(prefs: dict) -> str:
    """Format current user preferences."""
    roles = prefs.get("roles", [])
    role_names = [r.replace("_", " ").title() for r in roles]

    pref_formats = prefs.get("preferred_formats")
    if pref_formats:
        fmt_names = [_FORMAT_DISPLAY.get(f, f) for f in pref_formats]
        formats_str = ", ".join(fmt_names)
    else:
        formats_str = "All (no preference)"

    length_display = {"concise": "Concise", "standard": "Standard", "detailed": "Detailed"}
    question_length = prefs.get("question_length", "standard")

    lines = [
        "*Your Preferences*",
        "",
        f"{_BULLET} *Roles:* {_escape(', '.join(role_names) or 'none')}",
        f"{_BULLET} *Languages:* {_escape(', '.join(prefs['languages']) or 'none')}",
        f"{_BULLET} *Frameworks:* {_escape(', '.join(prefs['frameworks']) or 'none')}",
        f"{_BULLET} *Question Types:* {_escape(formats_str)}",
        f"{_BULLET} *Question Length:* {_escape(length_display.get(question_length, question_length.title()))}",
    ]

    return "\n".join(lines)


def format_assessment_results(results: dict[str, dict]) -> str:
    """Format level assessment results."""
    lines = [
        "*Level Assessment Complete*",
        "Your competency levels have been determined using adaptive testing.",
        "",
    ]

    for slug, data in results.items():
        comp_name = _competency_name(slug)
        level = data["level"]
        confidence = data["confidence"]
        level_label = DIFFICULTY_LABELS.get(level, f"L{level}")
        distribution = data.get("distribution", "")

        lines.append(f"{_BULLET} *{_escape(comp_name)}*: {_escape(level_label)} (confidence: {confidence:.0%})")
        if distribution:
            lines.append(f"  _{_escape(distribution)}_")

    lines.append("")
    lines.append("_These levels will adapt as you practice. Run /swet-test anytime to reassess._")

    return "\n".join(lines)


def format_session_summary(results: list[dict]) -> str:
    """Format a session summary after multiple questions."""
    if not results:
        return "No questions completed in this session."

    lines = ["*Session Summary*", ""]

    total_score = 0.0
    total_time = 0.0
    scored_count = 0

    for i, result in enumerate(results, 1):
        question = result["question"]
        score = result["score"]
        time_secs = result.get("time_seconds")

        comp_name = _competency_name(question["competency_slug"])
        title = question["title"][:40]

        score_str = "N/A"
        if score is not None:
            pct = score * 100
            score_str = f"{pct:.0f}%"
            total_score += score
            scored_count += 1

        time_str = ""
        if time_secs is not None:
            mins = int(time_secs // 60)
            secs = int(time_secs % 60)
            time_str = f" | {mins}m {secs}s" if mins > 0 else f" | {secs}s"
            total_time += time_secs

        lines.append(f"{i}. *{_escape(title)}* | {_escape(comp_name)} | {score_str}{time_str}")

    # Totals
    lines.append("")
    avg_score = (total_score / scored_count * 100) if scored_count > 0 else 0
    summary = f"Questions: *{len(results)}* | Average: *{avg_score:.0f}%*"
    if total_time > 0:
        total_mins = int(total_time // 60)
        total_secs = int(total_time % 60)
        summary += f" | Total time: *{total_mins}m {total_secs}s*"
    lines.append(summary)

    return "\n".join(lines)


def format_bookmarks(bookmarks: list[dict]) -> str:
    """Format bookmarked questions."""
    if not bookmarks:
        return "No bookmarks yet. Bookmark questions after answering them."

    lines = ["*Bookmarked Questions*", ""]

    for bm in bookmarks:
        comp_name = _competency_name(bm["competency_slug"])
        fmt_label = _FORMAT_DISPLAY.get(bm["format"], bm["format"])
        date_str = bm["bookmarked_at"][:10] if bm.get("bookmarked_at") else ""

        lines.append(
            f"{_BULLET} *{_escape(bm['title'][:40])}*\n"
            f"  {_escape(comp_name)} | {_escape(fmt_label)} | L{bm['difficulty']}"
            + (f" | {date_str}" if date_str else "")
        )

    return "\n".join(lines)


def format_competencies(competency_levels: dict[str, dict], all_slugs: list[str]) -> str:
    """Format competency list with levels."""
    lines = ["*Competency Areas*", ""]

    for i, slug in enumerate(all_slugs, 1):
        comp_name = _competency_name(slug)
        level_data = competency_levels.get(slug)
        if level_data:
            level_str = f"L{level_data['estimated_level']}"
            attempts_str = str(level_data["total_attempts"])
        else:
            level_str = "-"
            attempts_str = "0"

        lines.append(f"{i}. *{_escape(comp_name)}* | Level: {level_str} | Attempts: {attempts_str}")

    return "\n".join(lines)
