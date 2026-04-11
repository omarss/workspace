"""Assessment handler: /test command for Bayesian adaptive level assessment.

Uses Computerized Adaptive Testing (CAT) with Item Response Theory (IRT)
to efficiently determine the user's competency levels. Generates MCQ
questions at adaptive difficulty, updates Bayesian posterior, and stores
the estimated levels.
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

from swet_cli.assessment import (
    QUESTIONS_PER_COMPETENCY,
    BayesianLevelEstimator,
    select_assessment_competencies,
)
from swet_cli.data import COMPETENCY_BY_SLUG
from swet_cli.generator import generate_questions
from swet_cli.grader import grade_mcq
from swet_telegram.db import (
    get_or_create_user,
    get_user_preferences,
    save_user_attempt,
    save_user_question,
    update_user_competency_level,
)
from swet_telegram.formatters import format_assessment_results
from swet_telegram.formatters import format_question as fmt_question
from swet_telegram.keyboards import mcq_keyboard

logger = logging.getLogger(__name__)

# ELO rating midpoints for each level (mirrors swet_cli.assessment)
_LEVEL_ELO_MIDPOINTS = {
    1: 425.0,
    2: 975.0,
    3: 1225.0,
    4: 1475.0,
    5: 1800.0,
}

# Conversation state
ASSESSMENT_ANSWER = 0


def _get_user_id(update: Update) -> str:
    """Extract and ensure user exists in DB."""
    user = update.effective_user
    return get_or_create_user(
        chat_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /test — start the level assessment."""
    user_id = _get_user_id(update)
    prefs = get_user_preferences(user_id)

    if not prefs:
        await update.message.reply_text("No preferences set. Run /start first.")
        return ConversationHandler.END

    roles = prefs["roles"]
    comp_slugs = select_assessment_competencies(roles)
    if not comp_slugs:
        await update.message.reply_text("No competencies found for your roles.")
        return ConversationHandler.END

    total_questions = len(comp_slugs) * QUESTIONS_PER_COMPETENCY

    # Initialize assessment state
    context.user_data["assess_user_id"] = user_id
    context.user_data["assess_prefs"] = prefs
    context.user_data["assess_comp_slugs"] = comp_slugs
    context.user_data["assess_comp_idx"] = 0
    context.user_data["assess_q_idx"] = 0
    context.user_data["assess_question_num"] = 0
    context.user_data["assess_total"] = total_questions
    context.user_data["assess_results"] = {}
    context.user_data["assess_estimators"] = {slug: BayesianLevelEstimator() for slug in comp_slugs}

    await update.message.reply_text(
        f"<b>Level Assessment</b>\n"
        f"{len(comp_slugs)} competencies, {total_questions} questions\n\n"
        f"Answer MCQ questions to determine your level.",
        parse_mode="HTML",
    )

    return await _serve_next_assessment_question(update, context)


