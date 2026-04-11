"""Tests for the competency matrix data module."""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from swet_cli.data import (
    COMPETENCIES,
    COMPETENCY_BY_SLUG,
    COMPETENCY_SLUGS,
    DIFFICULTY_TO_LEVEL,
    EMPHASIS_WEIGHTS,
    FRAMEWORKS,
    LANGUAGES,
    LEVEL_DEFINITIONS,
    LEVEL_TO_DIFFICULTY,
    LEVELS,
    MATRIX,
    QUESTION_FORMATS,
    ROLE_EMPHASIS,
    ROLES,
    TECHNOLOGY_DOMAIN_NAMES,
    TECHNOLOGY_TAXONOMY,
    Competency,
    get_role_competency_weights,
    get_technologies_for_domains,
)

# =========================================================================
# Matrix loading and structure
# =========================================================================


def test_matrix_loaded():
    """Matrix JSON loaded successfully."""
    assert MATRIX is not None
    assert "competency_matrix" in MATRIX
    assert "role_emphasis_matrix" in MATRIX
    assert "technology_taxonomy" in MATRIX


def test_competencies_count():
    """Should have 29 competencies from the matrix."""
    assert len(COMPETENCIES) == 29
    assert len(COMPETENCY_BY_SLUG) == 29
    assert len(COMPETENCY_SLUGS) == 29


def test_competency_slugs_unique():
    """All competency slugs should be unique."""
    assert len(set(COMPETENCY_SLUGS)) == len(COMPETENCY_SLUGS)


def test_competency_has_levels():
    """Each competency should have 5 level descriptions."""
    for comp in COMPETENCIES:
        assert len(comp.levels) == 5, f"{comp.slug} has {len(comp.levels)} levels, expected 5"
        for level_name in LEVELS:
            assert level_name in comp.levels, f"{comp.slug} missing level '{level_name}'"


def test_competency_has_technology_domains():
    """Each competency should have at least one technology domain."""
    for comp in COMPETENCIES:
        assert len(comp.technology_domains) >= 1, f"{comp.slug} has no technology domains"


def test_known_competencies_exist():
    """Key competencies from the matrix should be present."""
    expected = [
        "programming_fundamentals",
        "system_design_and_architecture",
        "security_engineering",
        "ai_engineering_and_llm_systems",
        "machine_learning_engineering",
        "data_science_and_statistics",
        "governance_compliance_and_risk",
    ]
    for slug in expected:
        assert slug in COMPETENCY_BY_SLUG, f"Expected competency '{slug}' not found"


def test_competency_is_frozen_dataclass():
    """Competency instances should be immutable."""
    comp = COMPETENCIES[0]
    assert isinstance(comp, Competency)
    import dataclasses

    assert dataclasses.is_dataclass(comp)


# =========================================================================
# Levels
# =========================================================================


def test_levels_list():
    """Should have 5 career levels."""
    assert LEVELS == ["junior", "mid", "senior", "staff", "principal"]


def test_level_definitions_have_scope():
    """Each level definition should have a scope description."""
    for level in LEVELS:
        assert level in LEVEL_DEFINITIONS
        assert "scope" in LEVEL_DEFINITIONS[level]


def test_difficulty_to_level_mapping():
    """Difficulty 1-5 maps to the 5 levels."""
    assert DIFFICULTY_TO_LEVEL[1] == "junior"
    assert DIFFICULTY_TO_LEVEL[2] == "mid"
    assert DIFFICULTY_TO_LEVEL[3] == "senior"
    assert DIFFICULTY_TO_LEVEL[4] == "staff"
    assert DIFFICULTY_TO_LEVEL[5] == "principal"


def test_level_to_difficulty_inverse():
    """LEVEL_TO_DIFFICULTY is the inverse of DIFFICULTY_TO_LEVEL."""
    for diff, level in DIFFICULTY_TO_LEVEL.items():
        assert LEVEL_TO_DIFFICULTY[level] == diff


# =========================================================================
# Roles
# =========================================================================


def test_roles_count():
    """Should have 12 roles from the matrix."""
    assert len(ROLES) == 12


def test_known_roles_exist():
    """Key roles should be present."""
    expected = [
        "backend_engineer",
        "frontend_engineer",
        "ai_engineer",
        "data_scientist",
        "site_reliability_engineer",
    ]
    for role in expected:
        assert role in ROLES, f"Expected role '{role}' not found"


def test_role_emphasis_matches_roles():
    """Every role should have an emphasis matrix entry."""
    for role in ROLES:
        assert role in ROLE_EMPHASIS, f"Role '{role}' missing from emphasis matrix"


