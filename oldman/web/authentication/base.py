"""Who is making a request, and how they proved it."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from oldman.web.session.base import SessionData


class AnonymousUser:
    """No one. Every permission answers no, whatever else the request carries."""

    __slots__ = ()

    id: None = None
    username = ""
    display_name = ""
    is_authenticated = False
    is_anonymous = True
    is_active = False
    is_staff = False
    is_superuser = False
    role_ids: tuple[int, ...] = ()

    def __repr__(self) -> str:
        return "<AnonymousUser>"


#: The one anonymous user; compare with ``is`` or read ``is_authenticated``.
ANONYMOUS_USER = AnonymousUser()


@dataclass(frozen=True, slots=True)
class RequestUser:
    """A signed-in user as the request knows them: a snapshot, not a database row.

    The snapshot is taken where the credential was issued — at login for a session, at
    signing for a token — and nothing here reads the database again. A change to the user
    reaches requests through revocation: the session or token carrying the old snapshot
    stops being accepted. Code that needs the full row loads it by ``id``.
    """

    id: int
    username: str
    display_name: str = ""
    is_staff: bool = False
    is_superuser: bool = False
    #: The roles held when the credential was issued; permissions come from them.
    role_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if type(self.id) is not int:
            raise TypeError("RequestUser.id must be an int")

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def is_active(self) -> bool:
        # Inactive users are never authenticated, so a RequestUser always is.
        return True


@dataclass(frozen=True, slots=True)
class Authentication:
    """How the request proved who, or what, it is.

    ``user`` is the signed-in user, or anonymous when the caller is not a user at all — a
    service holding an API key, a network on an allowlist. ``caller`` then names which one.
    ``ambient`` says whether a browser attaches the credential by itself (a cookie, cached
    HTTP Basic, the client's address): such a credential can be carried by a forged
    cross-site request, so CSRF protection still applies. The default is the safe answer.
    """

    method: str
    user: RequestUser | AnonymousUser = ANONYMOUS_USER
    caller: str | None = None
    ambient: bool = True
    claims: Mapping[str, Any] | None = None


class Authenticator(Protocol):
    """One way of recognizing a request's credential.

    ``authenticate`` returns None when the request carries no credential of this kind, or
    one it does not accept; the next method is then tried. It never answers the request —
    deciding what an unauthenticated caller may do is the permission layer's job.
    """

    name: str

    async def authenticate(self, request: Any) -> Authentication | None: ...


def user_from_session(session: Any) -> RequestUser | AnonymousUser:
    """The user a browser session signs in, or anonymous."""
    if not isinstance(session, SessionData) or not session.is_authenticated() or session.user_id is None:
        return ANONYMOUS_USER
    return RequestUser(
        id=session.user_id,
        username=session.username,
        display_name=session.display_name or session.username,
        is_staff=session.is_staff,
        is_superuser=session.is_superuser,
        role_ids=tuple(session.role_ids),
    )


def request_user(request: Any) -> RequestUser | AnonymousUser:
    """The user the authentication pipeline recorded for this request.

    Applications use ``request.ctx.user`` directly; every WebApplication records one. The
    framework's own permission checks go through here so that they still work where no
    pipeline runs — a bare Sanic application with only the Session extension, a test that
    builds a request by hand. There the session answers, as it did before the pipeline.
    """
    ctx = getattr(request, "ctx", None)
    user = getattr(ctx, "user", None)
    if isinstance(user, RequestUser | AnonymousUser):
        return user
    return user_from_session(getattr(ctx, "session", None))


def record_authentication(request: Any, authentication: Authentication | None) -> None:
    """Set ``request.ctx.user`` and ``request.ctx.auth`` from one authentication, or anonymous."""
    request.ctx.user = ANONYMOUS_USER if authentication is None else authentication.user
    request.ctx.auth = authentication


def exempt_from_csrf(request: Any) -> bool:
    """Whether this request authenticated with a credential a forged request cannot carry.

    A bearer token or an API key in a header is attached by the client on purpose, never
    by the browser on its own, so a cross-site form cannot send it. A signed-in browser
    session on the same request keeps its protection whatever else came along: the
    session is what a forged request would be riding on.
    """
    ctx = getattr(request, "ctx", None)
    auth = getattr(ctx, "auth", None)
    if not isinstance(auth, Authentication) or auth.ambient:
        return False
    return user_from_session(getattr(ctx, "session", None)).is_anonymous


__all__ = [
    "ANONYMOUS_USER",
    "AnonymousUser",
    "Authentication",
    "Authenticator",
    "RequestUser",
    "exempt_from_csrf",
    "record_authentication",
    "request_user",
    "user_from_session",
]
