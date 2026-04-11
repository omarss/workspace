"""Bookmarks API router."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from swet_api.auth.dependencies import get_current_user
from swet_api.db import add_review_item, get_user_bookmarks, get_user_question, remove_user_bookmark, save_user_bookmark
from swet_api.schemas import BookmarkResponse

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get("", response_model=list[BookmarkResponse])
def list_bookmarks(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 50,
) -> list[BookmarkResponse]:
    """Get bookmarked questions."""
    return [BookmarkResponse(**bm) for bm in get_user_bookmarks(user["id"], limit=limit)]


@router.post("/{question_id}", status_code=status.HTTP_201_CREATED)
def add_bookmark(
    question_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Bookmark a question."""
    q = get_user_question(user["id"], question_id)
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    save_user_bookmark(user["id"], question_id)
    # Also add to review queue for spaced repetition
    review_due = date.fromordinal(date.today().toordinal() + 3).isoformat()
    add_review_item(user["id"], question_id, "bookmarked", review_due)
    return {"message": "Bookmarked"}


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(
    question_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> None:
    """Remove a bookmark."""
    remove_user_bookmark(user["id"], question_id)
