"""Authenticate a request by the browser session its cookie opened."""

from __future__ import annotations

from typing import Any

from oldman.web.authentication.base import Authentication, record_authentication, user_from_session

SESSION_METHOD = "session"


def session_authentication(session: Any) -> Authentication | None:
    """What a signed-in browser session proves, or None when it signs no one in.

    The cookie travels with every request the browser makes, forged or not, so the
    result is ambient and CSRF protection stays on.
    """
    user = user_from_session(session)
    if user.is_anonymous:
        return None
    return Authentication(method=SESSION_METHOD, user=user, ambient=True)


def forget_session_authentication(request: Any) -> None:
    """After this request's own session ended, it no longer authenticates by it.

    Only a session authentication is dropped: a request that proved itself some other way
    is still that caller after its browser signs out.
    """
    current = getattr(getattr(request, "ctx", None), "auth", None)
    if isinstance(current, Authentication) and current.method == SESSION_METHOD:
        record_authentication(request, None)


class SessionAuthentication:
    """The signed-in browser session, if the request has one.

    It reads what the Session middleware already attached, so it has to run after it; the
    Web runtime installs the pipeline right behind that middleware.
    """

    name = SESSION_METHOD

    async def authenticate(self, request: Any) -> Authentication | None:
        return session_authentication(getattr(getattr(request, "ctx", None), "session", None))


__all__ = ["SESSION_METHOD", "SessionAuthentication", "forget_session_authentication", "session_authentication"]
