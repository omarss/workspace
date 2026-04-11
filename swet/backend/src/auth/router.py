"""Auth API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.anonymous import create_anonymous_token, create_anonymous_user
from src.auth.models import User
from src.auth.schemas import AnonymousSessionResponse, UserResponse
from src.database import get_db
from src.dependencies import get_current_user

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get the currently authenticated user's info."""
    return current_user


@router.post("/anonymous", response_model=AnonymousSessionResponse)
async def create_anonymous_session(
    db: AsyncSession = Depends(get_db),
) -> AnonymousSessionResponse:
    """Create an anonymous session for trying the platform without OAuth."""
    user = await create_anonymous_user(db)
    token = create_anonymous_token(user.id)
    return AnonymousSessionResponse(
        token=token,
        user=UserResponse.model_validate(user),
    )
