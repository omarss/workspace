"""Reviews API router: spaced repetition review queue."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from swet_api.auth.dependencies import get_current_user
from swet_api.db import (
    dismiss_review_item,
    get_due_reviews,
    get_review_counts,
    get_review_item,
    get_review_item_with_question,
    update_review_item,
)
from swet_api.schemas import (
    ReviewCompleteRequest,
    ReviewCountResponse,
    ReviewItemResponse,
    ReviewSnoozeRequest,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("", response_model=list[ReviewItemResponse])
def list_reviews(
    user: Annotated[dict, Depends(get_current_user)],
    limit: int = 20,
) -> list[ReviewItemResponse]:
    """Get review items due for today or earlier."""
    items = get_due_reviews(user["id"], limit=limit)
    return [ReviewItemResponse(**item) for item in items]


@router.get("/count", response_model=ReviewCountResponse)
def review_count(
    user: Annotated[dict, Depends(get_current_user)],
) -> ReviewCountResponse:
    """Get review queue counts."""
    counts = get_review_counts(user["id"])
    return ReviewCountResponse(**counts)


@router.post("/{review_id}/complete", response_model=ReviewItemResponse)
def complete_review(
    review_id: str,
    req: ReviewCompleteRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> ReviewItemResponse:
    """Mark a review item as completed. Updates SM-2 interval."""
    item = get_review_item(user["id"], review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    # SM-2 algorithm
    quality = req.quality
    interval = item["interval_days"]
    ease = item["ease_factor"]
    review_count = item["review_count"] + 1

    if quality < 3:
        # Failed recall: reset interval
        interval = 1
    else:
        if interval == 1:
            interval = 6
        else:
            interval = round(interval * ease)
        # Update ease factor
        ease = max(1.3, ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))

    new_due = date.fromordinal(date.today().toordinal() + interval).isoformat()

    update_review_item(
        review_id=review_id,
        due_date=new_due,
        interval_days=interval,
        ease_factor=ease,
        review_count=review_count,
        status="pending",
    )

    # Fetch with question data (works regardless of due date)
    updated = get_review_item_with_question(user["id"], review_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Review item disappeared after update")
    return ReviewItemResponse(**updated)


@router.post("/{review_id}/snooze", response_model=ReviewItemResponse)
def snooze_review(
    review_id: str,
    req: ReviewSnoozeRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> ReviewItemResponse:
    """Snooze a review item for N days."""
    item = get_review_item(user["id"], review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    new_due = date.fromordinal(date.today().toordinal() + req.days).isoformat()
    update_review_item(
        review_id=review_id,
        due_date=new_due,
        interval_days=item["interval_days"],
        ease_factor=item["ease_factor"],
        review_count=item["review_count"],
        status="pending",
    )

    updated = get_review_item_with_question(user["id"], review_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Review item disappeared after update")
    return ReviewItemResponse(**updated)


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(
    review_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> None:
    """Dismiss a review item from the queue."""
    item = get_review_item(user["id"], review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    dismiss_review_item(review_id)
