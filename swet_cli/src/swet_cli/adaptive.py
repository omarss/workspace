"""Shared adaptive algorithm for competency selection, format selection, and ELO tracking.

This is the single source of truth for the adaptive algorithm. All entrypoints
(CLI, API, Telegram, Slack, WhatsApp) should use these functions with their own
DB adapter injected via the AdaptiveDB protocol.
"""

import math
import random
from datetime import date
from typing import Protocol

from swet_cli.data import (
    COMPETENCY_BY_SLUG,
    COMPETENCY_SLUGS,
    QUESTION_FORMATS,
    Competency,
    get_role_competency_weights,
)

# --- Algorithm Constants ---

ELO_K_FACTOR = 32
ELO_BASE_RATING = 1000.0
ELO_LEVEL_THRESHOLDS = {
    1: (0, 850),
    2: (850, 1100),
    3: (1100, 1350),
    4: (1350, 1600),
    5: (1600, 2500),
}

PROMOTE_CONSECUTIVE = 3
DEMOTE_CONSECUTIVE = 3
PROMOTE_THRESHOLD = 0.80
DEMOTE_THRESHOLD = 0.35

RECENCY_DECAY_DAYS = 14
UNATTEMPTED_BONUS = 2.0
COVERAGE_BONUS = 1.5
DIVERSITY_PENALTY = 0.3

FORMAT_BASE_WEIGHTS: dict[str, float] = {
    "mcq": 0.30,
    "code_review": 0.18,
    "debugging": 0.18,
    "short_answer": 0.17,
    "design_prompt": 0.17,
}

FORMAT_LEVEL_ADJUSTMENTS: dict[int, dict[str, float]] = {
    1: {"mcq": 0.15, "short_answer": -0.05, "design_prompt": -0.10},
    2: {"mcq": 0.05, "short_answer": 0.0, "design_prompt": -0.05},
    3: {},
    4: {"mcq": -0.10, "code_review": 0.05, "design_prompt": 0.05},
    5: {"mcq": -0.15, "code_review": 0.05, "design_prompt": 0.10},
}

STALENESS_LEVEL_MISMATCH = True


# --- DB Protocol ---


class AdaptiveDB(Protocol):
    """Protocol that any DB adapter must satisfy for the adaptive algorithm.

    Each entrypoint (CLI, API, bots) implements this by wrapping its own
    DB module. For user-scoped DBs, the user_id is bound at construction
    time of the adapter, not passed to each method.
    """

    def get_competency_level(self, competency_slug: str) -> dict | None: ...
    def get_all_competency_levels(self) -> dict[str, dict]: ...
    def get_competency_performance(self) -> list[dict]: ...
    def get_competency_rolling_avg(self, competency_slug: str, n: int = 5) -> float | None: ...
    def get_difficulty_override(self, competency_slug: str) -> int | None: ...
    def get_format_performance(self, competency_slug: str) -> list[dict]: ...
    def get_queued_question(
        self,
        competency_slug: str,
        question_format: str,
        difficulty: int,
    ) -> dict | None: ...
    def get_recent_competency_slugs(self, n: int = 10) -> list[str]: ...
    def get_recent_question_topics(self, n: int = 20) -> list[str]: ...
    def update_competency_level(
        self,
        competency_slug: str,
        estimated_level: int,
        elo_rating: float,
        consecutive_high: int,
        consecutive_low: int,
        total_attempts: int,
    ) -> None: ...


# --- Adaptive Algorithm Functions ---


