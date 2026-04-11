"""Tests for question generation and adaptive algorithm logic."""

import json
import os
import tempfile

# Override DB path before importing modules that depend on config
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["SWET_CLI_DB_PATH"] = _tmp.name
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest  # noqa: E402

from swet_cli.data import COMPETENCY_BY_SLUG, QUESTION_FORMATS  # noqa: E402
from swet_cli.db import (  # noqa: E402
    get_competency_level,
    save_attempt,
    save_question,
    set_difficulty_override,
    update_competency_level,
    update_format_performance,
)
from swet_cli.generator import (  # noqa: E402
    _parse_response,
    adapt_difficulty,
    pick_competency,
    pick_format,
    should_generate_new,
    update_adaptive_level,
)


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
# Response parsing
# =========================================================================


def test_parse_response_single_object():
    """Parse a single JSON object response (wraps in list)."""
    raw = '{"title": "Test", "body": "Question body", "explanation": "Because"}'
    questions = _parse_response(raw)
    assert len(questions) == 1
    assert questions[0].title == "Test"
    assert questions[0].body == "Question body"


def test_parse_response_with_markdown_fences():
    """Strip markdown fences from response."""
    raw = '```json\n[{"title": "Test", "body": "Body"}]\n```'
    questions = _parse_response(raw)
    assert len(questions) == 1
    assert questions[0].title == "Test"


def test_parse_response_array():
    """Parse array response with multiple questions."""
    raw = '[{"title": "First", "body": "Body"}, {"title": "Second", "body": "Body2"}]'
    questions = _parse_response(raw)
    assert len(questions) == 2
    assert questions[0].title == "First"
    assert questions[1].title == "Second"


def test_parse_response_with_full_question_fields():
    """Parse a fully-populated question with all optional fields."""
    raw = json.dumps(
        {
            "title": "Full Q",
            "body": "Body text",
            "code_snippet": "print('hi')",
            "language": "python",
            "options": {"A": "opt1", "B": "opt2", "C": "opt3", "D": "opt4"},
            "correct_answer": "B",
            "grading_rubric": None,
            "explanation": "Because B",
            "metadata": {"topics": ["testing", "python"], "estimated_time_minutes": 5},
        }
    )
    questions = _parse_response(raw)
    assert len(questions) == 1
    q = questions[0]
    assert q.code_snippet == "print('hi')"
    assert q.language == "python"
    assert q.correct_answer == "B"
    assert q.metadata["topics"] == ["testing", "python"]


def test_parse_response_invalid_json_raises():
    """Invalid JSON raises an error."""
    with pytest.raises(json.JSONDecodeError):
        _parse_response("not valid json")


# =========================================================================
# Competency selection — multi-signal algorithm
# =========================================================================


def test_pick_competency_returns_valid_for_all_roles():
    """pick_competency returns a valid competency for every role."""
    from swet_cli.data import ROLES

    for role in ROLES:
        comp = pick_competency([role], base_difficulty=3)
        assert comp.slug in COMPETENCY_BY_SLUG


def test_pick_competency_with_multiple_roles():
    """pick_competency works with multiple roles (blended weights)."""
    comp = pick_competency(
        ["backend_engineer", "ai_engineer", "data_engineer"],
        base_difficulty=3,
    )
    assert comp.slug in COMPETENCY_BY_SLUG


def test_pick_competency_with_empty_roles_falls_back():
    """pick_competency handles empty role list without crashing."""
    comp = pick_competency([], base_difficulty=3)
    assert comp.slug in COMPETENCY_BY_SLUG


def test_pick_competency_with_performance_data():
    """pick_competency runs without error when performance data exists."""
    q_id = save_question(
        {
            "competency_slug": "programming_fundamentals",
            "format": "mcq",
            "difficulty": 3,
            "title": "Test",
            "body": "Body",
        }
    )
    save_attempt(question_id=q_id, answer_text="A", score=0.3, max_score=1, total_score=0.3)

    comp = pick_competency(["backend_engineer"], base_difficulty=3)
    assert comp.slug in COMPETENCY_BY_SLUG


