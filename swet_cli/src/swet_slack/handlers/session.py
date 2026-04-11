"""Session handler: /swet-session command for multi-question practice sessions.

Runs a configurable number of questions in sequence, tracking results
and displaying a summary at the end. All state tracked in DB.
"""

import json
import logging
import time

from swet_cli.generator import generate_questions
from swet_cli.grader import grade_mcq, grade_open_ended
from swet_slack.blocks import mcq_blocks, session_count_blocks
from swet_slack.db import (
    get_or_create_user,
    get_user_preferences,
    get_user_queued_question,
    get_user_recent_question_topics,
    get_user_state,
    save_user_attempt,
    save_user_question,
    set_user_state,
    update_user_format_performance,
    update_user_streak,
)
from swet_slack.engine import (
    adapt_difficulty,
    pick_competency,
    pick_format,
    should_generate_new,
    update_adaptive_level,
)
from swet_slack.formatters import (
    format_grade,
    format_question,
    format_session_summary,
)

logger = logging.getLogger(__name__)


def _get_user_id(user_id: str, username: str | None = None) -> str:
    """Ensure user exists in DB and return user_id."""
    return get_or_create_user(user_id=user_id, username=username)


def _serve_next_session_question(user_id: str, channel: str, client) -> None:
    """Serve the next question in the session."""
    current_str = get_user_state(user_id, "session:current")
    total_str = get_user_state(user_id, "session:count")
    current = int(current_str) if current_str else 0
    total = int(total_str) if total_str else 0

    if current >= total:
        _end_session(user_id, channel, client)
        return

    # Increment counter
    set_user_state(user_id, "session:current", str(current + 1))

    prefs_json = get_user_state(user_id, "session:prefs")
    prefs = json.loads(prefs_json) if prefs_json else None
    if not prefs:
        client.chat_postMessage(channel=channel, text="Session error: no preferences found.")
        return

    client.chat_postMessage(
        channel=channel,
        text=f"*Question {current + 1}/{total}*",
    )

    # Pick competency, format, difficulty
    comp = pick_competency(user_id, prefs["roles"], prefs["difficulty"])
    q_format = pick_format(user_id, comp.slug, prefs["difficulty"], prefs.get("preferred_formats"))
    diff = adapt_difficulty(user_id, comp.slug, prefs["difficulty"])

    # Check DB or generate
    needs_generation = should_generate_new(user_id, comp.slug, q_format, diff)
    question_data = None

    if not needs_generation:
        question_data = get_user_queued_question(user_id, comp.slug, q_format, diff)

    if question_data is None:
        client.chat_postMessage(channel=channel, text=f"Generating for {comp.name}...")
        recent_topics = get_user_recent_question_topics(user_id, 20)

        question_models = generate_questions(
            competency=comp,
            difficulty=diff,
            question_format=q_format,
            roles=prefs["roles"],
            languages=prefs["languages"],
            frameworks=prefs["frameworks"],
            recent_topics=recent_topics,
            question_length=prefs.get("question_length", "standard"),
        )

        for qm in question_models:
            q_data = {
                "competency_slug": comp.slug,
                "format": q_format,
                "difficulty": diff,
                **qm.model_dump(),
            }
            save_user_question(user_id, q_data)

        question_data = get_user_queued_question(user_id, comp.slug, q_format, diff)
        if question_data is None:
            client.chat_postMessage(channel=channel, text="Failed to generate. Skipping...")
            _serve_next_session_question(user_id, channel, client)
            return

    # Store current session question in state
    set_user_state(user_id, "session:question", json.dumps(question_data))
    set_user_state(user_id, "session:answer_start", str(time.monotonic()))

    # Send question
    parts = format_question(question_data)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and question_data["format"] == "mcq" and question_data.get("options"):
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": part}},
                *mcq_blocks(question_data["options"], question_data["id"]),
            ]
            client.chat_postMessage(channel=channel, blocks=blocks, text=part)
        else:
            client.chat_postMessage(channel=channel, text=part)

    # Set conversation type so message handler knows context
    if question_data["format"] == "mcq":
        set_user_state(user_id, "conv:type", "session_mcq")
    else:
        set_user_state(user_id, "conv:type", "session_text")


