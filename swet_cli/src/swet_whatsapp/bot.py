"""WhatsApp bot entry point: Flask webhook for Twilio WhatsApp messages.

Receives incoming WhatsApp messages via Twilio webhook, routes them to
the appropriate handler, and responds via TwiML. For long responses that
exceed WhatsApp's message limit, uses Twilio REST client to send
additional messages.

Usage:
    SWET_WHATSAPP_ACCOUNT_SID=... SWET_WHATSAPP_AUTH_TOKEN=... \
    SWET_WHATSAPP_PHONE_NUMBER=whatsapp:+1234567890 python -m swet_whatsapp.bot
"""

import logging
import os

from flask import Flask, request
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from swet_whatsapp.config import get_whatsapp_config
from swet_whatsapp.db import (
    clear_user_conversation_state,
    get_or_create_user,
    get_user_preferences,
    get_user_state,
)
from swet_whatsapp.formatters import _split_message
from swet_whatsapp.handlers.assessment import (
    handle_assessment_cancel,
    handle_assessment_input,
    handle_test_command,
)
from swet_whatsapp.handlers.question import (
    handle_bookmark_command,
    handle_question_answer,
    handle_question_command,
)
from swet_whatsapp.handlers.session import (
    handle_session_command,
    handle_session_input,
    handle_session_stop,
)
from swet_whatsapp.handlers.setup import (
    handle_config_start,
    handle_setup_input,
    handle_setup_start,
)
from swet_whatsapp.handlers.stats import (
    handle_bookmarks,
    handle_competencies,
    handle_help,
    handle_history,
    handle_preferences,
    handle_stats,
)

logger = logging.getLogger(__name__)

app = Flask(__name__)


def _is_dev_mode() -> bool:
    """Check if running in development mode (skip signature validation)."""
    return os.environ.get("SWET_WHATSAPP_DEV", "").lower() in ("1", "true", "yes")


def _validate_twilio_signature(config) -> bool:
    """Validate that the incoming request is from Twilio.

    Returns True if valid or if in dev mode.
    """
    if _is_dev_mode():
        return True

    validator = RequestValidator(config.twilio_auth_token)
    url = request.url
    params = request.form.to_dict()
    signature = request.headers.get("X-Twilio-Signature", "")

    return validator.validate(url, params, signature)


def _send_response(config, user_phone: str, text: str) -> str:
    """Send response to user, handling message splitting.

    The first message part is returned as TwiML response body.
    Additional parts (if any) are sent via Twilio REST client.

    Returns the TwiML response XML string.
    """
    parts = _split_message(text)
    resp = MessagingResponse()

    if parts:
        # First part goes into TwiML response
        resp.message(parts[0])

        # Additional parts sent via REST client
        if len(parts) > 1:
            client = Client(config.twilio_account_sid, config.twilio_auth_token)
            for part in parts[1:]:
                try:
                    client.messages.create(
                        body=part,
                        from_=config.twilio_phone_number,
                        to=user_phone,
                    )
                except Exception:
                    logger.exception("Failed to send additional message part to %s", user_phone)

    return str(resp)


def _extract_command_and_args(text: str) -> tuple[str | None, str | None]:
    """Extract command and arguments from message text.

    Returns (command, args) where command is lowercase without the /
    prefix, or (None, None) if not a command.
    """
    text = text.strip()
    if not text.startswith("/"):
        return None, None

    parts = text.split(maxsplit=1)
    command = parts[0][1:].lower()  # remove / prefix
    args = parts[1] if len(parts) > 1 else None
    return command, args


def _route_message(user_id: str, text: str, display_name: str | None) -> str:
    """Route an incoming message to the appropriate handler.

    Returns the response text to send back to the user.
    """
    command, args = _extract_command_and_args(text)

    # --- Command routing (takes priority over conversation state) ---

    if command == "start":
        return handle_setup_start(user_id)

    if command == "config":
        return handle_config_start(user_id)

    if command in ("q", "question"):
        return handle_question_command(user_id)

    if command == "session":
        return handle_session_command(user_id, args)

    if command == "test":
        return handle_test_command(user_id)

    if command == "stats":
        return handle_stats(user_id)

    if command == "history":
        return handle_history(user_id, args)

    if command == "competencies":
        return handle_competencies(user_id)

    if command == "bookmarks":
        return handle_bookmarks(user_id)

    if command == "bookmark":
        return handle_bookmark_command(user_id)

    if command == "preferences":
        return handle_preferences(user_id)

    if command == "help":
        return handle_help()

    if command == "cancel":
        return _handle_cancel(user_id)

    if command == "stop":
        return _handle_stop(user_id)

    # --- Conversation state routing (for ongoing multi-step flows) ---

    conv_type = get_user_state(user_id, "conv:type")

    if conv_type == "setup":
        return handle_setup_input(user_id, text)

    if conv_type == "question":
        return handle_question_answer(user_id, text)

    if conv_type == "session":
        return handle_session_input(user_id, text)

    if conv_type == "assessment":
        return handle_assessment_input(user_id, text)

    # --- No active conversation and not a recognized command ---

    # Check if user has preferences set
    prefs = get_user_preferences(user_id)
    if not prefs:
        return "Welcome to SWET! Send /start to set up your profile, or /help to see all available commands."

    return "I didn't understand that. Send /help to see available commands, or /q to get a question."


def _handle_cancel(user_id: str) -> str:
    """Handle /cancel — cancel the current operation."""
    conv_type = get_user_state(user_id, "conv:type")

    if conv_type == "assessment":
        return handle_assessment_cancel(user_id)

    if conv_type == "session":
        return handle_session_stop(user_id)

    clear_user_conversation_state(user_id)
    if conv_type:
        return "Operation cancelled."
    return "Nothing to cancel."


def _handle_stop(user_id: str) -> str:
    """Handle /stop — stop the current session or operation."""
    conv_type = get_user_state(user_id, "conv:type")

    if conv_type == "session":
        return handle_session_stop(user_id)

    if conv_type == "assessment":
        return handle_assessment_cancel(user_id)

    clear_user_conversation_state(user_id)
    if conv_type:
        return "Operation stopped."
    return "Nothing to stop."


@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming WhatsApp messages from Twilio."""
    config = get_whatsapp_config()

    # Validate Twilio signature
    if not _validate_twilio_signature(config):
        logger.warning("Invalid Twilio signature — rejecting request")
        return "Forbidden", 403

    # Extract message data
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "").strip()
    profile_name = request.form.get("ProfileName")

    if not from_number or not body:
        resp = MessagingResponse()
        return str(resp)

    logger.info("Message from %s: %s", from_number, body[:50])

    # Get or create user (phone number used directly as user_id)
    user_id = get_or_create_user(from_number, display_name=profile_name)

    try:
        response_text = _route_message(user_id, body, profile_name)
    except Exception:
        logger.exception("Error handling message from %s", from_number)
        response_text = "An error occurred. Please try again or send /help."

    return _send_response(config, from_number, response_text), 200, {"Content-Type": "text/xml"}


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return {"status": "ok"}, 200


def main() -> None:
    """Start the Flask webhook server."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    config = get_whatsapp_config()
    logger.info(
        "SWET WhatsApp bot starting on %s:%d...",
        config.webhook_host,
        config.webhook_port,
    )
    app.run(
        host=config.webhook_host,
        port=config.webhook_port,
        debug=_is_dev_mode(),
    )


if __name__ == "__main__":
    main()
