"""Telegram InlineKeyboardMarkup builders for interactive UI elements.

All callback_data values follow the pattern: "{action}:{context}:{value}"
to enable clean routing in CallbackQueryHandlers.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from swet_cli.data import QUESTION_FORMATS

# --- MCQ Answer Keyboard ---


def mcq_keyboard(options: dict, question_id: str) -> InlineKeyboardMarkup:
    """Build inline keyboard for MCQ options.

    Each button's callback_data = "mcq:{question_id_short}:{option_key}"
    Uses first 12 chars of question_id to stay within 64-byte limit.
    """
    q_short = question_id[:12]
    buttons = [
        [InlineKeyboardButton(f"{key}. {text[:50]}", callback_data=f"mcq:{q_short}:{key}")]
        for key, text in sorted(options.items())
    ]
    return InlineKeyboardMarkup(buttons)


# --- Setup Flow Keyboards ---


def roles_keyboard(available_roles: list[str], selected: set[str]) -> InlineKeyboardMarkup:
    """Build toggle keyboard for role selection during setup.

    Selected roles are marked with a checkmark prefix.
    """
    buttons = []
    for role in available_roles:
        display = role.replace("_", " ").title()
        prefix = "\u2713 " if role in selected else ""
        buttons.append([InlineKeyboardButton(f"{prefix}{display}", callback_data=f"role:{role}")])
    buttons.append([InlineKeyboardButton("Done \u2192", callback_data="role:done")])
    return InlineKeyboardMarkup(buttons)


def languages_keyboard(available: list[str], selected: set[str]) -> InlineKeyboardMarkup:
    """Build toggle keyboard for language selection.

    Arranges languages in rows of 3 for compact display.
    """
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for lang in available:
        prefix = "\u2713 " if lang in selected else ""
        row.append(InlineKeyboardButton(f"{prefix}{lang}", callback_data=f"lang:{lang}"))
        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton("Skip \u2192", callback_data="lang:skip"),
            InlineKeyboardButton("Done \u2192", callback_data="lang:done"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


def frameworks_keyboard(available: list[str], selected: set[str]) -> InlineKeyboardMarkup:
    """Build toggle keyboard for framework selection.

    Arranges frameworks in rows of 2 (names tend to be longer).
    """
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for fw in available:
        prefix = "\u2713 " if fw in selected else ""
        display = fw[:25]  # truncate long names
        row.append(InlineKeyboardButton(f"{prefix}{display}", callback_data=f"fw:{fw}"))
        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton("Skip \u2192", callback_data="fw:skip"),
            InlineKeyboardButton("Done \u2192", callback_data="fw:done"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


def formats_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    """Build toggle keyboard for question format preferences."""
    format_display = {
        "mcq": "Multiple Choice",
        "code_review": "Code Review",
        "debugging": "Debugging",
        "short_answer": "Short Answer",
        "design_prompt": "System Design",
    }
    buttons = []
    for fmt in QUESTION_FORMATS:
        display = format_display.get(fmt, fmt)
        prefix = "\u2713 " if fmt in selected else ""
        buttons.append([InlineKeyboardButton(f"{prefix}{display}", callback_data=f"fmt:{fmt}")])
    buttons.append([InlineKeyboardButton("Done \u2192", callback_data="fmt:done")])
    return InlineKeyboardMarkup(buttons)


def length_keyboard(current: str) -> InlineKeyboardMarkup:
    """Build keyboard for question length preference."""
    options = [
        ("Concise", "concise"),
        ("Standard", "standard"),
        ("Detailed", "detailed"),
    ]
    buttons = []
    for display, value in options:
        prefix = "\u2713 " if value == current else ""
        buttons.append([InlineKeyboardButton(f"{prefix}{display}", callback_data=f"len:{value}")])
    return InlineKeyboardMarkup(buttons)


# --- Other Keyboards ---


def confirm_keyboard(yes_data: str = "confirm:yes", no_data: str = "confirm:no") -> InlineKeyboardMarkup:
    """Build a yes/no confirmation keyboard."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data=yes_data),
                InlineKeyboardButton("No", callback_data=no_data),
            ]
        ]
    )


def session_count_keyboard() -> InlineKeyboardMarkup:
    """Build keyboard for selecting session question count."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("3", callback_data="session:3"),
                InlineKeyboardButton("5", callback_data="session:5"),
                InlineKeyboardButton("10", callback_data="session:10"),
            ]
        ]
    )


def bookmark_keyboard(question_id: str) -> InlineKeyboardMarkup:
    """Build a bookmark toggle button."""
    q_short = question_id[:12]
    return InlineKeyboardMarkup([[InlineKeyboardButton("Bookmark", callback_data=f"bookmark:{q_short}")]])


def post_answer_keyboard(question_id: str) -> InlineKeyboardMarkup:
    """Build keyboard shown after grading (bookmark + next question)."""
    q_short = question_id[:12]
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Bookmark", callback_data=f"bookmark:{q_short}"),
                InlineKeyboardButton("Next Question", callback_data="next_q"),
            ]
        ]
    )
