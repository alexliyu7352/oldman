"""Build the configured authentication methods and run them on every request."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from oldman.utils.module_loading import build_configured
from oldman.web.authentication.api_key import APIKeyAuthentication
from oldman.web.authentication.base import Authenticator, record_authentication
from oldman.web.authentication.http_basic import HTTPBasicAuthentication
from oldman.web.authentication.ip_allowlist import IP_ALLOWLIST_METHOD, IPAllowlistAuthentication
from oldman.web.authentication.jwt import JWTAuthentication
from oldman.web.authentication.session import SessionAuthentication

#: Methods a service names by a bare word in ``web.auth.authenticators``; anything else
#: there is an import path to a project's own class.
BUILTIN_AUTHENTICATORS: dict[str, Callable[[], Authenticator]] = {
    "session": SessionAuthentication,
    "jwt": JWTAuthentication,
    "api_key": APIKeyAuthentication,
    "http_basic": HTTPBasicAuthentication,
    "ip_allowlist": IPAllowlistAuthentication,
}


def resolve_authenticators(names: Sequence[str] | None, *, session_enabled: bool) -> tuple[Authenticator, ...]:
    """Build the methods a service tries, in the order they are listed.

    Leaving the list unset means the session alone when sessions are on, and nothing when
    they are off: no method runs that a deployment did not choose. Listing ``session``
    without the Session middleware is refused at startup rather than never matching, and so
    is ``ip_allowlist`` anywhere but last.
    """
    selected = list(names) if names is not None else (["session"] if session_enabled else [])
    if "session" in selected and not session_enabled:
        raise ValueError("web.auth.authenticators lists 'session' but web.session.enabled is false")
    if IP_ALLOWLIST_METHOD in selected and selected[-1] != IP_ALLOWLIST_METHOD:
        # Tried first, an allowed address would stand in for the session or token the same request carries.
        raise ValueError("web.auth.authenticators must list 'ip_allowlist' last")
    authenticators = build_configured(selected, BUILTIN_AUTHENTICATORS, setting="web.auth.authenticators")
    for name, authenticator in zip(selected, authenticators, strict=True):
        if not isinstance(getattr(authenticator, "name", None), str) or not callable(getattr(authenticator, "authenticate", None)):
            raise TypeError(f"{name!r} does not build an authenticator: it needs a name and authenticate(request)")
    return tuple(authenticators)


def install_authentication(app: Any, authenticators: Sequence[Authenticator]) -> None:
    """Record ``request.ctx.user`` and ``request.ctx.auth`` before any handler runs.

    The methods are tried in order and the first to recognize a credential decides; a
    request nothing recognizes leaves anonymous. Request middleware runs in registration
    order, so this has to be registered after the Session middleware.
    """
    methods = tuple(authenticators)

    async def authenticate_request(request: Any) -> None:
        for authenticator in methods:
            result = await authenticator.authenticate(request)
            if result is not None:
                record_authentication(request, result)
                return
        record_authentication(request, None)

    app.register_middleware(authenticate_request, "request")


__all__ = ["BUILTIN_AUTHENTICATORS", "install_authentication", "resolve_authenticators"]
