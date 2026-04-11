"""Onboarding service for profile management."""

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.errors import ConflictError, NotFoundError
from src.onboarding.models import UserProfile
from src.onboarding.schemas import ProfileCreateRequest, ProfileUpdateRequest


def compute_config_hash(
    role: str,
    interests: list[str],
    languages: list[str],
    frameworks: list[str],
) -> str:
    """Compute a deterministic SHA-256 hash of the user's configuration.

    Used for question pool cache lookup - users with identical configs
    share the same question pools.
    """
    config = {
        "role": role,
        "interests": sorted(interests),
        "languages": sorted(languages),
        "frameworks": sorted(frameworks),
    }
    config_str = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(config_str.encode()).hexdigest()


async def get_profile(db: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    """Get a user's profile."""
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    return result.scalar_one_or_none()


async def create_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: ProfileCreateRequest,
) -> UserProfile:
    """Create a new user profile during onboarding."""
    existing = await get_profile(db, user_id)
    if existing:
        raise ConflictError("Profile already exists. Use PUT to update.")

    technologies = data.technologies.model_dump()
    config_hash = compute_config_hash(
        role=data.primary_role,
        interests=data.interests,
        languages=technologies.get("languages", []),
        frameworks=technologies.get("frameworks", []),
    )

    profile = UserProfile(
        user_id=user_id,
        primary_role=data.primary_role,
        interests=data.interests,
        technologies=technologies,
        experience_years=data.experience_years,
        config_hash=config_hash,
    )
    db.add(profile)
    await db.flush()
    return profile


async def update_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: ProfileUpdateRequest,
) -> UserProfile:
    """Update an existing user profile."""
    profile = await get_profile(db, user_id)
    if not profile:
        raise NotFoundError("UserProfile")

    if data.primary_role is not None:
        profile.primary_role = data.primary_role
    if data.interests is not None:
        profile.interests = data.interests
    if data.technologies is not None:
        profile.technologies = data.technologies.model_dump()
    if data.experience_years is not None:
        profile.experience_years = data.experience_years

    # Recompute config hash
    technologies = profile.technologies
    profile.config_hash = compute_config_hash(
        role=profile.primary_role,
        interests=profile.interests,
        languages=technologies.get("languages", []),
        frameworks=technologies.get("frameworks", []),
    )

    await db.flush()
    return profile


def get_onboarding_options() -> dict[str, list[str]]:
    """Return available options for the onboarding form."""
    return {
        "roles": [
            "backend",
            "frontend",
            "fullstack",
            "mobile",
            "devops",
            "data",
            "ml",
            "security",
            "qa",
            "gamedev",
        ],
        "interests": [
            "web_development",
            "mobile_development",
            "cloud_infrastructure",
            "data_engineering",
            "machine_learning",
            "security",
            "distributed_systems",
            "embedded_systems",
            "game_development",
            "developer_tools",
        ],
        "languages": [
            "python",
            "javascript",
            "typescript",
            "java",
            "csharp",
            "go",
            "rust",
            "cpp",
            "ruby",
            "swift",
            "kotlin",
            "php",
            "scala",
            "elixir",
        ],
        "frameworks": [
            "react",
            "nextjs",
            "vue",
            "angular",
            "svelte",
            "django",
            "fastapi",
            "flask",
            "spring",
            "express",
            "nestjs",
            "rails",
            "dotnet",
            "phoenix",
            "gin",
            "actix",
        ],
    }
