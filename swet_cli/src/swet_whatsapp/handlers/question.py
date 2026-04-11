"""Question handler: /q command for getting and answering questions via WhatsApp.

Handles the full question lifecycle:
1. Pick competency, format, difficulty (adaptive)
2. Generate or serve from DB queue
3. Display question with MCQ options as text (A/B/C/D)
4. Grade answer (MCQ via letter reply, open-ended via text)
5. Update adaptive levels and show results

All state is persisted to SQLite between stateless webhook calls.
"""

import json
import logging
import time

from swet_cli.generator import generate_questions
from swet_cli.grader import grade_mcq, grade_open_ended
from swet_whatsapp.db import (
    clear_user_conversation_state,
    get_user_competency_level,
    get_user_preferences,
    get_user_question,
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
from swet_whatsapp.engine import (
    adapt_difficulty,
    pick_competency,
    pick_format,
    should_generate_new,
    update_adaptive_level,
)
from swet_whatsapp.formatters import (
    _MCQ_LABELS,
    format_grade,
    format_level_progress,
    format_question,
    format_streak,
)

logger = logging.getLogger(__name__)


def handle_question_command(user_id: str) -> str:
    """Handle /q — generate or serve an adaptive question.

    Returns the formatted question text. Sets conversation state for
    awaiting the answer on the next webhook call.
    """
    prefs = get_user_preferences(user_id)
    if not prefs:
        return "No preferences set. Send /start to set up your profile first."

    return _generate_and_send(user_id, prefs)


def _generate_and_send(user_id: str, prefs: dict) -> str:
    """Core logic: pick, generate/serve, format, and return a question."""
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
        # Generate new questions via LLM
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

        # Save all generated questions to DB
        for qm in question_models:
            q_data = {
                "competency_slug": comp.slug,
                "format": q_format,
                "difficulty": diff,
                **qm.model_dump(),
            }
            save_user_question(user_id, q_data)

        # Retrieve the first one from DB
        question_data = get_user_queued_question(user_id, comp.slug, q_format, diff)
        if question_data is None:
            return "Failed to generate questions. Please try again."

    # Store conversation state for answer handling
    clear_user_conversation_state(user_id)
    set_user_state(user_id, "conv:type", "question")

    if question_data["format"] == "mcq":
        set_user_state(user_id, "conv:step", "waiting_mcq")
    else:
        set_user_state(user_id, "conv:step", "waiting_text")

    conv_data = {
        "question_id": question_data["id"],
        "start_time": time.time(),
    }
    set_user_state(user_id, "conv:data", json.dumps(conv_data))

    # Format and return the question text
    parts = format_question(question_data)
    return "\n\n".join(parts)


def handle_question_answer(user_id: str, text: str) -> str:
    """Handle a user's answer to an active question.

    Returns the grading result text.
    """
    step = get_user_state(user_id, "conv:step")
    data_str = get_user_state(user_id, "conv:data")
    if not data_str:
        clear_user_conversation_state(user_id)
        return "No active question. Send /q to get one."

    data = json.loads(data_str)
    question_id = data.get("question_id")
    start_time = data.get("start_time")

    if not question_id:
        clear_user_conversation_state(user_id)
        return "No active question. Send /q to get one."

    question_data = get_user_question(user_id, question_id)
    if question_data is None:
        clear_user_conversation_state(user_id)
        return "Question not found. Send /q for a new question."

    elapsed = time.time() - start_time if start_time else None

    if step == "waiting_mcq":
        return _grade_mcq_answer(user_id, text, question_data, elapsed)
    if step == "waiting_text":
        return _grade_text_answer(user_id, text, question_data, elapsed)

    clear_user_conversation_state(user_id)
    return "Unexpected state. Send /q for a new question."


def _grade_mcq_answer(user_id: str, text: str, question_data: dict, elapsed: float | None) -> str:
    """Grade an MCQ answer given as a letter (A/B/C/D)."""
    answer_key = text.strip().upper()

    # Validate the answer is a valid MCQ option letter
    options = question_data.get("options", [])
    valid_labels = _MCQ_LABELS[: len(options)] if options else _MCQ_LABELS[:4]

    if answer_key not in valid_labels:
        return f"Please reply with one of: {', '.join(valid_labels)}"

    grade = grade_mcq(answer_key, question_data["correct_answer"])
    return _save_and_format_result(user_id, question_data, answer_key, grade, elapsed)


def _grade_text_answer(user_id: str, text: str, question_data: dict, elapsed: float | None) -> str:
    """Grade an open-ended text answer via LLM."""
    answer_text = text.strip()
    if not answer_text:
        return "Please provide an answer, or send /cancel to skip."

    grade = grade_open_ended(
        question_title=question_data["title"],
        question_body=question_data["body"],
        question_format=question_data["format"],
        rubric=question_data["grading_rubric"],
        answer_text=answer_text,
        code_snippet=question_data.get("code_snippet"),
    )

    return _save_and_format_result(user_id, question_data, answer_text, grade, elapsed)


def _save_and_format_result(
    user_id: str,
    question_data: dict,
    answer_text: str,
    grade,
    elapsed: float | None,
) -> str:
    """Save attempt, update adaptive levels, and format the result."""
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

    response += "\n\nSend /q for another question, or /bookmark to save this one."

    # Clear conversation state
    clear_user_conversation_state(user_id)

    return response


def handle_bookmark_command(user_id: str) -> str:
    """Handle /bookmark — bookmark the most recently answered question."""
    # Check if there's a recent question in conversation state or find the last attempt
    data_str = get_user_state(user_id, "conv:data")
    if data_str:
        data = json.loads(data_str)
        question_id = data.get("question_id")
        if question_id:
            save_user_bookmark(user_id, question_id)
            return "Question bookmarked! View your bookmarks with /bookmarks."

    # Try to bookmark the most recent attempt's question
    from swet_whatsapp.db import get_user_history

    history = get_user_history(user_id, limit=1)
    if history:
        save_user_bookmark(user_id, history[0]["question_id"])
        return "Last question bookmarked! View your bookmarks with /bookmarks."

    return "No question to bookmark. Answer a question first."
