"""Slack Block Kit JSON structure builders for interactive UI elements.

All action_id values follow the pattern "{action}_{context}_{value}"
and value fields encode "{context}:{value}" for clean action routing.
"""

from swet_cli.data import QUESTION_FORMATS

_FORMAT_DISPLAY = {
    "mcq": "Multiple Choice",
    "code_review": "Code Review",
    "debugging": "Debugging",
    "short_answer": "Short Answer",
    "design_prompt": "System Design",
}


def _text_block(text: str) -> dict:
    """Create a mrkdwn section block."""
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _plain_text(text: str) -> dict:
    """Create a plain_text object."""
    return {"type": "plain_text", "text": text}


def mcq_blocks(options: dict, question_id: str) -> list[dict]:
    """Build action blocks with buttons for MCQ answer options.

    Each button's action_id = "mcq_{q_short}_{key}" and
    value = "{q_short}:{key}" for routing.
    """
    q_short = question_id[:12]
    elements = []
    for key, text in sorted(options.items()):
        display = f"{key}. {text[:60]}"
        elements.append(
            {
                "type": "button",
                "text": _plain_text(display),
                "action_id": f"mcq_{q_short}_{key}",
                "value": f"{q_short}:{key}",
            }
        )

    return [{"type": "actions", "elements": elements}]


def roles_blocks(available_roles: list[str], selected: set[str]) -> list[dict]:
    """Build action blocks with toggle buttons for role selection.

    Selected roles have "primary" style. Includes a Done button.
    """
    elements = []
    for role in available_roles:
        display = role.replace("_", " ").title()
        if role in selected:
            display = f"\u2713 {display}"
        btn: dict = {
            "type": "button",
            "text": _plain_text(display),
            "action_id": f"role_{role}",
            "value": role,
        }
        if role in selected:
            btn["style"] = "primary"
        elements.append(btn)

    # Slack limits actions block to 25 elements, split into groups if needed
    blocks: list[dict] = []
    for i in range(0, len(elements), 5):
        blocks.append({"type": "actions", "elements": elements[i : i + 5]})

    # Done button in its own actions block
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": _plain_text("Done \u2192"),
                    "action_id": "role_done",
                    "value": "done",
                    "style": "primary",
                }
            ],
        }
    )

    return blocks


def languages_blocks(available: list[str], selected: set[str]) -> list[dict]:
    """Build action blocks with toggle buttons for language selection.

    Arranges languages in rows of 5. Includes Skip and Done buttons.
    """
    elements = []
    for lang in available:
        display = f"\u2713 {lang}" if lang in selected else lang
        btn: dict = {
            "type": "button",
            "text": _plain_text(display),
            "action_id": f"lang_{lang}",
            "value": lang,
        }
        if lang in selected:
            btn["style"] = "primary"
        elements.append(btn)

    blocks: list[dict] = []
    for i in range(0, len(elements), 5):
        blocks.append({"type": "actions", "elements": elements[i : i + 5]})

    # Skip + Done buttons
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": _plain_text("Skip \u2192"),
                    "action_id": "lang_skip",
                    "value": "skip",
                },
                {
                    "type": "button",
                    "text": _plain_text("Done \u2192"),
                    "action_id": "lang_done",
                    "value": "done",
                    "style": "primary",
                },
            ],
        }
    )

    return blocks


def frameworks_blocks(available: list[str], selected: set[str]) -> list[dict]:
    """Build action blocks with toggle buttons for framework selection.

    Arranges frameworks in rows of 4 (names tend to be longer). Includes Skip and Done buttons.
    """
    elements = []
    for fw in available:
        display_name = fw[:25]
        display = f"\u2713 {display_name}" if fw in selected else display_name
        btn: dict = {
            "type": "button",
            "text": _plain_text(display),
            "action_id": f"fw_{fw}",
            "value": fw,
        }
        if fw in selected:
            btn["style"] = "primary"
        elements.append(btn)

    blocks: list[dict] = []
    for i in range(0, len(elements), 4):
        blocks.append({"type": "actions", "elements": elements[i : i + 4]})

    # Skip + Done buttons
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": _plain_text("Skip \u2192"),
                    "action_id": "fw_skip",
                    "value": "skip",
                },
                {
                    "type": "button",
                    "text": _plain_text("Done \u2192"),
                    "action_id": "fw_done",
                    "value": "done",
                    "style": "primary",
                },
            ],
        }
    )

    return blocks


def formats_blocks(selected: set[str]) -> list[dict]:
    """Build action blocks with toggle buttons for question format preferences."""
    elements = []
    for fmt in QUESTION_FORMATS:
        display = _FORMAT_DISPLAY.get(fmt, fmt)
        if fmt in selected:
            display = f"\u2713 {display}"
        btn: dict = {
            "type": "button",
            "text": _plain_text(display),
            "action_id": f"fmt_{fmt}",
            "value": fmt,
        }
        if fmt in selected:
            btn["style"] = "primary"
        elements.append(btn)

    blocks: list[dict] = [{"type": "actions", "elements": elements}]

    # Done button
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": _plain_text("Done \u2192"),
                    "action_id": "fmt_done",
                    "value": "done",
                    "style": "primary",
                }
            ],
        }
    )

    return blocks


def length_blocks(current: str) -> list[dict]:
    """Build action blocks with radio-style buttons for question length preference."""
    options = [
        ("Concise", "concise"),
        ("Standard", "standard"),
        ("Detailed", "detailed"),
    ]
    elements = []
    for display, value in options:
        prefix = "\u2713 " if value == current else ""
        btn: dict = {
            "type": "button",
            "text": _plain_text(f"{prefix}{display}"),
            "action_id": f"len_{value}",
            "value": value,
        }
        if value == current:
            btn["style"] = "primary"
        elements.append(btn)

    return [{"type": "actions", "elements": elements}]


def confirm_blocks(yes_action: str, no_action: str) -> list[dict]:
    """Build action blocks with Yes/No confirmation buttons."""
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": _plain_text("Yes"),
                    "action_id": yes_action,
                    "value": "yes",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": _plain_text("No"),
                    "action_id": no_action,
                    "value": "no",
                },
            ],
        }
    ]


def session_count_blocks() -> list[dict]:
    """Build action blocks for selecting session question count."""
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": _plain_text("3"),
                    "action_id": "session_3",
                    "value": "3",
                },
                {
                    "type": "button",
                    "text": _plain_text("5"),
                    "action_id": "session_5",
                    "value": "5",
                },
                {
                    "type": "button",
                    "text": _plain_text("10"),
                    "action_id": "session_10",
                    "value": "10",
                },
            ],
        }
    ]


def post_answer_blocks(question_id: str) -> list[dict]:
    """Build action blocks shown after grading (bookmark + next question)."""
    q_short = question_id[:12]
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": _plain_text("Bookmark"),
                    "action_id": f"bookmark_{q_short}",
                    "value": q_short,
                },
                {
                    "type": "button",
                    "text": _plain_text("Next Question"),
                    "action_id": "next_q",
                    "value": "next",
                    "style": "primary",
                },
            ],
        }
    ]
