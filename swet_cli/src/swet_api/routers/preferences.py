"""Preferences API router."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from swet_api.auth.dependencies import get_current_user
from swet_api.auth.schemas import MessageResponse
from swet_api.db import clear_user_data, get_user_preferences, reset_user_levels, save_user_preferences
from swet_api.schemas import PreferencesRequest, PreferencesResponse

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesResponse)
def get_preferences(user: Annotated[dict, Depends(get_current_user)]) -> PreferencesResponse:
    """Get the current user's preferences."""
    prefs = get_user_preferences(user["id"])
    if prefs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No preferences set. Use PUT /preferences to configure.",
        )
    return PreferencesResponse(**prefs)


@router.put("", response_model=PreferencesResponse)
def update_preferences(
    req: PreferencesRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> PreferencesResponse:
    """Set or update the current user's preferences."""
    from swet_cli.data import QUESTION_FORMATS, ROLES

    # Validate roles
    for r in req.roles:
        if r not in ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role '{r}'",
            )
    if not req.roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one role is required",
        )

    # Validate formats if provided
    if req.preferred_formats:
        for f in req.preferred_formats:
            if f not in QUESTION_FORMATS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid format '{f}'",
                )

    # Validate question length
    valid_lengths = ("concise", "standard", "detailed")
    if req.question_length not in valid_lengths:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid question_length '{req.question_length}'. Choose from: {', '.join(valid_lengths)}",
        )

    save_user_preferences(
        user_id=user["id"],
        roles=req.roles,
        languages=req.languages,
        frameworks=req.frameworks,
        preferred_formats=req.preferred_formats,
        question_length=req.question_length,
    )

    prefs = get_user_preferences(user["id"])
    return PreferencesResponse(**prefs)


@router.post("/reset-level", response_model=MessageResponse)
def reset_level(user: Annotated[dict, Depends(get_current_user)]) -> MessageResponse:
    """Reset all competency levels and assessment data. Keeps preferences, questions, and history."""
    reset_user_levels(user["id"])
    return MessageResponse(message="Levels and assessments reset. You can re-assess from the Today page.")


@router.post("/clear-data", response_model=MessageResponse)
def clear_data(user: Annotated[dict, Depends(get_current_user)]) -> MessageResponse:
    """Delete all training data. Keeps account and preferences."""
    clear_user_data(user["id"])
    return MessageResponse(message="All training data cleared.")
