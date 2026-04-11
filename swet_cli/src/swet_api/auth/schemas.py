"""Pydantic schemas for auth requests and responses."""

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """Registration with email or mobile (at least one required)."""

    email: str | None = None
    mobile: str | None = None


class OTPSendRequest(BaseModel):
    """Request to send OTP. Provide the same email or mobile used for registration."""

    email: str | None = None
    mobile: str | None = None


class OTPVerifyRequest(BaseModel):
    """Verify OTP code to get JWT tokens."""

    email: str | None = None
    mobile: str | None = None
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class RefreshRequest(BaseModel):
    """Request to refresh an access token."""

    refresh_token: str


class TokenResponse(BaseModel):
    """JWT token pair returned after successful auth."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str
