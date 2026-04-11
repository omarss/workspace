"""API-specific configuration loaded from environment variables."""

import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _find_and_load_dotenv() -> None:
    """Load .env from project root or ~/.config/swet_cli/."""
    candidates = [
        Path.cwd() / ".env",
        Path.home() / ".config" / "swet_cli" / ".env",
    ]
    for path in candidates:
        if path.exists():
            load_dotenv(path)
            return


@dataclass(frozen=True)
class APIConfig:
    """API server configuration."""

    # JWT
    jwt_secret: str
    jwt_access_ttl_minutes: int = 60
    jwt_refresh_ttl_days: int = 30

    # OTP
    otp_ttl_seconds: int = 300  # 5 minutes
    otp_provider: str = "console"  # "console", "twilio", "sendgrid"

    # Database
    db_path: Path = Path.home() / ".local" / "share" / "swet_api" / "swet_api.db"

    # Twilio (optional, for SMS OTP or Verify)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_verify_service_sid: str = ""

    # SendGrid (optional, for email OTP)
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""


_config: APIConfig | None = None


def get_api_config() -> APIConfig:
    """Load and return the API config (cached after first call)."""
    global _config  # noqa: PLW0603
    if _config is not None:
        return _config

    _find_and_load_dotenv()

    jwt_secret = os.environ.get("SWET_API_JWT_SECRET", "")
    if not jwt_secret:
        # Generate a random secret for development; warn the user
        jwt_secret = secrets.token_urlsafe(32)
        print(
            "Warning: SWET_API_JWT_SECRET not set. Using a random secret "
            "(tokens will be invalid after server restart).",
            file=sys.stderr,
        )

    db_path_str = os.environ.get("SWET_API_DB_PATH")
    db_path = Path(db_path_str) if db_path_str else APIConfig.db_path

    _config = APIConfig(
        jwt_secret=jwt_secret,
        jwt_access_ttl_minutes=int(os.environ.get("SWET_API_ACCESS_TTL_MINUTES", "60")),
        jwt_refresh_ttl_days=int(os.environ.get("SWET_API_REFRESH_TTL_DAYS", "30")),
        otp_ttl_seconds=int(os.environ.get("SWET_API_OTP_TTL_SECONDS", "300")),
        otp_provider=os.environ.get("SWET_API_OTP_PROVIDER", "console"),
        db_path=db_path,
        twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        twilio_phone_number=os.environ.get("TWILIO_PHONE_NUMBER", ""),
        twilio_verify_service_sid=os.environ.get("TWILIO_VERIFY_SERVICE_SID", ""),
        sendgrid_api_key=os.environ.get("SENDGRID_API_KEY", ""),
        sendgrid_from_email=os.environ.get("SENDGRID_FROM_EMAIL", ""),
    )
    return _config