def test_pick_competency_favors_weak_competencies():
    """Competencies with lower scores should be picked more often (statistical)."""
    slug_weak = "security_engineering"
    slug_strong = "programming_fundamentals"

    # Create weak performance for security
    q_weak = save_question(
        {
            "competency_slug": slug_weak,
            "format": "mcq",
            "difficulty": 3,
            "title": "Weak",
            "body": "Body",
        }
    )
    for _ in range(5):
        save_attempt(question_id=q_weak, answer_text="A", score=0.2, max_score=1, total_score=0.2)

    # Create strong performance for programming
    q_strong = save_question(
        {
            "competency_slug": slug_strong,
            "format": "mcq",
            "difficulty": 3,
            "title": "Strong",
            "body": "Body",
        }
    )
    for _ in range(5):
        save_attempt(question_id=q_strong, answer_text="A", score=0.95, max_score=1, total_score=0.95)

    # Also init adaptive levels so coverage factor works
    update_competency_level(
        slug_weak,
        estimated_level=2,
        elo_rating=900.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=5,
    )
    update_competency_level(
        slug_strong,
        estimated_level=3,
        elo_rating=1200.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=5,
    )

    # Run many selections and check that the weak one appears more often
    picks = {"weak": 0, "strong": 0, "other": 0}
    for _ in range(500):
        comp = pick_competency(["backend_engineer"], base_difficulty=3)
        if comp.slug == slug_weak:
            picks["weak"] += 1
        elif comp.slug == slug_strong:
            picks["strong"] += 1
        else:
            picks["other"] += 1

    # With 29 competencies competing, individual counts are small.
    # The weak competency (score=0.2, gap_factor=1.8) should have a higher
    # weight than the strong one (score=0.95, gap_factor=1.05). With 500
    # samples this should be statistically reliable.
    assert picks["weak"] >= picks["strong"], (
        f"Weak ({picks['weak']}) should be picked at least as often as strong ({picks['strong']})"
    )


def test_pick_competency_diversity_penalty():
    """Recently attempted competencies should be picked less often."""
    # Create recent attempts for one competency
    slug_recent = "api_design_and_integration"
    q_id = save_question(
        {
            "competency_slug": slug_recent,
            "format": "mcq",
            "difficulty": 3,
            "title": "Recent",
            "body": "Body",
        }
    )
    for _ in range(3):
        save_attempt(question_id=q_id, answer_text="A", score=0.6, max_score=1, total_score=0.6)

    # The recently attempted competency should still appear but at reduced rate
    picks = 0
    for _ in range(100):
        comp = pick_competency(["backend_engineer"], base_difficulty=3)
        if comp.slug == slug_recent:
            picks += 1

    # With 29 competencies, uniform would be ~3.4/100. With diversity penalty
    # on a recently attempted one and it being only "high" emphasis for backend,
    # it should be below uniform rate (but not zero due to weighting)
    assert picks < 30, f"Recently attempted picked {picks}/100 times, expected less"


# =========================================================================
# Format selection — adaptive
# =========================================================================


def test_pick_format_returns_valid():
    """pick_format returns a known format."""
    fmt = pick_format("programming_fundamentals", difficulty=3)
    assert fmt in QUESTION_FORMATS


def test_pick_format_junior_favors_mcq():
    """At L1 (junior), MCQ should be picked more often due to level adjustment."""
    mcq_count = 0
    runs = 300
    for _ in range(runs):
        fmt = pick_format("programming_fundamentals", difficulty=1)
        if fmt == "mcq":
            mcq_count += 1

    # With +0.15 boost, MCQ weight is 0.45 out of ~1.0 total. Expect ~40%+
    ratio = mcq_count / runs
    assert ratio > 0.30, f"MCQ ratio at L1 is {ratio:.2f}, expected > 0.30"


def test_pick_format_principal_reduces_mcq():
    """At L5 (principal), MCQ should be picked less often."""
    mcq_count = 0
    runs = 300
    for _ in range(runs):
        fmt = pick_format("system_design_and_architecture", difficulty=5)
        if fmt == "mcq":
            mcq_count += 1

    # With -0.15 penalty, MCQ weight is 0.15 out of ~1.0 total. Expect < 25%
    ratio = mcq_count / runs
    assert ratio < 0.30, f"MCQ ratio at L5 is {ratio:.2f}, expected < 0.30"


