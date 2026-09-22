"""Password reset tokens and lookups, after django.contrib.auth.tokens.

A token is an HMAC over the user's identity, current password hash, last login time and the issue
time, so it stops working by itself once the password changes, the user signs in, or the configured
lifetime passes. Nothing is stored.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import hmac
from collections.abc import Callable
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from oldman.auth.base import AbstractUser
from oldman.auth.registry import get_user_model
from oldman.auth.services import _auth_settings, _db_manager, normalize_email
from oldman.auth.settings import AuthSettings, PasswordResetSettings
from oldman.db import DatabaseManager

_KEY_SALT = "oldman.auth.password_reset"
_BASE36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(number: int) -> str:
    if number < 0:
        raise ValueError("base36 needs a non-negative integer")
    if number < 36:
        return _BASE36_ALPHABET[number]
    digits: list[str] = []
    while number:
        number, remainder = divmod(number, 36)
        digits.append(_BASE36_ALPHABET[remainder])
    return "".join(reversed(digits))


def encode_user_id(user_id: int) -> str:
    """URL-safe form of a user id for the reset link (base64 without padding, like Django's uidb64)."""
    return base64.urlsafe_b64encode(str(int(user_id)).encode("ascii")).decode("ascii").rstrip("=")


def decode_user_id(value: str) -> int | None:
    """Reverse `encode_user_id`; None for anything that is not one of its outputs."""
    if not value or len(value) > 32:
        return None
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not decoded.isdigit():
        return None
    return int(decoded)


def password_reset_settings(auth_settings: AuthSettings | None = None) -> PasswordResetSettings:
    """The reset settings of the given or the installed Auth app."""
    return _auth_settings(auth_settings).password_reset


class PasswordResetTokenGenerator:
    """Make and check reset tokens for one user; `expiry` seconds after issue they are dead."""

    def __init__(
        self,
        secret: str | bytes | None = None,
        *,
        expiry: int | None = None,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._secret = secret
        self._expiry = expiry
        self._now = now or (lambda: dt.datetime.now(dt.UTC))

    @property
    def secret(self) -> bytes:
        secret = self._secret
        if secret is None:
            from oldman.conf import settings

            secret = settings.web.security.secret_key
        if not secret:
            raise RuntimeError("password reset tokens need web.security.secret_key")
        return secret.encode("utf-8") if isinstance(secret, str) else secret

    @property
    def expiry(self) -> int:
        return self._expiry if self._expiry is not None else password_reset_settings().expiry

    def make_token(self, user: Any) -> str:
        """Token for `user` issued now."""
        return self._make_token_with_timestamp(user, self._seconds_now())

    def check_token(self, user: Any, token: str | None) -> bool:
        """True when `token` was made for the user's current state and has not expired."""
        if user is None or not token:
            return False
        timestamp_part, separator, _signature = token.partition("-")
        if not separator:
            return False
        try:
            issued = int(timestamp_part, 36)
        except ValueError:
            return False
        if not hmac.compare_digest(self._make_token_with_timestamp(user, issued), token):
            return False
        return 0 <= self._seconds_now() - issued <= self.expiry

    def _seconds_now(self) -> int:
        return int(self._now().timestamp())

    def _make_token_with_timestamp(self, user: Any, timestamp: int) -> str:
        digest = hmac.new(
            hashlib.sha256(_KEY_SALT.encode("utf-8") + self.secret).digest(),
            self._hash_value(user, timestamp).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        # Every other character, as Django does: shorter link, still 128 bits.
        return f"{_base36(timestamp)}-{digest[::2]}"

    @staticmethod
    def _hash_value(user: Any, timestamp: int) -> str:
        last_login = getattr(user, "last_login_at", None)
        login_stamp = "" if last_login is None else last_login.replace(microsecond=0, tzinfo=None).isoformat()
        email = getattr(user, "email", None) or ""
        return f"{getattr(user, 'id', '')}{getattr(user, 'password_hash', '')}{login_stamp}{timestamp}{email}"


default_token_generator = PasswordResetTokenGenerator()


async def get_user_by_email(
    email: str,
    *,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
) -> AbstractUser | None:
    """The user whose email matches, case-insensitively; None for blank input or no match.

    New rows are stored normalized, but legacy rows may differ only in case, so the comparison
    lowercases both sides and an active account wins over an inactive one.
    """
    normalized = normalize_email(email)
    if normalized is None:
        return None
    user_model = get_user_model(_auth_settings(auth_settings))
    manager = _db_manager(db_manager)
    async with manager.get_read_session() as session:
        query = select(user_model).where(func.lower(user_model.email) == normalized).order_by(user_model.is_active.desc(), user_model.id)
        result = await session.exec(query)
        return result.first()


__all__ = [
    "PasswordResetTokenGenerator",
    "decode_user_id",
    "default_token_generator",
    "encode_user_id",
    "get_user_by_email",
    "password_reset_settings",
]
