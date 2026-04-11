"""Sophisticated adaptive question generation engine.

Uses a multi-signal algorithm to select competencies, adapt difficulty per-competency,
choose optimal question formats, and intelligently decide when to call the LLM vs
serve from the local question database.

Key design principles:
- Zone of Proximal Development: target ~60-70% success rate for optimal learning
- ELO-like rating per competency for smooth difficulty progression
- Spaced repetition with recency decay and coverage balancing
- Format selection adapts to user's weak formats per competency
- Smart caching: only calls the model when the DB lacks suitable questions
"""

import json
import logging
import math
import random
from datetime import date

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from swet_cli.config import get_config
from swet_cli.data import (
    COMPETENCY_BY_SLUG,
    COMPETENCY_SLUGS,
    DIFFICULTY_TO_LEVEL,
    QUESTION_FORMATS,
    Competency,
    get_role_competency_weights,
)
from swet_cli.db import (
    get_all_competency_levels,
    get_competency_level,
    get_competency_performance,
    get_competency_rolling_avg,
    get_difficulty_override,
    get_format_performance,
    get_queued_question,
    get_recent_competency_slugs,
    get_recent_question_topics,
    update_competency_level,
)
from swet_cli.llm import chat
from swet_cli.models import GeneratedQuestion
from swet_cli.prompts import build_generation_prompt

logger = logging.getLogger(__name__)

# --- Algorithm Constants ---

# ELO-like rating parameters
_ELO_K_FACTOR = 32  # how much a single result shifts the rating
_ELO_BASE_RATING = 1000.0
# Rating thresholds for level transitions (rating ranges per level)
_ELO_LEVEL_THRESHOLDS = {
    1: (0, 850),  # junior
    2: (850, 1100),  # mid
    3: (1100, 1350),  # senior
    4: (1350, 1600),  # staff
    5: (1600, 2500),  # principal
}

# Consecutive score thresholds for level promotion/demotion
_PROMOTE_CONSECUTIVE = 3  # promote after 3 consecutive high scores
_DEMOTE_CONSECUTIVE = 3  # demote after 3 consecutive low scores
_PROMOTE_THRESHOLD = 0.80  # score above this counts as "high"
_DEMOTE_THRESHOLD = 0.35  # score below this counts as "low"

# Spaced repetition parameters
_RECENCY_DECAY_DAYS = 14  # half-life in days for recency weighting
_UNATTEMPTED_BONUS = 2.0  # multiplier for never-attempted competencies
_COVERAGE_BONUS = 1.5  # bonus for competencies with fewer attempts
_DIVERSITY_PENALTY = 0.3  # penalty for recently attempted competencies

# Format selection parameters (base weights)
_FORMAT_BASE_WEIGHTS: dict[str, float] = {
    "mcq": 0.30,
    "code_review": 0.18,
    "debugging": 0.18,
    "short_answer": 0.17,
    "design_prompt": 0.17,
}

# Format weights shift by difficulty level (higher levels get fewer MCQs)
_FORMAT_LEVEL_ADJUSTMENTS: dict[int, dict[str, float]] = {
    1: {"mcq": 0.15, "short_answer": -0.05, "design_prompt": -0.10},
    2: {"mcq": 0.05, "short_answer": 0.0, "design_prompt": -0.05},
    3: {},  # baseline
    4: {"mcq": -0.10, "code_review": 0.05, "design_prompt": 0.05},
    5: {"mcq": -0.15, "code_review": 0.05, "design_prompt": 0.10},
}

# Question batch generation
BATCH_SIZE = 10

# Staleness: if queued questions were generated before the user's level changed,
# consider them stale and regenerate
_STALENESS_LEVEL_MISMATCH = True


