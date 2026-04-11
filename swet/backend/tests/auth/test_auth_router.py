"""Tests for auth endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient):
    """GET /auth/me without auth should return 401."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_authenticated(authenticated_client: AsyncClient):
    """GET /auth/me with valid JWT should return user data."""
    response = await authenticated_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["github_id"] == 12345678
    assert data["github_username"] == "testuser"
    assert data["is_active"] is True
