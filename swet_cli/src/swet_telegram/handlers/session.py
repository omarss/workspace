"""Session handler: /session command for multi-question practice sessions.

Runs a configurable number of questions in sequence, tracking results
and displaying a summary at the end.
"""

import asyncio
import logging
import time

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from swet_cli.generator import generate_questions
from swet_cli.grader import grade_mcq, grade_open_ended
from swet_telegram.db import (
    get_or_create_user,
    get_user_preferences,
    get_user_queued_question,
    get_user_recent_question_topics,
    save_user_attempt,
    save_user_question,
    update_user_format_performance,
    update_user_streak,
)
from swet_telegram.engine import (
    adapt_difficulty,
    pick_competency,
    pick_format,
    should_generate_new,
    update_adaptive_level,
)
from swet_telegram.formatters import (
    format_grade,
    format_session_summary,
)
from swet_telegram.formatters import format_question as fmt_question
from swet_telegram.keyboards import mcq_keyboard, session_count_keyboard

logger = logging.getLogger(__name__)

# Conversation states
SELECT_COUNT, SESSION_MCQ, SESSION_TEXT = range(3)


def _get_user_id(update: Update) -> str:
    """Extract and ensure user exists in DB."""
    user = update.effective_user
    return get_or_create_user(
        chat_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )


async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /session — start a multi-question session."""
    user_id = _get_user_id(update)
    prefs = get_user_preferences(user_id)

    if not prefs:
        await update.message.reply_text("No preferences set. Run /start first.")
        return ConversationHandler.END

    # Check if count was provided as argument
    args = context.args
    if args and args[0].isdigit():
        count = int(args[0])
        count = max(1, min(count, 20))  # clamp to 1-20
        return await _start_session(update, context, user_id, prefs, count)

    # Ask for count
    await update.message.reply_text(
        "How many questions?",
        reply_markup=session_count_keyboard(),
    )
    return SELECT_COUNT


async def handle_count_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle session count selection callback."""
    query = update.callback_query
    await query.answer()

    count = int(query.data.replace("session:", ""))
    user_id = _get_user_id(update)
    prefs = get_user_preferences(user_id)

    if not prefs:
        await query.edit_message_text("No preferences set. Run /start first.")
        return ConversationHandler.END

    await query.edit_message_text(f"Starting session with {count} questions...")
    return await _start_session(update, context, user_id, prefs, count)


async def _start_session(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: str,
    prefs: dict,
    count: int,
) -> int:
    """Initialize session state and serve the first question."""
    context.user_data["session_count"] = count
    context.user_data["session_current"] = 0
    context.user_data["session_results"] = []
    context.user_data["session_user_id"] = user_id
    context.user_data["session_prefs"] = prefs

    return await _serve_next_session_question(update, context)


