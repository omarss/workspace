"""Setup handler: /start and /config commands for user onboarding via WhatsApp.

Text-based multi-step onboarding using numbered selections. All conversation
state is persisted to SQLite between webhook calls since WhatsApp is stateless.
"""

import json
import logging

from swet_cli.data import (
    QUESTION_FORMATS,
    ROLES,
    get_frameworks_for_roles,
    get_languages_for_roles,
)
from swet_whatsapp.db import (
    clear_user_conversation_state,
    get_user_preferences,
    get_user_state,
    save_user_preferences,
    set_user_state,
)
from swet_whatsapp.formatters import _FORMAT_DISPLAY, format_preferences

logger = logging.getLogger(__name__)

# Setup steps
_STEP_ROLES = "roles"
_STEP_LANGUAGES = "languages"
_STEP_FRAMEWORKS = "frameworks"
_STEP_FORMATS = "formats"
_STEP_LENGTH = "length"
_STEP_CONFIRM_ASSESSMENT = "confirm_assessment"

# Display names for roles
_ROLE_DISPLAY = {role: role.replace("_", " ").title() for role in ROLES}

# Length options
_LENGTH_OPTIONS = ["concise", "standard", "detailed"]
_LENGTH_DISPLAY = {"concise": "Concise", "standard": "Standard", "detailed": "Detailed"}


def _parse_numbered_selections(text: str, options: list[str]) -> list[str] | None:
    """Parse comma-separated numbers into corresponding options.

    Returns None if any selection is invalid.
    """
    text = text.strip()
    if not text:
        return None

    selected = []
    for part in text.split(","):
        part = part.strip()
        if not part.isdigit():
            return None
        idx = int(part) - 1
        if idx < 0 or idx >= len(options):
            return None
        if options[idx] not in selected:
            selected.append(options[idx])

    return selected if selected else None


def _build_numbered_list(items: list[str], display_map: dict[str, str] | None = None) -> str:
    """Build a numbered list string from items."""
    lines = []
    for i, item in enumerate(items, 1):
        display = display_map.get(item, item) if display_map else item
        lines.append(f"{i}. {display}")
    return "\n".join(lines)


def handle_setup_start(user_id: str) -> str:
    """Start the setup flow or redirect if already configured.

    Returns response text to send to the user.
    """
    prefs = get_user_preferences(user_id)
    if prefs:
        return (
            "Welcome back! You already have preferences set.\n"
            "Send /config to edit them, /q for a question, or /help for all commands."
        )

    # Initialize setup conversation state
    clear_user_conversation_state(user_id)
    set_user_state(user_id, "conv:type", "setup")
    set_user_state(user_id, "conv:step", _STEP_ROLES)
    set_user_state(user_id, "conv:data", json.dumps({}))

    role_list = _build_numbered_list(ROLES, _ROLE_DISPLAY)
    return (
        "*Welcome to SWET!*\n\n"
        "Let's set up your profile. Select your engineering roles by typing "
        "the numbers (comma-separated):\n\n"
        f"{role_list}"
    )


def handle_config_start(user_id: str) -> str:
    """Start the config editing flow.

    Returns response text to send to the user.
    """
    prefs = get_user_preferences(user_id)

    # Initialize setup conversation state
    clear_user_conversation_state(user_id)
    set_user_state(user_id, "conv:type", "setup")
    set_user_state(user_id, "conv:step", _STEP_ROLES)

    # Pre-fill with existing preferences if available
    data = {}
    if prefs:
        data = {
            "roles": prefs["roles"],
            "languages": prefs["languages"],
            "frameworks": prefs["frameworks"],
            "formats": prefs.get("preferred_formats") or [],
            "length": prefs.get("question_length", "standard"),
        }

    set_user_state(user_id, "conv:data", json.dumps(data))

    role_list = _build_numbered_list(ROLES, _ROLE_DISPLAY)
    header = "*Edit Preferences*\n\n" if prefs else "No preferences set yet. Let's set up your profile.\n\n"
    return f"{header}Select your engineering roles by typing the numbers (comma-separated):\n\n{role_list}"


def handle_setup_input(user_id: str, text: str) -> str:
    """Route input to the current setup step.

    Returns response text to send to the user.
    """
    step = get_user_state(user_id, "conv:step")
    data_str = get_user_state(user_id, "conv:data")
    data = json.loads(data_str) if data_str else {}

    if step == _STEP_ROLES:
        return _handle_roles(user_id, text, data)
    if step == _STEP_LANGUAGES:
        return _handle_languages(user_id, text, data)
    if step == _STEP_FRAMEWORKS:
        return _handle_frameworks(user_id, text, data)
    if step == _STEP_FORMATS:
        return _handle_formats(user_id, text, data)
    if step == _STEP_LENGTH:
        return _handle_length(user_id, text, data)
    if step == _STEP_CONFIRM_ASSESSMENT:
        return _handle_assessment_confirm(user_id, text, data)

    # Unknown step, reset
    clear_user_conversation_state(user_id)
    return "Something went wrong. Send /start to begin again."


def _handle_roles(user_id: str, text: str, data: dict) -> str:
    """Handle role selection input."""
    selected = _parse_numbered_selections(text, ROLES)
    if selected is None:
        role_list = _build_numbered_list(ROLES, _ROLE_DISPLAY)
        return f"Invalid selection. Please enter numbers separated by commas.\nExample: 1,3,5\n\n{role_list}"

    data["roles"] = selected

    # Get available languages for selected roles
    available_langs = sorted(set(get_languages_for_roles(selected)))
    data["available_languages"] = available_langs
    set_user_state(user_id, "conv:data", json.dumps(data))
    set_user_state(user_id, "conv:step", _STEP_LANGUAGES)

    if not available_langs:
        # Skip languages, go to frameworks
        return _advance_to_frameworks(user_id, data, languages=[])

    lang_list = _build_numbered_list(available_langs)
    return (
        f"Select your programming languages (comma-separated numbers).\nType *skip* to skip this step.\n\n{lang_list}"
    )


