"""Shared dependency injection functions."""

import uuid

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.auth.service import get_user_by_id, upsert_user
from src.database import get_db
from src.errors import UnauthorizedError


async def _try_anonymous_auth(request: Request, db: AsyncSession) -> User | None:
    """Check for a valid anonymous Bearer token and return the user if found."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer ") :]

    # Lazy import to avoid circular deps at module level
    from src.auth.anonymous import decode_anonymous_token

    payload = decode_anonymous_token(token)
    if payload is None:
        return None

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None

    return await get_user_by_id(db, user_id)


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from an anonymous Bearer token
    or the NextAuth JWT (checked in that order).

    Anonymous tokens are checked first via the Authorization header.
    If not present, the middleware-injected NextAuth JWT is used as fallback.
    """
    # 1. Try anonymous Bearer token
    user = await _try_anonymous_auth(request, db)
    if user is not None:
        if not user.is_active:
            raise UnauthorizedError("User account is deactivated")
        return user

    # 2. Fall back to NextAuth JWT (injected by fastapi-nextauth-jwt middleware)
    jwt_payload = getattr(request.state, "jwt", None)
    if jwt_payload is None:
        raise UnauthorizedError("No valid authentication token found")

    # NextAuth GitHub provider puts the GitHub profile in the JWT
    github_id = jwt_payload.get("github_id")
    if github_id is None:
        # Try sub field (NextAuth v5 default)
        sub = jwt_payload.get("sub")
        if sub is None:
            raise UnauthorizedError("Invalid token: missing user identifier")
        try:
            github_id = int(sub)
        except (ValueError, TypeError) as err:
            raise UnauthorizedError("Invalid token: malformed user identifier") from err

    # Upsert user on every request to keep profile data fresh
    user = await upsert_user(
        db=db,
        github_id=github_id,
        github_username=jwt_payload.get("name", jwt_payload.get("login", "")),
        email=jwt_payload.get("email"),
        avatar_url=jwt_payload.get("picture", jwt_payload.get("image")),
    )

    if not user.is_active:
        raise UnauthorizedError("User account is deactivated")

    return user
