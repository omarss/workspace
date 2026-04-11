"""User-scoped adaptive algorithm wrappers for the Slack bot.

Thin adapter around the shared adaptive module in swet_cli.adaptive.
Binds user_id into a UserScopedDB adapter and delegates all logic.
"""

import swet_slack.db as slack_db
from swet_cli.adaptive import (
    AdaptiveDB,
)
from swet_cli.adaptive import (
    adapt_difficulty as _adapt_difficulty,
)
from swet_cli.adaptive import (
    pick_competency as _pick_competency,
)
from swet_cli.adaptive import (
    pick_format as _pick_format,
)
from swet_cli.adaptive import (
    should_generate_new as _should_generate_new,
)
from swet_cli.adaptive import (
    update_adaptive_level as _update_adaptive_level,
)
from swet_cli.adaptive_db import UserScopedDB
from swet_cli.data import Competency


def _db(user_id: str) -> AdaptiveDB:
    """Create a user-scoped DB adapter for the Slack database."""
    return UserScopedDB(user_id, slack_db)


def pick_competency(user_id: str, roles: list[str], base_difficulty: int) -> Competency:
    """Pick a competency using user-scoped adaptive selection."""
    return _pick_competency(_db(user_id), roles, base_difficulty)


def pick_format(
    user_id: str,
    competency_slug: str,
    difficulty: int,
    preferred_formats: list[str] | None = None,
) -> str:
    """Pick a question format using user-scoped adaptive selection."""
    return _pick_format(_db(user_id), competency_slug, difficulty, preferred_formats)


def adapt_difficulty(user_id: str, competency_slug: str, base_difficulty: int) -> int:
    """Adapt difficulty per-competency using user-scoped ELO."""
    return _adapt_difficulty(_db(user_id), competency_slug, base_difficulty)


def update_adaptive_level(user_id: str, competency_slug: str, score: float, difficulty: int) -> int:
    """Update user-scoped ELO rating after an attempt. Returns new level."""
    return _update_adaptive_level(_db(user_id), competency_slug, score, difficulty)


def should_generate_new(
    user_id: str,
    competency_slug: str,
    question_format: str,
    difficulty: int,
) -> bool:
    """Check if new questions should be generated for this user."""
    return _should_generate_new(_db(user_id), competency_slug, question_format, difficulty)
