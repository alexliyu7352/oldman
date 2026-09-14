"""Authentication services shared by Web and non-Web applications."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.exc import StatementError
from sqlmodel import select

from oldman.auth.base import AbstractUser
from oldman.auth.contracts import UserModelContractError
from oldman.auth.registry import get_user_model
from oldman.auth.settings import AuthSettings
from oldman.db.session import DatabaseManager
from oldman.db.session import db_manager as default_db_manager


class UserIdentityError(ValueError):
    """Report an unavailable or unsupported configured User identity."""


def _auth_settings(auth_settings: AuthSettings | None) -> AuthSettings:
    """Resolve explicit settings or the Auth App instance bound at bootstrap."""
    if auth_settings is not None:
        return auth_settings

    from oldman.auth.apps import app as auth_app

    return auth_app.settings


def _db_manager(db_manager: DatabaseManager | None) -> DatabaseManager:
    """Resolve the process database singleton unless a manager was supplied."""
    return db_manager if db_manager is not None else default_db_manager


def _require_user_id(user_id: int) -> int:
    """Enforce the integer-only Python boundary without restricting its range."""
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise TypeError("user_id must be an int")
    return user_id


async def get_user_by_username(
    username: str,
    *,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
) -> AbstractUser | None:
    """Return the configured User matching a normalized username."""
    normalized_username = username.strip()
    if not normalized_username:
        return None

    user_model = get_user_model(_auth_settings(auth_settings))
    manager = _db_manager(db_manager)
    async with manager.get_read_session() as session:
        result = await session.exec(select(user_model).where(user_model.username == normalized_username))
        return result.one_or_none()


async def get_user_by_id(
    user_id: int,
    *,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
) -> AbstractUser | None:
    """Return the configured User for one integer database identity."""
    identity = _require_user_id(user_id)
    user_model = get_user_model(_auth_settings(auth_settings))

    manager = _db_manager(db_manager)
    async with manager.get_read_session() as session:
        try:
            return await session.get(user_model, identity)
        except OverflowError:
            return None
        except StatementError as exc:
            # Some drivers wrap an out-of-range integer conversion rather than
            # raising OverflowError directly.
            if isinstance(exc.orig, OverflowError):
                return None
            raise


async def authenticate_user(
    username: str,
    password: str,
    *,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
) -> AbstractUser | None:
    """Authenticate one active User without applying staff authorization."""
    user = await get_user_by_username(
        username,
        auth_settings=auth_settings,
        db_manager=db_manager,
    )
    if user is None or not bool(user.is_active):
        return None
    if not bool(user.check_password(password)):
        return None
    return user


async def change_user_password(
    user_id: int,
    raw_password: str,
    *,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
) -> AbstractUser | None:
    """Change one configured User password in a single write transaction."""
    identity = _require_user_id(user_id)
    user_model = get_user_model(_auth_settings(auth_settings))

    manager = _db_manager(db_manager)
    async with manager.get_session() as session:
        try:
            user = await session.get(user_model, identity)
        except OverflowError:
            return None
        except StatementError as exc:
            if isinstance(exc.orig, OverflowError):
                return None
            raise
        if user is None:
            return None
        user.set_password(raw_password)
        return user


def user_identity(user: AbstractUser) -> int:
    """Return one persisted User's integer primary-key value unchanged."""
    if not isinstance(user, AbstractUser):
        raise UserIdentityError("User must be an AbstractUser instance")
    identity = user.id
    if identity is None:
        raise UserIdentityError("User identity is not available before persistence")
    if isinstance(identity, bool) or not isinstance(identity, int):
        raise UserModelContractError("mapped User identity value must be an integer")
    return identity


async def touch_last_login(
    user_id: int,
    *,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
) -> None:
    """Persist the current UTC time for one configured User identity."""
    identity = _require_user_id(user_id)
    user_model = get_user_model(_auth_settings(auth_settings))

    manager = _db_manager(db_manager)
    async with manager.get_session() as session:
        try:
            user = await session.get(user_model, identity)
        except OverflowError:
            return
        except StatementError as exc:
            if isinstance(exc.orig, OverflowError):
                return
            raise
        if user is not None:
            # SQLAlchemy's portable DateTime column is timezone-naive here, so
            # store a naive value whose clock is explicitly UTC.
            user.last_login_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)


def has_staff_access(user: Any | None, *, require_superuser: bool = False) -> bool:
    """Return whether an active User satisfies the reusable staff policy."""
    if user is None or not bool(user.is_active) or not bool(user.is_staff):
        return False
    return not require_superuser or bool(user.is_superuser)


async def ensure_superuser(
    username: str,
    password: str,
    email: str | None = None,
    *,
    auth_settings: AuthSettings | None = None,
    db_manager: DatabaseManager | None = None,
) -> AbstractUser:
    """Create or update one configured User as an active superuser."""
    normalized_username = username.strip()
    if not normalized_username:
        raise ValueError("Superuser username must not be blank")

    user_model = get_user_model(_auth_settings(auth_settings))
    manager = _db_manager(db_manager)
    async with manager.get_session() as session:
        result = await session.exec(select(user_model).where(user_model.username == normalized_username))
        user = result.one_or_none()
        created = user is None
        if created:
            user = user_model(username=normalized_username)
            session.add(user)

        if email:
            user.email = email
        if created:
            user.display_name = normalized_username
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        if created or password:
            user.set_password(password)
        return user


__all__ = [
    "UserIdentityError",
    "authenticate_user",
    "change_user_password",
    "ensure_superuser",
    "get_user_by_id",
    "get_user_by_username",
    "has_staff_access",
    "touch_last_login",
    "user_identity",
]
