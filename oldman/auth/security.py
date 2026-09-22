"""Password record policy: the stored format, the iteration count, and verification.

The algorithm itself lives in `oldman.utils.crypto`; this module owns how a password
record is written, read and compared, so there is exactly one place that decides what a
stored Oldman password looks like.
"""

from __future__ import annotations

import secrets

from oldman.utils.crypto import constant_time_equals, pbkdf2_sha256

PASSWORD_ALGORITHM = "oldman_pbkdf2_sha256"
PASSWORD_ITERATIONS = 390000
SALT_BYTES = 16


def make_password(raw_password: str) -> str:
    """Return an encoded password hash with a new random salt."""
    salt = secrets.token_hex(SALT_BYTES)
    digest = pbkdf2_sha256(raw_password, salt, PASSWORD_ITERATIONS)
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

    actual_digest = pbkdf2_sha256(raw_password, salt, iterations)
    return constant_time_equals(actual_digest, expected_digest)


# A record nothing can match: the salt is fixed and the digest is not the hash of any
# password. Neither value has to be secret, because no password is ever stored here — the
# record exists only to give `run_dummy_verification` a full round of work to spend.
_DUMMY_PASSWORD_RECORD = f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${'0' * (SALT_BYTES * 2)}${'0' * 64}"


def run_dummy_verification(raw_password: str) -> None:
    """Spend one verification's worth of work when there is no stored password to check.

    Authentication returns early when the username is unknown or the account is inactive.
    Without this, that branch answers in microseconds while a real account spends a full
    PBKDF2 round, and the difference in response time is itself the answer to "does this
    username exist?" — which the deliberately identical error message is there to withhold.
    """
    check_password(raw_password, _DUMMY_PASSWORD_RECORD)
