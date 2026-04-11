"""JWT token creation and validation."""

import hashlib
from datetime import UTC, datetime, timedelta

import jwt

from swet_api.config import get_api_config


def create_access_token(user_id: str) -> str:
    """Create a JWT access token for a user."""
    config = get_api_config()
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=config.jwt_access_ttl_minutes),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token for a user."""
    config = get_api_config()
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(days=config.jwt_refresh_ttl_days),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def decode_token(token: str, expected_type: str = "access") -> dict | None:
    """Decode and validate a JWT token. Returns the payload or None if invalid."""
    config = get_api_config()
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != expected_type:
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def hash_token(token: str) -> str:
    """Hash a token for storage (used for refresh tokens)."""
    return hashlib.sha256(token.encode()).hexdigest()
