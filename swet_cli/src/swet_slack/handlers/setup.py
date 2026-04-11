"""Setup handler: /swet-setup and /swet-config commands for user onboarding.

Tracks setup state via the DB state table (no ConversationHandler in Slack).
Each step reads state, processes the action, writes updated state, and
updates the message with new Block Kit blocks.
"""

import json
import logging

from swet_cli.data import (
    QUESTION_FORMATS,
    ROLES,
    get_frameworks_for_roles,
    get_languages_for_roles,
)
from swet_slack.blocks import (
    confirm_blocks,
    formats_blocks,
    frameworks_blocks,
    languages_blocks,
    length_blocks,
    roles_blocks,
)
from swet_slack.db import (
    clear_user_state,
    get_or_create_user,
    get_user_preferences,
    get_user_state,
    save_user_preferences,
    set_user_state,
)
from swet_slack.formatters import format_preferences

logger = logging.getLogger(__name__)


def _get_user_id(user_id: str, username: str | None = None, display_name: str | None = None) -> str:
    """Ensure user exists in DB and return user_id."""
    return get_or_create_user(user_id=user_id, username=username, display_name=display_name)


def register_setup_handlers(app) -> None:
    """Register all setup-related slash commands and action handlers."""

    @app.command("/swet-setup")
    def handle_setup(ack, command, respond, client):
        """Handle /swet-setup — begin the setup flow."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        prefs = get_user_preferences(user_id)

        if prefs:
            respond(
                text="Welcome back! You already have preferences set.\n"
                "Use `/swet-config` to edit them, `/swet-q` for a question, or `/swet-help` for all commands.",
            )
            return

        # Initialize setup state
        set_user_state(user_id, "setup:step", "roles")
        set_user_state(user_id, "setup:roles", json.dumps([]))
        set_user_state(user_id, "setup:languages", json.dumps([]))
        set_user_state(user_id, "setup:frameworks", json.dumps([]))
        set_user_state(user_id, "setup:formats", json.dumps([]))
        set_user_state(user_id, "setup:length", "standard")

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Welcome to SWET!*\n\n"
                        "Let's set up your profile. First, select your engineering roles.\n"
                        "Tap to toggle, then tap *Done* when finished."
                    ),
                },
            },
            *roles_blocks(ROLES, set()),
        ]
        respond(blocks=blocks, text="Welcome to SWET! Select your engineering roles.")

    @app.command("/swet-config")
    def handle_config(ack, command, respond, client):
        """Handle /swet-config — edit existing preferences."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        prefs = get_user_preferences(user_id)

        if not prefs:
            # No preferences yet, redirect to setup
            set_user_state(user_id, "setup:step", "roles")
            set_user_state(user_id, "setup:roles", json.dumps([]))
            set_user_state(user_id, "setup:languages", json.dumps([]))
            set_user_state(user_id, "setup:frameworks", json.dumps([]))
            set_user_state(user_id, "setup:formats", json.dumps([]))
            set_user_state(user_id, "setup:length", "standard")

            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ("No preferences set yet. Let's set up your profile.\nSelect your engineering roles:"),
                    },
                },
                *roles_blocks(ROLES, set()),
            ]
            respond(blocks=blocks, text="Select your engineering roles.")
            return

        # Pre-fill from existing preferences
        set_user_state(user_id, "setup:step", "roles")
        set_user_state(user_id, "setup:roles", json.dumps(prefs["roles"]))
        set_user_state(user_id, "setup:languages", json.dumps(prefs["languages"]))
        set_user_state(user_id, "setup:frameworks", json.dumps(prefs["frameworks"]))
        set_user_state(user_id, "setup:formats", json.dumps(prefs.get("preferred_formats") or []))
        set_user_state(user_id, "setup:length", prefs.get("question_length", "standard"))

        selected = set(prefs["roles"])
        header_text = "*Edit Preferences*\n\nSelect your engineering roles:"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
            *roles_blocks(ROLES, selected),
        ]
        respond(blocks=blocks, text="Edit preferences: select your engineering roles.")

    @app.action("role_done")
    def handle_role_done(ack, body, respond, client):
        """Handle Done button after role selection — move to languages."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        selected_json = get_user_state(user_id, "setup:roles")
        selected = set(json.loads(selected_json)) if selected_json else set()

        if not selected:
            respond(text="Please select at least one role.", replace_original=False)
            return

        # Move to language selection
        roles_list = sorted(selected)
        available_langs = sorted(set(get_languages_for_roles(roles_list)))
        set_user_state(user_id, "setup:step", "languages")
        set_user_state(user_id, "setup:available_languages", json.dumps(available_langs))

        existing_langs_json = get_user_state(user_id, "setup:languages")
        existing_langs = set(json.loads(existing_langs_json)) if existing_langs_json else set()

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Select your programming languages:"}},
            *languages_blocks(available_langs, existing_langs),
        ]
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=blocks,
            text="Select your programming languages.",
        )

    @app.action("lang_done")
    def handle_lang_done(ack, body, client):
        """Handle Done button after language selection — move to frameworks."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))

        selected_json = get_user_state(user_id, "setup:languages")
        selected = set(json.loads(selected_json)) if selected_json else set()
        roles_json = get_user_state(user_id, "setup:roles")
        roles_list = sorted(json.loads(roles_json)) if roles_json else []
        langs_list = sorted(selected)

        available_fws = sorted(set(get_frameworks_for_roles(roles_list, languages=langs_list)))
        set_user_state(user_id, "setup:step", "frameworks")
        set_user_state(user_id, "setup:available_frameworks", json.dumps(available_fws))

        if not available_fws:
            # Skip frameworks, go to formats
            set_user_state(user_id, "setup:step", "formats")
            existing_fmts_json = get_user_state(user_id, "setup:formats")
            existing_fmts = set(json.loads(existing_fmts_json)) if existing_fmts_json else set()

            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ("Select your preferred question types\n(all selected = no preference):"),
                    },
                },
                *formats_blocks(existing_fmts),
            ]
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                blocks=blocks,
                text="Select your preferred question types.",
            )
            return

        existing_fws_json = get_user_state(user_id, "setup:frameworks")
        existing_fws = set(json.loads(existing_fws_json)) if existing_fws_json else set()

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Select your frameworks and tools:"}},
            *frameworks_blocks(available_fws, existing_fws),
        ]
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=blocks,
            text="Select your frameworks and tools.",
        )

    @app.action("lang_skip")
    def handle_lang_skip(ack, body, client):
        """Handle Skip button for language selection."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        set_user_state(user_id, "setup:languages", json.dumps([]))

        # Proceed same as lang_done with empty selection
        roles_json = get_user_state(user_id, "setup:roles")
        roles_list = sorted(json.loads(roles_json)) if roles_json else []

        available_fws = sorted(set(get_frameworks_for_roles(roles_list, languages=[])))
        set_user_state(user_id, "setup:step", "frameworks")
        set_user_state(user_id, "setup:available_frameworks", json.dumps(available_fws))

        if not available_fws:
            set_user_state(user_id, "setup:step", "formats")
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ("Select your preferred question types\n(all selected = no preference):"),
                    },
                },
                *formats_blocks(set()),
            ]
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                blocks=blocks,
                text="Select your preferred question types.",
            )
            return

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Select your frameworks and tools:"}},
            *frameworks_blocks(available_fws, set()),
        ]
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=blocks,
            text="Select your frameworks and tools.",
        )

    @app.action("fw_done")
    def handle_fw_done(ack, body, client):
        """Handle Done button after framework selection — move to formats."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        set_user_state(user_id, "setup:step", "formats")

        existing_fmts_json = get_user_state(user_id, "setup:formats")
        existing_fmts = set(json.loads(existing_fmts_json)) if existing_fmts_json else set()

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ("Select your preferred question types\n(all selected = no preference):"),
                },
            },
            *formats_blocks(existing_fmts),
        ]
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=blocks,
            text="Select your preferred question types.",
        )

    @app.action("fw_skip")
    def handle_fw_skip(ack, body, client):
        """Handle Skip button for framework selection."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        set_user_state(user_id, "setup:frameworks", json.dumps([]))
        set_user_state(user_id, "setup:step", "formats")

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ("Select your preferred question types\n(all selected = no preference):"),
                },
            },
            *formats_blocks(set()),
        ]
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=blocks,
            text="Select your preferred question types.",
        )

    @app.action("fmt_done")
    def handle_fmt_done(ack, body, client):
        """Handle Done button after format selection — move to length."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        set_user_state(user_id, "setup:step", "length")

        current_length = get_user_state(user_id, "setup:length") or "standard"

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Preferred question length:"}},
            *length_blocks(current_length),
        ]
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=blocks,
            text="Select preferred question length.",
        )

    @app.action("confirm_assess_yes")
    def handle_assess_yes(ack, body, client):
        """Handle yes for running assessment after setup."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        clear_user_state(user_id, "setup:")

        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": ("Starting level assessment...\nUse `/swet-test` to begin.")},
                }
            ],
            text="Starting level assessment. Use /swet-test to begin.",
        )

    @app.action("confirm_assess_no")
    def handle_assess_no(ack, body, client):
        """Handle no for running assessment after setup."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        clear_user_state(user_id, "setup:")

        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": ("Setup complete! Use `/swet-q` to get your first question.")},
                }
            ],
            text="Setup complete! Use /swet-q to get your first question.",
        )

    def _register_toggle_action(action_prefix: str, state_key: str):
        """Register a generic toggle action for role/lang/fw/fmt buttons."""

        @app.action({"action_id": f"^{action_prefix}_(?!done$|skip$).*$", "type": "button"})
        def handle_toggle(ack, body, client, action):
            ack()
            user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))

            # Read current selection from DB
            current_json = get_user_state(user_id, state_key)
            current = set(json.loads(current_json)) if current_json else set()

            # Toggle the value
            value = action["value"]
            if value in current:
                current.discard(value)
            else:
                current.add(value)

            # Save back
            set_user_state(user_id, state_key, json.dumps(sorted(current)))

            # Rebuild the blocks for the current step
            step = get_user_state(user_id, "setup:step")
            blocks: list[dict] = []

            if step == "roles":
                blocks = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "Select your engineering roles:"}},
                    *roles_blocks(ROLES, current),
                ]
            elif step == "languages":
                available_json = get_user_state(user_id, "setup:available_languages")
                available = json.loads(available_json) if available_json else []
                blocks = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "Select your programming languages:"}},
                    *languages_blocks(available, current),
                ]
            elif step == "frameworks":
                available_json = get_user_state(user_id, "setup:available_frameworks")
                available = json.loads(available_json) if available_json else []
                blocks = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "Select your frameworks and tools:"}},
                    *frameworks_blocks(available, current),
                ]
            elif step == "formats":
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": ("Select your preferred question types\n(all selected = no preference):"),
                        },
                    },
                    *formats_blocks(current),
                ]

            if blocks:
                client.chat_update(
                    channel=body["channel"]["id"],
                    ts=body["message"]["ts"],
                    blocks=blocks,
                    text="Select options.",
                )

    # Register toggle handlers for each setup step
    _register_toggle_action("role", "setup:roles")
    _register_toggle_action("lang", "setup:languages")
    _register_toggle_action("fw", "setup:frameworks")
    _register_toggle_action("fmt", "setup:formats")

    def _register_length_actions():
        """Register length selection action handlers."""
        for length_value in ("concise", "standard", "detailed"):

            @app.action(f"len_{length_value}")
            def handle_length(ack, body, client, action):
                """Handle length selection — final step, save preferences."""
                ack()
                user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))

                length = action["value"]
                set_user_state(user_id, "setup:length", length)

                # Save preferences
                roles_json = get_user_state(user_id, "setup:roles")
                roles = sorted(json.loads(roles_json)) if roles_json else []

                langs_json = get_user_state(user_id, "setup:languages")
                languages = sorted(json.loads(langs_json)) if langs_json else []

                fws_json = get_user_state(user_id, "setup:frameworks")
                frameworks = sorted(json.loads(fws_json)) if fws_json else []

                fmts_json = get_user_state(user_id, "setup:formats")
                selected_formats = set(json.loads(fmts_json)) if fmts_json else set()

                # If all formats selected or none, treat as no preference
                preferred_formats = (
                    sorted(selected_formats) if 0 < len(selected_formats) < len(QUESTION_FORMATS) else None
                )

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

                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"Preferences saved!\n\n{format_preferences(prefs)}\n\n"
                                "Would you like to run a level assessment now?\n"
                                "(Recommended for accurate difficulty adaptation)"
                            ),
                        },
                    },
                    *confirm_blocks("confirm_assess_yes", "confirm_assess_no"),
                ]
                client.chat_update(
                    channel=body["channel"]["id"],
                    ts=body["message"]["ts"],
                    blocks=blocks,
                    text="Preferences saved! Would you like to run a level assessment?",
                )

    _register_length_actions()
