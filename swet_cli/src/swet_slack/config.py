"""Slack bot configuration loaded from environment variables."""

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
class SlackConfig:
    """Slack bot configuration."""

    bot_token: str
    app_token: str
    db_path: Path = Path.home() / ".local" / "share" / "swet_slack" / "swet_slack.db"


_config: SlackConfig | None = None


def get_slack_config() -> SlackConfig:
    """Load and return the Slack config (cached after first call)."""
    global _config  # noqa: PLW0603
    if _config is not None:
        return _config

    _find_and_load_dotenv()

    bot_token = os.environ.get("SWET_SLACK_BOT_TOKEN", "")
    if not bot_token:
        print(
            "Error: SWET_SLACK_BOT_TOKEN is required. Create a Slack app at https://api.slack.com/apps.",
            file=sys.stderr,
        )
        sys.exit(1)

    app_token = os.environ.get("SWET_SLACK_APP_TOKEN", "")
    if not app_token:
        print(
            "Error: SWET_SLACK_APP_TOKEN is required for Socket Mode. Enable Socket Mode in your Slack app settings.",
            file=sys.stderr,
        )
        sys.exit(1)

    db_path_str = os.environ.get("SWET_SLACK_DB_PATH")
    db_path = Path(db_path_str) if db_path_str else SlackConfig.db_path

    _config = SlackConfig(bot_token=bot_token, app_token=app_token, db_path=db_path)
    return _config