def pick_competency(db: AdaptiveDB, roles: list[str], base_difficulty: int) -> Competency:
    """Pick a competency using multi-signal weighted selection.

    Blends 5 signals: role emphasis, performance gap (ZPD targeting),
    spaced repetition recency, coverage balancing, and diversity penalty.
    """
    role_weights = get_role_competency_weights(roles)
    performance = db.get_competency_performance()
    perf_by_slug = {p["competency_slug"]: p for p in performance}
    all_levels = db.get_all_competency_levels()
    max_attempts = max((lv.get("total_attempts", 0) for lv in all_levels.values()), default=1) or 1
    recent_slugs = db.get_recent_competency_slugs(n=5)

    today_ordinal = date.today().toordinal()
    final_weights: dict[str, float] = {}

    for slug in COMPETENCY_SLUGS:
        base_w = role_weights.get(slug, 0.02)
        perf = perf_by_slug.get(slug)
        level_data = all_levels.get(slug)

        if perf is None:
            weight = base_w * UNATTEMPTED_BONUS
        else:
            gap_factor = 1.0 + (1.0 - perf["avg_score"])
            recency_factor = 1.0
            if perf["last_attempt_date"]:
                try:
                    last_date = date.fromisoformat(perf["last_attempt_date"][:10])
                    days_since = today_ordinal - last_date.toordinal()
                    recency_factor = 1.0 + (1.0 - math.exp(-days_since / RECENCY_DECAY_DAYS))
                except ValueError:
                    pass

            attempts = level_data["total_attempts"] if level_data else perf["attempt_count"]
            coverage_factor = 1.0 + (COVERAGE_BONUS - 1.0) * (1.0 - attempts / max_attempts)
            weight = base_w * gap_factor * recency_factor * coverage_factor

        if slug in recent_slugs:
            position = recent_slugs.index(slug)
            penalty = DIVERSITY_PENALTY * (1.0 - position / len(recent_slugs))
            weight *= 1.0 - penalty

        final_weights[slug] = max(weight, 0.001)

    slugs = list(final_weights.keys())
    weights = [final_weights[s] for s in slugs]
    chosen_slug = random.choices(slugs, weights=weights, k=1)[0]

    return COMPETENCY_BY_SLUG[chosen_slug]


def pick_format(
    db: AdaptiveDB,
    competency_slug: str,
    difficulty: int,
    preferred_formats: list[str] | None = None,
) -> str:
    """Pick a question format using adaptive selection.

    Adjusts base weights by difficulty level, boosts preferred formats 3x,
    and compensates for weak format performance.
    """
    weights: dict[str, float] = dict(FORMAT_BASE_WEIGHTS)
    level_adj = FORMAT_LEVEL_ADJUSTMENTS.get(difficulty, {})
    for fmt, adj in level_adj.items():
        weights[fmt] = max(0.02, weights.get(fmt, 0.15) + adj)

    if preferred_formats:
        pref_set = set(preferred_formats)
        for fmt in weights:
            if fmt in pref_set:
                weights[fmt] *= 3.0
            else:
                weights[fmt] *= 0.1

    format_perf = db.get_format_performance(competency_slug)
    perf_by_fmt = {fp["format"]: fp for fp in format_perf}

    for fmt in QUESTION_FORMATS:
        fp = perf_by_fmt.get(fmt)
        if fp is not None and fp["attempt_count"] >= 2:
            gap = 1.0 - fp["avg_score"]
            weights[fmt] *= 1.0 + gap * 0.5
        elif fp is None:
            weights[fmt] *= 1.1

    formats = list(weights.keys())
    w_values = [weights[f] for f in formats]
    return random.choices(formats, weights=w_values, k=1)[0]


def adapt_difficulty(db: AdaptiveDB, competency_slug: str, base_difficulty: int) -> int:
    """Adaptively determine difficulty using ELO-like per-competency tracking.

    Priority: explicit override > ELO level > rolling avg > base difficulty.
    """
    override = db.get_difficulty_override(competency_slug)
    if override is not None:
        return override

    level_data = db.get_competency_level(competency_slug)
    if level_data is None:
        rolling_avg = db.get_competency_rolling_avg(competency_slug, n=5)
        if rolling_avg is not None:
            if rolling_avg > PROMOTE_THRESHOLD and base_difficulty < 5:
                return base_difficulty + 1
            if rolling_avg < DEMOTE_THRESHOLD and base_difficulty > 1:
                return base_difficulty - 1
        return base_difficulty

    return level_data["estimated_level"]


