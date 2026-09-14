"""Password hashing helpers shared by authentication User models and consumers."""

from __future__ import annotations

import hashlib
import hmac
import secrets

PASSWORD_ALGORITHM = "oldman_pbkdf2_sha256"
PASSWORD_ITERATIONS = 390000
SALT_BYTES = 16


def make_password(raw_password: str) -> str:
    """Return an encoded password hash with a new random salt."""
    salt = secrets.token_hex(SALT_BYTES)
    digest = _pbkdf2_digest(raw_password, salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${digest}"


def check_password(raw_password: str, encoded_password: str) -> bool:
    """Return whether a raw password matches an encoded Oldman password."""
    try:
        algorithm, iterations_text, salt, expected_digest = encoded_password.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iterations_text)
    except (AttributeError, TypeError, ValueError):
        return False

    actual_digest = _pbkdf2_digest(raw_password, salt, iterations)
    return hmac.compare_digest(actual_digest, expected_digest)


def _pbkdf2_digest(raw_password: str, salt: str, iterations: int) -> str:
    """Return one PBKDF2-HMAC-SHA256 hexadecimal digest."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        raw_password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
