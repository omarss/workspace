"""Stats handlers: /stats, /history, /competencies, /bookmarks commands.

Simple command handlers (no conversation state needed) that fetch data
from the user-scoped database and send formatted messages.
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from swet_cli.data import COMPETENCY_SLUGS
from swet_telegram.db import (
    get_or_create_user,
    get_user_bookmarks,
    get_user_competency_levels,
    get_user_history,
    get_user_preferences,
    get_user_state,
    get_user_stats,
)
from swet_telegram.formatters import (
    _split_message,
    format_bookmarks,
    format_competencies,
    format_history,
    format_preferences,
    format_stats,
)

logger = logging.getLogger(__name__)


def _get_user_id(update: Update) -> str:
    """Extract and ensure user exists in DB."""
    user = update.effective_user
    return get_or_create_user(
        chat_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats — show aggregate stats by competency."""
    user_id = _get_user_id(update)
    data = await asyncio.to_thread(get_user_stats, user_id)
    streak_str = await asyncio.to_thread(get_user_state, user_id, "current_streak")
    longest_str = await asyncio.to_thread(get_user_state, user_id, "longest_streak")
    streak = int(streak_str) if streak_str else None
    longest = int(longest_str) if longest_str else None

    text = format_stats(data, streak=streak, longest_streak=longest)
    for part in _split_message(text):
        await update.message.reply_text(part, parse_mode="HTML")


async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /history — show recent attempt history."""
    user_id = _get_user_id(update)

    limit = 10
    if context.args and context.args[0].isdigit():
        limit = int(context.args[0])

    data = await asyncio.to_thread(get_user_history, user_id, limit)
    text = format_history(data)
    for part in _split_message(text):
        await update.message.reply_text(part, parse_mode="HTML")


async def competencies_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /competencies — list all competencies with levels."""
    user_id = _get_user_id(update)
    levels = await asyncio.to_thread(get_user_competency_levels, user_id)
    text = format_competencies(levels, COMPETENCY_SLUGS)
    for part in _split_message(text):
        await update.message.reply_text(part, parse_mode="HTML")


async def bookmarks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /bookmarks — list bookmarked questions."""
    user_id = _get_user_id(update)
    data = await asyncio.to_thread(get_user_bookmarks, user_id)
    text = format_bookmarks(data)
    for part in _split_message(text):
        await update.message.reply_text(part, parse_mode="HTML")


async def preferences_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /preferences — show current preferences."""
    user_id = _get_user_id(update)
    prefs = await asyncio.to_thread(get_user_preferences, user_id)
    if not prefs:
        await update.message.reply_text("No preferences set. Run /start to set up.")
        return
    text = format_preferences(prefs)
    await update.message.reply_text(text, parse_mode="HTML")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — show available commands."""
    text = (
        "<b>SWET Bot Commands</b>\n\n"
        "/start - Set up your profile (roles, languages, frameworks)\n"
        "/q - Get an adaptive question\n"
        "/session - Multi-question practice session\n"
        "/test - Run a level assessment\n"
        "/stats - View performance stats\n"
        "/history - View recent attempts\n"
        "/competencies - List all competency areas\n"
        "/bookmarks - View bookmarked questions\n"
        "/preferences - View current preferences\n"
        "/config - Edit preferences\n"
        "/help - Show this help message\n"
        "/cancel - Cancel current operation"
    )
    await update.message.reply_text(text, parse_mode="HTML")
