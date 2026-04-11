"""Assessments API router: calibration flow with Bayesian adaptive testing."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from swet_api.auth.dependencies import get_current_user
from swet_api.db import (
    cancel_assessment,
    create_assessment,
    finalize_assessment,
    get_active_assessment,
    get_assessment,
    get_user_preferences,
    save_user_question,
    update_assessment_progress,
    update_user_competency_level,
)
from swet_api.schemas import (
    AssessmentAnswerRequest,
    AssessmentAnswerResponse,
    AssessmentResultsResponse,
    AssessmentStartRequest,
    AssessmentStartResponse,
    AssessmentStateResponse,
    CompetencyResult,
    QuestionResponse,
)
from swet_cli.assessment import SELF_RATING_PRIORS, BayesianLevelEstimator
from swet_cli.data import (
    COMPETENCY_BY_SLUG,
    get_role_competency_weights,
)
from swet_cli.grader import grade_mcq

router = APIRouter(prefix="/assessments", tags=["assessments"])

_TOTAL_QUESTIONS = 100
_PART1_QUESTIONS = 50  # concepts (language-agnostic)
_PART2_QUESTIONS = 50  # language-specific
_LEVEL_ELO_MIDPOINTS = {1: 425.0, 2: 975.0, 3: 1225.0, 4: 1475.0, 5: 1800.0}


def _select_assessment_competencies(roles: list[str]) -> list[str]:
    """Select competencies for assessment based on role emphasis.

    Uses all competencies with meaningful weight (above baseline 0.02),
    not capped at 6. More competencies = better coverage across 50 questions.
    """
    weights = get_role_competency_weights(roles)
    # Include all competencies above baseline weight
    baseline = 0.03
    sorted_slugs = sorted(weights.keys(), key=lambda s: weights[s], reverse=True)
    return [s for s in sorted_slugs if weights[s] >= baseline]


def _distribute_questions(
    comp_slugs: list[str], roles: list[str], total: int
) -> dict[str, int]:
    """Distribute questions across competencies proportional to role weights.

    Minimum 2 per competency. Remainder goes to highest-weighted.
    """
    weights = get_role_competency_weights(roles)
    active_weights = {s: weights.get(s, 0.02) for s in comp_slugs}
    total_weight = sum(active_weights.values())

    # Proportional allocation with minimum 2
    allocation: dict[str, int] = {}
    remaining = total
    for slug in comp_slugs:
        count = max(2, round((active_weights[slug] / total_weight) * total))
        allocation[slug] = count
        remaining -= count

    # Adjust to hit exact total: add/remove from highest-weighted
    sorted_by_weight = sorted(comp_slugs, key=lambda s: active_weights[s], reverse=True)
    idx = 0
    while remaining > 0:
        allocation[sorted_by_weight[idx % len(sorted_by_weight)]] += 1
        remaining -= 1
        idx += 1
    while remaining < 0:
        slug = sorted_by_weight[idx % len(sorted_by_weight)]
        if allocation[slug] > 2:
            allocation[slug] -= 1
            remaining += 1
        idx += 1

    return allocation


def _generate_assessment_mcq(
    user_id: str,
    competency_slug: str,
    difficulty: int,
    language: str | None = None,
) -> QuestionResponse:
    """Generate an MCQ question for the assessment.

    For Part 2, pass language to generate language-specific questions with code.
    """
    from swet_cli.generator import generate_questions

    comp = COMPETENCY_BY_SLUG[competency_slug]
    questions = generate_questions(
        competency=comp,
        difficulty=difficulty,
        question_format="mcq",
        roles=[],
        languages=[language] if language else [],
        frameworks=[],
        count=1,
        question_length="concise",
    )
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate assessment question"
        )

    qm = questions[0]
    q_data = {
        "competency_slug": competency_slug,
        "format": "mcq",
        "difficulty": difficulty,
        **qm.model_dump(),
    }
    q_id = save_user_question(user_id, q_data)
    return QuestionResponse(
        id=q_id,
        competency_slug=competency_slug,
        format="mcq",
        difficulty=difficulty,
        title=qm.title,
        body=qm.body,
        code_snippet=qm.code_snippet,
        language=qm.language,
        options=qm.options,
        metadata=qm.metadata,
    )


def _serialize_posteriors(estimators: dict[str, BayesianLevelEstimator]) -> str:
    """Serialize estimator state to JSON for DB storage."""
    data = {}
    for slug, est in estimators.items():
        data[slug] = {
            "posterior": est.posterior,
            "questions_asked": est.questions_asked,
        }
    return json.dumps(data)


def _deserialize_posteriors(posteriors: dict) -> dict[str, BayesianLevelEstimator]:
    """Restore estimators from DB-stored JSON."""
    estimators: dict[str, BayesianLevelEstimator] = {}
    for slug, state in posteriors.items():
        est = BayesianLevelEstimator()
        try:
            est.posterior = {int(k): float(v) for k, v in state["posterior"].items()}
            est.questions_asked = int(state["questions_asked"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"Corrupted assessment data for competency {slug}") from exc
        estimators[slug] = est
    return estimators


def _build_results(
    assessment_id: str, competency_slugs: list[str], estimators: dict[str, BayesianLevelEstimator]
) -> AssessmentResultsResponse:
    """Build assessment results from estimators."""
    competencies = []
    for slug in competency_slugs:
        est = estimators[slug]
        comp = COMPETENCY_BY_SLUG.get(slug)
        competencies.append(
            CompetencyResult(
                slug=slug,
                name=comp.name if comp else slug,
                estimated_level=est.estimated_level(),
                confidence=est.confidence(),
                posterior=est.posterior,
            )
        )
    return AssessmentResultsResponse(
        assessment_id=assessment_id,
        status="completed",
        competencies=competencies,
    )


@router.post("", response_model=AssessmentStartResponse, status_code=status.HTTP_201_CREATED)
def start_assessment(
    user: Annotated[dict, Depends(get_current_user)],
    req: AssessmentStartRequest | None = None,
) -> AssessmentStartResponse:
    """Start a new calibration assessment.

    Optionally accepts self_ratings (competency_slug → 0-5) to create
    informative priors. Rating 0 skips the competency entirely.
    """
    # Check for existing in-progress assessment
    existing = get_active_assessment(user["id"])
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Assessment already in progress")

    prefs = get_user_preferences(user["id"])
    if prefs is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Set preferences first")

    # Select competencies based on roles
    if not prefs.get("roles"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No roles configured. Update preferences first."
        )
    all_comp_slugs = _select_assessment_competencies(prefs["roles"])
    if not all_comp_slugs:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No competencies found for your roles")

    self_ratings = (req.self_ratings if req else None) or {}

    # Filter out competencies rated 0 (no exposure) and set them to L1 directly
    active_slugs: list[str] = []
    for slug in all_comp_slugs:
        rating = self_ratings.get(slug, 3)  # default to "comfortable" (= current behavior)
        if rating == 0:
            update_user_competency_level(user["id"], slug, 1, _LEVEL_ELO_MIDPOINTS[1], 0, 0, 0)
        else:
            active_slugs.append(slug)

    if not active_slugs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All competencies were skipped. Rate at least one above 'No exposure'.",
        )

    # Determine primary language for Part 2
    languages = prefs.get("languages", [])
    primary_language = languages[0] if languages else None

    # Distribute questions across competencies for each part
    questions_per_comp = _distribute_questions(active_slugs, prefs["roles"], _PART1_QUESTIONS)

    # Initialize estimators with self-rating-based priors
    estimators: dict[str, BayesianLevelEstimator] = {}
    for slug in active_slugs:
        rating = self_ratings.get(slug, 3)
        prior = SELF_RATING_PRIORS.get(rating)
        estimators[slug] = BayesianLevelEstimator(prior=prior)

    posteriors_json = _serialize_posteriors(estimators)

    assessment_id = create_assessment(
        user["id"],
        active_slugs,
        _TOTAL_QUESTIONS,
        posteriors_json,
        primary_language=primary_language,
        questions_per_comp=questions_per_comp,
    )

    # Generate first question (Part 1: concepts, no language)
    first_slug = active_slugs[0]
    difficulty = estimators[first_slug].best_next_difficulty()
    first_question = _generate_assessment_mcq(user["id"], first_slug, difficulty)

    return AssessmentStartResponse(
        assessment_id=assessment_id,
        competencies=active_slugs,
        total_questions=_TOTAL_QUESTIONS,
        first_question=first_question,
        primary_language=primary_language,
        assessment_phase="concepts",
    )


@router.get("/current", response_model=AssessmentStateResponse | None)
def get_current_assessment(
    user: Annotated[dict, Depends(get_current_user)],
) -> AssessmentStateResponse | None:
    """Get the current in-progress assessment, if any."""
    from swet_api.db import get_user_queued_question

    assessment = get_active_assessment(user["id"])
    if assessment is None:
        return None

    # Try to find the current unanswered question
    current_question = None
    comp_slugs = assessment["competency_slugs"]
    comp_idx = assessment["current_comp_idx"]
    if comp_idx < len(comp_slugs):
        current_slug = comp_slugs[comp_idx]
        q = get_user_queued_question(user["id"], competency_slug=current_slug, question_format="mcq")
        if q:
            current_question = QuestionResponse(**{k: v for k, v in q.items() if k != "correct_answer"})

    return AssessmentStateResponse(
        assessment_id=assessment["id"],
        status=assessment["status"],
        competencies=comp_slugs,
        questions_completed=assessment["questions_completed"],
        total_questions=assessment["total_questions"],
        current_question=current_question,
        assessment_phase=assessment.get("assessment_phase", "concepts"),
        primary_language=assessment.get("primary_language"),
    )


@router.post("/{assessment_id}/answer", response_model=AssessmentAnswerResponse)
def answer_assessment_question(
    assessment_id: str,
    req: AssessmentAnswerRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> AssessmentAnswerResponse:
    """Answer the current assessment question."""
    assessment = get_assessment(user["id"], assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    if assessment["status"] != "in_progress":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assessment is not in progress")

    comp_slugs = assessment["competency_slugs"]
    comp_idx = assessment["current_comp_idx"]
    q_idx = assessment["current_q_idx"]
    questions_completed = assessment["questions_completed"]
    current_phase = assessment.get("assessment_phase", "concepts")
    primary_language = assessment.get("primary_language")
    questions_per_comp = assessment.get("questions_per_comp") or {}

    current_slug = comp_slugs[comp_idx]
    estimators = _deserialize_posteriors(assessment["posteriors"])

    # Grade the MCQ answer
    from swet_api.db import get_user_queued_question

    question = get_user_queued_question(user["id"], competency_slug=current_slug, question_format="mcq")
    if question is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No current question found")
    if not question.get("correct_answer"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Assessment question missing correct answer"
        )

    grade = grade_mcq(req.answer, question["correct_answer"])
    score = grade.normalized_score

    from swet_api.db import save_user_attempt

    save_user_attempt(
        user_id=user["id"],
        question_id=question["id"],
        answer_text=req.answer,
        score=score,
        max_score=1,
        total_score=int(score),
    )

    # Update the Bayesian posterior
    estimator = estimators[current_slug]
    difficulty = question["difficulty"]
    estimator.update(difficulty, score)
    questions_completed += 1

    # Determine how many questions this competency gets in the current phase
    max_q_for_comp = questions_per_comp.get(current_slug, 3)

    # Advance to next question
    q_idx += 1
    next_question = None
    is_complete = False
    new_phase = current_phase

    if q_idx >= max_q_for_comp:
        # Move to next competency
        q_idx = 0
        comp_idx += 1
        if comp_idx >= len(comp_slugs):
            if current_phase == "concepts":
                # Transition to Part 2: language-specific
                new_phase = "language"
                comp_idx = 0
                q_idx = 0
                # Redistribute questions for Part 2
                questions_per_comp = _distribute_questions(comp_slugs, [], _PART2_QUESTIONS)
            else:
                # Part 2 done — assessment complete
                is_complete = True

    if not is_complete:
        next_slug = comp_slugs[comp_idx]
        next_est = estimators[next_slug]
        next_diff = next_est.best_next_difficulty()
        lang = primary_language if new_phase == "language" else None
        next_question = _generate_assessment_mcq(user["id"], next_slug, next_diff, language=lang)

    # Save progress
    posteriors_json = _serialize_posteriors(estimators)
    # Store updated questions_per_comp when phase transitions
    if new_phase != current_phase:
        from swet_api.db import get_db

        conn = get_db()
        conn.execute(
            "UPDATE assessments SET questions_per_comp = ? WHERE id = ?",
            (json.dumps(questions_per_comp), assessment_id),
        )
        conn.commit()
        conn.close()
    update_assessment_progress(
        assessment_id, comp_idx, q_idx, questions_completed, posteriors_json,
        assessment_phase=new_phase if new_phase != current_phase else None,
    )

    results = None
    if is_complete:
        results_response = _build_results(assessment_id, comp_slugs, estimators)
        total_per_comp = sum(questions_per_comp.get(s, 3) for s in comp_slugs)
        for cr in results_response.competencies:
            elo = _LEVEL_ELO_MIDPOINTS.get(cr.estimated_level, 1000.0)
            update_user_competency_level(
                user["id"], cr.slug, cr.estimated_level, elo, 0, 0, estimators[cr.slug].questions_asked
            )
        results_json = json.dumps([c.model_dump() for c in results_response.competencies])
        finalize_assessment(assessment_id, results_json)
        results = results_response

    return AssessmentAnswerResponse(
        correct=score >= 0.5,
        correct_answer=question["correct_answer"],
        explanation=question.get("explanation"),
        questions_completed=questions_completed,
        total_questions=assessment["total_questions"],
        is_complete=is_complete,
        next_question=next_question,
        results=results,
        assessment_phase=new_phase,
    )


@router.post("/{assessment_id}/finalize", response_model=AssessmentResultsResponse)
def finalize_assessment_endpoint(
    assessment_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> AssessmentResultsResponse:
    """Explicitly finalize an assessment (also called automatically when all questions answered)."""
    assessment = get_assessment(user["id"], assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    if assessment["status"] == "completed" and assessment["results"]:
        # Already finalized — return existing results
        results_data = assessment["results"]
        return AssessmentResultsResponse(
            assessment_id=assessment_id,
            status="completed",
            competencies=[CompetencyResult(**r) for r in results_data],
            completed_at=assessment["completed_at"],
        )

    comp_slugs = assessment["competency_slugs"]
    estimators = _deserialize_posteriors(assessment["posteriors"])

    results = _build_results(assessment_id, comp_slugs, estimators)
    for cr in results.competencies:
        elo = _LEVEL_ELO_MIDPOINTS.get(cr.estimated_level, 1000.0)
        update_user_competency_level(
            user["id"], cr.slug, cr.estimated_level, elo, 0, 0, assessment["questions_completed"]
        )
    results_json = json.dumps([c.model_dump() for c in results.competencies])
    finalize_assessment(assessment_id, results_json)
    results.completed_at = assessment.get("completed_at")
    return results


@router.get("/{assessment_id}", response_model=AssessmentResultsResponse)
def get_assessment_results(
    assessment_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> AssessmentResultsResponse:
    """Get the results of a completed assessment."""
    assessment = get_assessment(user["id"], assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    if assessment["results"] is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assessment not yet completed")
    return AssessmentResultsResponse(
        assessment_id=assessment_id,
        status=assessment["status"],
        competencies=[CompetencyResult(**r) for r in assessment["results"]],
        completed_at=assessment["completed_at"],
    )


@router.delete("/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_assessment_endpoint(
    assessment_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> None:
    """Cancel an in-progress assessment."""
    assessment = get_assessment(user["id"], assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    if assessment["status"] != "in_progress":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assessment is not in progress")
    cancel_assessment(assessment_id)
