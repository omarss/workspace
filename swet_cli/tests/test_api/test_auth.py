"""Tests for the API auth flow: register, OTP, JWT."""

import os
import tempfile

# Override DB paths before importing
_tmp_api = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_api.close()
os.environ["SWET_API_DB_PATH"] = _tmp_api.name
os.environ["SWET_API_JWT_SECRET"] = "test-secret-key-for-testing-must-be-32-bytes-long"
os.environ["SWET_API_OTP_PROVIDER"] = "console"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from swet_api.app import app  # noqa: E402
import swet_api.config  # noqa: E402

# Reset cached config so test env vars take effect
swet_api.config._config = None

client = TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup():
    """Reset API DB after each test."""
    yield
    try:
        os.unlink(os.environ["SWET_API_DB_PATH"])
    except FileNotFoundError:
        pass
    _tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp2.close()
    os.environ["SWET_API_DB_PATH"] = _tmp2.name
    import swet_api.config

    swet_api.config._config = None


# --- Health ---


def test_health():
    """Health endpoint returns ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- Registration ---


def test_register_with_email():
    """Register a new user with email."""
    resp = client.post("/auth/register", json={"email": "test@example.com"})
    assert resp.status_code == 201
    assert "Registered" in resp.json()["message"]


def test_register_with_mobile():
    """Register a new user with mobile."""
    resp = client.post("/auth/register", json={"mobile": "+1234567890"})
    assert resp.status_code == 201


def test_register_no_credentials():
    """Registration fails without email or mobile."""
    resp = client.post("/auth/register", json={})
    assert resp.status_code == 400


def test_register_duplicate():
    """Registration fails for duplicate email."""
    client.post("/auth/register", json={"email": "dup@example.com"})
    resp = client.post("/auth/register", json={"email": "dup@example.com"})
    assert resp.status_code == 409


# --- OTP Flow ---


def test_send_otp():
    """Send OTP to a registered user."""
    client.post("/auth/register", json={"email": "otp@example.com"})
    resp = client.post("/auth/otp/send", json={"email": "otp@example.com"})
    assert resp.status_code == 200
    assert "OTP sent" in resp.json()["message"]


def test_send_otp_auto_registers():
    """Sending OTP to unregistered user auto-registers them."""
    resp = client.post("/auth/otp/send", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert resp.json()["message"] == "OTP sent successfully"


def test_verify_otp_and_get_tokens():
    """Full OTP flow: register → send → verify → get tokens."""
    email = "verify@example.com"
    client.post("/auth/register", json={"email": email})
    client.post("/auth/otp/send", json={"email": email})

    # For testing, insert an OTP we know the code for
    from datetime import UTC, datetime, timedelta

    from swet_api.auth.otp import generate_otp, hash_otp
    from swet_api.db import get_user_by_email, save_otp

    user = get_user_by_email(email)
    code = generate_otp()

    expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    save_otp(user["id"], hash_otp(code), expires)

    resp = client.post("/auth/otp/verify", json={"email": email, "code": code})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_verify_otp_wrong_code():
    """Invalid OTP code is rejected."""
    email = "wrong@example.com"
    client.post("/auth/register", json={"email": email})

    from datetime import UTC, datetime, timedelta

    from swet_api.auth.otp import hash_otp
    from swet_api.db import get_user_by_email, save_otp

    user = get_user_by_email(email)
    expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    save_otp(user["id"], hash_otp("123456"), expires)

    resp = client.post("/auth/otp/verify", json={"email": email, "code": "999999"})
    assert resp.status_code == 400


# --- JWT ---


def test_refresh_token():
    """Refresh token returns new token pair."""
    # Register and get tokens
    email = "refresh@example.com"
    client.post("/auth/register", json={"email": email})

    from datetime import UTC, datetime, timedelta

    from swet_api.auth.otp import generate_otp, hash_otp
    from swet_api.db import get_user_by_email, save_otp

    user = get_user_by_email(email)
    code = generate_otp()
    expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    save_otp(user["id"], hash_otp(code), expires)

    resp = client.post("/auth/otp/verify", json={"email": email, "code": code})
    tokens = resp.json()

    # Refresh
    resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert "access_token" in new_tokens
    # New token pair should be valid
    assert new_tokens["token_type"] == "bearer"


def test_protected_endpoint_without_token():
    """Accessing protected endpoints without token fails."""
    resp = client.get("/preferences")
    assert resp.status_code in (401, 403)  # depends on FastAPI/Starlette version


def test_protected_endpoint_with_token():
    """Accessing protected endpoints with valid token works."""
    # Get a token
    email = "auth@example.com"
    client.post("/auth/register", json={"email": email})

    from datetime import UTC, datetime, timedelta

    from swet_api.auth.otp import generate_otp, hash_otp
    from swet_api.db import get_user_by_email, save_otp

    user = get_user_by_email(email)
    code = generate_otp()
    expires = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    save_otp(user["id"], hash_otp(code), expires)

    resp = client.post("/auth/otp/verify", json={"email": email, "code": code})
    token = resp.json()["access_token"]

    # Access protected endpoint
    resp = client.get("/preferences", headers={"Authorization": f"Bearer {token}"})
    # 404 because no preferences set yet, but auth worked
    assert resp.status_code == 404
