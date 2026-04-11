"""Assessment handler: /swet-test command for Bayesian adaptive level assessment.

Uses Computerized Adaptive Testing (CAT) with Item Response Theory (IRT)
to efficiently determine the user's competency levels. Generates MCQ
questions at adaptive difficulty, updates Bayesian posterior, and stores
the estimated levels.

Assessment state is stored in-memory (short-lived) keyed by user_id.
"""

import logging

from swet_cli.assessment import (
    QUESTIONS_PER_COMPETENCY,
    BayesianLevelEstimator,
    select_assessment_competencies,
)
from swet_cli.data import COMPETENCY_BY_SLUG
from swet_cli.generator import generate_questions
from swet_cli.grader import grade_mcq
from swet_slack.blocks import mcq_blocks
from swet_slack.db import (
    get_or_create_user,
    get_user_preferences,
    get_user_question,
    save_user_attempt,
    save_user_question,
    update_user_competency_level,
)
from swet_slack.formatters import (
    _split_message,
    format_assessment_results,
    format_question,
)

logger = logging.getLogger(__name__)

# ELO rating midpoints for each level (mirrors swet_cli.assessment)
_LEVEL_ELO_MIDPOINTS = {
    1: 425.0,
    2: 975.0,
    3: 1225.0,
    4: 1475.0,
    5: 1800.0,
}

# In-memory assessment state, keyed by user_id.
# Short-lived (assessment takes ~5 min), so in-memory is fine.
_active_assessments: dict[str, dict] = {}


def _get_user_id(user_id: str, username: str | None = None) -> str:
    """Ensure user exists in DB and return user_id."""
    return get_or_create_user(user_id=user_id, username=username)


def _serve_next_assessment_question(user_id: str, channel: str, client) -> None:
    """Generate and serve the next assessment question."""
    state = _active_assessments.get(user_id)
    if not state:
        client.chat_postMessage(channel=channel, text="No active assessment. Use `/swet-test` to start.")
        return

    comp_slugs = state["comp_slugs"]
    comp_idx = state["comp_idx"]
    q_idx = state["q_idx"]
    prefs = state["prefs"]

    # Check if all competencies are done
    if comp_idx >= len(comp_slugs):
        _finalize_assessment(user_id, channel, client)
        return

    slug = comp_slugs[comp_idx]
    comp = COMPETENCY_BY_SLUG[slug]
    estimator = state["estimators"][slug]

    # Check if this competency is done
    if q_idx >= QUESTIONS_PER_COMPETENCY:
        state["comp_idx"] = comp_idx + 1
        state["q_idx"] = 0
        _serve_next_assessment_question(user_id, channel, client)
        return

    difficulty = estimator.best_next_difficulty()
    state["question_num"] += 1
    question_num = state["question_num"]
    total = state["total"]

    client.chat_postMessage(
        channel=channel,
        text=f"*{comp.name}* | Question {question_num}/{total} (L{difficulty})",
    )

    # Generate a single MCQ
    client.chat_postMessage(channel=channel, text="Generating question...")

    question_models = generate_questions(
        competency=comp,
        difficulty=difficulty,
        question_format="mcq",
        roles=prefs["roles"],
        languages=prefs["languages"],
        frameworks=prefs["frameworks"],
        count=1,
    )

    if not question_models:
        client.chat_postMessage(channel=channel, text="Failed to generate question. Skipping...")
        state["q_idx"] = q_idx + 1
        _serve_next_assessment_question(user_id, channel, client)
        return

    # Save question
    q_data = {
        "competency_slug": slug,
        "format": "mcq",
        "difficulty": difficulty,
        **question_models[0].model_dump(),
    }
    q_id = save_user_question(user_id, q_data)

    # Re-read from DB for consistent format
    question_data = get_user_question(user_id, q_id)
    if question_data is None:
        state["q_idx"] = q_idx + 1
        _serve_next_assessment_question(user_id, channel, client)
        return

    state["current_question"] = question_data

    # Send question with MCQ buttons
    parts = format_question(question_data)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and question_data.get("options"):
            blocks = [
                {"type": "section", "text": {"type": "mrkdwn", "text": part}},
                *mcq_blocks(question_data["options"], question_data["id"]),
            ]
            client.chat_postMessage(channel=channel, blocks=blocks, text=part)
        else:
            client.chat_postMessage(channel=channel, text=part)


