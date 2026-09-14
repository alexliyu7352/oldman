"""Map configured authentication Users to strongly typed Web sessions."""

from __future__ import annotations

import time
from typing import Any

from oldman.auth import user_identity
from oldman.web.session import SessionData


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


__all__ = ["session_data_for_user"]
