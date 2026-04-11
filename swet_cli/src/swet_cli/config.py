"""Configuration loaded from environment variables and .env file."""

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
class Config:
    """Application configuration."""

    anthropic_api_key: str
    db_path: Path
    generation_model: str = "claude-opus-4-6"
    grading_model: str = "claude-sonnet-4-6"
    # When set, routes requests through an OpenAI-compatible proxy (e.g. claude-max-api)
    llm_base_url: str | None = None


def _default_db_path() -> Path:
    """XDG-compliant default database path."""
    data_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_dir / "swet_cli" / "swet.db"


# Lazy singleton so we can import config early but only fail when actually used
_config: Config | None = None


def get_config() -> Config:
    """Load and return the application config (cached after first call)."""
    global _config  # noqa: PLW0603
    if _config is not None:
        return _config

    _find_and_load_dotenv()

    llm_base_url = os.environ.get("SWET_CLI_BASE_URL", "")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key and not llm_base_url:
        print("Error: ANTHROPIC_API_KEY environment variable is required.", file=sys.stderr)
        print("Or set SWET_CLI_BASE_URL to use a proxy (e.g. http://localhost:3456/v1).", file=sys.stderr)
        print("See .env.example for details.", file=sys.stderr)
        sys.exit(1)

    db_path_str = os.environ.get("SWET_CLI_DB_PATH")
    db_path = Path(db_path_str) if db_path_str else _default_db_path()

    # Default models depend on backend: proxy uses OpenAI-style names
    default_gen_model = "claude-opus-4" if llm_base_url else "claude-opus-4-6"
    default_grade_model = "claude-sonnet-4" if llm_base_url else "claude-sonnet-4-6"

    _config = Config(
        anthropic_api_key=api_key or "not-needed",
        db_path=db_path,
        generation_model=os.environ.get("SWET_CLI_GEN_MODEL", default_gen_model),
        grading_model=os.environ.get("SWET_CLI_GRADE_MODEL", default_grade_model),
        llm_base_url=llm_base_url or None,
    )
    return _config
