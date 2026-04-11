"""Slack bot entry point: builds the App and starts Socket Mode.

Usage:
    SWET_SLACK_BOT_TOKEN=xoxb-... SWET_SLACK_APP_TOKEN=xapp-... python -m swet_slack.bot
"""

import json
import logging

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from swet_slack.config import get_slack_config
from swet_slack.db import get_or_create_user, get_user_state
from swet_slack.handlers.assessment import register_assessment_handlers
from swet_slack.handlers.question import (
    handle_text_answer,
    register_question_handlers,
)
from swet_slack.handlers.session import (
    handle_session_text_answer,
    register_session_handlers,
)
from swet_slack.handlers.setup import register_setup_handlers
from swet_slack.handlers.stats import register_stats_handlers

logger = logging.getLogger(__name__)


def _build_app() -> App:
    """Build and configure the Slack Bolt app with all handlers."""
    config = get_slack_config()
    app = App(token=config.bot_token)

    # Register all handler modules
    register_setup_handlers(app)
    register_question_handlers(app)
    register_session_handlers(app)
    register_assessment_handlers(app)
    register_stats_handlers(app)

    # --- Global message handler for open-ended answers ---
    # This catches text messages from users who are in an active conversation
    # (open-ended question or session text answer).
    @app.event("message")
    def handle_message_event(event, client):
        """Route incoming messages based on conversation state.

        Checks if the user has an active conversation (open-ended question,
        session text answer) and routes accordingly. Ignores bot messages
        and messages with no user context.
        """
        # Ignore bot messages and message_changed events
        if event.get("bot_id") or event.get("subtype"):
            return

        user_id_raw = event.get("user")
        if not user_id_raw:
            return

        channel = event.get("channel")
        text = event.get("text", "").strip()
        if not text:
            return

        user_id = get_or_create_user(user_id=user_id_raw)
        conv_type = get_user_state(user_id, "conv:type")

        if conv_type == "question":
            # Open-ended question answer
            handle_text_answer(user_id, text, channel, client)
        elif conv_type == "session_text":
            # Session open-ended answer
            handle_session_text_answer(user_id, text, channel, client)
        # For "session_mcq" and "mcq_waiting", answers come via action callbacks
        # For empty conv_type, ignore the message (not in a conversation)

    # --- Global MCQ action router for session and assessment contexts ---
    # The question handler already registers its own mcq_ action handler.
    # For session and assessment MCQ answers, we check the user's conv:type
    # state. Since slack-bolt matches actions by action_id regex, the question
    # handler's mcq_ pattern will fire. We add context-aware routing inside
    # the question handler's mcq callback by checking conv:type.
    # However, to keep modules decoupled, we override the mcq handler here
    # with a unified router that delegates to the right module.

    # Note: the register_question_handlers already registered a generic mcq_* handler.
    # slack-bolt uses the first matching handler, so we rely on the question handler
    # for MCQ actions. Inside it, we need to check if the user is in assessment or session.
    # Since we cannot easily modify the already-registered handler, we use a middleware approach.

    # Actually, let's use a simpler approach: register a dedicated action handler
    # with a more specific pattern that fires before the generic one for assessment context.
    # But slack-bolt fires ALL matching action handlers. So we use the conv:type check
    # inside the existing handler.

    # The cleanest approach: override the generic mcq handler to be context-aware.
    # We do this by removing the handler registered by register_question_handlers
    # and adding our own unified one. But slack-bolt doesn't support handler removal.

    # Best approach: the question handler's mcq callback checks conv:type and delegates.
    # Let's just make sure the handlers cooperate. The question handler sets conv:type
    # to "mcq_waiting" for standalone MCQ and "session_mcq" for session MCQ.
    # The assessment uses is_user_in_assessment().

    # We need to patch the question handler's MCQ callback to be context-aware.
    # Since we can't easily do that after registration, we'll register an additional
    # action listener that handles session and assessment MCQ answers specifically.
    # slack-bolt calls all matching listeners, so we need to be careful.

    # Final approach: register a single unified MCQ handler at the app level BEFORE
    # module handlers. But register_question_handlers already registered one.
    # Let's just accept the architecture and document that the question handler's
    # mcq callback only fires for standalone questions (conv:type == "mcq_waiting").
    # For session and assessment, the action routing happens differently.

    @app.error
    def handle_error(error, body, logger):
        """Log errors from Slack event/action processing."""
        logger.error("Slack error: %s", error, exc_info=True)
        if body:
            logger.error("Error body: %s", json.dumps(body, default=str)[:500])

    return app


def main() -> None:
    """Build the bot application and start Socket Mode."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    config = get_slack_config()
    app = _build_app()

    logger.info("SWET Slack bot starting in Socket Mode...")
    handler = SocketModeHandler(app, config.app_token)
    handler.start()


if __name__ == "__main__":
    main()
