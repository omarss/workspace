"""Question handler: /swet-q command for getting and answering questions.

Handles the full question lifecycle:
1. Pick competency, format, difficulty (adaptive)
2. Generate or serve from DB queue
3. Display question with MCQ Block Kit buttons or text prompt
4. Grade answer (MCQ via action callback, open-ended via message listener)
5. Update adaptive levels and show results
"""

import json
import logging
import time

from swet_cli.generator import generate_questions
from swet_cli.grader import grade_mcq, grade_open_ended
from swet_slack.blocks import mcq_blocks, post_answer_blocks
from swet_slack.db import (
    get_or_create_user,
    get_user_competency_level,
    get_user_preferences,
    get_user_queued_question,
    get_user_recent_question_topics,
    get_user_state,
    save_user_attempt,
    save_user_bookmark,
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
    _split_message,
    format_grade,
    format_level_progress,
    format_question,
    format_streak,
)

logger = logging.getLogger(__name__)


def _get_user_id(user_id: str, username: str | None = None) -> str:
    """Ensure user exists in DB and return user_id."""
    return get_or_create_user(user_id=user_id, username=username)


def _generate_and_send(user_id: str, prefs: dict, channel: str, client) -> None:
    """Core logic: pick, generate/serve, and send a question to the channel."""
    base_diff = prefs["difficulty"]
    roles = prefs["roles"]

    # 1. Pick competency
    comp = pick_competency(user_id, roles, base_diff)

    # 2. Pick format
    q_format = pick_format(user_id, comp.slug, base_diff, prefs.get("preferred_formats"))

    # 3. Adapt difficulty
    diff = adapt_difficulty(user_id, comp.slug, base_diff)

    # 4. Check DB or generate
    needs_generation = should_generate_new(user_id, comp.slug, q_format, diff)

    question_data = None
    if not needs_generation:
        question_data = get_user_queued_question(user_id, comp.slug, q_format, diff)

    if question_data is None:
        # Generate new questions
        client.chat_postMessage(
            channel=channel,
            text=f"Generating questions for {comp.name} at L{diff}...",
        )

        recent_topics = get_user_recent_question_topics(user_id, 20)

        question_models = generate_questions(
            competency=comp,
            difficulty=diff,
            question_format=q_format,
            roles=roles,
            languages=prefs["languages"],
            frameworks=prefs["frameworks"],
            recent_topics=recent_topics,
            question_length=prefs.get("question_length", "standard"),
        )

        # Save all to DB
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
            client.chat_postMessage(channel=channel, text="Failed to generate questions. Please try again.")
            return

    # Store current question in user state for grading
    set_user_state(user_id, "conv:question", json.dumps(question_data))
    set_user_state(user_id, "conv:type", "question")
    set_user_state(user_id, "conv:start_time", str(time.monotonic()))

    # Send the question
    parts = format_question(question_data)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and question_data["format"] == "mcq" and question_data.get("options"):
            # Last part with MCQ buttons
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": part}},
                *mcq_blocks(question_data["options"], question_data["id"]),
            ]
            client.chat_postMessage(channel=channel, blocks=blocks, text=part)
        else:
            client.chat_postMessage(channel=channel, text=part)

    # If not MCQ, we wait for a text message from the user
    if question_data["format"] == "mcq":
        # MCQ answer comes via action callback; clear conv:type so message handler ignores
        set_user_state(user_id, "conv:type", "mcq_waiting")


