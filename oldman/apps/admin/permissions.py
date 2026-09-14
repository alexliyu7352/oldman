"""Admin permission helpers."""

from __future__ import annotations

from typing import Any

from oldman.web.session import SessionData


def request_session(request: Any) -> SessionData | None:
    """Return the request's strongly typed SessionData when available."""
    session = getattr(getattr(request, "ctx", None), "session", None)
    return session if isinstance(session, SessionData) else None


def is_authenticated(request: Any) -> bool:
    """Return whether request has an authenticated session."""
    session = request_session(request)
    return bool(session and session.is_authenticated())


def is_staff(request: Any) -> bool:
    """Return whether current session has Admin staff permission."""
    session = request_session(request)
    return bool(session and session.is_staff)


def is_superuser(request: Any) -> bool:
    """Return whether current session has superuser permission."""
    session = request_session(request)
    return bool(session and session.is_superuser)


def has_admin_permission(request: Any, *, require_superuser: bool = False) -> bool:
    """Return whether request can access Admin."""
    if not is_authenticated(request):
        return False
    if not is_staff(request):
        return False
    if require_superuser and not is_superuser(request):
        return False
    return True
