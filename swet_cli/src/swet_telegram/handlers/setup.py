"""Setup handler: /start and /config commands for user onboarding.

Uses ConversationHandler to walk users through role, language, framework,
format, and length selection using inline keyboard toggles.
"""

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from swet_cli.data import (
    QUESTION_FORMATS,
    ROLES,
    get_frameworks_for_roles,
    get_languages_for_roles,
)
from swet_telegram.db import (
    get_or_create_user,
    get_user_preferences,
    save_user_preferences,
)
from swet_telegram.formatters import format_preferences
from swet_telegram.keyboards import (
    confirm_keyboard,
    formats_keyboard,
    frameworks_keyboard,
    languages_keyboard,
    length_keyboard,
    roles_keyboard,
)

logger = logging.getLogger(__name__)

# Conversation states
SELECT_ROLES, SELECT_LANGUAGES, SELECT_FRAMEWORKS, SELECT_FORMATS, SELECT_LENGTH, CONFIRM_ASSESSMENT = range(6)


def _get_user_id(update: Update) -> str:
    """Extract and ensure user exists in DB."""
    user = update.effective_user
    return get_or_create_user(
        chat_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — begin the setup flow."""
    user_id = _get_user_id(update)
    prefs = get_user_preferences(user_id)

    if prefs:
        await update.message.reply_text(
            "Welcome back! You already have preferences set.\n"
            "Use /config to edit them, /q for a question, or /help for all commands.",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # Initialize setup state
    context.user_data["setup_roles"] = set()
    context.user_data["setup_languages"] = set()
    context.user_data["setup_frameworks"] = set()
    context.user_data["setup_formats"] = set()

    await update.message.reply_text(
        "<b>Welcome to SWET!</b>\n\n"
        "Let's set up your profile. First, select your engineering roles.\n"
        "Tap to toggle, then tap <b>Done</b> when finished.",
        reply_markup=roles_keyboard(ROLES, set()),
        parse_mode="HTML",
    )
    return SELECT_ROLES


async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /config — edit existing preferences."""
    user_id = _get_user_id(update)
    prefs = get_user_preferences(user_id)

    if not prefs:
        # No preferences yet, redirect to /start flow
        context.user_data["setup_roles"] = set()
        context.user_data["setup_languages"] = set()
        context.user_data["setup_frameworks"] = set()
        context.user_data["setup_formats"] = set()

        await update.message.reply_text(
            "No preferences set yet. Let's set up your profile.\nSelect your engineering roles:",
            reply_markup=roles_keyboard(ROLES, set()),
            parse_mode="HTML",
        )
        return SELECT_ROLES

    # Pre-fill from existing preferences
    context.user_data["setup_roles"] = set(prefs["roles"])
    context.user_data["setup_languages"] = set(prefs["languages"])
    context.user_data["setup_frameworks"] = set(prefs["frameworks"])
    context.user_data["setup_formats"] = set(prefs.get("preferred_formats") or [])
    context.user_data["setup_length"] = prefs.get("question_length", "standard")

    await update.message.reply_text(
        "<b>Edit Preferences</b>\n\nSelect your engineering roles:",
        reply_markup=roles_keyboard(ROLES, context.user_data["setup_roles"]),
        parse_mode="HTML",
    )
    return SELECT_ROLES


async def handle_role_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle role toggle buttons."""
    query = update.callback_query
    await query.answer()

    data = query.data
    selected = context.user_data.get("setup_roles", set())

    if data == "role:done":
        if not selected:
            await query.answer("Please select at least one role.", show_alert=True)
            return SELECT_ROLES

        # Move to language selection
        roles_list = sorted(selected)
        available_langs = sorted(set(get_languages_for_roles(roles_list)))
        context.user_data["available_languages"] = available_langs

        await query.edit_message_text(
            "Select your programming languages:",
            reply_markup=languages_keyboard(available_langs, context.user_data.get("setup_languages", set())),
            parse_mode="HTML",
        )
        return SELECT_LANGUAGES

    # Toggle role
    role = data.replace("role:", "")
    if role in selected:
        selected.discard(role)
    else:
        selected.add(role)
    context.user_data["setup_roles"] = selected

    await query.edit_message_reply_markup(
        reply_markup=roles_keyboard(ROLES, selected),
    )
    return SELECT_ROLES


async def handle_language_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle language toggle buttons."""
    query = update.callback_query
    await query.answer()

    data = query.data
    selected = context.user_data.get("setup_languages", set())

    if data in ("lang:done", "lang:skip"):
        if data == "lang:skip":
            selected = set()
            context.user_data["setup_languages"] = selected

        # Move to framework selection
        roles_list = sorted(context.user_data["setup_roles"])
        langs_list = sorted(selected)
        available_fws = sorted(set(get_frameworks_for_roles(roles_list, languages=langs_list)))
        context.user_data["available_frameworks"] = available_fws

        if not available_fws:
            # Skip frameworks, go to formats
            await query.edit_message_text(
                "Select your preferred question types\n(all selected = no preference):",
                reply_markup=formats_keyboard(context.user_data.get("setup_formats", set())),
                parse_mode="HTML",
            )
            return SELECT_FORMATS

        await query.edit_message_text(
            "Select your frameworks and tools:",
            reply_markup=frameworks_keyboard(available_fws, context.user_data.get("setup_frameworks", set())),
            parse_mode="HTML",
        )
        return SELECT_FRAMEWORKS

    # Toggle language
    lang = data.replace("lang:", "")
    if lang in selected:
        selected.discard(lang)
    else:
        selected.add(lang)
    context.user_data["setup_languages"] = selected

    available = context.user_data.get("available_languages", [])
    await query.edit_message_reply_markup(
        reply_markup=languages_keyboard(available, selected),
    )
    return SELECT_LANGUAGES


async def handle_framework_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle framework toggle buttons."""
    query = update.callback_query
    await query.answer()

    data = query.data
    selected = context.user_data.get("setup_frameworks", set())

    if data in ("fw:done", "fw:skip"):
        if data == "fw:skip":
            selected = set()
            context.user_data["setup_frameworks"] = selected

        # Move to format selection
        await query.edit_message_text(
            "Select your preferred question types\n(all selected = no preference):",
            reply_markup=formats_keyboard(context.user_data.get("setup_formats", set())),
            parse_mode="HTML",
        )
        return SELECT_FORMATS

    # Toggle framework
    fw = data.replace("fw:", "")
    if fw in selected:
        selected.discard(fw)
    else:
        selected.add(fw)
    context.user_data["setup_frameworks"] = selected

    available = context.user_data.get("available_frameworks", [])
    await query.edit_message_reply_markup(
        reply_markup=frameworks_keyboard(available, selected),
    )
    return SELECT_FRAMEWORKS


async def handle_format_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle format preference toggle buttons."""
    query = update.callback_query
    await query.answer()

    data = query.data
    selected = context.user_data.get("setup_formats", set())

    if data == "fmt:done":
        # Move to length selection
        current_length = context.user_data.get("setup_length", "standard")
        await query.edit_message_text(
            "Preferred question length:",
            reply_markup=length_keyboard(current_length),
            parse_mode="HTML",
        )
        return SELECT_LENGTH

    # Toggle format
    fmt = data.replace("fmt:", "")
    if fmt in selected:
        selected.discard(fmt)
    else:
        selected.add(fmt)
    context.user_data["setup_formats"] = selected

    await query.edit_message_reply_markup(
        reply_markup=formats_keyboard(selected),
    )
    return SELECT_FORMATS


async def handle_length_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle length selection — final step, save preferences."""
    query = update.callback_query
    await query.answer()

    length = query.data.replace("len:", "")
    context.user_data["setup_length"] = length

    # Save preferences
    user_id = _get_user_id(update)
    roles = sorted(context.user_data["setup_roles"])
    languages = sorted(context.user_data.get("setup_languages", set()))
    frameworks = sorted(context.user_data.get("setup_frameworks", set()))
    selected_formats = context.user_data.get("setup_formats", set())

    # If all formats selected or none, treat as no preference
    preferred_formats = sorted(selected_formats) if 0 < len(selected_formats) < len(QUESTION_FORMATS) else None

    await asyncio.to_thread(
        save_user_preferences,
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

    await query.edit_message_text(
        f"Preferences saved!\n\n{format_preferences(prefs)}\n\n"
        "Would you like to run a level assessment now?\n"
        "(Recommended for accurate difficulty adaptation)",
        reply_markup=confirm_keyboard("confirm:assess_yes", "confirm:assess_no"),
        parse_mode="HTML",
    )
    return CONFIRM_ASSESSMENT


async def handle_assessment_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle yes/no for running assessment after setup."""
    query = update.callback_query
    await query.answer()

    if query.data == "confirm:assess_yes":
        await query.edit_message_text(
            "Starting level assessment...\nUse /test to begin.",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text(
            "Setup complete! Use /q to get your first question.",
            parse_mode="HTML",
        )

    # Clean up setup state
    for key in (
        "setup_roles",
        "setup_languages",
        "setup_frameworks",
        "setup_formats",
        "setup_length",
        "available_languages",
        "available_frameworks",
    ):
        context.user_data.pop(key, None)

    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel during setup."""
    # Clean up setup state
    for key in (
        "setup_roles",
        "setup_languages",
        "setup_frameworks",
        "setup_formats",
        "setup_length",
        "available_languages",
        "available_frameworks",
    ):
        context.user_data.pop(key, None)

    await update.message.reply_text("Setup cancelled.")
    return ConversationHandler.END


def setup_conversation_handler() -> ConversationHandler:
    """Build the ConversationHandler for /start and /config."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("config", config_command),
        ],
        states={
            SELECT_ROLES: [CallbackQueryHandler(handle_role_toggle, pattern=r"^role:")],
            SELECT_LANGUAGES: [CallbackQueryHandler(handle_language_toggle, pattern=r"^lang:")],
            SELECT_FRAMEWORKS: [CallbackQueryHandler(handle_framework_toggle, pattern=r"^fw:")],
            SELECT_FORMATS: [CallbackQueryHandler(handle_format_toggle, pattern=r"^fmt:")],
            SELECT_LENGTH: [CallbackQueryHandler(handle_length_select, pattern=r"^len:")],
            CONFIRM_ASSESSMENT: [CallbackQueryHandler(handle_assessment_confirm, pattern=r"^confirm:assess_")],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        per_user=True,
        per_chat=True,
    )
