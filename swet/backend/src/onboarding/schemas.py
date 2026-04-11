"""Onboarding request/response schemas."""

import uuid
from typing import Any

from pydantic import BaseModel, Field


class TechnologySelection(BaseModel):
    """User's technology selections during onboarding."""

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)


class ProfileCreateRequest(BaseModel):
    """Request to create a user profile during onboarding."""

    primary_role: str = Field(min_length=1, max_length=100)
    interests: list[str] = Field(default_factory=list)
    technologies: TechnologySelection
    experience_years: int | None = Field(default=None, ge=0, le=50)


class ProfileUpdateRequest(BaseModel):
    """Request to update user profile (before first assessment)."""

    primary_role: str | None = Field(default=None, min_length=1, max_length=100)
    interests: list[str] | None = None
    technologies: TechnologySelection | None = None
    experience_years: int | None = Field(default=None, ge=0, le=50)


class ProfileResponse(BaseModel):
    """User profile response."""

    id: uuid.UUID
    user_id: uuid.UUID
    primary_role: str
    interests: list[str]
    technologies: dict[str, Any]
    experience_years: int | None
    config_hash: str | None

    model_config = {"from_attributes": True}


class OnboardingOptionsResponse(BaseModel):
    """Available options for the onboarding form."""

    roles: list[str]
    interests: list[str]
    languages: list[str]
    frameworks: list[str]
