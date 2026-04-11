"""Anonymous session management.

Issues signed JWTs for anonymous users so they can try the platform
without GitHub OAuth. Anonymous users get a real User row with a
negative github_id (real GitHub IDs are always positive).
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.config import settings

# Anonymous tokens use HS256 signed with the same secret as NextAuth
_ALGORITHM = "HS256"
_TOKEN_TTL = timedelta(hours=24)

# Negative range for anonymous github_id (real GitHub IDs are always > 0)
_ANON_ID_MIN = -(2**53)
_ANON_ID_MAX = -1


def create_anonymous_token(user_id: uuid.UUID) -> str:
    """Create a signed JWT for an anonymous session."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": "anonymous",
        "iat": now,
        "exp": now + _TOKEN_TTL,
    }
    return str(jwt.encode(payload, settings.nextauth_secret, algorithm=_ALGORITHM))


def decode_anonymous_token(token: str) -> dict[str, str] | None:
    """Verify and decode an anonymous JWT. Returns payload or None."""
    try:
        payload: dict[str, str] = jwt.decode(
            token, settings.nextauth_secret, algorithms=[_ALGORITHM]
        )
        if payload.get("type") != "anonymous":
            return None
        return payload
    except JWTError:
        return None


async def create_anonymous_user(db: AsyncSession) -> User:
    """Create a User row with a random negative github_id for anonymous access."""
    github_id = random.randint(_ANON_ID_MIN, _ANON_ID_MAX)
    user = User(
        github_id=github_id,
        github_username="anonymous",
        email=None,
        avatar_url=None,
    )
    db.add(user)
    await db.flush()
    return user
