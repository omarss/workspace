"""Tests for onboarding endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_options(client: AsyncClient):
    """GET /onboarding/options should return available options."""
    response = await client.get("/api/v1/onboarding/options")
    assert response.status_code == 200
    data = response.json()
    assert "roles" in data
    assert "languages" in data
    assert "frameworks" in data
    assert len(data["roles"]) > 0


@pytest.mark.asyncio
async def test_create_profile(authenticated_client: AsyncClient):
    """POST /onboarding/profile should create a profile and mark onboarding complete."""
    response = await authenticated_client.post(
        "/api/v1/onboarding/profile",
        json={
            "primary_role": "backend",
            "interests": ["web_development"],
            "technologies": {
                "languages": ["python", "typescript"],
                "frameworks": ["fastapi"],
            },
            "experience_years": 5,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["primary_role"] == "backend"
    assert data["config_hash"] is not None
    assert len(data["config_hash"]) == 64


@pytest.mark.asyncio
async def test_create_profile_unauthenticated(client: AsyncClient):
    """POST /onboarding/profile without auth should return 401."""
    response = await client.post(
        "/api/v1/onboarding/profile",
        json={
            "primary_role": "backend",
            "interests": [],
            "technologies": {"languages": ["python"], "frameworks": []},
        },
    )
    assert response.status_code == 401
