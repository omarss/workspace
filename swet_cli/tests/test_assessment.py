"""Tests for the Bayesian adaptive level assessment algorithm."""

import os
import tempfile

# Override DB path before importing modules that depend on config
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SWET_CLI_DB_PATH"] = _tmp.name
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest  # noqa: E402

from swet_cli.assessment import (  # noqa: E402
    BayesianLevelEstimator,
    finalize_assessment,
    irt_probability,
    select_assessment_competencies,
)
from swet_cli.db import get_competency_level  # noqa: E402


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean up test database after each test."""
    yield
    try:
        os.unlink(os.environ["SWET_CLI_DB_PATH"])
    except FileNotFoundError:
        pass
    _tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp2.close()
    os.environ["SWET_CLI_DB_PATH"] = _tmp2.name
    import swet_cli.config

    swet_cli.config._config = None


# =========================================================================
# IRT probability model
# =========================================================================


def test_irt_probability_equal_ability_difficulty():
    """When ability equals difficulty, probability should be ~0.5."""
    p = irt_probability(3, 3)
    assert abs(p - 0.5) < 0.01


def test_irt_probability_high_ability():
    """High ability on low difficulty should give high probability."""
    p = irt_probability(5, 1)
    assert p > 0.95


def test_irt_probability_low_ability():
    """Low ability on high difficulty should give low probability."""
    p = irt_probability(1, 5)
    assert p < 0.05


def test_irt_probability_monotonic():
    """Probability should increase with ability for fixed difficulty."""
    probs = [irt_probability(level, 3) for level in range(1, 6)]
    for i in range(len(probs) - 1):
        assert probs[i] < probs[i + 1], f"P(L{i + 1}) should be < P(L{i + 2})"


def test_irt_probability_decreases_with_difficulty():
    """Probability should decrease with difficulty for fixed ability."""
    probs = [irt_probability(3, diff) for diff in range(1, 6)]
    for i in range(len(probs) - 1):
        assert probs[i] > probs[i + 1], f"P(D{i + 1}) should be > P(D{i + 2})"


# =========================================================================
# Bayesian level estimator
# =========================================================================


def test_estimator_initial_prior():
    """Initial MAP estimate should be L3 (highest prior)."""
    est = BayesianLevelEstimator()
    assert est.estimated_level() == 3


def test_estimator_updates_up_on_correct():
    """Correct answers at high difficulty should push estimate up."""
    est = BayesianLevelEstimator()
    # Answer 3 hard questions correctly
    est.update(question_difficulty=4, score=1.0)
    est.update(question_difficulty=5, score=1.0)
    est.update(question_difficulty=5, score=1.0)

    assert est.estimated_level() >= 4


def test_estimator_updates_down_on_incorrect():
    """Incorrect answers at low difficulty should push estimate down."""
    est = BayesianLevelEstimator()
    # Fail 3 easy questions
    est.update(question_difficulty=1, score=0.0)
    est.update(question_difficulty=2, score=0.0)
    est.update(question_difficulty=1, score=0.0)

    assert est.estimated_level() <= 2


def test_estimator_converges_on_mid():
    """Mixed performance at L3 should keep estimate around L3."""
    est = BayesianLevelEstimator()
    est.update(question_difficulty=3, score=0.7)
    est.update(question_difficulty=3, score=0.5)
    est.update(question_difficulty=3, score=0.6)

    assert est.estimated_level() == 3


def test_estimator_confidence_increases():
    """Confidence should increase with more consistent data."""
    est = BayesianLevelEstimator()
    initial_conf = est.confidence()

    # 3 consistent high-level correct answers
    est.update(question_difficulty=4, score=1.0)
    est.update(question_difficulty=4, score=1.0)
    est.update(question_difficulty=4, score=1.0)

    assert est.confidence() > initial_conf


def test_estimator_best_next_difficulty_starts_at_map():
    """Next difficulty should start at the MAP estimate."""
    est = BayesianLevelEstimator()
    assert est.best_next_difficulty() == 3  # MAP is initially L3


def test_estimator_best_next_difficulty_probes_up():
    """When confident, should probe one level above."""
    est = BayesianLevelEstimator()
    # Get very confident at L3
    est.update(question_difficulty=3, score=0.9)
    est.update(question_difficulty=3, score=0.85)
    est.update(question_difficulty=3, score=0.9)

    next_diff = est.best_next_difficulty()
    # Should probe L4 or stay at L3, depending on confidence
    assert next_diff in (3, 4)


def test_estimator_distribution_str():
    """Distribution string should contain all 5 levels."""
    est = BayesianLevelEstimator()
    dist_str = est.distribution_str()
    for level in range(1, 6):
        assert f"L{level}:" in dist_str


def test_estimator_questions_asked_counter():
    """Questions asked counter should track updates."""
    est = BayesianLevelEstimator()
    assert est.questions_asked == 0

    est.update(3, 0.5)
    assert est.questions_asked == 1

    est.update(3, 0.8)
    assert est.questions_asked == 2


def test_estimator_posterior_sums_to_one():
    """Posterior should sum to 1.0 after updates."""
    est = BayesianLevelEstimator()
    est.update(3, 0.7)
    est.update(4, 0.3)

    total = sum(est.posterior.values())
    assert abs(total - 1.0) < 1e-9


# =========================================================================
# Competency selection for assessment
# =========================================================================


def test_select_assessment_competencies_backend():
    """Backend engineer should get relevant competencies."""
    slugs = select_assessment_competencies(["backend_engineer"])
    assert len(slugs) > 0
    assert len(slugs) <= 6
    # Backend should include API design (very_high)
    assert "api_design_and_integration" in slugs


def test_select_assessment_competencies_frontend():
    """Frontend engineer should get frontend-relevant competencies."""
    slugs = select_assessment_competencies(["frontend_engineer"])
    assert "frontend_engineering" in slugs


def test_select_assessment_competencies_multi_role():
    """Multi-role should get union of competencies, deduplicated."""
    slugs_be = select_assessment_competencies(["backend_engineer"])
    slugs_fe = select_assessment_competencies(["frontend_engineer"])
    slugs_both = select_assessment_competencies(["backend_engineer", "frontend_engineer"])

    # Should have unique slugs from both roles
    assert len(slugs_both) == len(set(slugs_both))
    # Should include competencies from both
    assert len(slugs_both) >= max(len(slugs_be), len(slugs_fe))


def test_select_assessment_competencies_capped():
    """Should never return more than MAX_COMPETENCIES."""
    from swet_cli.assessment import MAX_COMPETENCIES

    slugs = select_assessment_competencies(["backend_engineer", "frontend_engineer", "ai_engineer"])
    assert len(slugs) <= MAX_COMPETENCIES


def test_select_assessment_competencies_prioritizes_very_high():
    """very_high competencies should appear before high ones."""
    from swet_cli.data import ROLE_EMPHASIS

    slugs = select_assessment_competencies(["backend_engineer"])
    very_high = ROLE_EMPHASIS["backend_engineer"]["very_high"]

    # All very_high should appear in the results (if within cap)
    for vh in very_high:
        assert vh in slugs, f"very_high competency '{vh}' should be in assessment"


def test_select_assessment_competencies_empty_roles():
    """Empty roles should return empty list."""
    assert select_assessment_competencies([]) == []


# =========================================================================
# Finalize assessment (DB storage)
# =========================================================================


def test_finalize_assessment_stores_level():
    """Finalize should store the estimated level in the database."""
    est = BayesianLevelEstimator()
    est.update(4, 1.0)
    est.update(5, 1.0)
    est.update(5, 0.9)

    level = finalize_assessment("programming_fundamentals", est)
    assert 1 <= level <= 5

    db_level = get_competency_level("programming_fundamentals")
    assert db_level is not None
    assert db_level["estimated_level"] == level
    assert db_level["total_attempts"] == 3


def test_finalize_assessment_sets_elo_midpoint():
    """Finalize should set ELO to the level's midpoint."""
    from swet_cli.assessment import _LEVEL_ELO_MIDPOINTS

    est = BayesianLevelEstimator()
    est.update(3, 0.7)

    level = finalize_assessment("testing_and_quality_engineering", est)

    db_level = get_competency_level("testing_and_quality_engineering")
    expected_elo = _LEVEL_ELO_MIDPOINTS[level]
    assert db_level["elo_rating"] == pytest.approx(expected_elo)


def test_finalize_assessment_resets_consecutive():
    """Finalize should set consecutive counters to 0."""
    est = BayesianLevelEstimator()
    est.update(3, 0.7)

    finalize_assessment("security_engineering", est)

    db_level = get_competency_level("security_engineering")
    assert db_level["consecutive_high"] == 0
    assert db_level["consecutive_low"] == 0
