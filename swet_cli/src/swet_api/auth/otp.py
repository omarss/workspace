"""OTP generation, hashing, and verification."""

import hashlib
import secrets


def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically random numeric OTP."""
    # Use secrets for cryptographic randomness
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_otp(code: str) -> str:
    """Hash an OTP code for secure storage."""
    return hashlib.sha256(code.encode()).hexdigest()


def verify_otp(code: str, code_hash: str) -> bool:
    """Verify an OTP code against its hash."""
    return hash_otp(code) == code_hash
