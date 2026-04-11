"""WhatsApp bot configuration loaded from environment variables."""

import os
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
class WhatsAppConfig:
    """WhatsApp bot configuration via Twilio."""

    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str  # must have whatsapp: prefix
    db_path: Path = Path.home() / ".local" / "share" / "swet_whatsapp" / "swet_whatsapp.db"
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 5000


_config: WhatsAppConfig | None = None


def get_whatsapp_config() -> WhatsAppConfig:
    """Load and return the WhatsApp config (cached after first call)."""
    global _config  # noqa: PLW0603
    if _config is not None:
        return _config

    _find_and_load_dotenv()

    account_sid = os.environ.get("SWET_WHATSAPP_ACCOUNT_SID", "")
    if not account_sid:
        print(
            "Error: SWET_WHATSAPP_ACCOUNT_SID is required. Get one from your Twilio console.",
            file=sys.stderr,
        )
        sys.exit(1)

    auth_token = os.environ.get("SWET_WHATSAPP_AUTH_TOKEN", "")
    if not auth_token:
        print(
            "Error: SWET_WHATSAPP_AUTH_TOKEN is required. Get one from your Twilio console.",
            file=sys.stderr,
        )
        sys.exit(1)

    phone_number = os.environ.get("SWET_WHATSAPP_PHONE_NUMBER", "")
    if not phone_number:
        print(
            "Error: SWET_WHATSAPP_PHONE_NUMBER is required. Set your Twilio WhatsApp sender number.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Ensure whatsapp: prefix is present
    if not phone_number.startswith("whatsapp:"):
        phone_number = f"whatsapp:{phone_number}"

    db_path_str = os.environ.get("SWET_WHATSAPP_DB_PATH")
    db_path = Path(db_path_str) if db_path_str else WhatsAppConfig.db_path

    webhook_host = os.environ.get("SWET_WHATSAPP_HOST", "0.0.0.0")
    webhook_port = int(os.environ.get("SWET_WHATSAPP_PORT", "5000"))

    _config = WhatsAppConfig(
        twilio_account_sid=account_sid,
        twilio_auth_token=auth_token,
        twilio_phone_number=phone_number,
        db_path=db_path,
        webhook_host=webhook_host,
        webhook_port=webhook_port,
    )
    return _config