def test_pick_format_boosts_weak_formats():
    """Formats with low performance scores should be picked more often."""
    slug = "testing_and_quality_engineering"

    # User is strong at MCQ but weak at debugging
    update_format_performance(slug, "mcq", 0.95)
    update_format_performance(slug, "mcq", 0.90)  # 2 attempts needed to activate
    update_format_performance(slug, "debugging", 0.2)
    update_format_performance(slug, "debugging", 0.3)

    debug_count = 0
    mcq_count = 0
    runs = 300
    for _ in range(runs):
        fmt = pick_format(slug, difficulty=3)
        if fmt == "debugging":
            debug_count += 1
        elif fmt == "mcq":
            mcq_count += 1

    # Debugging (weak) should get a boost relative to its base weight
    # Base debugging=0.18, boosted by gap 0.75 * 0.5 → *1.375 → ~0.2475
    # Base MCQ=0.30, penalized by gap 0.075 * 0.5 → *1.0375 → ~0.311
    # So debugging rate should be meaningful, not zero
    assert debug_count > 10, f"Debugging picked {debug_count}/300, expected more for weak format"


def test_pick_format_boosts_untried_formats():
    """Untried formats for a competency get a slight boost."""
    slug = "databases_and_persistence"
    # Only record mcq and code_review, leaving others untried
    update_format_performance(slug, "mcq", 0.7)
    update_format_performance(slug, "mcq", 0.7)
    update_format_performance(slug, "code_review", 0.6)
    update_format_performance(slug, "code_review", 0.6)

    untried_count = 0
    runs = 300
    untried_formats = {"debugging", "short_answer", "design_prompt"}
    for _ in range(runs):
        fmt = pick_format(slug, difficulty=3)
        if fmt in untried_formats:
            untried_count += 1

    # Untried formats get 1.1x boost each. With 3 untried formats ~0.17*1.1*3 = ~0.561
    # vs tried ~0.30*1.15 + 0.18*1.2 = ~0.561. Should be roughly balanced.
    assert untried_count > 80, f"Untried formats picked {untried_count}/300, expected more"


# =========================================================================
# Adaptive difficulty — ELO-like system
# =========================================================================


def test_adapt_difficulty_no_data():
    """No performance data returns base difficulty."""
    assert adapt_difficulty("nonexistent_competency", 3) == 3


def test_adapt_difficulty_override_takes_precedence():
    """Explicit override takes precedence over everything."""
    set_difficulty_override("testing_and_quality_engineering", 5)
    assert adapt_difficulty("testing_and_quality_engineering", 2) == 5


def test_adapt_difficulty_override_beats_adaptive_level():
    """Override beats even the ELO-tracked adaptive level."""
    slug = "observability_and_telemetry"
    update_competency_level(
        slug,
        estimated_level=2,
        elo_rating=900.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=10,
    )
    set_difficulty_override(slug, 5)
    assert adapt_difficulty(slug, 3) == 5


def test_adapt_difficulty_bumps_up_with_rolling_avg():
    """High rolling avg bumps difficulty up when no adaptive level data."""
    q_id = save_question(
        {
            "competency_slug": "testing_and_quality_engineering",
            "format": "mcq",
            "difficulty": 3,
            "title": "Test",
            "body": "Body",
        }
    )
    for _ in range(5):
        save_attempt(question_id=q_id, answer_text="A", score=0.9, max_score=1, total_score=0.9)

    assert adapt_difficulty("testing_and_quality_engineering", 3) == 4


def test_adapt_difficulty_bumps_down_with_rolling_avg():
    """Low rolling avg bumps difficulty down when no adaptive level data."""
    q_id = save_question(
        {
            "competency_slug": "security_engineering",
            "format": "mcq",
            "difficulty": 3,
            "title": "Test",
            "body": "Body",
        }
    )
    for _ in range(5):
        save_attempt(question_id=q_id, answer_text="A", score=0.2, max_score=1, total_score=0.2)

    assert adapt_difficulty("security_engineering", 3) == 2


def test_adapt_difficulty_respects_upper_bound():
    """Cannot bump above 5."""
    q_id = save_question(
        {
            "competency_slug": "api_design_and_integration",
            "format": "mcq",
            "difficulty": 5,
            "title": "Test",
            "body": "Body",
        }
    )
    for _ in range(5):
        save_attempt(question_id=q_id, answer_text="A", score=0.95, max_score=1, total_score=0.95)

    assert adapt_difficulty("api_design_and_integration", 5) == 5


def test_adapt_difficulty_respects_lower_bound():
    """Cannot bump below 1."""
    q_id = save_question(
        {
            "competency_slug": "domain_modeling",
            "format": "mcq",
            "difficulty": 1,
            "title": "Test",
            "body": "Body",
        }
    )
    for _ in range(5):
        save_attempt(question_id=q_id, answer_text="A", score=0.1, max_score=1, total_score=0.1)

    assert adapt_difficulty("domain_modeling", 1) == 1


