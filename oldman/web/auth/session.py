"""Map configured authentication Users to strongly typed Web sessions."""

from __future__ import annotations

import time
from typing import Any

import oldman.conf as conf
from oldman.auth import user_identity
from oldman.logging import get_logger
from oldman.security import require_user_id
from oldman.web.authentication import forget_session_authentication, revoke_user_tokens
from oldman.web.session import Session, SessionData

logger = get_logger("default.web.auth.session")


def session_data_for_user[TSessionData: SessionData](
    session_model: type[TSessionData],
    user: Any,
    *,
    expiry: int | None = None,
    login_ip: str = "",
    login_time: int | None = None,
    role_ids: tuple[int, ...] = (),
) -> TSessionData:
    """Build one base authorization snapshot for an authenticated User."""
    if not isinstance(session_model, type) or not issubclass(session_model, SessionData):
        raise TypeError("session_model must be a SessionData subclass")

    # Login metadata belongs to the immutable authentication snapshot. Callers
    # may pin the timestamp for imported sessions and deterministic tests.
    resolved_login_time = int(time.time()) if login_time is None else int(login_time)
    return session_model(
        expiry=expiry,
        user_id=user_identity(user),
        username=str(user.username),
        display_name=str(getattr(user, "display_name", "") or user.username),
        login_ip=str(login_ip),
        login_time=resolved_login_time,
        is_active=bool(user.is_active),
        is_staff=bool(user.is_staff),
        is_superuser=bool(user.is_superuser),
        role_ids=tuple(role_ids),
    )


async def revoke_user_logins(request: Any, user_id: int) -> bool:
    """End every session and token one user holds; report whether the caller ended its own.

    Every path that changes a password or takes a user's access away goes through this — the
    user changing their own password, an operator changing it or disabling, demoting or
    deleting the account, the reset flow behind a mailed link — so that no login outlives
    the password or the permissions it was opened under, whichever route changed them.

    A store that cannot be reached is logged rather than raised. The change has already
    been made by the time this runs, and failing here would only turn a working change into
    a 500. A session store that is down is not one that is still authenticating anybody; a
    token cutoff that could not be written leaves old tokens valid until they expire.

    The caller is told whether its own session was among them, because if it was, the
    browser has to be sent to the login page — nothing else it renders will work.
    """
    identity = require_user_id(user_id)
    session_data = getattr(getattr(request, "ctx", None), "session", None)
    ended_own = isinstance(session_data, SessionData) and session_data.user_id == identity
    # A site with a password form and no session store is misconfigured; say so rather than
    # quietly leaving every session alive after a password change.
    manager = Session.get_session_manager(request)
    try:
        await manager.force_logout_user(identity)
        if ended_own:
            await Session.logout_session(request)
            forget_session_authentication(request)
    except Exception:
        logger.warning("Sessions of user %s could not be ended", identity, exc_info=True)
    await _revoke_tokens(identity)
    return ended_own


async def end_user_logins(user_id: int) -> None:
    """End every session and token one user holds, where there is no request.

    For the command line and background work. A request handler uses revoke_user_logins,
    which ends the same things through the application's own session store and also signs
    its browser out when it was among them. Failures are logged, as there.
    """
    identity = require_user_id(user_id)
    if conf.settings.web.session.enabled:
        try:
            await Session._configured_interface(SessionData).force_logout_user(identity)
        except Exception:
            logger.warning("Sessions of user %s could not be ended", identity, exc_info=True)
    await _revoke_tokens(identity)


async def _revoke_tokens(user_id: int) -> None:
    """Cut the user's access and refresh tokens off, apart from the sessions: one store failing leaves the other."""
    try:
        await revoke_user_tokens(user_id)
    except Exception:
        logger.warning("Tokens of user %s could not be revoked", user_id, exc_info=True)


__all__ = ["end_user_logins", "revoke_user_logins", "session_data_for_user"]
