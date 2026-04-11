"""Question handler: /q command for getting and answering questions.

Handles the full question lifecycle:
1. Pick competency, format, difficulty (adaptive)
2. Generate or serve from DB queue
3. Display question with MCQ keyboard or text prompt
4. Grade answer (MCQ via callback, open-ended via text)
5. Update adaptive levels and show results
"""

import asyncio
import logging
import time

from telegram import Update
from telegram.ext import (
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
    get_user_competency_level,
    get_user_preferences,
    get_user_queued_question,
    get_user_recent_question_topics,
    save_user_attempt,
    save_user_bookmark,
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
    format_level_progress,
    format_streak,
)
from swet_telegram.formatters import format_question as fmt_question
from swet_telegram.keyboards import mcq_keyboard, post_answer_keyboard

logger = logging.getLogger(__name__)

# Conversation states
WAITING_TEXT_ANSWER = 0


def _get_user_id(update: Update) -> str:
    """Extract and ensure user exists in DB."""
    user = update.effective_user
    return get_or_create_user(
        chat_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )


async def question_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /q or /question — serve an adaptive question."""
    user_id = _get_user_id(update)
    prefs = get_user_preferences(user_id)

    if not prefs:
        await update.message.reply_text(
            "No preferences set. Run /start to set up your profile first.",
        )
        return ConversationHandler.END

    # Generate and send question
    return await _generate_and_send(update, context, user_id, prefs)


async def _generate_and_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: str,
    prefs: dict,
) -> int:
    """Core logic: pick, generate/serve, and send a question."""
    base_diff = prefs["difficulty"]
    roles = prefs["roles"]

    # 1. Pick competency
    comp = await asyncio.to_thread(pick_competency, user_id, roles, base_diff)

    # 2. Pick format
    q_format = await asyncio.to_thread(
        pick_format,
        user_id,
        comp.slug,
        base_diff,
        prefs.get("preferred_formats"),
    )

    # 3. Adapt difficulty
    diff = await asyncio.to_thread(adapt_difficulty, user_id, comp.slug, base_diff)

    # 4. Check DB or generate
    needs_generation = await asyncio.to_thread(
        should_generate_new,
        user_id,
        comp.slug,
        q_format,
        diff,
    )

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
        # Generate new questions — show a placeholder message
        msg = await update.effective_message.reply_text(
            f"Generating questions for {comp.name} at L{diff}...",
        )

        recent_topics = await asyncio.to_thread(get_user_recent_question_topics, user_id, 20)

        question_models = await asyncio.to_thread(
            generate_questions,
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
            await asyncio.to_thread(save_user_question, user_id, q_data)

        # Delete the placeholder
        await msg.delete()

        question_data = await asyncio.to_thread(
            get_user_queued_question,
            user_id,
            comp.slug,
            q_format,
            diff,
        )
        if question_data is None:
            await update.effective_message.reply_text("Failed to generate questions. Please try again.")
            return ConversationHandler.END

    # Store current question in user_data for grading
    context.user_data["current_question"] = question_data
    context.user_data["answer_start_time"] = time.monotonic()

    # Send the question
    parts = fmt_question(question_data)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and question_data["format"] == "mcq" and question_data.get("options"):
            # Last part with MCQ keyboard
            await update.effective_message.reply_text(
                part,
                reply_markup=mcq_keyboard(question_data["options"], question_data["id"]),
                parse_mode="HTML",
            )
        else:
            await update.effective_message.reply_text(part, parse_mode="HTML")

    if question_data["format"] != "mcq":
        return WAITING_TEXT_ANSWER

    # MCQ — answer comes via callback, handled outside conversation
    return ConversationHandler.END


async def handle_mcq_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle MCQ answer callback (outside ConversationHandler)."""
    query = update.callback_query
    await query.answer()

    # Parse callback data: "mcq:{q_short}:{key}"
    parts = query.data.split(":")
    if len(parts) != 3:
        return

    _, q_short, answer_key = parts
    user_id = _get_user_id(update)

    # Find the question from user_data or DB
    question_data = context.user_data.get("current_question")
    if question_data is None or not question_data["id"].startswith(q_short):
        # Try to find from recent questions
        await query.edit_message_text("Question expired. Use /q for a new question.")
        return

    elapsed = None
    start_time = context.user_data.get("answer_start_time")
    if start_time is not None:
        elapsed = time.monotonic() - start_time

    # Grade
    grade = grade_mcq(answer_key, question_data["correct_answer"])

    # Save attempt
    await asyncio.to_thread(
        save_user_attempt,
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
    prev_level_data = await asyncio.to_thread(
        get_user_competency_level,
        user_id,
        question_data["competency_slug"],
    )
    old_level = prev_level_data["estimated_level"] if prev_level_data else question_data["difficulty"]

    new_level = await asyncio.to_thread(
        update_adaptive_level,
        user_id,
        question_data["competency_slug"],
        grade.normalized_score,
        question_data["difficulty"],
    )

    # Update format performance
    await asyncio.to_thread(
        update_user_format_performance,
        user_id,
        question_data["competency_slug"],
        question_data["format"],
        grade.normalized_score,
    )

    # Update streak
    streak_count, is_new_day = await asyncio.to_thread(update_user_streak, user_id)

    # Build response
    response = format_grade(grade, question_data, elapsed)
    response += f"\n\n{format_streak(streak_count, is_new_day)}"
    if new_level != old_level:
        response += f"\n{format_level_progress(question_data['competency_slug'], old_level, new_level)}"

    await query.edit_message_text(
        response,
        reply_markup=post_answer_keyboard(question_data["id"]),
        parse_mode="HTML",
    )

    # Clean up
    context.user_data.pop("current_question", None)
    context.user_data.pop("answer_start_time", None)


async def handle_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text answer for open-ended questions."""
    user_id = _get_user_id(update)
    question_data = context.user_data.get("current_question")

    if question_data is None:
        await update.message.reply_text("No active question. Use /q to get one.")
        return ConversationHandler.END

    answer_text = update.message.text.strip()
    if not answer_text:
        await update.message.reply_text("Please provide an answer, or /cancel to skip.")
        return WAITING_TEXT_ANSWER

    elapsed = None
    start_time = context.user_data.get("answer_start_time")
    if start_time is not None:
        elapsed = time.monotonic() - start_time

    # Show grading placeholder
    msg = await update.message.reply_text("Grading your answer...")

    # Grade via LLM
    grade = await asyncio.to_thread(
        grade_open_ended,
        question_title=question_data["title"],
        question_body=question_data["body"],
        question_format=question_data["format"],
        rubric=question_data["grading_rubric"],
        answer_text=answer_text,
        code_snippet=question_data.get("code_snippet"),
    )

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
    prev_level_data = await asyncio.to_thread(
        get_user_competency_level,
        user_id,
        question_data["competency_slug"],
    )
    old_level = prev_level_data["estimated_level"] if prev_level_data else question_data["difficulty"]

    new_level = await asyncio.to_thread(
        update_adaptive_level,
        user_id,
        question_data["competency_slug"],
        grade.normalized_score,
        question_data["difficulty"],
    )

    # Update format performance
    await asyncio.to_thread(
        update_user_format_performance,
        user_id,
        question_data["competency_slug"],
        question_data["format"],
        grade.normalized_score,
    )

    # Update streak
    streak_count, is_new_day = await asyncio.to_thread(update_user_streak, user_id)

    # Build response
    response = format_grade(grade, question_data, elapsed)
    response += f"\n\n{format_streak(streak_count, is_new_day)}"
    if new_level != old_level:
        response += f"\n{format_level_progress(question_data['competency_slug'], old_level, new_level)}"

    # Edit the grading placeholder
    await msg.edit_text(
        response,
        reply_markup=post_answer_keyboard(question_data["id"]),
        parse_mode="HTML",
    )

    # Clean up
    context.user_data.pop("current_question", None)
    context.user_data.pop("answer_start_time", None)

    return ConversationHandler.END


async def handle_bookmark_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bookmark button callback."""
    query = update.callback_query
    await query.answer()

    q_short = query.data.replace("bookmark:", "")
    user_id = _get_user_id(update)

    # Find question by short ID prefix
    question_data = context.user_data.get("current_question")
    if question_data and question_data["id"].startswith(q_short):
        await asyncio.to_thread(save_user_bookmark, user_id, question_data["id"])
        await query.answer("Bookmarked!", show_alert=True)
    else:
        await query.answer("Could not find the question to bookmark.", show_alert=True)


async def handle_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle 'Next Question' button callback."""
    query = update.callback_query
    await query.answer()

    user_id = _get_user_id(update)
    prefs = get_user_preferences(user_id)

    if not prefs:
        await query.edit_message_text("Run /start to set up your profile first.")
        return

    # Generate and send a new question
    await _generate_and_send(update, context, user_id, prefs)


async def cancel_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel during question answering."""
    context.user_data.pop("current_question", None)
    context.user_data.pop("answer_start_time", None)
    await update.message.reply_text("Question skipped.")
    return ConversationHandler.END


def question_conversation_handler() -> ConversationHandler:
    """Build the ConversationHandler for /q and /question."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("q", question_command),
            CommandHandler("question", question_command),
        ],
        states={
            WAITING_TEXT_ANSWER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_answer),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_question)],
        per_user=True,
        per_chat=True,
    )