def test_role_emphasis_contains_valid_competencies():
    """All competencies in role emphasis should be valid slugs."""
    for role, emphasis in ROLE_EMPHASIS.items():
        for level, slugs in emphasis.items():
            assert level in EMPHASIS_WEIGHTS, f"Unknown emphasis level '{level}' in role '{role}'"
            for slug in slugs:
                assert slug in COMPETENCY_BY_SLUG, f"Unknown competency '{slug}' in role '{role}' emphasis"


# =========================================================================
# Role competency weights
# =========================================================================


def test_get_role_competency_weights_single_role():
    """Weights should be computed for a single role."""
    weights = get_role_competency_weights(["backend_engineer"])
    assert len(weights) == 29  # all competencies get a weight

    # very_high competencies should have highest weight
    backend_very_high = ROLE_EMPHASIS["backend_engineer"]["very_high"]
    for slug in backend_very_high:
        assert weights[slug] == EMPHASIS_WEIGHTS["very_high"]


def test_get_role_competency_weights_multi_role():
    """Weights should be blended (averaged) across multiple roles."""
    w_single_be = get_role_competency_weights(["backend_engineer"])
    w_single_fe = get_role_competency_weights(["frontend_engineer"])
    w_blended = get_role_competency_weights(["backend_engineer", "frontend_engineer"])

    # Blended weight should be the average of the two individual weights
    for slug in COMPETENCY_SLUGS:
        expected_avg = (w_single_be[slug] + w_single_fe[slug]) / 2
        assert abs(w_blended[slug] - expected_avg) < 1e-10, (
            f"Blended weight for '{slug}': {w_blended[slug]} != {expected_avg}"
        )


def test_get_role_competency_weights_empty_roles():
    """Empty roles should return baseline weights for all competencies."""
    weights = get_role_competency_weights([])
    assert len(weights) == 29
    for slug, w in weights.items():
        assert w == 0.02, f"Expected baseline 0.02 for '{slug}', got {w}"


def test_get_role_competency_weights_unknown_role():
    """Unknown role should return baseline weights (no emphasis data)."""
    weights = get_role_competency_weights(["nonexistent_role"])
    # All should be baseline
    for slug, w in weights.items():
        assert w == 0.02


def test_role_weights_very_high_greater_than_high():
    """very_high competencies should have higher weight than high."""
    weights = get_role_competency_weights(["backend_engineer"])
    be = ROLE_EMPHASIS["backend_engineer"]

    if "very_high" in be and "high" in be:
        very_high_slugs = be["very_high"]
        high_slugs = be["high"]
        if very_high_slugs and high_slugs:
            avg_very_high = sum(weights[s] for s in very_high_slugs) / len(very_high_slugs)
            avg_high = sum(weights[s] for s in high_slugs) / len(high_slugs)
            assert avg_very_high > avg_high


# =========================================================================
# Technology taxonomy
# =========================================================================


def test_technology_taxonomy_loaded():
    """Technology taxonomy should be a non-empty dict."""
    assert isinstance(TECHNOLOGY_TAXONOMY, dict)
    assert len(TECHNOLOGY_TAXONOMY) > 0


def test_technology_domain_names():
    """Should have 30 technology domain names."""
    assert len(TECHNOLOGY_DOMAIN_NAMES) == 30


def test_get_technologies_for_domains():
    """Should return technologies for given domains."""
    techs = get_technologies_for_domains(["languages"])
    assert "Python" in techs
    assert "Java" in techs
    assert "Go" in techs


def test_get_technologies_for_domains_multiple():
    """Should aggregate technologies from multiple domains."""
    techs = get_technologies_for_domains(["databases", "messaging_and_streaming"])
    assert "PostgreSQL" in techs
    assert "Kafka" in techs


def test_get_technologies_for_domains_empty():
    """Empty domain list returns empty list."""
    assert get_technologies_for_domains([]) == []


def test_get_technologies_for_domains_unknown():
    """Unknown domain returns empty list."""
    assert get_technologies_for_domains(["nonexistent_domain"]) == []


# =========================================================================
# Languages and frameworks
# =========================================================================


def test_languages_populated():
    """Languages list should contain common programming languages."""
    assert "Python" in LANGUAGES
    assert "Java" in LANGUAGES
    assert "TypeScript" in LANGUAGES
    assert "Go" in LANGUAGES


def test_frameworks_populated():
    """Frameworks list should contain common frameworks."""
    assert "FastAPI" in FRAMEWORKS
    assert "React" in FRAMEWORKS
    assert "Spring Boot" in FRAMEWORKS


def test_question_formats():
    """Should have 5 question formats."""
    assert len(QUESTION_FORMATS) == 5
    assert "mcq" in QUESTION_FORMATS
    assert "code_review" in QUESTION_FORMATS
    assert "debugging" in QUESTION_FORMATS
    assert "short_answer" in QUESTION_FORMATS
    assert "design_prompt" in QUESTION_FORMATS
