"""Questions API router: generate, get next, get by ID."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from swet_api.auth.dependencies import get_current_user
from swet_api.db import get_user_question, get_user_queued_question
from swet_api.schemas import GenerateRequest, QuestionResponse
from swet_api.services.question_service import generate_for_user

router = APIRouter(prefix="/questions", tags=["questions"])


@router.post("/generate", response_model=list[QuestionResponse])
def generate(
    req: GenerateRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> list[QuestionResponse]:
    """Generate a batch of adaptive questions."""
    try:
        return generate_for_user(user["id"], req)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/next", response_model=QuestionResponse | None)
def get_next_question(
    user: Annotated[dict, Depends(get_current_user)],
    competency: str | None = None,
    format: str | None = None,
    difficulty: int | None = None,
) -> QuestionResponse | None:
    """Get the next queued (unanswered) question."""
    q = get_user_queued_question(
        user_id=user["id"],
        competency_slug=competency,
        question_format=format,
        difficulty=difficulty,
    )
    if q is None:
        return None
    return QuestionResponse(**{k: v for k, v in q.items() if k != "correct_answer"})


@router.get("/{question_id}", response_model=QuestionResponse)
def get_question(
    question_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> QuestionResponse:
    """Get a specific question by ID."""
    q = get_user_question(user["id"], question_id)
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return QuestionResponse(**{k: v for k, v in q.items() if k != "correct_answer"})
