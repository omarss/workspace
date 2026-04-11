"""Stats handlers: /stats, /history, /competencies, /bookmarks, /preferences, /help.

Simple command handlers (no conversation state needed) that fetch data
from the user-scoped database and return formatted text strings.
"""

import logging

from swet_cli.data import COMPETENCY_SLUGS
from swet_whatsapp.db import (
    get_user_bookmarks,
    get_user_competency_levels,
    get_user_history,
    get_user_preferences,
    get_user_state,
    get_user_stats,
)
from swet_whatsapp.formatters import (
    format_bookmarks,
    format_competencies,
    format_history,
    format_preferences,
    format_stats,
)

logger = logging.getLogger(__name__)


def handle_stats(user_id: str) -> str:
    """Handle /stats — show aggregate stats by competency."""
    data = get_user_stats(user_id)
    streak_str = get_user_state(user_id, "current_streak")
    longest_str = get_user_state(user_id, "longest_streak")
    streak = int(streak_str) if streak_str else None
    longest = int(longest_str) if longest_str else None

    return format_stats(data, streak=streak, longest_streak=longest)


def handle_history(user_id: str, args: str | None = None) -> str:
    """Handle /history — show recent attempt history."""
    limit = 10
    if args and args.strip().isdigit():
        limit = int(args.strip())

    data = get_user_history(user_id, limit)
    return format_history(data)


def handle_competencies(user_id: str) -> str:
    """Handle /competencies — list all competencies with levels."""
    levels = get_user_competency_levels(user_id)
    return format_competencies(levels, COMPETENCY_SLUGS)


def handle_bookmarks(user_id: str) -> str:
    """Handle /bookmarks — list bookmarked questions."""
    data = get_user_bookmarks(user_id)
    return format_bookmarks(data)


def handle_preferences(user_id: str) -> str:
    """Handle /preferences — show current preferences."""
    prefs = get_user_preferences(user_id)
    if not prefs:
        return "No preferences set. Send /start to set up."
    return format_preferences(prefs)


def handle_help() -> str:
    """Handle /help — show available commands."""
    return (
        "*SWET WhatsApp Bot Commands*\n\n"
        "/start - Set up your profile (roles, languages, frameworks)\n"
        "/q - Get an adaptive question\n"
        "/session - Multi-question practice session\n"
        "/test - Run a level assessment\n"
        "/stats - View performance stats\n"
        "/history - View recent attempts\n"
        "/competencies - List all competency areas\n"
        "/bookmarks - View bookmarked questions\n"
        "/bookmark - Bookmark the last answered question\n"
        "/preferences - View current preferences\n"
        "/config - Edit preferences\n"
        "/help - Show this help message\n"
        "/cancel - Cancel current operation\n"
        "/stop - End current session"
    )