def pick_competency(roles: list[str], base_difficulty: int) -> Competency:
    """Pick a competency using multi-signal weighted selection.

    Signals blended into the final weight:
    1. Role emphasis weights (from the competency matrix)
    2. Performance gap: weaker competencies get higher weight
    3. Spaced repetition: older attempts get exponential decay bonus
    4. Coverage balancing: under-practiced competencies get a bonus
    5. Diversity: recently attempted competencies get penalized
    6. Level appropriateness: competencies relevant to the user's level

    Args:
        roles: User's selected roles.
        base_difficulty: User's base difficulty level (1-5).

    Returns:
        The selected Competency.
    """
    # Signal 1: Role-based competency weights
    role_weights = get_role_competency_weights(roles)

    # Signal 2 + 3: Performance and recency data
    performance = get_competency_performance()
    perf_by_slug = {p["competency_slug"]: p for p in performance}

    # Signal 4: Coverage data (attempt counts)
    all_levels = get_all_competency_levels()
    max_attempts = max((lv.get("total_attempts", 0) for lv in all_levels.values()), default=1) or 1

    # Signal 5: Recent competency diversity
    recent_slugs = get_recent_competency_slugs(n=5)

    today_ordinal = date.today().toordinal()
    final_weights: dict[str, float] = {}

    for slug in COMPETENCY_SLUGS:
        base_w = role_weights.get(slug, 0.02)
        perf = perf_by_slug.get(slug)
        level_data = all_levels.get(slug)

        if perf is None:
            # Never attempted — strong bonus to surface new competencies
            weight = base_w * _UNATTEMPTED_BONUS
        else:
            # Performance gap: lower scores → higher weight (ZPD targeting)
            # Maps [0.0, 1.0] avg score to [2.0, 1.0] multiplier
            gap_factor = 1.0 + (1.0 - perf["avg_score"])

            # Recency decay: exponential decay based on days since last attempt
            recency_factor = 1.0
            if perf["last_attempt_date"]:
                try:
                    last_date = date.fromisoformat(perf["last_attempt_date"][:10])
                    days_since = today_ordinal - last_date.toordinal()
                    # Exponential decay: doubles weight every _RECENCY_DECAY_DAYS
                    recency_factor = 1.0 + (1.0 - math.exp(-days_since / _RECENCY_DECAY_DAYS))
                except ValueError:
                    pass

            # Coverage: competencies with fewer attempts relative to max get a bonus
            attempts = level_data["total_attempts"] if level_data else perf["attempt_count"]
            coverage_factor = 1.0 + (_COVERAGE_BONUS - 1.0) * (1.0 - attempts / max_attempts)

            weight = base_w * gap_factor * recency_factor * coverage_factor

        # Diversity penalty: recently attempted competencies get downweighted
        if slug in recent_slugs:
            position = recent_slugs.index(slug)
            # More recent = stronger penalty (position 0 is most recent)
            penalty = _DIVERSITY_PENALTY * (1.0 - position / len(recent_slugs))
            weight *= 1.0 - penalty

        final_weights[slug] = max(weight, 0.001)  # floor to prevent zero weights

    # Weighted random selection
    slugs = list(final_weights.keys())
    weights = [final_weights[s] for s in slugs]
    chosen_slug = random.choices(slugs, weights=weights, k=1)[0]

    return COMPETENCY_BY_SLUG[chosen_slug]