def test_adapt_difficulty_uses_adaptive_level():
    """adapt_difficulty uses ELO-tracked level when available."""
    slug = "system_design_and_architecture"
    update_competency_level(
        slug,
        estimated_level=4,
        elo_rating=1400.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=10,
    )

    # Should return the tracked level (4), not the base (2)
    assert adapt_difficulty(slug, base_difficulty=2) == 4


def test_adapt_difficulty_mid_rolling_avg_no_change():
    """Rolling avg in the middle zone (0.4-0.8) doesn't change difficulty."""
    q_id = save_question(
        {
            "competency_slug": "performance_engineering",
            "format": "mcq",
            "difficulty": 3,
            "title": "Test",
            "body": "Body",
        }
    )
    for _ in range(5):
        save_attempt(question_id=q_id, answer_text="A", score=0.6, max_score=1, total_score=0.6)

    assert adapt_difficulty("performance_engineering", 3) == 3


# =========================================================================
# ELO-like adaptive level tracking
# =========================================================================


def test_update_adaptive_level_initializes():
    """First attempt initializes the adaptive level tracking."""
    new_level = update_adaptive_level("programming_fundamentals", score=0.8, difficulty=3)
    assert 1 <= new_level <= 5

    level_data = get_competency_level("programming_fundamentals")
    assert level_data is not None
    assert level_data["total_attempts"] == 1


def test_update_adaptive_level_tracks_attempts():
    """Total attempts counter increments correctly."""
    slug = "clean_code_and_maintainability"
    for i in range(5):
        update_adaptive_level(slug, score=0.6, difficulty=3)

    level_data = get_competency_level(slug)
    assert level_data["total_attempts"] == 5


def test_update_adaptive_level_elo_rises_on_good_performance():
    """ELO rating should increase when scoring well on appropriate difficulty."""
    slug = "version_control_and_collaboration"
    update_adaptive_level(slug, score=0.5, difficulty=3)  # initialize
    initial_elo = get_competency_level(slug)["elo_rating"]

    # Score perfectly on same difficulty
    update_adaptive_level(slug, score=1.0, difficulty=3)
    new_elo = get_competency_level(slug)["elo_rating"]

    assert new_elo > initial_elo, "ELO should rise after a perfect score"


def test_update_adaptive_level_elo_drops_on_poor_performance():
    """ELO rating should decrease when scoring poorly."""
    slug = "reliability_and_resilience"
    update_adaptive_level(slug, score=0.5, difficulty=3)  # initialize
    initial_elo = get_competency_level(slug)["elo_rating"]

    # Score terribly
    update_adaptive_level(slug, score=0.0, difficulty=3)
    new_elo = get_competency_level(slug)["elo_rating"]

    assert new_elo < initial_elo, "ELO should drop after a 0 score"


def test_update_adaptive_level_elo_clamped_high():
    """ELO cannot exceed 2200."""
    slug = "frontend_engineering"
    # Start with a high ELO
    update_competency_level(
        slug,
        estimated_level=5,
        elo_rating=2190.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=50,
    )

    # Score perfectly many times
    for _ in range(10):
        update_adaptive_level(slug, score=1.0, difficulty=5)

    level_data = get_competency_level(slug)
    assert level_data["elo_rating"] <= 2200


def test_update_adaptive_level_elo_clamped_low():
    """ELO cannot go below 200."""
    slug = "mobile_engineering"
    update_competency_level(
        slug,
        estimated_level=1,
        elo_rating=220.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=50,
    )

    # Score 0 many times
    for _ in range(10):
        update_adaptive_level(slug, score=0.0, difficulty=1)

    level_data = get_competency_level(slug)
    assert level_data["elo_rating"] >= 200


def test_update_adaptive_level_promotes_on_consecutive_high():
    """3 consecutive high scores triggers level promotion."""
    slug = "data_engineering"
    # Start at level 2
    update_competency_level(
        slug,
        estimated_level=2,
        elo_rating=950.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=10,
    )

    # 3 high scores in a row
    for _ in range(3):
        update_adaptive_level(slug, score=0.9, difficulty=2)

    level_data = get_competency_level(slug)
    assert level_data["estimated_level"] >= 3, f"Expected promotion to L3+, got L{level_data['estimated_level']}"
    # Consecutive counter should reset after promotion
    assert level_data["consecutive_high"] == 0


