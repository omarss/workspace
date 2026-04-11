"""Session handler: /session command for multi-question practice sessions via WhatsApp.

Runs a configurable number of questions in sequence, tracking results
and displaying a summary at the end. All state is serialized to SQLite
between stateless webhook calls.
"""

import json
import logging
import time

from swet_cli.generator import generate_questions
from swet_cli.grader import grade_mcq, grade_open_ended
from swet_whatsapp.db import (
    clear_user_conversation_state,
    get_user_preferences,
    get_user_question,
    get_user_queued_question,
    get_user_recent_question_topics,
    get_user_state,
    save_user_attempt,
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
    format_question,
    format_session_summary,
)

logger = logging.getLogger(__name__)


def handle_session_command(user_id: str, args: str | None = None) -> str:
    """Handle /session — start a multi-question session.

    If args contains a number, use that as the session count.
    Otherwise, prompt the user to choose.
    """
    prefs = get_user_preferences(user_id)
    if not prefs:
        return "No preferences set. Send /start first."

    # Check if count was provided as argument
    if args and args.strip().isdigit():
        count = int(args.strip())
        count = max(1, min(count, 20))  # clamp to 1-20
        return _start_session(user_id, prefs, count)

    # Ask for count
    clear_user_conversation_state(user_id)
    set_user_state(user_id, "conv:type", "session")
    set_user_state(user_id, "conv:step", "select_count")
    set_user_state(user_id, "conv:data", json.dumps({}))

    return (
        "How many questions?\nReply with a number (1-20), or choose:\n\n1. 3 questions\n2. 5 questions\n3. 10 questions"
    )


def handle_session_input(user_id: str, text: str) -> str:
    """Route session input to the current step.

    Returns response text to send to the user.
    """
    step = get_user_state(user_id, "conv:step")
    data_str = get_user_state(user_id, "conv:data")
    data = json.loads(data_str) if data_str else {}

    if step == "select_count":
        return _handle_count_selection(user_id, text)
    if step in ("waiting_mcq", "waiting_text"):
        return _handle_answer(user_id, text, data)

    clear_user_conversation_state(user_id)
    return "Session state lost. Send /session to start a new one."


def _handle_count_selection(user_id: str, text: str) -> str:
    """Handle session count selection."""
    text = text.strip()

    # Map shortcut selections to counts
    count_map = {"1": 3, "2": 5, "3": 10}
    if text in count_map:
        count = count_map[text]
    elif text.isdigit():
        count = int(text)
        count = max(1, min(count, 20))
    else:
        return "Please enter a number (1-20), or choose 1, 2, or 3 from the list."

    prefs = get_user_preferences(user_id)
    if not prefs:
        clear_user_conversation_state(user_id)
        return "No preferences set. Send /start first."

    return _start_session(user_id, prefs, count)


def _start_session(user_id: str, prefs: dict, count: int) -> str:
    """Initialize session state and serve the first question."""
    clear_user_conversation_state(user_id)
    set_user_state(user_id, "conv:type", "session")

    data = {
        "count": count,
        "current": 0,
        "results": [],
    }
    set_user_state(user_id, "conv:data", json.dumps(data))

    header = f"Starting session with {count} questions...\n\n"
    question_text = _serve_next_question(user_id, prefs, data)
    return header + question_text


def _serve_next_question(user_id: str, prefs: dict, data: dict) -> str:
    """Serve the next question in the session. Returns question text."""
    current = data["current"]
    total = data["count"]

    if current >= total:
        return _end_session(user_id, data)

    data["current"] = current + 1
    base_diff = prefs["difficulty"]
    roles = prefs["roles"]

    # Pick competency, format, difficulty
    comp = pick_competency(user_id, roles, base_diff)
    q_format = pick_format(user_id, comp.slug, base_diff, prefs.get("preferred_formats"))
    diff = adapt_difficulty(user_id, comp.slug, base_diff)

    # Check DB or generate
    needs_generation = should_generate_new(user_id, comp.slug, q_format, diff)
    question_data = None

    if not needs_generation:
        question_data = get_user_queued_question(user_id, comp.slug, q_format, diff)

    if question_data is None:
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
            # Skip this question, try next
            data["current"] = current + 1
            set_user_state(user_id, "conv:data", json.dumps(data))
            return f"Failed to generate question {current + 1}. Skipping...\n\n" + _serve_next_question(
                user_id, prefs, data
            )

    # Set conversation state for answer
    if question_data["format"] == "mcq":
        set_user_state(user_id, "conv:step", "waiting_mcq")
    else:
        set_user_state(user_id, "conv:step", "waiting_text")

    data["question_id"] = question_data["id"]
    data["start_time"] = time.time()
    set_user_state(user_id, "conv:data", json.dumps(data))

    # Format question
    parts = format_question(question_data)
    header = f"*Question {current + 1}/{total}*\n\n"
    return header + "\n\n".join(parts)


def _handle_answer(user_id: str, text: str, data: dict) -> str:
    """Handle an answer during a session."""
    question_id = data.get("question_id")
    start_time = data.get("start_time")
    step = get_user_state(user_id, "conv:step")

    if not question_id:
        clear_user_conversation_state(user_id)
        return "Session state lost. Send /session to start a new one."

    question_data = get_user_question(user_id, question_id)
    if question_data is None:
        clear_user_conversation_state(user_id)
        return "Question not found. Send /session for a new session."

    elapsed = time.time() - start_time if start_time else None

    # Grade the answer
    if step == "waiting_mcq":
        answer_key = text.strip().upper()
        options = question_data.get("options", [])
        valid_labels = _MCQ_LABELS[: len(options)] if options else _MCQ_LABELS[:4]

        if answer_key not in valid_labels:
            return f"Please reply with one of: {', '.join(valid_labels)}"

        grade = grade_mcq(answer_key, question_data["correct_answer"])
        answer_text = answer_key
    else:
        answer_text = text.strip()
        if not answer_text:
            return "Please provide an answer, or send /stop to end the session."

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

    # Update adaptive level and format performance
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

    # Track result
    results = data.get("results", [])
    results.append(
        {
            "question": {
                "title": question_data["title"],
                "competency_slug": question_data["competency_slug"],
            },
            "score": grade.normalized_score,
            "time_seconds": elapsed,
        }
    )
    data["results"] = results
    set_user_state(user_id, "conv:data", json.dumps(data))

    # Show brief result
    grade_text = format_grade(grade, question_data, elapsed)

    # Serve next question
    prefs = get_user_preferences(user_id)
    if not prefs:
        clear_user_conversation_state(user_id)
        return grade_text + "\n\nSession ended (preferences not found)."

    next_text = _serve_next_question(user_id, prefs, data)
    return grade_text + "\n\n---\n\n" + next_text


def _end_session(user_id: str, data: dict) -> str:
    """End the session and show summary."""
    results = data.get("results", [])

    # Update streak once for the session
    if results:
        update_user_streak(user_id)

    summary = format_session_summary(results)
    clear_user_conversation_state(user_id)

    return summary


def handle_session_stop(user_id: str) -> str:
    """Handle /stop — end session early and show partial summary."""
    data_str = get_user_state(user_id, "conv:data")
    data = json.loads(data_str) if data_str else {}
    return _end_session(user_id, data)
