"""Auth service for user management."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User


async def get_user_by_github_id(db: AsyncSession, github_id: int) -> User | None:
    """Find a user by their GitHub ID."""
    result = await db.execute(select(User).where(User.github_id == github_id))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Find a user by their internal UUID."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def upsert_user(
    db: AsyncSession,
    github_id: int,
    github_username: str,
    email: str | None = None,
    avatar_url: str | None = None,
) -> User:
    """Create or update a user from GitHub OAuth data."""
    user = await get_user_by_github_id(db, github_id)

    if user is None:
        user = User(
            github_id=github_id,
            github_username=github_username,
            email=email,
            avatar_url=avatar_url,
        )
        db.add(user)
    else:
        # Update fields that may have changed
        user.github_username = github_username
        if email is not None:
            user.email = email
        if avatar_url is not None:
            user.avatar_url = avatar_url

    await db.flush()
    return user
