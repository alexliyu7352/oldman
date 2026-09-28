"""Admin permission helpers."""

from __future__ import annotations

from typing import Any

from oldman.web.authentication import request_user


def is_authenticated(request: Any) -> bool:
    """Return whether the request comes from a signed-in user, however it authenticated."""
    return request_user(request).is_authenticated


def is_staff(request: Any) -> bool:
    """Return whether the request's user has Admin staff permission."""
    return request_user(request).is_staff


def is_superuser(request: Any) -> bool:
    """Return whether the request's user has superuser permission."""
    return request_user(request).is_superuser


def has_admin_permission(request: Any, *, require_superuser: bool = False) -> bool:
    """Return whether request can access Admin."""
    if not is_authenticated(request):
        return False
    if not is_staff(request):
        return False
    if require_superuser and not is_superuser(request):
        return False
    return True
