"""Telegram bot entry point: builds the Application and starts polling.

Usage:
    SWET_TELEGRAM_BOT_TOKEN=your_token python -m swet_telegram.bot
"""

import logging

from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler

from swet_telegram.config import get_telegram_config
from swet_telegram.handlers.assessment import assessment_conversation_handler
from swet_telegram.handlers.question import (
    handle_bookmark_callback,
    handle_mcq_answer,
    handle_next_question,
    question_conversation_handler,
)
from swet_telegram.handlers.session import session_conversation_handler
from swet_telegram.handlers.setup import setup_conversation_handler
from swet_telegram.handlers.stats import (
    bookmarks_handler,
    competencies_handler,
    help_handler,
    history_handler,
    preferences_handler,
    stats_handler,
)

logger = logging.getLogger(__name__)


async def error_handler(update, context) -> None:
    """Log errors and notify the user."""
    logger.error("Update %s caused error: %s", update, context.error, exc_info=context.error)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "An error occurred. Please try again or use /help.",
            )
        except Exception:
            pass


def main() -> None:
    """Build the bot application and start polling."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    config = get_telegram_config()
    app = ApplicationBuilder().token(config.bot_token).build()

    # ConversationHandlers (order matters — first match wins)
    app.add_handler(setup_conversation_handler())
    app.add_handler(assessment_conversation_handler())
    app.add_handler(session_conversation_handler())
    app.add_handler(question_conversation_handler())

    # Standalone MCQ callback handler (for questions outside ConversationHandler)
    app.add_handler(CallbackQueryHandler(handle_mcq_answer, pattern=r"^mcq:"))
    app.add_handler(CallbackQueryHandler(handle_bookmark_callback, pattern=r"^bookmark:"))
    app.add_handler(CallbackQueryHandler(handle_next_question, pattern=r"^next_q$"))

    # Simple command handlers
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("history", history_handler))
    app.add_handler(CommandHandler("competencies", competencies_handler))
    app.add_handler(CommandHandler("bookmarks", bookmarks_handler))
    app.add_handler(CommandHandler("preferences", preferences_handler))
    app.add_handler(CommandHandler("help", help_handler))

    # Error handler
    app.add_error_handler(error_handler)

    logger.info("SWET Telegram bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