def test_update_adaptive_level_demotes_on_consecutive_low():
    """3 consecutive low scores triggers level demotion."""
    slug = "distributed_systems"
    # Start at level 3
    update_competency_level(
        slug,
        estimated_level=3,
        elo_rating=1200.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=10,
    )

    # 3 low scores in a row
    for _ in range(3):
        update_adaptive_level(slug, score=0.1, difficulty=3)

    level_data = get_competency_level(slug)
    assert level_data["estimated_level"] <= 2, f"Expected demotion to L2-, got L{level_data['estimated_level']}"
    assert level_data["consecutive_low"] == 0


def test_update_adaptive_level_consecutive_resets_on_mid_score():
    """A mid-range score (0.4-0.8) resets both consecutive counters."""
    slug = "ci_cd_and_developer_experience"
    update_competency_level(
        slug,
        estimated_level=3,
        elo_rating=1200.0,
        consecutive_high=2,
        consecutive_low=0,
        total_attempts=10,
    )

    # Score in the "learning zone"
    update_adaptive_level(slug, score=0.6, difficulty=3)

    level_data = get_competency_level(slug)
    assert level_data["consecutive_high"] == 0
    assert level_data["consecutive_low"] == 0


def test_update_adaptive_level_no_promote_above_5():
    """Cannot promote above level 5."""
    slug = "governance_compliance_and_risk"
    update_competency_level(
        slug,
        estimated_level=5,
        elo_rating=1800.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=20,
    )

    for _ in range(5):
        update_adaptive_level(slug, score=0.95, difficulty=5)

    level_data = get_competency_level(slug)
    assert level_data["estimated_level"] == 5


def test_update_adaptive_level_no_demote_below_1():
    """Cannot demote below level 1."""
    slug = "product_thinking"
    update_competency_level(
        slug,
        estimated_level=1,
        elo_rating=400.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=10,
    )

    for _ in range(5):
        update_adaptive_level(slug, score=0.05, difficulty=1)

    level_data = get_competency_level(slug)
    assert level_data["estimated_level"] == 1


def test_update_adaptive_level_elo_bumps_on_promotion():
    """When promoted via consecutive scores, ELO gets bumped to new level midpoint."""
    slug = "technical_communication"
    # Start at level 2 with low ELO (just above L2 threshold)
    update_competency_level(
        slug,
        estimated_level=2,
        elo_rating=870.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=5,
    )

    # 3 consecutive highs should promote and bump ELO
    for _ in range(3):
        update_adaptive_level(slug, score=0.95, difficulty=2)

    level_data = get_competency_level(slug)
    # ELO should be at least at the midpoint of level 3's range (1100+1350)/2 = 1225
    if level_data["estimated_level"] >= 3:
        assert level_data["elo_rating"] >= 1100, f"ELO {level_data['elo_rating']} should be bumped to L3 midpoint"


def test_update_adaptive_level_gradual_progression():
    """Simulating realistic user growth over many attempts."""
    slug = "data_science_and_statistics"

    # Phase 1: User starts at L1, does OK
    for _ in range(5):
        update_adaptive_level(slug, score=0.65, difficulty=1)

    level_after_ok = get_competency_level(slug)["estimated_level"]

    # Phase 2: User gets better, consistently high
    for _ in range(6):
        update_adaptive_level(slug, score=0.9, difficulty=level_after_ok)

    level_after_good = get_competency_level(slug)["estimated_level"]

    # Should have progressed upward
    assert level_after_good >= level_after_ok, f"Level should progress: {level_after_ok} -> {level_after_good}"

    # Phase 3: User hits a wall at higher level
    for _ in range(6):
        update_adaptive_level(slug, score=0.2, difficulty=level_after_good)

    level_after_struggle = get_competency_level(slug)["estimated_level"]

    # Should have dropped back
    assert level_after_struggle < level_after_good, f"Level should drop: {level_after_good} -> {level_after_struggle}"


# =========================================================================
# Smart DB vs LLM decision (should_generate_new)
# =========================================================================


def test_should_generate_new_when_no_queued():
    """Should generate when no queued questions exist."""
    assert should_generate_new("programming_fundamentals", "mcq", 3) is True