def pick_format(
    competency_slug: str,
    difficulty: int,
    preferred_formats: list[str] | None = None,
) -> str:
    """Pick a question format using adaptive selection.

    Considers:
    1. User's preferred formats (heavy boost, non-preferred get suppressed)
    2. Base format weights (shifted by difficulty level)
    3. Per-competency format performance (weaker formats get higher weight)
    4. Randomization for variety

    Higher difficulty levels get fewer MCQs and more design/code_review questions.
    Formats where the user performs poorly get a boost to help them improve.
    If the user has preferred formats, those get a strong boost and others are
    heavily suppressed (but not zeroed, to maintain occasional variety).
    """
    # Start with base weights adjusted for difficulty level
    weights: dict[str, float] = dict(_FORMAT_BASE_WEIGHTS)
    level_adj = _FORMAT_LEVEL_ADJUSTMENTS.get(difficulty, {})
    for fmt, adj in level_adj.items():
        weights[fmt] = max(0.02, weights.get(fmt, 0.15) + adj)

    # Apply user format preferences: boost preferred, suppress others
    if preferred_formats:
        pref_set = set(preferred_formats)
        for fmt in weights:
            if fmt in pref_set:
                weights[fmt] *= 3.0  # strong boost for preferred formats
            else:
                weights[fmt] *= 0.1  # heavily suppress non-preferred

    # Adjust based on per-competency format performance
    format_perf = get_format_performance(competency_slug)
    perf_by_fmt = {fp["format"]: fp for fp in format_perf}

    for fmt in QUESTION_FORMATS:
        fp = perf_by_fmt.get(fmt)
        if fp is not None and fp["attempt_count"] >= 2:
            # Boost formats where user scores lower (gap = 1 - avg)
            gap = 1.0 - fp["avg_score"]
            weights[fmt] *= 1.0 + gap * 0.5
        elif fp is None:
            # Slight boost for untried formats in this competency
            weights[fmt] *= 1.1

    formats = list(weights.keys())
    w_values = [weights[f] for f in formats]
    return random.choices(formats, weights=w_values, k=1)[0]


def adapt_difficulty(competency_slug: str, base_difficulty: int) -> int:
    """Adaptively determine difficulty using ELO-like per-competency tracking.

    Decision hierarchy:
    1. Explicit user override (from difficulty_overrides table) → use as-is
    2. Per-competency ELO rating → map to appropriate level
    3. Rolling average heuristic → fine-tune within the ELO level
    4. Fall back to base difficulty if no data exists

    The algorithm targets the Zone of Proximal Development (~60-70% success rate)
    by promoting when the user consistently scores high and demoting when they
    consistently score low.

    Returns:
        Adjusted difficulty level (1-5).
    """
    # 1. Explicit override takes absolute precedence
    override = get_difficulty_override(competency_slug)
    if override is not None:
        return override

    # 2. Check per-competency adaptive level
    level_data = get_competency_level(competency_slug)
    if level_data is None:
        # No tracking data yet — use base difficulty but check rolling avg
        rolling_avg = get_competency_rolling_avg(competency_slug, n=5)
        if rolling_avg is not None:
            if rolling_avg > _PROMOTE_THRESHOLD and base_difficulty < 5:
                return base_difficulty + 1
            if rolling_avg < _DEMOTE_THRESHOLD and base_difficulty > 1:
                return base_difficulty - 1
        return base_difficulty

    # Use the ELO-derived estimated level
    return level_data["estimated_level"]