def _finalize_assessment(user_id: str, channel: str, client) -> None:
    """Finalize assessment: store levels and show results."""
    state = _active_assessments.get(user_id)
    if not state:
        return

    estimators = state["estimators"]
    results: dict[str, dict] = {}

    for slug, estimator in estimators.items():
        if estimator.questions_asked == 0:
            continue

        level = estimator.estimated_level()
        elo = _LEVEL_ELO_MIDPOINTS[level]

        update_user_competency_level(
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
        for part in _split_message(text):
            client.chat_postMessage(channel=channel, text=part)
    else:
        client.chat_postMessage(channel=channel, text="No competencies were assessed.")

    # Clean up
    _active_assessments.pop(user_id, None)


def handle_assessment_mcq_answer(user_id: str, answer_key: str, q_short: str, channel: str, client) -> None:
    """Handle MCQ answer during assessment. Called from bot.py action handler."""
    state = _active_assessments.get(user_id)
    if not state:
        client.chat_postMessage(channel=channel, text="No active assessment.")
        return

    question_data = state.get("current_question")
    if not question_data or not question_data["id"].startswith(q_short):
        return

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
    )

    # Show inline result
    if grade.normalized_score == 1.0:
        result_text = "\u2713 Correct"
    else:
        result_text = f"\u2717 Incorrect (answer: {question_data.get('correct_answer', '?')})"

    explanation = ""
    if question_data.get("explanation"):
        explanation = f"\n_{question_data['explanation'][:150]}_"

    client.chat_postMessage(channel=channel, text=f"{result_text}{explanation}")

    # Update Bayesian estimator
    slug = question_data["competency_slug"]
    estimator = state["estimators"][slug]
    estimator.update(question_data["difficulty"], grade.normalized_score)

    # Move to next question
    state["q_idx"] = state["q_idx"] + 1

    _serve_next_assessment_question(user_id, channel, client)


def register_assessment_handlers(app) -> None:
    """Register all assessment-related slash commands."""

    @app.command("/swet-test")
    def handle_test_command(ack, command, respond, client):
        """Handle /swet-test — start the level assessment."""
        ack()
        user_id = _get_user_id(command["user_id"], username=command.get("user_name"))
        prefs = get_user_preferences(user_id)

        if not prefs:
            respond(text="No preferences set. Run `/swet-setup` first.")
            return

        roles = prefs["roles"]
        comp_slugs = select_assessment_competencies(roles)
        if not comp_slugs:
            respond(text="No competencies found for your roles.")
            return

        total_questions = len(comp_slugs) * QUESTIONS_PER_COMPETENCY

        # Initialize assessment state in memory
        _active_assessments[user_id] = {
            "prefs": prefs,
            "comp_slugs": comp_slugs,
            "comp_idx": 0,
            "q_idx": 0,
            "question_num": 0,
            "total": total_questions,
            "estimators": {slug: BayesianLevelEstimator() for slug in comp_slugs},
            "current_question": None,
        }

        channel = command["channel_id"]
        client.chat_postMessage(
            channel=channel,
            text=(
                f"*Level Assessment*\n"
                f"{len(comp_slugs)} competencies, {total_questions} questions\n\n"
                f"Answer MCQ questions to determine your level."
            ),
        )

        _serve_next_assessment_question(user_id, channel, client)


def is_user_in_assessment(user_id: str) -> bool:
    """Check if a user currently has an active assessment."""
    return user_id in _active_assessments
