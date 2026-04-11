"""Tests for anonymous session authentication."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_anonymous_session(client: AsyncClient):
    """POST /auth/anonymous should return a token and user with negative github_id."""
    response = await client.post("/api/v1/auth/anonymous")
    assert response.status_code == 200

    data = response.json()
    assert "token" in data
    assert "user" in data
    assert data["user"]["github_id"] < 0
    assert data["user"]["github_username"] == "anonymous"
    assert data["user"]["is_anonymous"] is True
    assert data["user"]["is_active"] is True


@pytest.mark.asyncio
async def test_anonymous_token_authenticates_me(client: AsyncClient):
    """An anonymous token should authenticate GET /auth/me and return is_anonymous=True."""
    # Create anonymous session
    create_resp = await client.post("/api/v1/auth/anonymous")
    token = create_resp.json()["token"]

    # Use token to access /me
    me_resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200

    user = me_resp.json()
    assert user["is_anonymous"] is True
    assert user["github_id"] < 0


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client: AsyncClient):
    """An invalid Bearer token should return 401."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token-here"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_anonymous_user_can_access_onboarding_options(
    anonymous_client: tuple[AsyncClient, str],
):
    """An anonymous user should be able to access the onboarding options endpoint."""
    ac, _token = anonymous_client
    response = await ac.get("/api/v1/onboarding/options")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_anonymous_client_fixture(
    anonymous_client: tuple[AsyncClient, str],
):
    """The anonymous_client fixture should provide a working authenticated client."""
    ac, _token = anonymous_client
    response = await ac.get("/api/v1/auth/me")
    assert response.status_code == 200

    data = response.json()
    assert data["is_anonymous"] is True
    assert data["github_id"] < 0