def _handle_languages(user_id: str, text: str, data: dict) -> str:
    """Handle language selection input."""
    available_langs = data.get("available_languages", [])

    if text.strip().lower() == "skip":
        return _advance_to_frameworks(user_id, data, languages=[])

    selected = _parse_numbered_selections(text, available_langs)
    if selected is None:
        lang_list = _build_numbered_list(available_langs)
        return f"Invalid selection. Enter numbers separated by commas, or type *skip*.\nExample: 1,2\n\n{lang_list}"

    return _advance_to_frameworks(user_id, data, languages=selected)


def _advance_to_frameworks(user_id: str, data: dict, languages: list[str]) -> str:
    """Move to framework selection step."""
    data["languages"] = languages
    roles = data["roles"]

    available_fws = sorted(set(get_frameworks_for_roles(roles, languages=languages)))
    data["available_frameworks"] = available_fws
    set_user_state(user_id, "conv:data", json.dumps(data))

    if not available_fws:
        # Skip frameworks, go to formats
        return _advance_to_formats(user_id, data, frameworks=[])

    set_user_state(user_id, "conv:step", _STEP_FRAMEWORKS)
    fw_list = _build_numbered_list(available_fws)
    return f"Select your frameworks and tools (comma-separated numbers).\nType *skip* to skip this step.\n\n{fw_list}"


def _handle_frameworks(user_id: str, text: str, data: dict) -> str:
    """Handle framework selection input."""
    available_fws = data.get("available_frameworks", [])

    if text.strip().lower() == "skip":
        return _advance_to_formats(user_id, data, frameworks=[])

    selected = _parse_numbered_selections(text, available_fws)
    if selected is None:
        fw_list = _build_numbered_list(available_fws)
        return f"Invalid selection. Enter numbers separated by commas, or type *skip*.\nExample: 1,3\n\n{fw_list}"

    return _advance_to_formats(user_id, data, frameworks=selected)


def _advance_to_formats(user_id: str, data: dict, frameworks: list[str]) -> str:
    """Move to format selection step."""
    data["frameworks"] = frameworks
    set_user_state(user_id, "conv:step", _STEP_FORMATS)
    set_user_state(user_id, "conv:data", json.dumps(data))

    fmt_list = _build_numbered_list(QUESTION_FORMATS, _FORMAT_DISPLAY)
    return (
        "Select your preferred question types (comma-separated numbers).\n"
        "Type *skip* for no preference (all types equally weighted).\n\n"
        f"{fmt_list}"
    )


def _handle_formats(user_id: str, text: str, data: dict) -> str:
    """Handle format preference input."""
    if text.strip().lower() == "skip":
        data["formats"] = []
    else:
        selected = _parse_numbered_selections(text, QUESTION_FORMATS)
        if selected is None:
            fmt_list = _build_numbered_list(QUESTION_FORMATS, _FORMAT_DISPLAY)
            return (
                f"Invalid selection. Enter numbers separated by commas, or type *skip*.\nExample: 1,2,4\n\n{fmt_list}"
            )
        # If all formats selected, treat as no preference
        if len(selected) >= len(QUESTION_FORMATS):
            data["formats"] = []
        else:
            data["formats"] = selected

    set_user_state(user_id, "conv:step", _STEP_LENGTH)
    set_user_state(user_id, "conv:data", json.dumps(data))

    length_list = _build_numbered_list(_LENGTH_OPTIONS, _LENGTH_DISPLAY)
    return f"Select preferred question length:\n\n{length_list}"


def _handle_length(user_id: str, text: str, data: dict) -> str:
    """Handle length selection — final step, save preferences."""
    selected = _parse_numbered_selections(text, _LENGTH_OPTIONS)
    if selected is None or len(selected) != 1:
        length_list = _build_numbered_list(_LENGTH_OPTIONS, _LENGTH_DISPLAY)
        return f"Please select exactly one option (1, 2, or 3).\n\n{length_list}"

    length = selected[0]
    roles = data.get("roles", [])
    languages = data.get("languages", [])
    frameworks = data.get("frameworks", [])
    formats = data.get("formats", [])

    # If all formats selected or none, treat as no preference
    preferred_formats = formats if formats else None

    save_user_preferences(
        user_id=user_id,
        roles=roles,
        languages=languages,
        frameworks=frameworks,
        difficulty=3,
        preferred_formats=preferred_formats,
        question_length=length,
    )

    prefs = {
        "roles": roles,
        "languages": languages,
        "frameworks": frameworks,
        "preferred_formats": preferred_formats,
        "question_length": length,
    }

    set_user_state(user_id, "conv:step", _STEP_CONFIRM_ASSESSMENT)
    set_user_state(user_id, "conv:data", json.dumps(data))

    return (
        f"Preferences saved!\n\n{format_preferences(prefs)}\n\n"
        "Would you like to run a level assessment now?\n"
        "(Recommended for accurate difficulty adaptation)\n\n"
        "Type *yes* or *no*"
    )


def _handle_assessment_confirm(user_id: str, text: str, data: dict) -> str:
    """Handle yes/no for running assessment after setup."""
    clear_user_conversation_state(user_id)

    answer = text.strip().lower()
    if answer in ("yes", "y"):
        return "Starting level assessment...\nSend /test to begin."

    return "Setup complete! Send /q to get your first question."
