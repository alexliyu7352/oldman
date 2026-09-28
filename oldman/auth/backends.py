"""Login backends: check a credential at sign-in and return the User it signs in.

A login backend answers one question when someone signs in or asks for a token: whose
credential is this? It is not consulted again on later requests — those carry a session
or a token, and the request authentication pipeline recognizes that instead.
"""

from __future__ import annotations

from functools import cache
from typing import Any, Protocol

from oldman.auth.base import AbstractUser
from oldman.auth.services import authenticate_user
from oldman.utils.module_loading import build_configured


class LoginBackend(Protocol):
    """One kind of credential a service accepts at sign-in.

    ``credentials`` are keyword arguments, as in Django: each backend takes the ones it
    understands and returns None when they are missing or do not match, so the next
    backend is tried. It returns the User to sign in, never a response.
    """

    name: str

    async def authenticate(self, request: Any, **credentials: Any) -> AbstractUser | None: ...


class UserTableBackend:
    """A username and password checked against the configured User table.

    It reads ``username`` and ``password`` and, when a caller has its own, the
    ``auth_settings`` and ``db_manager`` to reach the table with; see
    :func:`oldman.auth.authenticate_user` for the checks themselves.
    """

    name = "users"

    async def authenticate(
        self,
        request: Any,
        *,
        username: Any = None,
        password: Any = None,
        auth_settings: Any = None,
        db_manager: Any = None,
        **credentials: Any,
    ) -> AbstractUser | None:
        del request, credentials
        if not isinstance(username, str) or not isinstance(password, str):
            return None
        return await authenticate_user(username, password, auth_settings=auth_settings, db_manager=db_manager)


#: Backends a service names by a bare word in ``web.auth.login_backends``.
BUILTIN_LOGIN_BACKENDS: dict[str, type[LoginBackend]] = {
    "users": UserTableBackend,
}


@cache
def resolve_login_backends(names: tuple[str, ...]) -> tuple[LoginBackend, ...]:
    """Build the backends a service tries, in the order they are listed.

    Cached by the list itself, since sign-in asks for them every time and they hold no
    state of their own.
    """
    backends = build_configured(names, BUILTIN_LOGIN_BACKENDS, setting="web.auth.login_backends")
    for name, backend in zip(names, backends, strict=True):
        if not isinstance(getattr(backend, "name", None), str) or not callable(getattr(backend, "authenticate", None)):
            raise TypeError(f"{name!r} does not build a login backend: it needs a name and authenticate(request, **credentials)")
    return tuple(backends)


async def authenticate_with(backends: tuple[LoginBackend, ...], request: Any, **credentials: Any) -> AbstractUser | None:
    """Ask each backend in turn; the first to accept the credential decides."""
    for backend in backends:
        user = await backend.authenticate(request, **credentials)
        if user is not None:
            return user
    return None


__all__ = ["BUILTIN_LOGIN_BACKENDS", "LoginBackend", "UserTableBackend", "authenticate_with", "resolve_login_backends"]
