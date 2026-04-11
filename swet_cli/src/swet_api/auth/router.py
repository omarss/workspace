"""Auth API router: register, send OTP, verify OTP, refresh token."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status

from swet_api.auth.jwt import create_access_token, create_refresh_token, decode_token, hash_token
from swet_api.auth.otp import generate_otp, hash_otp, verify_otp
from swet_api.auth.providers import get_otp_provider
from swet_api.auth.schemas import (
    MessageResponse,
    OTPSendRequest,
    OTPVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from swet_api.config import get_api_config
from swet_api.db import (
    create_user,
    get_latest_otp,
    get_refresh_token,
    get_user_by_email,
    get_user_by_mobile,
    mark_otp_verified,
    mark_user_verified,
    revoke_refresh_token,
    save_otp,
    save_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_mobile(mobile: str) -> str:
    """Normalize a mobile number to E.164 format.

    Strips spaces/dashes. Numbers starting with 0 are assumed KSA (+966).
    """
    mobile = mobile.strip().replace(" ", "").replace("-", "")
    if mobile.startswith("0") and not mobile.startswith("00"):
        mobile = "+966" + mobile[1:]
    elif mobile.startswith("00"):
        mobile = "+" + mobile[2:]
    elif not mobile.startswith("+"):
        mobile = "+" + mobile
    return mobile


def _find_user(email: str | None, mobile: str | None) -> dict | None:
    """Find a user by email or mobile."""
    if email:
        return get_user_by_email(email)
    if mobile:
        return get_user_by_mobile(mobile)
    return None


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest) -> MessageResponse:
    """Register a new user with email or mobile number.

    At least one of email or mobile is required. If the user already exists,
    returns a message suggesting to request an OTP instead.
    """
    if req.mobile:
        req.mobile = _normalize_mobile(req.mobile)
    if not req.email and not req.mobile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either email or mobile is required",
        )

    # Check if user already exists
    existing = _find_user(req.email, req.mobile)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already registered. Request an OTP to sign in.",
        )

    create_user(email=req.email, mobile=req.mobile)
    return MessageResponse(message="Registered successfully. Request an OTP to verify your account.")


@router.post("/otp/send", response_model=MessageResponse)
def send_otp(req: OTPSendRequest) -> MessageResponse:
    """Send an OTP to the user's email or mobile.

    Auto-registers the user if they don't exist yet.
    The OTP expires after the configured TTL (default 5 minutes).
    """
    if req.mobile:
        req.mobile = _normalize_mobile(req.mobile)
    if not req.email and not req.mobile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either email or mobile is required",
        )

    user = _find_user(req.email, req.mobile)
    if user is None:
        # Auto-register on first OTP request
        create_user(email=req.email, mobile=req.mobile)
        user = _find_user(req.email, req.mobile)

    config = get_api_config()
    destination = req.email or req.mobile or ""
    provider = get_otp_provider()

    if provider.manages_verification:
        # Provider handles OTP generation and delivery (e.g. Twilio Verify).
        # Save a placeholder OTP record so verify_otp_endpoint knows who requested it.
        expires_at = (datetime.now(UTC) + timedelta(seconds=config.otp_ttl_seconds)).isoformat()
        save_otp(user_id=user["id"], code_hash="managed_by_provider", expires_at=expires_at)
        provider.send(destination, "")
    else:
        # We generate the OTP, store its hash, and send via the provider.
        code = generate_otp()
        code_hashed = hash_otp(code)
        expires_at = (datetime.now(UTC) + timedelta(seconds=config.otp_ttl_seconds)).isoformat()
        save_otp(user_id=user["id"], code_hash=code_hashed, expires_at=expires_at)
        provider.send(destination, code)

    return MessageResponse(message="OTP sent successfully")


@router.post("/otp/verify", response_model=TokenResponse)
def verify_otp_endpoint(req: OTPVerifyRequest) -> TokenResponse:
    """Verify an OTP and return JWT access + refresh tokens.

    This also marks the user as verified if they haven't been verified yet.
    """
    if req.mobile:
        req.mobile = _normalize_mobile(req.mobile)
    if not req.email and not req.mobile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either email or mobile is required",
        )

    user = _find_user(req.email, req.mobile)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    otp_record = get_latest_otp(user["id"])
    if otp_record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending OTP. Request a new one.",
        )

    # Check expiry
    expires_at = datetime.fromisoformat(otp_record["expires_at"])
    if datetime.now(UTC) > expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP expired. Request a new one.",
        )

    # Verify the code — delegate to provider or check our own hash
    provider = get_otp_provider()
    destination = req.email or req.mobile or ""
    if provider.manages_verification:
        if not provider.verify(destination, req.code):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP code",
            )
    else:
        if not verify_otp(req.code, otp_record["code_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP code",
            )

    # Mark OTP as used and user as verified
    mark_otp_verified(otp_record["id"])
    if not user["is_verified"]:
        mark_user_verified(user["id"])

    # Generate tokens
    access_token = create_access_token(user["id"])
    refresh_token = create_refresh_token(user["id"])

    # Store refresh token hash
    config = get_api_config()
    refresh_expires = (datetime.now(UTC) + timedelta(days=config.jwt_refresh_ttl_days)).isoformat()
    save_refresh_token(
        user_id=user["id"],
        token_hash=hash_token(refresh_token),
        expires_at=refresh_expires,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(req: RefreshRequest) -> TokenResponse:
    """Refresh an access token using a valid refresh token."""
    payload = decode_token(req.refresh_token, expected_type="refresh")
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_id = payload["sub"]

    # Check if the refresh token is in the database, not revoked, and belongs to this user
    token_hash = hash_token(req.refresh_token)
    token_record = get_refresh_token(token_hash)
    if token_record is None or token_record["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked or not found",
        )

    # Revoke the old refresh token (rotation)
    revoke_refresh_token(token_record["id"])

    # Issue new tokens
    new_access = create_access_token(user_id)
    new_refresh = create_refresh_token(user_id)

    config = get_api_config()
    refresh_expires = (datetime.now(UTC) + timedelta(days=config.jwt_refresh_ttl_days)).isoformat()
    save_refresh_token(
        user_id=user_id,
        token_hash=hash_token(new_refresh),
        expires_at=refresh_expires,
    )

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)
