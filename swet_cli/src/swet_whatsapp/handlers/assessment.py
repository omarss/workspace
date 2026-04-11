"""Assessment handler: /test command for Bayesian adaptive level assessment via WhatsApp.

Uses Computerized Adaptive Testing (CAT) with Item Response Theory (IRT)
to efficiently determine the user's competency levels. All estimator state
(posteriors, question counts) is serialized to SQLite between webhook calls.
"""

import json
import logging

from swet_cli.assessment import (
    QUESTIONS_PER_COMPETENCY,
    BayesianLevelEstimator,
    select_assessment_competencies,
)
from swet_cli.data import COMPETENCY_BY_SLUG
from swet_cli.generator import generate_questions
from swet_cli.grader import grade_mcq
from swet_whatsapp.db import (
    clear_user_conversation_state,
    get_user_preferences,
    get_user_question,
    get_user_state,
    save_user_attempt,
    save_user_question,
    set_user_state,
    update_user_competency_level,
)
from swet_whatsapp.formatters import (
    _MCQ_LABELS,
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


def _serialize_estimator(estimator: BayesianLevelEstimator) -> dict:
    """Serialize a BayesianLevelEstimator to a JSON-safe dict."""
    return {
        "posterior": {str(k): v for k, v in estimator.posterior.items()},
        "questions_asked": estimator.questions_asked,
    }


def _deserialize_estimator(data: dict) -> BayesianLevelEstimator:
    """Reconstruct a BayesianLevelEstimator from serialized data."""
    estimator = BayesianLevelEstimator()
    estimator.posterior = {int(k): v for k, v in data["posterior"].items()}
    estimator.questions_asked = data["questions_asked"]
    return estimator


def handle_test_command(user_id: str) -> str:
    """Handle /test — start the level assessment.

    Returns the first question text.
    """
    prefs = get_user_preferences(user_id)
    if not prefs:
        return "No preferences set. Send /start first."

    roles = prefs["roles"]
    comp_slugs = select_assessment_competencies(roles)
    if not comp_slugs:
        return "No competencies found for your roles."

    total_questions = len(comp_slugs) * QUESTIONS_PER_COMPETENCY

    # Initialize assessment state with serialized estimators
    estimators = {slug: BayesianLevelEstimator() for slug in comp_slugs}
    serialized_posteriors = {slug: _serialize_estimator(est) for slug, est in estimators.items()}

    clear_user_conversation_state(user_id)
    set_user_state(user_id, "conv:type", "assessment")

    data = {
        "comp_slugs": comp_slugs,
        "comp_idx": 0,
        "q_idx": 0,
        "question_num": 0,
        "total": total_questions,
        "posteriors": serialized_posteriors,
    }
    set_user_state(user_id, "conv:data", json.dumps(data))

    header = (
        f"*Level Assessment*\n"
        f"{len(comp_slugs)} competencies, {total_questions} questions\n\n"
        f"Answer MCQ questions to determine your level.\n\n"
    )

    question_text = _serve_next_assessment_question(user_id, prefs, data)
    return header + question_text


def handle_assessment_input(user_id: str, text: str) -> str:
    """Handle MCQ answer during assessment.

    Returns result + next question text, or final results.
    """
    step = get_user_state(user_id, "conv:step")
    data_str = get_user_state(user_id, "conv:data")
    if not data_str:
        clear_user_conversation_state(user_id)
        return "Assessment state lost. Send /test to start a new one."

    data = json.loads(data_str)

    if step != "waiting_answer":
        clear_user_conversation_state(user_id)
        return "Unexpected state. Send /test to start a new assessment."

    # Validate MCQ answer
    answer_key = text.strip().upper()
    if answer_key not in _MCQ_LABELS[:4]:
        return f"Please reply with one of: {', '.join(_MCQ_LABELS[:4])}"

    question_id = data.get("question_id")
    if not question_id:
        clear_user_conversation_state(user_id)
        return "Question not found. Send /test to restart."

    question_data = get_user_question(user_id, question_id)
    if question_data is None:
        clear_user_conversation_state(user_id)
        return "Question not found. Send /test to restart."

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

    # Update Bayesian estimator
    slug = question_data["competency_slug"]
    posteriors = data["posteriors"]
    estimator = _deserialize_estimator(posteriors[slug])
    estimator.update(question_data["difficulty"], grade.normalized_score)
    posteriors[slug] = _serialize_estimator(estimator)

    # Advance to next question
    data["q_idx"] = data["q_idx"] + 1
    data["posteriors"] = posteriors
    set_user_state(user_id, "conv:data", json.dumps(data))

    prefs = get_user_preferences(user_id)
    if not prefs:
        clear_user_conversation_state(user_id)
        return f"{result_text}{explanation}\n\nAssessment ended (preferences not found)."

    next_text = _serve_next_assessment_question(user_id, prefs, data)
    return f"{result_text}{explanation}\n\n{next_text}"


def _serve_next_assessment_question(user_id: str, prefs: dict, data: dict) -> str:
    """Generate and serve the next assessment question. Returns question text."""
    comp_slugs = data["comp_slugs"]
    comp_idx = data["comp_idx"]
    q_idx = data["q_idx"]
    question_num = data["question_num"]
    total = data["total"]
    posteriors = data["posteriors"]

    # Check if current competency is done
    if q_idx >= QUESTIONS_PER_COMPETENCY:
        data["comp_idx"] = comp_idx + 1
        data["q_idx"] = 0
        set_user_state(user_id, "conv:data", json.dumps(data))
        return _serve_next_assessment_question(user_id, prefs, data)

    # Check if all competencies are done
    comp_idx = data["comp_idx"]
    if comp_idx >= len(comp_slugs):
        return _finalize_assessment(user_id, data)

    slug = comp_slugs[comp_idx]
    comp = COMPETENCY_BY_SLUG[slug]
    estimator = _deserialize_estimator(posteriors[slug])

    difficulty = estimator.best_next_difficulty()
    question_num += 1
    data["question_num"] = question_num

    # Generate a single MCQ
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
        data["q_idx"] = q_idx + 1
        set_user_state(user_id, "conv:data", json.dumps(data))
        return "Failed to generate question. Skipping...\n\n" + _serve_next_assessment_question(user_id, prefs, data)

    # Save question to DB
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
        data["q_idx"] = q_idx + 1
        set_user_state(user_id, "conv:data", json.dumps(data))
        return _serve_next_assessment_question(user_id, prefs, data)

    # Store question ID and update state
    data["question_id"] = question_data["id"]
    set_user_state(user_id, "conv:step", "waiting_answer")
    set_user_state(user_id, "conv:data", json.dumps(data))

    # Format question
    parts = format_question(question_data)
    header = f"*{comp.name}* | Question {question_num}/{total} (L{difficulty})\n\n"
    return header + "\n\n".join(parts)


def _finalize_assessment(user_id: str, data: dict) -> str:
    """Finalize assessment: store levels and show results."""
    posteriors = data["posteriors"]
    results: dict[str, dict] = {}

    for slug, est_data in posteriors.items():
        estimator = _deserialize_estimator(est_data)
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

    clear_user_conversation_state(user_id)

    if results:
        return format_assessment_results(results)

    return "No competencies were assessed."


def handle_assessment_cancel(user_id: str) -> str:
    """Handle /cancel during assessment — save partial results."""
    data_str = get_user_state(user_id, "conv:data")
    if data_str:
        data = json.loads(data_str)
        if "posteriors" in data:
            result = _finalize_assessment(user_id, data)
            return f"Assessment cancelled. Saving partial results...\n\n{result}"

    clear_user_conversation_state(user_id)
    return "Assessment cancelled."