def update_adaptive_level(competency_slug: str, score: float, difficulty: int) -> int:
    """Update the per-competency adaptive level after an attempt.

    Uses an ELO-inspired rating system:
    - Expected score is derived from the difficulty vs current rating
    - Rating adjusts based on over/under-performance
    - Level boundaries are defined by rating thresholds
    - Consecutive high/low scores trigger faster promotion/demotion

    Also updates format performance tracking.

    Args:
        competency_slug: The competency that was tested.
        score: Normalized score (0.0-1.0).
        difficulty: The difficulty level of the question.

    Returns:
        The new estimated level (1-5).
    """
    level_data = get_competency_level(competency_slug)

    if level_data is None:
        # Initialize from the difficulty of the first question
        elo_rating = _ELO_BASE_RATING
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

    # ELO update: expected score based on difficulty vs rating
    # Higher difficulty questions are "harder opponents"
    difficulty_rating = _ELO_LEVEL_THRESHOLDS[difficulty][0] + 150  # midpoint of level range
    expected = 1.0 / (1.0 + 10 ** ((difficulty_rating - elo_rating) / 400))

    # Update rating: actual vs expected performance
    elo_rating += _ELO_K_FACTOR * (score - expected)
    elo_rating = max(200, min(2200, elo_rating))  # clamp to reasonable range

    # Track consecutive scores
    if score >= _PROMOTE_THRESHOLD:
        consecutive_high += 1
        consecutive_low = 0
    elif score <= _DEMOTE_THRESHOLD:
        consecutive_low += 1
        consecutive_high = 0
    else:
        # In the "learning zone" — reset both counters
        consecutive_high = 0
        consecutive_low = 0

    total_attempts += 1

    # Determine new level from ELO rating
    new_level = estimated_level
    for lvl, (low, high) in _ELO_LEVEL_THRESHOLDS.items():
        if low <= elo_rating < high:
            new_level = lvl
            break

    # Consecutive-based promotion/demotion (faster than pure ELO)
    if consecutive_high >= _PROMOTE_CONSECUTIVE and new_level < 5:
        new_level = min(5, new_level + 1)
        consecutive_high = 0  # reset after promotion
        # Bump ELO to the new level's midpoint if it hasn't caught up
        level_mid = (_ELO_LEVEL_THRESHOLDS[new_level][0] + _ELO_LEVEL_THRESHOLDS[new_level][1]) / 2
        elo_rating = max(elo_rating, level_mid)

    if consecutive_low >= _DEMOTE_CONSECUTIVE and new_level > 1:
        new_level = max(1, new_level - 1)
        consecutive_low = 0  # reset after demotion
        level_mid = (_ELO_LEVEL_THRESHOLDS[new_level][0] + _ELO_LEVEL_THRESHOLDS[new_level][1]) / 2
        elo_rating = min(elo_rating, level_mid)

    # Persist
    update_competency_level(
        competency_slug=competency_slug,
        estimated_level=new_level,
        elo_rating=elo_rating,
        consecutive_high=consecutive_high,
        consecutive_low=consecutive_low,
        total_attempts=total_attempts,
    )

    return new_level


def should_generate_new(
    competency_slug: str,
    question_format: str,
    difficulty: int,
) -> bool:
    """Intelligently decide whether to call the LLM or serve from the DB.

    Checks:
    1. Are there any queued questions matching the exact criteria?
    2. Has the user's level changed since queued questions were generated?
    3. Have recent topics become repetitive?

    Returns:
        True if we should generate new questions, False if DB has suitable ones.
    """
    # Check if there's a queued question matching exact criteria
    queued = get_queued_question(
        competency_slug=competency_slug,
        question_format=question_format,
        difficulty=difficulty,
    )
    if queued is None:
        return True

    # Check for level mismatch (staleness)
    if _STALENESS_LEVEL_MISMATCH:
        level_data = get_competency_level(competency_slug)
        if level_data is not None:
            current_level = level_data["estimated_level"]
            if queued["difficulty"] != current_level:
                return True

    # Check topic diversity — if recent topics overlap too much with queued question
    recent_topics = get_recent_question_topics(n=15)
    if queued.get("metadata") and recent_topics:
        meta = queued["metadata"]
        if isinstance(meta, dict) and "topics" in meta:
            q_topics = set(t.lower() for t in meta["topics"])
            recent_set = set(t.lower() for t in recent_topics)
            overlap = len(q_topics & recent_set)
            # If more than 60% of the question's topics were recently covered, regenerate
            if q_topics and overlap / len(q_topics) > 0.6:
                return True

    return False


def _validate_question(item: dict) -> list[str]:
    """Validate a generated question dict. Returns a list of issues (empty = valid)."""
    issues: list[str] = []

    title = item.get("title", "")
    if not title:
        issues.append("missing title")
    elif len(title) > 200:
        issues.append(f"title too long ({len(title)} chars)")

    if not item.get("body"):
        issues.append("missing body")

    # MCQ-specific validation
    options = item.get("options")
    correct = item.get("correct_answer")
    if options is not None:
        expected_keys = {"A", "B", "C", "D"}
        if set(options.keys()) != expected_keys:
            issues.append(f"MCQ options must be A/B/C/D, got {set(options.keys())}")
        if correct not in (options or {}):
            issues.append(f"correct_answer '{correct}' not in options")

    # Rubric validation
    rubric = item.get("grading_rubric")
    if rubric and isinstance(rubric, dict):
        criteria = rubric.get("criteria", [])
        max_score = rubric.get("max_score")
        if criteria and max_score is not None:
            criteria_total = sum(c.get("max_points", 0) for c in criteria)
            if criteria_total != max_score:
                issues.append(f"rubric criteria sum {criteria_total} != max_score {max_score}")

    if not item.get("explanation"):
        issues.append("missing explanation")

    return issues


