"""DB adapters for the shared adaptive algorithm.

Each adapter wraps a user-scoped DB module to satisfy the AdaptiveDB protocol.
The user_id is bound at construction, not passed to each method.
"""

from __future__ import annotations

from types import ModuleType


class UserScopedDB:
    """Wraps a user-scoped DB module (API, Telegram, Slack, WhatsApp) into AdaptiveDB.

    Each bot/API DB module uses `get_user_*` prefixed functions with user_id
    as the first parameter. This adapter binds the user_id and presents the
    unprefixed interface that AdaptiveDB expects.
    """

    def __init__(self, user_id: str, db: ModuleType) -> None:
        self._user_id = user_id
        self._db = db

    def get_competency_level(self, competency_slug: str) -> dict | None:
        return self._db.get_user_competency_level(self._user_id, competency_slug)

    def get_all_competency_levels(self) -> dict[str, dict]:
        return self._db.get_user_competency_levels(self._user_id)

    def get_competency_performance(self) -> list[dict]:
        return self._db.get_user_competency_performance(self._user_id)

    def get_competency_rolling_avg(self, competency_slug: str, n: int = 5) -> float | None:
        return self._db.get_user_competency_rolling_avg(self._user_id, competency_slug, n)

    def get_difficulty_override(self, competency_slug: str) -> int | None:
        return self._db.get_user_difficulty_override(self._user_id, competency_slug)

    def get_format_performance(self, competency_slug: str) -> list[dict]:
        return self._db.get_user_format_performance(self._user_id, competency_slug)

    def get_queued_question(
        self,
        competency_slug: str,
        question_format: str,
        difficulty: int,
    ) -> dict | None:
        return self._db.get_user_queued_question(
            self._user_id,
            competency_slug=competency_slug,
            question_format=question_format,
            difficulty=difficulty,
        )

    def get_recent_competency_slugs(self, n: int = 10) -> list[str]:
        return self._db.get_user_recent_competency_slugs(self._user_id, n)

    def get_recent_question_topics(self, n: int = 20) -> list[str]:
        return self._db.get_user_recent_question_topics(self._user_id, n)

    def update_competency_level(
        self,
        competency_slug: str,
        estimated_level: int,
        elo_rating: float,
        consecutive_high: int,
        consecutive_low: int,
        total_attempts: int,
    ) -> None:
        self._db.update_user_competency_level(
            self._user_id, competency_slug, estimated_level, elo_rating,
            consecutive_high, consecutive_low, total_attempts,
        )


class SingletonDB:
    """Wraps the CLI's singleton (non-user-scoped) DB module into AdaptiveDB.

    The CLI DB uses unprefixed functions without user_id. This adapter
    delegates directly.
    """

    def __init__(self, db: ModuleType) -> None:
        self._db = db

    def get_competency_level(self, competency_slug: str) -> dict | None:
        return self._db.get_competency_level(competency_slug)

    def get_all_competency_levels(self) -> dict[str, dict]:
        return self._db.get_all_competency_levels()

    def get_competency_performance(self) -> list[dict]:
        return self._db.get_competency_performance()

    def get_competency_rolling_avg(self, competency_slug: str, n: int = 5) -> float | None:
        return self._db.get_competency_rolling_avg(competency_slug, n)

    def get_difficulty_override(self, competency_slug: str) -> int | None:
        return self._db.get_difficulty_override(competency_slug)

    def get_format_performance(self, competency_slug: str) -> list[dict]:
        return self._db.get_format_performance(competency_slug)

    def get_queued_question(
        self,
        competency_slug: str,
        question_format: str,
        difficulty: int,
    ) -> dict | None:
        return self._db.get_queued_question(
            competency_slug=competency_slug,
            question_format=question_format,
            difficulty=difficulty,
        )

    def get_recent_competency_slugs(self, n: int = 10) -> list[str]:
        return self._db.get_recent_competency_slugs(n)

    def get_recent_question_topics(self, n: int = 20) -> list[str]:
        return self._db.get_recent_question_topics(n)

    def update_competency_level(
        self,
        competency_slug: str,
        estimated_level: int,
        elo_rating: float,
        consecutive_high: int,
        consecutive_low: int,
        total_attempts: int,
    ) -> None:
        self._db.update_competency_level(
            competency_slug, estimated_level, elo_rating,
            consecutive_high, consecutive_low, total_attempts,
        )
