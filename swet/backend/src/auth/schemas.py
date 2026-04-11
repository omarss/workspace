"""Auth request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class UserResponse(BaseModel):
    """User info returned from /me endpoint."""

    id: uuid.UUID
    github_id: int
    github_username: str
    email: str | None
    avatar_url: str | None
    is_active: bool
    onboarding_completed: bool
    created_at: datetime
    is_anonymous: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _compute_is_anonymous(self) -> "UserResponse":
        """Infer anonymous status from negative github_id."""
        self.is_anonymous = self.github_id < 0
        return self


class AnonymousSessionResponse(BaseModel):
    """Response from the anonymous session endpoint."""

    token: str
    user: UserResponse


class AuthCallbackRequest(BaseModel):
    """Request body for auth callback (not typically needed since JWT is in header)."""

    pass
