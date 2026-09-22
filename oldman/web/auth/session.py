"""Map configured authentication Users to strongly typed Web sessions."""

from __future__ import annotations

import time
from typing import Any

from oldman.auth import user_identity
from oldman.logging import get_logger
from oldman.web.session import Session, SessionData

logger = get_logger("default.web.auth.session")


def session_data_for_user[TSessionData: SessionData](
    session_model: type[TSessionData],
    user: Any,
    *,
    expiry: int | None = None,
    login_ip: str = "",
    login_time: int | None = None,
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
    )


async def revoke_user_sessions(request: Any, user_id: int) -> bool:
    """End every session one user holds; report whether the caller ended its own.

    Every path that changes a password goes through this — the user changing their own, an
    operator changing it for them, and the reset flow behind a mailed link — so that no
    session outlives the password it was opened under, whichever route changed it.

    A store that cannot be reached is logged rather than raised. The password has already
    changed by the time this runs, and a session store that is down is not one that is
    still authenticating anybody; failing here would only turn a working change into a 500.

    The caller is told whether its own session was among them, because if it was, the
    browser has to be sent to the login page — nothing else it renders will work.
    """
    if type(user_id) is not int:
        raise TypeError("user_id must be an int")
    identity = user_id
    session_data = getattr(getattr(request, "ctx", None), "session", None)
    ended_own = isinstance(session_data, SessionData) and session_data.user_id == identity
    # A site with a password form and no session store is misconfigured; say so rather than
    # quietly leaving every session alive after a password change.
    manager = Session.get_session_manager(request)
    try:
        await manager.force_logout_user(identity)
        if ended_own:
            await Session.logout_session(request)
    except Exception:
        logger.warning(
            "Password changed for user %s but its sessions could not be ended",
            identity,
            exc_info=True,
        )
    return ended_own


__all__ = ["revoke_user_sessions", "session_data_for_user"]
