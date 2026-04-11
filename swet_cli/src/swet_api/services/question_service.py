"""Question service: adaptive generation and retrieval."""

from swet_api.db import get_user_preferences, save_user_question
from swet_api.engine import adapt_difficulty, pick_competency, pick_format
from swet_api.schemas import GenerateRequest, QuestionResponse
from swet_cli.data import COMPETENCY_BY_SLUG
from swet_cli.generator import generate_questions


def generate_for_user(user_id: str, req: GenerateRequest) -> list[QuestionResponse]:
    """Generate a batch of adaptive questions for a user.

    Uses the user-scoped adaptive engine for competency/format/difficulty selection,
    then calls the LLM for question generation.

    Raises ValueError if preferences are not set or competency is unknown.
    """
    prefs = get_user_preferences(user_id)
    if prefs is None:
        raise ValueError("Set preferences first via PUT /preferences")

    # Pick competency
    if req.competency_slug:
        comp = COMPETENCY_BY_SLUG.get(req.competency_slug)
        if comp is None:
            raise ValueError("Unknown competency")
    else:
        comp = pick_competency(user_id, prefs["roles"], prefs["difficulty"])

    # Pick format
    q_format = req.question_format or pick_format(
        user_id, comp.slug, prefs["difficulty"], preferred_formats=prefs.get("preferred_formats")
    )

    # Adapt difficulty
    difficulty = req.difficulty or adapt_difficulty(user_id, comp.slug, prefs["difficulty"])

    # Generate via LLM
    question_models = generate_questions(
        competency=comp,
        difficulty=difficulty,
        question_format=q_format,
        roles=prefs["roles"],
        languages=prefs["languages"],
        frameworks=prefs["frameworks"],
        count=req.count,
        question_length=prefs.get("question_length", "standard"),
    )

    # Save and build responses
    results: list[QuestionResponse] = []
    for qm in question_models:
        q_data = {
            "competency_slug": comp.slug,
            "format": q_format,
            "difficulty": difficulty,
            **qm.model_dump(),
        }
        q_id = save_user_question(user_id, q_data)
        results.append(
            QuestionResponse(
                id=q_id,
                competency_slug=comp.slug,
                format=q_format,
                difficulty=difficulty,
                title=qm.title,
                body=qm.body,
                code_snippet=qm.code_snippet,
                language=qm.language,
                options=qm.options,
                explanation_detail=qm.explanation_detail,
                metadata=qm.metadata,
            )
        )

    return results


def generate_single(
    user_id: str,
    prefs: dict,
    competency_slug: str | None = None,
    question_format: str | None = None,
    difficulty: int | None = None,
) -> QuestionResponse:
    """Generate a single adaptive question for session/assessment use.

    Optional overrides let callers pin competency, format, or difficulty
    instead of using adaptive selection.

    Raises ValueError if generation fails or competency is unknown.
    """
    if competency_slug:
        comp = COMPETENCY_BY_SLUG.get(competency_slug)
        if comp is None:
            raise ValueError(f"Unknown competency: {competency_slug}")
    else:
        comp = pick_competency(user_id, prefs["roles"], prefs["difficulty"])

    q_format = question_format or pick_format(
        user_id, comp.slug, prefs["difficulty"], preferred_formats=prefs.get("preferred_formats")
    )
    difficulty = difficulty or adapt_difficulty(user_id, comp.slug, prefs["difficulty"])

    question_models = generate_questions(
        competency=comp,
        difficulty=difficulty,
        question_format=q_format,
        roles=prefs["roles"],
        languages=prefs["languages"],
        frameworks=prefs["frameworks"],
        count=1,
        question_length=prefs.get("question_length", "standard"),
    )
    if not question_models:
        raise ValueError("Failed to generate question")

    qm = question_models[0]
    q_data = {
        "competency_slug": comp.slug,
        "format": q_format,
        "difficulty": difficulty,
        **qm.model_dump(),
    }
    q_id = save_user_question(user_id, q_data)
    return QuestionResponse(
        id=q_id,
        competency_slug=comp.slug,
        format=q_format,
        difficulty=difficulty,
        title=qm.title,
        body=qm.body,
        code_snippet=qm.code_snippet,
        language=qm.language,
        options=qm.options,
        explanation_detail=qm.explanation_detail,
        metadata=qm.metadata,
    )