def _shuffle_mcq_options(item: dict) -> dict:
    """Shuffle MCQ options using cryptographic randomness and update correct_answer."""
    options = item.get("options")
    correct = item.get("correct_answer")
    if not options or not correct or correct not in options:
        return item

    # Collect the option texts, noting which is correct
    correct_text = options[correct]
    entries = list(options.values())

    # Shuffle with secrets (cryptographically secure)
    import secrets

    for i in range(len(entries) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        entries[i], entries[j] = entries[j], entries[i]

    # Rebuild options dict with new letter assignments
    labels = ["A", "B", "C", "D"]
    new_options = {}
    new_correct = correct
    for idx, text in enumerate(entries):
        label = labels[idx]
        new_options[label] = text
        if text == correct_text:
            new_correct = label

    item["options"] = new_options
    item["correct_answer"] = new_correct
    return item


def _parse_response(raw_text: str) -> list[GeneratedQuestion]:
    """Parse and validate the LLM's JSON response into a list of GeneratedQuestion."""
    text = raw_text.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    data = json.loads(text)

    # Normalize: always work with a list
    if isinstance(data, dict):
        data = [data]

    # Validate and filter out invalid questions
    valid_data = []
    for item in data:
        issues = _validate_question(item)
        if issues:
            logger.warning("Skipping invalid question '%s': %s", item.get("title", "?")[:50], "; ".join(issues))
        else:
            valid_data.append(item)

    # Shuffle MCQ options so correct answer isn't always in the same position
    valid_data = [_shuffle_mcq_options(item) for item in valid_data]

    return [GeneratedQuestion.model_validate(item) for item in valid_data]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type((anthropic.APIConnectionError, anthropic.APITimeoutError)),
)
def generate_questions(
    competency: Competency,
    difficulty: int,
    question_format: str,
    roles: list[str],
    languages: list[str],
    frameworks: list[str],
    count: int = BATCH_SIZE,
    recent_topics: list[str] | None = None,
    question_length: str = "standard",
) -> list[GeneratedQuestion]:
    """Generate a batch of questions via Claude Opus 4.6.

    Passes rich context to the model including:
    - Competency level descriptions from the matrix
    - Technology domains relevant to the competency
    - User's roles, languages, and frameworks
    - Recently covered topics to avoid repetition
    - Question length preference (concise/standard/detailed)

    Args:
        competency: The competency area to test.
        difficulty: Difficulty level 1-5.
        question_format: One of the QUESTION_FORMATS.
        roles: User's engineering roles.
        languages: User's preferred languages.
        frameworks: User's preferred frameworks.
        count: Number of questions to generate.
        recent_topics: Topics to avoid for variety.
        question_length: Length preference — "concise", "standard", or "detailed".

    Returns:
        A list of validated GeneratedQuestion objects.
    """
    config = get_config()

    # Get level description from the competency matrix
    level_name = DIFFICULTY_TO_LEVEL.get(difficulty, "mid")
    level_description = competency.levels.get(level_name, "")

    system_msg, user_msg = build_generation_prompt(
        competency_name=competency.name,
        competency_description=level_description,
        difficulty=difficulty,
        question_format=question_format,
        roles=roles,
        languages=languages,
        frameworks=frameworks,
        count=count,
        technology_domains=list(competency.technology_domains),
        recent_topics=recent_topics,
        question_length=question_length,
    )

    raw_text = chat(system=system_msg, user_message=user_msg, model=config.generation_model)
    return _parse_response(raw_text)