def _grade_and_record(user_id: str, answer_text: str, is_mcq: bool, channel: str, client) -> None:
    """Grade an answer, record it, and move to the next question."""
    question_json = get_user_state(user_id, "session:question")
    if not question_json:
        client.chat_postMessage(channel=channel, text="Session error: no active question.")
        return

    question_data = json.loads(question_json)

    # Calculate elapsed time
    elapsed = None
    start_str = get_user_state(user_id, "session:answer_start")
    if start_str:
        try:
            elapsed = time.monotonic() - float(start_str)
        except ValueError:
            pass

    # Grade
    if is_mcq:
        grade = grade_mcq(answer_text, question_data["correct_answer"])
    else:
        grading_msg = client.chat_postMessage(channel=channel, text="Grading...")
        grade = grade_open_ended(
            question_title=question_data["title"],
            question_body=question_data["body"],
            question_format=question_data["format"],
            rubric=question_data["grading_rubric"],
            answer_text=answer_text,
            code_snippet=question_data.get("code_snippet"),
        )
        try:
            client.chat_delete(channel=channel, ts=grading_msg["ts"])
        except Exception:
            pass

    # Save attempt
    save_user_attempt(
        user_id=user_id,
        question_id=question_data["id"],
        answer_text=answer_text,
        score=grade.normalized_score,
        max_score=grade.max_score,
        total_score=grade.total_score,
        grade_details=grade.model_dump(),
        feedback=grade.overall_feedback,
        time_seconds=elapsed,
    )

    # Update adaptive level
    update_adaptive_level(
        user_id,
        question_data["competency_slug"],
        grade.normalized_score,
        question_data["difficulty"],
    )
    update_user_format_performance(
        user_id,
        question_data["competency_slug"],
        question_data["format"],
        grade.normalized_score,
    )

    # Show brief result
    response = format_grade(grade, question_data, elapsed)
    client.chat_postMessage(channel=channel, text=response)

    # Track session result
    results_json = get_user_state(user_id, "session:results")
    results = json.loads(results_json) if results_json else []
    results.append(
        {
            "question": question_data,
            "score": grade.normalized_score,
            "time_seconds": elapsed,
        }
    )
    set_user_state(user_id, "session:results", json.dumps(results))

    # Next question
    _serve_next_session_question(user_id, channel, client)


def _end_session(user_id: str, channel: str, client) -> None:
    """End the session and show summary."""
    results_json = get_user_state(user_id, "session:results")
    results = json.loads(results_json) if results_json else []

    # Update streak once for the session
    if results:
        update_user_streak(user_id)

    summary = format_session_summary(results)
    client.chat_postMessage(channel=channel, text=summary)

    # Clean up session state
    for key in (
        "session:count",
        "session:current",
        "session:results",
        "session:prefs",
        "session:question",
        "session:answer_start",
    ):
        set_user_state(user_id, key, "")
    set_user_state(user_id, "conv:type", "")


def register_session_handlers(app) -> None:
    """Register all session-related slash commands and action handlers."""

    @app.command("/swet-session")
    def handle_session_command(ack, command, respond, client):
        """Handle /swet-session — start a multi-question session."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        prefs = get_user_preferences(user_id)

        if not prefs:
            respond(text="No preferences set. Run `/swet-setup` first.")
            return

        # Check if count was provided as argument
        text = command.get("text", "").strip()
        if text and text.isdigit():
            count = max(1, min(int(text), 20))
            _start_session(user_id, prefs, count, command["channel_id"], client)
            return

        # Ask for count
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "How many questions?"}},
            *session_count_blocks(),
        ]
        respond(blocks=blocks, text="How many questions?")

    for count_val in ("3", "5", "10"):

        @app.action(f"session_{count_val}")
        def handle_count_select(ack, body, client, action):
            """Handle session count selection button."""
            ack()
            user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
            prefs = get_user_preferences(user_id)

            if not prefs:
                client.chat_postMessage(
                    channel=body["channel"]["id"],
                    text="No preferences set. Run `/swet-setup` first.",
                )
                return

            count = int(action["value"])

            # Update the selection message
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text=f"Starting session with {count} questions...",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": (f"Starting session with {count} questions...")},
                    }
                ],
            )

            _start_session(user_id, prefs, count, body["channel"]["id"], client)


def _start_session(user_id: str, prefs: dict, count: int, channel: str, client) -> None:
    """Initialize session state and serve the first question."""
    set_user_state(user_id, "session:count", str(count))
    set_user_state(user_id, "session:current", "0")
    set_user_state(user_id, "session:results", json.dumps([]))
    set_user_state(user_id, "session:prefs", json.dumps(prefs))

    _serve_next_session_question(user_id, channel, client)


def handle_session_mcq_answer(user_id: str, answer_key: str, channel: str, client) -> None:
    """Handle MCQ answer during a session. Called from bot.py action handler."""
    _grade_and_record(user_id, answer_key, is_mcq=True, channel=channel, client=client)


def handle_session_text_answer(user_id: str, answer_text: str, channel: str, client) -> None:
    """Handle text answer during a session. Called from message listener in bot.py."""
    if not answer_text.strip():
        client.chat_postMessage(channel=channel, text="Please provide an answer.")
        return
    _grade_and_record(user_id, answer_text, is_mcq=False, channel=channel, client=client)