def register_question_handlers(app) -> None:
    """Register all question-related slash commands and action handlers."""

    @app.command("/swet-q")
    def handle_question_command(ack, command, respond, client):
        """Handle /swet-q — serve an adaptive question."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        prefs = get_user_preferences(user_id)

        if not prefs:
            respond(text="No preferences set. Run `/swet-setup` to set up your profile first.")
            return

        # Use respond for the initial ack, then post messages to channel
        channel = command["channel_id"]
        _generate_and_send(user_id, prefs, channel, client)

    @app.action({"action_id": "^mcq_.*", "type": "button"})
    def handle_mcq_answer(ack, body, client, action):
        """Handle MCQ answer button click."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))

        # Parse action value: "{q_short}:{key}"
        value = action["value"]
        parts = value.split(":")
        if len(parts) != 2:
            return

        q_short, answer_key = parts

        # Get current question from state
        question_json = get_user_state(user_id, "conv:question")
        if not question_json:
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text="Question expired. Use `/swet-q` for a new question.",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": ("Question expired. Use `/swet-q` for a new question.")},
                    }
                ],
            )
            return

        question_data = json.loads(question_json)
        if not question_data["id"].startswith(q_short):
            client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text="Question expired. Use `/swet-q` for a new question.",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": ("Question expired. Use `/swet-q` for a new question.")},
                    }
                ],
            )
            return

        # Calculate elapsed time
        elapsed = None
        start_str = get_user_state(user_id, "conv:start_time")
        if start_str:
            try:
                elapsed = time.monotonic() - float(start_str)
            except ValueError:
                pass

        # Grade
        grade = grade_mcq(answer_key, question_data["correct_answer"])

        # Save attempt
        save_user_attempt(
            user_id=user_id,
            question_id=question_data["id"],
            answer_text=answer_key,
            score=grade.normalized_score,
            max_score=grade.max_score,
            total_score=grade.total_score,
            grade_details=grade.model_dump(),
            feedback=grade.overall_feedback,
            time_seconds=elapsed,
        )

        # Update adaptive level
        prev_level_data = get_user_competency_level(user_id, question_data["competency_slug"])
        old_level = prev_level_data["estimated_level"] if prev_level_data else question_data["difficulty"]

        new_level = update_adaptive_level(
            user_id,
            question_data["competency_slug"],
            grade.normalized_score,
            question_data["difficulty"],
        )

        # Update format performance
        update_user_format_performance(
            user_id,
            question_data["competency_slug"],
            question_data["format"],
            grade.normalized_score,
        )

        # Update streak
        streak_count, is_new_day = update_user_streak(user_id)

        # Build response
        response = format_grade(grade, question_data, elapsed)
        response += f"\n\n{format_streak(streak_count, is_new_day)}"
        if new_level != old_level:
            response += f"\n{format_level_progress(question_data['competency_slug'], old_level, new_level)}"

        # Update the message with result + post-answer buttons
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": response}},
            *post_answer_blocks(question_data["id"]),
        ]
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            blocks=blocks,
            text=response,
        )

        # Clean up conversation state
        set_user_state(user_id, "conv:type", "")
        set_user_state(user_id, "conv:question", "")
        set_user_state(user_id, "conv:start_time", "")

    @app.action({"action_id": "^bookmark_.*", "type": "button"})
    def handle_bookmark(ack, body, action):
        """Handle bookmark button click."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        q_short = action["value"]

        # Try to find the question from state
        question_json = get_user_state(user_id, "conv:question")
        if question_json:
            try:
                question_data = json.loads(question_json)
                if question_data["id"].startswith(q_short):
                    save_user_bookmark(user_id, question_data["id"])
                    return
            except (json.JSONDecodeError, KeyError):
                pass

        logger.warning("Could not find question %s to bookmark for user %s", q_short, user_id)

    @app.action("next_q")
    def handle_next_question(ack, body, client):
        """Handle 'Next Question' button click."""
        ack()
        user_id = _get_user_id(body["user"]["id"], username=body["user"].get("username"))
        prefs = get_user_preferences(user_id)

        if not prefs:
            client.chat_postMessage(
                channel=body["channel"]["id"],
                text="Run `/swet-setup` to set up your profile first.",
            )
            return

        channel = body["channel"]["id"]
        _generate_and_send(user_id, prefs, channel, client)


def handle_text_answer(user_id: str, answer_text: str, channel: str, client) -> None:
    """Grade an open-ended text answer for the current question.

    Called from the message listener in bot.py when conv:type == "question".
    """
    question_json = get_user_state(user_id, "conv:question")
    if not question_json:
        client.chat_postMessage(channel=channel, text="No active question. Use `/swet-q` to get one.")
        return

    question_data = json.loads(question_json)

    if not answer_text.strip():
        client.chat_postMessage(channel=channel, text="Please provide an answer.")
        return

    # Calculate elapsed time
    elapsed = None
    start_str = get_user_state(user_id, "conv:start_time")
    if start_str:
        try:
            elapsed = time.monotonic() - float(start_str)
        except ValueError:
            pass

    # Show grading placeholder
    grading_msg = client.chat_postMessage(channel=channel, text="Grading your answer...")

    # Grade via LLM
    grade = grade_open_ended(
        question_title=question_data["title"],
        question_body=question_data["body"],
        question_format=question_data["format"],
        rubric=question_data["grading_rubric"],
        answer_text=answer_text,
        code_snippet=question_data.get("code_snippet"),
    )

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
    prev_level_data = get_user_competency_level(user_id, question_data["competency_slug"])
    old_level = prev_level_data["estimated_level"] if prev_level_data else question_data["difficulty"]

    new_level = update_adaptive_level(
        user_id,
        question_data["competency_slug"],
        grade.normalized_score,
        question_data["difficulty"],
    )

    # Update format performance
    update_user_format_performance(
        user_id,
        question_data["competency_slug"],
        question_data["format"],
        grade.normalized_score,
    )

    # Update streak
    streak_count, is_new_day = update_user_streak(user_id)

    # Build response
    response = format_grade(grade, question_data, elapsed)
    response += f"\n\n{format_streak(streak_count, is_new_day)}"
    if new_level != old_level:
        response += f"\n{format_level_progress(question_data['competency_slug'], old_level, new_level)}"

    # Send the grading result
    for part in _split_message(response):
        client.chat_postMessage(channel=channel, text=part)

    # Post the action buttons separately
    client.chat_postMessage(
        channel=channel,
        blocks=post_answer_blocks(question_data["id"]),
        text="What would you like to do next?",
    )

    # Try to delete the grading placeholder
    try:
        client.chat_delete(channel=channel, ts=grading_msg["ts"])
    except Exception:
        pass

    # Clean up conversation state
    set_user_state(user_id, "conv:type", "")
    set_user_state(user_id, "conv:question", "")
    set_user_state(user_id, "conv:start_time", "")
