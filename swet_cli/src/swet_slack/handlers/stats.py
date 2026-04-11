"""Stats handlers: /swet-stats, /swet-history, /swet-competencies, etc.

Simple slash command handlers (no conversation state needed) that fetch data
from the user-scoped database and send formatted messages.
"""

import logging

from swet_cli.data import COMPETENCY_SLUGS
from swet_slack.db import (
    get_or_create_user,
    get_user_bookmarks,
    get_user_competency_levels,
    get_user_history,
    get_user_preferences,
    get_user_state,
    get_user_stats,
)
from swet_slack.formatters import (
    _split_message,
    format_bookmarks,
    format_competencies,
    format_history,
    format_preferences,
    format_stats,
)

logger = logging.getLogger(__name__)


def _get_user_id(user_id: str, username: str | None = None) -> str:
    """Ensure user exists in DB and return user_id."""
    return get_or_create_user(user_id=user_id, username=username)


def register_stats_handlers(app) -> None:
    """Register all stats-related slash command handlers."""

    @app.command("/swet-stats")
    def handle_stats(ack, command, respond):
        """Handle /swet-stats — show aggregate stats by competency."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        data = get_user_stats(user_id)
        streak_str = get_user_state(user_id, "current_streak")
        longest_str = get_user_state(user_id, "longest_streak")
        streak = int(streak_str) if streak_str else None
        longest = int(longest_str) if longest_str else None

        text = format_stats(data, streak=streak, longest_streak=longest)
        for part in _split_message(text):
            respond(text=part)

    @app.command("/swet-history")
    def handle_history(ack, command, respond):
        """Handle /swet-history — show recent attempt history."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))

        limit = 10
        text_arg = command.get("text", "").strip()
        if text_arg and text_arg.isdigit():
            limit = int(text_arg)

        data = get_user_history(user_id, limit)
        text = format_history(data)
        for part in _split_message(text):
            respond(text=part)

    @app.command("/swet-competencies")
    def handle_competencies(ack, command, respond):
        """Handle /swet-competencies — list all competencies with levels."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        levels = get_user_competency_levels(user_id)
        text = format_competencies(levels, COMPETENCY_SLUGS)
        for part in _split_message(text):
            respond(text=part)

    @app.command("/swet-bookmarks")
    def handle_bookmarks(ack, command, respond):
        """Handle /swet-bookmarks — list bookmarked questions."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        data = get_user_bookmarks(user_id)
        text = format_bookmarks(data)
        for part in _split_message(text):
            respond(text=part)

    @app.command("/swet-preferences")
    def handle_preferences(ack, command, respond):
        """Handle /swet-preferences — show current preferences."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        prefs = get_user_preferences(user_id)
        if not prefs:
            respond(text="No preferences set. Run `/swet-setup` to set up.")
            return
        text = format_preferences(prefs)
        respond(text=text)

    @app.command("/swet-help")
    def handle_help(ack, command, respond):
        """Handle /swet-help — show available commands."""
        text = (
            "*SWET Bot Commands*\n\n"
            "`/swet-setup` - Set up your profile (roles, languages, frameworks)\n"
            "`/swet-q` - Get an adaptive question\n"
            "`/swet-session` - Multi-question practice session\n"
            "`/swet-test` - Run a level assessment\n"
            "`/swet-stats` - View performance stats\n"
            "`/swet-history` - View recent attempts\n"
            "`/swet-competencies` - List all competency areas\n"
            "`/swet-bookmarks` - View bookmarked questions\n"
            "`/swet-preferences` - View current preferences\n"
            "`/swet-config` - Edit preferences\n"
            "`/swet-help` - Show this help message"
        )
        respond(text=text)
