"""Computerized Adaptive Testing (CAT) for initial level assessment.

Uses Bayesian estimation to efficiently determine the user's competency
level across their role-relevant competencies. The algorithm:

1. Selects the most important competencies for the user's roles
2. For each competency, runs 3 adaptive questions
3. Starts at L3 (senior) and adjusts based on responses
4. Uses a Bayesian posterior over levels to converge on the true level
5. Stores the estimated level per competency in the database

Based on Item Response Theory (IRT) — the probability of a correct
response is modeled as a logistic function of the difference between
the user's ability and the question's difficulty.
"""

import math

from swet_cli.data import (
    COMPETENCY_BY_SLUG,
    ROLE_EMPHASIS,
)
from swet_cli.db import update_competency_level

# --- CAT Algorithm Constants ---

# Total assessment questions (50 concepts + 50 language-specific)
TOTAL_ASSESSMENT_QUESTIONS = 100
PART1_QUESTIONS = 50
PART2_QUESTIONS = 50

# IRT discrimination parameter — controls how sharply the logistic curve
# separates levels. Higher = more discriminating questions.
_IRT_DISCRIMINATION = 1.5

# Prior: slightly favor mid-levels (bell-shaped prior centered on L3)
_LEVEL_PRIOR = {
    1: 0.10,
    2: 0.20,
    3: 0.40,
    4: 0.20,
    5: 0.10,
}

# ELO rating midpoints for each level (used to initialize after assessment)
_LEVEL_ELO_MIDPOINTS = {
    1: 425.0,
    2: 975.0,
    3: 1225.0,
    4: 1475.0,
    5: 1800.0,
}

# Priors shaped by self-evaluation ratings (0 = skip, 1-5 = familiarity)
SELF_RATING_PRIORS: dict[int, dict[int, float]] = {
    1: {1: 0.45, 2: 0.30, 3: 0.15, 4: 0.07, 5: 0.03},  # Beginner
    2: {1: 0.15, 2: 0.35, 3: 0.30, 4: 0.15, 5: 0.05},  # Some experience
    3: {1: 0.10, 2: 0.20, 3: 0.40, 4: 0.20, 5: 0.10},  # Comfortable (= default)
    4: {1: 0.03, 2: 0.07, 3: 0.20, 4: 0.40, 5: 0.30},  # Strong
    5: {1: 0.02, 2: 0.05, 3: 0.13, 4: 0.30, 5: 0.50},  # Expert
}


def select_assessment_competencies(roles: list[str]) -> list[str]:
    """Select competencies to assess based on role emphasis.

    Picks competencies with very_high and high emphasis across all selected
    roles, deduplicated and capped at MAX_COMPETENCIES. Prioritizes
    very_high over high.

    Returns:
        List of competency slugs to assess.
    """
    very_high: list[str] = []
    high: list[str] = []

    for role in roles:
        emphasis = ROLE_EMPHASIS.get(role, {})
        very_high.extend(emphasis.get("very_high", []))
        high.extend(emphasis.get("high", []))

    # Deduplicate preserving priority order (very_high first)
    seen: set[str] = set()
    ordered: list[str] = []
    for slug in very_high + high:
        if slug not in seen and slug in COMPETENCY_BY_SLUG:
            seen.add(slug)
            ordered.append(slug)

    return ordered[:MAX_COMPETENCIES]


def irt_probability(ability_level: int, question_difficulty: int) -> float:
    """Compute probability of a correct response using the IRT 1PL model.

    Uses the logistic function: P(correct) = 1 / (1 + exp(-a * (theta - b)))
    where theta = ability level, b = question difficulty, a = discrimination.

    Args:
        ability_level: The user's assumed ability (1-5).
        question_difficulty: The question's difficulty (1-5).

    Returns:
        Probability of scoring >= 0.6 (passing) on the question.
    """
    theta = ability_level
    b = question_difficulty
    return 1.0 / (1.0 + math.exp(-_IRT_DISCRIMINATION * (theta - b)))


class BayesianLevelEstimator:
    """Bayesian estimator for a single competency's level.

    Maintains a posterior distribution over levels 1-5 and updates it
    after each scored question using IRT-based likelihoods.
    """

    def __init__(self, prior: dict[int, float] | None = None) -> None:
        # Initialize posterior from custom prior or default
        self.posterior: dict[int, float] = dict(prior or _LEVEL_PRIOR)
        self.questions_asked: int = 0

    def update(self, question_difficulty: int, score: float) -> None:
        """Update the posterior after observing a score.

        Args:
            question_difficulty: The difficulty level of the question (1-5).
            score: Normalized score (0.0-1.0).
        """
        # Treat score >= 0.6 as "correct" for the IRT model, but use the
        # continuous score for smoother updates
        for level in self.posterior:
            p_correct = irt_probability(level, question_difficulty)
            # Likelihood: blend between binary and continuous
            # If score is high, higher levels are more likely; if low, lower levels
            likelihood = p_correct * score + (1.0 - p_correct) * (1.0 - score)
            self.posterior[level] *= likelihood

        # Normalize
        total = sum(self.posterior.values())
        if total > 0:
            self.posterior = {k: v / total for k, v in self.posterior.items()}

        self.questions_asked += 1

    def best_next_difficulty(self) -> int:
        """Pick the question difficulty that maximizes expected information gain.

        Strategy:
        - If confident (>60%) at current MAP level and not at L5, probe one
          level above to check if the user can handle harder questions.
        - Otherwise, test at the current MAP estimate to gather more data.

        Returns:
            Optimal difficulty level (1-5) for the next question.
        """
        map_level = self.estimated_level()
        confidence = self.posterior.get(map_level, 0)

        # When confident, probe one level above to test for promotion
        if confidence > 0.6 and map_level < 5:
            return map_level + 1

        return map_level

    def estimated_level(self) -> int:
        """Return the Maximum A Posteriori (MAP) level estimate."""
        return max(self.posterior, key=lambda k: self.posterior[k])

    def confidence(self) -> float:
        """Return the posterior probability of the MAP estimate."""
        level = self.estimated_level()
        return self.posterior.get(level, 0.0)

    def distribution_str(self) -> str:
        """Return a human-readable string of the posterior distribution."""
        parts = []
        for level in sorted(self.posterior):
            pct = self.posterior[level] * 100
            parts.append(f"L{level}: {pct:.0f}%")
        return "  ".join(parts)


def finalize_assessment(
    competency_slug: str,
    estimator: BayesianLevelEstimator,
) -> int:
    """Store the assessment result in the database.

    Converts the Bayesian estimate to an ELO rating and stores it as
    the initial competency level.

    Returns:
        The estimated level (1-5).
    """
    level = estimator.estimated_level()
    elo = _LEVEL_ELO_MIDPOINTS[level]

    update_competency_level(
        competency_slug=competency_slug,
        estimated_level=level,
        elo_rating=elo,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=estimator.questions_asked,
    )

    return level
