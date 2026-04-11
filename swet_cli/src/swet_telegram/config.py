"""Telegram bot configuration loaded from environment variables."""

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
class TelegramConfig:
    """Telegram bot configuration."""

    bot_token: str
    db_path: Path = Path.home() / ".local" / "share" / "swet_telegram" / "swet_telegram.db"


_config: TelegramConfig | None = None


def get_telegram_config() -> TelegramConfig:
    """Load and return the Telegram config (cached after first call)."""
    global _config  # noqa: PLW0603
    if _config is not None:
        return _config

    _find_and_load_dotenv()

    bot_token = os.environ.get("SWET_TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print(
            "Error: SWET_TELEGRAM_BOT_TOKEN is required. Get one from @BotFather on Telegram.",
            file=sys.stderr,
        )
        sys.exit(1)

    db_path_str = os.environ.get("SWET_TELEGRAM_DB_PATH")
    db_path = Path(db_path_str) if db_path_str else TelegramConfig.db_path

    _config = TelegramConfig(bot_token=bot_token, db_path=db_path)
    return _config
