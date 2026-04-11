"""CLI local configuration management.

Stores user preferences and API settings in ~/.swet/config.json,
enabling the CLI to work standalone without PostgreSQL.
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

CONFIG_DIR = Path.home() / ".swet"
CONFIG_FILE = CONFIG_DIR / "config.json"


class CLIProfile(BaseModel):
    """User's engineering profile for question targeting."""

    primary_role: str = ""
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    experience_years: int = 0
    interests: list[str] = Field(default_factory=list)


class CLIConfig(BaseModel):
    """Full CLI configuration persisted to ~/.swet/config.json."""

    # API key: env var ANTHROPIC_API_KEY takes precedence over this field
    anthropic_api_key: str = ""
    llm_base_url: str = ""
    llm_api_key: str = "not-needed"
    llm_generation_model: str = "claude-sonnet-4-6"
    llm_grading_model: str = "claude-sonnet-4-6"
    profile: CLIProfile = Field(default_factory=CLIProfile)

    def get_api_key(self) -> str:
        """Return API key from env var or config, preferring env var."""
        return os.environ.get("ANTHROPIC_API_KEY", "") or self.anthropic_api_key

    def has_api_key(self) -> bool:
        """Check if an API key is available from any source."""
        return bool(self.get_api_key())

    def has_profile(self) -> bool:
        """Check if the user has completed profile setup."""
        return bool(self.profile.primary_role and self.profile.languages)


def ensure_config_dir() -> None:
    """Create ~/.swet/ directory with secure permissions if it doesn't exist."""
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def load_config() -> CLIConfig:
    """Load config from ~/.swet/config.json, returning defaults if missing."""
    if not CONFIG_FILE.exists():
        return CLIConfig()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return CLIConfig.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return CLIConfig()


def save_config(config: CLIConfig) -> None:
    """Save config to ~/.swet/config.json with secure permissions."""
    ensure_config_dir()
    content = config.model_dump_json(indent=2)
    CONFIG_FILE.write_text(content, encoding="utf-8")
    # Restrict permissions since the file may contain an API key
    CONFIG_FILE.chmod(0o600)


def patch_settings(config: CLIConfig) -> None:
    """Override src.config.settings singleton with CLI values.

    Must be called BEFORE importing src.questions.generator or
    src.scoring.grader, since they read settings at module level.
    """
    import src.config

    patched = src.config.Settings(
        anthropic_api_key=config.get_api_key(),
        llm_base_url=config.llm_base_url,
        llm_api_key=config.llm_api_key,
        llm_generation_model=config.llm_generation_model,
        llm_grading_model=config.llm_grading_model,
        # Safe defaults for fields we don't use in CLI mode
        database_url="sqlite+aiosqlite:///:memory:",
        nextauth_secret="cli-mode-unused",
    )
    src.config.settings = patched