async def _serve_next_session_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Serve the next question in the session."""
    current = context.user_data["session_current"]
    total = context.user_data["session_count"]
    user_id = context.user_data["session_user_id"]
    prefs = context.user_data["session_prefs"]

    if current >= total:
        return await _end_session(update, context)

    context.user_data["session_current"] = current + 1

    await update.effective_message.reply_text(
        f"<b>Question {current + 1}/{total}</b>",
        parse_mode="HTML",
    )

    # Pick competency, format, difficulty
    comp = await asyncio.to_thread(pick_competency, user_id, prefs["roles"], prefs["difficulty"])
    q_format = await asyncio.to_thread(
        pick_format,
        user_id,
        comp.slug,
        prefs["difficulty"],
        prefs.get("preferred_formats"),
    )
    diff = await asyncio.to_thread(adapt_difficulty, user_id, comp.slug, prefs["difficulty"])

    # Check DB or generate
    needs_generation = await asyncio.to_thread(should_generate_new, user_id, comp.slug, q_format, diff)
    question_data = None

    if not needs_generation:
        question_data = await asyncio.to_thread(
            get_user_queued_question,
            user_id,
            comp.slug,
            q_format,
            diff,
        )

    if question_data is None:
        msg = await update.effective_message.reply_text(f"Generating for {comp.name}...")
        recent_topics = await asyncio.to_thread(get_user_recent_question_topics, user_id, 20)

        question_models = await asyncio.to_thread(
            generate_questions,
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
            await asyncio.to_thread(save_user_question, user_id, q_data)

        await msg.delete()

        question_data = await asyncio.to_thread(
            get_user_queued_question,
            user_id,
            comp.slug,
            q_format,
            diff,
        )
        if question_data is None:
            await update.effective_message.reply_text("Failed to generate. Skipping...")
            return await _serve_next_session_question(update, context)

    context.user_data["session_question"] = question_data
    context.user_data["session_answer_start"] = time.monotonic()

    # Send question
    parts = fmt_question(question_data)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and question_data["format"] == "mcq" and question_data.get("options"):
            await update.effective_message.reply_text(
                part,
                reply_markup=mcq_keyboard(question_data["options"], question_data["id"]),
                parse_mode="HTML",
            )
        else:
            await update.effective_message.reply_text(part, parse_mode="HTML")

    if question_data["format"] == "mcq":
        return SESSION_MCQ
    return SESSION_TEXT


async def _grade_and_record(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    answer_text: str,
    is_mcq: bool,
) -> int:
    """Grade an answer, record it, and move to the next question."""
    user_id = context.user_data["session_user_id"]
    question_data = context.user_data["session_question"]

    elapsed = None
    start_time = context.user_data.get("session_answer_start")
    if start_time is not None:
        elapsed = time.monotonic() - start_time

    # Grade
    if is_mcq:
        grade = grade_mcq(answer_text, question_data["correct_answer"])
    else:
        msg = await update.effective_message.reply_text("Grading...")
        grade = await asyncio.to_thread(
            grade_open_ended,
            question_title=question_data["title"],
            question_body=question_data["body"],
            question_format=question_data["format"],
            rubric=question_data["grading_rubric"],
            answer_text=answer_text,
            code_snippet=question_data.get("code_snippet"),
        )
        await msg.delete()

    # Save attempt
    await asyncio.to_thread(
        save_user_attempt,
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
    await asyncio.to_thread(
        update_adaptive_level,
        user_id,
        question_data["competency_slug"],
        grade.normalized_score,
        question_data["difficulty"],
    )
    await asyncio.to_thread(
        update_user_format_performance,
        user_id,
        question_data["competency_slug"],
        question_data["format"],
        grade.normalized_score,
    )

    # Show brief result
    response = format_grade(grade, question_data, elapsed)
    await update.effective_message.reply_text(response, parse_mode="HTML")

    # Track session result
    context.user_data["session_results"].append(
        {
            "question": question_data,
            "score": grade.normalized_score,
            "time_seconds": elapsed,
        }
    )

    # Next question
    return await _serve_next_session_question(update, context)


async def handle_session_mcq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle MCQ answer during a session."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "mcq":
        return SESSION_MCQ

    answer_key = parts[2]

    # Remove the keyboard from the question message
    await query.edit_message_reply_markup(reply_markup=None)

    return await _grade_and_record(update, context, answer_key, is_mcq=True)


async def handle_session_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text answer during a session."""
    answer_text = update.message.text.strip()
    if not answer_text:
        await update.message.reply_text("Please provide an answer, or /stop to end the session.")
        return SESSION_TEXT

    return await _grade_and_record(update, context, answer_text, is_mcq=False)


async def _end_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """End the session and show summary."""
    results = context.user_data.get("session_results", [])
    user_id = context.user_data.get("session_user_id")

    # Update streak once for the session
    if results and user_id:
        await asyncio.to_thread(update_user_streak, user_id)

    summary = format_session_summary(results)
    await update.effective_message.reply_text(summary, parse_mode="HTML")

    # Clean up
    for key in (
        "session_count",
        "session_current",
        "session_results",
        "session_user_id",
        "session_prefs",
        "session_question",
        "session_answer_start",
    ):
        context.user_data.pop(key, None)

    return ConversationHandler.END


async def stop_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /stop to end session early."""
    return await _end_session(update, context)


def session_conversation_handler() -> ConversationHandler:
    """Build the ConversationHandler for /session."""
    return ConversationHandler(
        entry_points=[CommandHandler("session", session_command)],
        states={
            SELECT_COUNT: [CallbackQueryHandler(handle_count_select, pattern=r"^session:")],
            SESSION_MCQ: [CallbackQueryHandler(handle_session_mcq, pattern=r"^mcq:")],
            SESSION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_session_text)],
        },
        fallbacks=[
            CommandHandler("stop", stop_session),
            CommandHandler("cancel", stop_session),
        ],
        per_user=True,
        per_chat=True,
    )