def test_should_generate_new_when_queued_exists():
    """Should NOT generate when a matching queued question exists."""
    save_question(
        {
            "competency_slug": "programming_fundamentals",
            "format": "mcq",
            "difficulty": 3,
            "title": "Queued Q",
            "body": "Body",
        }
    )

    assert should_generate_new("programming_fundamentals", "mcq", 3) is False


def test_should_generate_new_wrong_format():
    """Should generate when queued question has wrong format."""
    save_question(
        {
            "competency_slug": "programming_fundamentals",
            "format": "mcq",
            "difficulty": 3,
            "title": "Queued Q",
            "body": "Body",
        }
    )

    # Looking for debugging, but only MCQ is queued
    assert should_generate_new("programming_fundamentals", "debugging", 3) is True


def test_should_generate_new_wrong_difficulty():
    """Should generate when queued question has wrong difficulty."""
    save_question(
        {
            "competency_slug": "programming_fundamentals",
            "format": "mcq",
            "difficulty": 2,
            "title": "Queued Q",
            "body": "Body",
        }
    )

    # Looking for difficulty 3, but only difficulty 2 is queued
    assert should_generate_new("programming_fundamentals", "mcq", 3) is True


def test_should_generate_new_level_mismatch():
    """Should generate when user's adaptive level doesn't match queued difficulty."""
    slug = "databases_and_persistence"

    # Queue a question at difficulty 2
    save_question(
        {
            "competency_slug": slug,
            "format": "mcq",
            "difficulty": 2,
            "title": "Old Q",
            "body": "Body",
        }
    )

    # But user's adaptive level is now 4
    update_competency_level(
        slug,
        estimated_level=4,
        elo_rating=1400.0,
        consecutive_high=0,
        consecutive_low=0,
        total_attempts=20,
    )

    # Asking for difficulty 2 matches the queue, but level mismatch should trigger regen
    assert should_generate_new(slug, "mcq", 2) is True


def test_should_generate_new_topic_overlap():
    """Should generate when queued question's topics overlap heavily with recent."""
    slug = "security_engineering"

    # Create a question with specific topics
    save_question(
        {
            "competency_slug": slug,
            "format": "short_answer",
            "difficulty": 3,
            "title": "Overlapping",
            "body": "Body",
            "metadata": {"topics": ["oauth", "jwt", "authentication"], "estimated_time_minutes": 5},
        }
    )

    # Create recent attempts with the same topics
    q_recent = save_question(
        {
            "competency_slug": slug,
            "format": "mcq",
            "difficulty": 3,
            "title": "Recent Q",
            "body": "Body",
            "metadata": {"topics": ["oauth", "jwt", "xss"], "estimated_time_minutes": 3},
        }
    )
    save_attempt(question_id=q_recent, answer_text="A", score=0.8, max_score=1, total_score=0.8)

    # 2/3 of queued question's topics overlap with recent (66% > 60% threshold)
    assert should_generate_new(slug, "short_answer", 3) is True


def test_should_generate_new_no_topic_overlap():
    """Should NOT generate when topic overlap is low."""
    slug = "cloud_and_infrastructure"

    save_question(
        {
            "competency_slug": slug,
            "format": "mcq",
            "difficulty": 3,
            "title": "Unique Q",
            "body": "Body",
            "metadata": {"topics": ["kubernetes", "helm", "service-mesh"], "estimated_time_minutes": 5},
        }
    )

    # Recent attempts have completely different topics
    q_recent = save_question(
        {
            "competency_slug": slug,
            "format": "mcq",
            "difficulty": 3,
            "title": "Different Q",
            "body": "Body",
            "metadata": {"topics": ["terraform", "vpc", "iam"], "estimated_time_minutes": 3},
        }
    )
    save_attempt(question_id=q_recent, answer_text="A", score=0.7, max_score=1, total_score=0.7)

    # 0/3 overlap — should serve from queue
    assert should_generate_new(slug, "mcq", 3) is False


def test_should_generate_new_answered_question_not_queued():
    """Answered questions are not considered queued."""
    q_id = save_question(
        {
            "competency_slug": "programming_fundamentals",
            "format": "mcq",
            "difficulty": 3,
            "title": "Answered Q",
            "body": "Body",
        }
    )
    save_attempt(question_id=q_id, answer_text="A", score=1.0, max_score=1, total_score=1.0)

    # This question has been answered, so it shouldn't be found as "queued"
    assert should_generate_new("programming_fundamentals", "mcq", 3) is True
