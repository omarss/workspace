"""Onboarding API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.database import get_db
from src.dependencies import get_current_user
from src.errors import NotFoundError
from src.onboarding.schemas import (
    OnboardingOptionsResponse,
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)
from src.onboarding.service import (
    create_profile,
    get_onboarding_options,
    get_profile,
    update_profile,
)

router = APIRouter()


@router.get("/options", response_model=OnboardingOptionsResponse)
async def options() -> dict[str, list[str]]:
    """Get available options for the onboarding form."""
    return get_onboarding_options()


@router.post("/profile", response_model=ProfileResponse, status_code=201)
async def create_user_profile(
    data: ProfileCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """Submit onboarding profile."""
    profile = await create_profile(db, current_user.id, data)
    # Mark onboarding as completed
    current_user.onboarding_completed = True
    await db.flush()
    return ProfileResponse.model_validate(profile)


@router.get("/profile", response_model=ProfileResponse)
async def get_user_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """Get the current user's profile."""
    profile = await get_profile(db, current_user.id)
    if not profile:
        raise NotFoundError("UserProfile")
    return ProfileResponse.model_validate(profile)


@router.put("/profile", response_model=ProfileResponse)
async def update_user_profile(
    data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """Update the user's profile (allowed before first assessment)."""
    profile = await update_profile(db, current_user.id, data)
    return ProfileResponse.model_validate(profile)
