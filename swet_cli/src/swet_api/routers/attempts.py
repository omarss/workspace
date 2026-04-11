"""Attempts API router: submit answers, get history."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from swet_api.auth.dependencies import get_current_user
from swet_api.db import get_user_history
from swet_api.schemas import AnswerRequest, GradeResponse
from swet_api.services.attempt_service import grade_and_save

router = APIRouter(prefix="/attempts", tags=["attempts"])


@router.post("", response_model=GradeResponse, status_code=status.HTTP_201_CREATED)
def submit_answer(
    req: AnswerRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> GradeResponse:
    """Submit an answer to a question and get it graded."""
    try:
        response, _ = grade_and_save(user["id"], req)
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    return response


@router.get("/history")
def get_history(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 20,
) -> list[dict]:
    """Get recent attempt history."""
    return get_user_history(user["id"], limit=limit)
