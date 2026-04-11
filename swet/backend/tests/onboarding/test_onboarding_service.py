"""Tests for onboarding service."""

from src.onboarding.service import compute_config_hash, get_onboarding_options


def test_compute_config_hash_deterministic():
    """Same inputs should always produce the same hash."""
    hash1 = compute_config_hash(
        role="backend",
        interests=["web", "cloud"],
        languages=["python", "go"],
        frameworks=["fastapi", "gin"],
    )
    hash2 = compute_config_hash(
        role="backend",
        interests=["cloud", "web"],  # different order
        languages=["go", "python"],  # different order
        frameworks=["gin", "fastapi"],  # different order
    )
    assert hash1 == hash2


def test_compute_config_hash_different_roles():
    """Different roles should produce different hashes."""
    hash1 = compute_config_hash("backend", [], ["python"], [])
    hash2 = compute_config_hash("frontend", [], ["python"], [])
    assert hash1 != hash2


def test_get_onboarding_options():
    """Options should include roles, interests, languages, and frameworks."""
    options = get_onboarding_options()
    assert len(options["roles"]) == 10
    assert "backend" in options["roles"]
    assert "python" in options["languages"]
    assert "react" in options["frameworks"]