async def _serve_next_assessment_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Generate and serve the next assessment question."""
    comp_slugs = context.user_data["assess_comp_slugs"]
    comp_idx = context.user_data["assess_comp_idx"]
    q_idx = context.user_data["assess_q_idx"]
    user_id = context.user_data["assess_user_id"]
    prefs = context.user_data["assess_prefs"]
    question_num = context.user_data["assess_question_num"]
    total = context.user_data["assess_total"]

    # Check if all competencies are done
    if comp_idx >= len(comp_slugs):
        return await _finalize_assessment(update, context)

    slug = comp_slugs[comp_idx]
    comp = COMPETENCY_BY_SLUG[slug]
    estimator = context.user_data["assess_estimators"][slug]

    # Check if this competency is done
    if q_idx >= QUESTIONS_PER_COMPETENCY:
        context.user_data["assess_comp_idx"] = comp_idx + 1
        context.user_data["assess_q_idx"] = 0
        return await _serve_next_assessment_question(update, context)

    difficulty = estimator.best_next_difficulty()
    question_num += 1
    context.user_data["assess_question_num"] = question_num

    await update.effective_message.reply_text(
        f"<b>{comp.name}</b> | Question {question_num}/{total} (L{difficulty})",
        parse_mode="HTML",
    )

    # Generate a single MCQ
    msg = await update.effective_message.reply_text("Generating question...")

    question_models = await asyncio.to_thread(
        generate_questions,
        competency=comp,
        difficulty=difficulty,
        question_format="mcq",
        roles=prefs["roles"],
        languages=prefs["languages"],
        frameworks=prefs["frameworks"],
        count=1,
    )

    await msg.delete()

    if not question_models:
        await update.effective_message.reply_text("Failed to generate question. Skipping...")
        context.user_data["assess_q_idx"] = q_idx + 1
        return await _serve_next_assessment_question(update, context)

    # Save question
    q_data = {
        "competency_slug": slug,
        "format": "mcq",
        "difficulty": difficulty,
        **question_models[0].model_dump(),
    }
    q_id = await asyncio.to_thread(save_user_question, user_id, q_data)

    # Re-read from DB to get consistent format
    from swet_telegram.db import get_user_question

    question_data = await asyncio.to_thread(get_user_question, user_id, q_id)
    if question_data is None:
        context.user_data["assess_q_idx"] = q_idx + 1
        return await _serve_next_assessment_question(update, context)

    context.user_data["assess_current_question"] = question_data

    # Send question with MCQ keyboard
    parts = fmt_question(question_data)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and question_data.get("options"):
            await update.effective_message.reply_text(
                part,
                reply_markup=mcq_keyboard(question_data["options"], question_data["id"]),
                parse_mode="HTML",
            )
        else:
            await update.effective_message.reply_text(part, parse_mode="HTML")

    return ASSESSMENT_ANSWER


async def handle_assessment_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle MCQ answer during assessment."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "mcq":
        return ASSESSMENT_ANSWER

    answer_key = parts[2]
    user_id = context.user_data["assess_user_id"]
    question_data = context.user_data.get("assess_current_question")

    if question_data is None:
        return ASSESSMENT_ANSWER

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
    )

    # Show inline result
    if grade.normalized_score == 1.0:
        result_text = "\u2713 Correct"
    else:
        result_text = f"\u2717 Incorrect (answer: {question_data.get('correct_answer', '?')})"

    explanation = ""
    if question_data.get("explanation"):
        explanation = f"\n<i>{question_data['explanation'][:150]}</i>"

    await query.edit_message_text(
        f"{result_text}{explanation}",
        parse_mode="HTML",
    )

    # Update Bayesian estimator
    slug = question_data["competency_slug"]
    estimator = context.user_data["assess_estimators"][slug]
    estimator.update(question_data["difficulty"], grade.normalized_score)

    # Move to next question
    context.user_data["assess_q_idx"] = context.user_data["assess_q_idx"] + 1

    return await _serve_next_assessment_question(update, context)


async def _finalize_assessment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Finalize assessment: store levels and show results."""
    user_id = context.user_data["assess_user_id"]
    estimators = context.user_data["assess_estimators"]
    results: dict[str, dict] = {}

    for slug, estimator in estimators.items():
        if estimator.questions_asked == 0:
            continue

        level = estimator.estimated_level()
        elo = _LEVEL_ELO_MIDPOINTS[level]

        await asyncio.to_thread(
            update_user_competency_level,
            user_id=user_id,
            competency_slug=slug,
            estimated_level=level,
            elo_rating=elo,
            consecutive_high=0,
            consecutive_low=0,
            total_attempts=estimator.questions_asked,
        )

        results[slug] = {
            "level": level,
            "confidence": estimator.confidence(),
            "distribution": estimator.distribution_str(),
        }

    if results:
        text = format_assessment_results(results)
        # Split if needed
        from swet_telegram.formatters import _split_message

        for part in _split_message(text):
            await update.effective_message.reply_text(part, parse_mode="HTML")
    else:
        await update.effective_message.reply_text("No competencies were assessed.")

    # Clean up
    for key in (
        "assess_user_id",
        "assess_prefs",
        "assess_comp_slugs",
        "assess_comp_idx",
        "assess_q_idx",
        "assess_question_num",
        "assess_total",
        "assess_results",
        "assess_estimators",
        "assess_current_question",
    ):
        context.user_data.pop(key, None)

    return ConversationHandler.END


async def cancel_assessment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel during assessment."""
    # Try to finalize partial results
    if "assess_estimators" in context.user_data:
        await update.message.reply_text("Assessment cancelled. Saving partial results...")
        return await _finalize_assessment(update, context)

    await update.message.reply_text("Assessment cancelled.")
    return ConversationHandler.END


def assessment_conversation_handler() -> ConversationHandler:
    """Build the ConversationHandler for /test."""
    return ConversationHandler(
        entry_points=[CommandHandler("test", test_command)],
        states={
            ASSESSMENT_ANSWER: [CallbackQueryHandler(handle_assessment_answer, pattern=r"^mcq:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_assessment)],
        per_user=True,
        per_chat=True,
    )