def update_adaptive_level(db: AdaptiveDB, competency_slug: str, score: float, difficulty: int) -> int:
    """Update the per-competency adaptive level after an attempt.

    Uses ELO rating system with consecutive-score promotion/demotion.
    Returns the new estimated level (1-5).
    """
    level_data = db.get_competency_level(competency_slug)

    if level_data is None:
        elo_rating = ELO_BASE_RATING
        consecutive_high = 0
        consecutive_low = 0
        total_attempts = 0
        estimated_level = difficulty
    else:
        elo_rating = level_data["elo_rating"]
        consecutive_high = level_data["consecutive_high"]
        consecutive_low = level_data["consecutive_low"]
        total_attempts = level_data["total_attempts"]
        estimated_level = level_data["estimated_level"]

    # ELO update
    difficulty_rating = ELO_LEVEL_THRESHOLDS[difficulty][0] + 150
    expected = 1.0 / (1.0 + 10 ** ((difficulty_rating - elo_rating) / 400))
    elo_rating += ELO_K_FACTOR * (score - expected)
    elo_rating = max(200, min(2200, elo_rating))

    # Track consecutive scores
    if score >= PROMOTE_THRESHOLD:
        consecutive_high += 1
        consecutive_low = 0
    elif score <= DEMOTE_THRESHOLD:
        consecutive_low += 1
        consecutive_high = 0
    else:
        consecutive_high = 0
        consecutive_low = 0

    total_attempts += 1

    # Determine new level from ELO rating
    new_level = estimated_level
    for lvl, (low, high) in ELO_LEVEL_THRESHOLDS.items():
        if low <= elo_rating < high:
            new_level = lvl
            break

    # Consecutive-based promotion/demotion
    if consecutive_high >= PROMOTE_CONSECUTIVE and new_level < 5:
        new_level = min(5, new_level + 1)
        consecutive_high = 0
        level_mid = (ELO_LEVEL_THRESHOLDS[new_level][0] + ELO_LEVEL_THRESHOLDS[new_level][1]) / 2
        elo_rating = max(elo_rating, level_mid)

    if consecutive_low >= DEMOTE_CONSECUTIVE and new_level > 1:
        new_level = max(1, new_level - 1)
        consecutive_low = 0
        level_mid = (ELO_LEVEL_THRESHOLDS[new_level][0] + ELO_LEVEL_THRESHOLDS[new_level][1]) / 2
        elo_rating = min(elo_rating, level_mid)

    # Ensure level stays in valid range
    new_level = max(1, min(5, new_level))

    db.update_competency_level(
        competency_slug=competency_slug,
        estimated_level=new_level,
        elo_rating=elo_rating,
        consecutive_high=consecutive_high,
        consecutive_low=consecutive_low,
        total_attempts=total_attempts,
    )

    return new_level


def should_generate_new(
    db: AdaptiveDB,
    competency_slug: str,
    question_format: str,
    difficulty: int,
) -> bool:
    """Decide whether to call the LLM or serve from the DB cache.

    Regenerates when: no cached question, level mismatch, or >60% topic overlap.
    """
    queued = db.get_queued_question(competency_slug, question_format, difficulty)
    if queued is None:
        return True

    if STALENESS_LEVEL_MISMATCH:
        level_data = db.get_competency_level(competency_slug)
        if level_data is not None:
            current_level = level_data["estimated_level"]
            if queued["difficulty"] != current_level:
                return True

    recent_topics = db.get_recent_question_topics(n=15)
    if queued.get("metadata") and recent_topics:
        meta = queued["metadata"]
        if isinstance(meta, dict) and "topics" in meta:
            q_topics = set(t.lower() for t in meta["topics"])
            recent_set = set(t.lower() for t in recent_topics)
            overlap = len(q_topics & recent_set)
            if q_topics and overlap / len(q_topics) > 0.6:
                return True

    return False
