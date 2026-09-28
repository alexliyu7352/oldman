"""Authenticate requests by a bearer access token: a JWT signed with ``web.auth.jwt.secret``.

An access token carries a snapshot of the user it was issued to, so reading it needs no
database. It lives ``web.auth.jwt.access_token_ttl`` seconds; a client renews it with a
refresh token rather than by holding one for long.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from redis.exceptions import RedisError
from sanic.exceptions import ServiceUnavailable

import oldman.conf as conf
from oldman.i18n import gettext
from oldman.providers.redis import redis_key
from oldman.security import require_user_id
from oldman.security.jwt import JWTError, jwt_decode, jwt_encode
from oldman.web.authentication.base import Authentication, RequestUser
from oldman.web.request import bearer_credential

JWT_METHOD = "jwt"
_ALGORITHM = "HS256"
_FLAG_CLAIMS = ("is_staff", "is_superuser")
_TEXT_CLAIMS = ("jti", "username", "display_name")


@dataclass(frozen=True, slots=True)
class AccessToken:
    """A signed access token and what a client needs to know about it."""

    token: str
    expires_in: int
    claims: Mapping[str, Any]


def _jwt_settings() -> Any:
    settings = conf.settings.web.auth.jwt
    if settings.secret is None:
        raise RuntimeError("web.auth.jwt.secret is not set")
    return settings


def issue_access_token(user: Any, *, role_ids: Iterable[int] = ()) -> AccessToken:
    """Sign an access token for a user who has just proved who they are.

    ``iat`` and ``exp`` come from one clock reading, so the token's lifetime is exactly
    the configured one — verification refuses anything longer. ``jti`` names this token
    alone, which is what revoking one token later needs. ``roles`` carries the ids of the
    roles the user holds, as a session does; permissions are read from them.
    """
    if type(user.id) is not int:
        raise TypeError("an access token needs a user with an integer id")
    if not user.is_active:
        raise ValueError("an inactive user gets no access token")
    settings = _jwt_settings()
    issued_at = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(user.id),
        "iat": issued_at,
        "exp": issued_at + settings.access_token_ttl,
        "jti": uuid.uuid4().hex,
        "username": str(user.username),
        "display_name": str(user.display_name or user.username),
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
        "roles": sorted(set(role_ids)),
    }
    if settings.issuer is not None:
        claims["iss"] = settings.issuer
    if settings.audience is not None:
        claims["aud"] = settings.audience
    return AccessToken(jwt_encode(claims, settings.secret, algorithm=_ALGORITHM), settings.access_token_ttl, claims)


def read_access_token(token: str) -> Mapping[str, Any] | None:
    """The claims of a valid access token, or None for anything else.

    Beyond the signature and expiry the codec checks, every claim ``issue_access_token``
    writes must be there with its type, and the token may not live longer than the
    configured lifetime: a token signed for longer — before the setting was lowered, or
    by anyone else holding the key — is refused.
    """
    settings = _jwt_settings()
    try:
        claims = jwt_decode(token, settings.secret, algorithms=(_ALGORITHM,), audience=settings.audience, issuer=settings.issuer)
    except JWTError:
        return None
    subject, issued_at, expires_at = claims.get("sub"), claims.get("iat"), claims.get("exp")
    if not isinstance(subject, str) or not subject.isdigit():
        return None
    if type(issued_at) is not int or type(expires_at) is not int or expires_at - issued_at > settings.access_token_ttl:
        return None
    if any(type(claims.get(name)) is not bool for name in _FLAG_CLAIMS):
        return None
    if any(not isinstance(claims.get(name), str) for name in _TEXT_CLAIMS) or not claims["jti"]:
        return None
    roles = claims.get("roles")
    if not isinstance(roles, list) or any(type(role_id) is not int for role_id in roles):
        return None
    return claims


def _revoked_before_key(user_id: int) -> str:
    return redis_key("token", "revoked_before", user_id)


def _revoked_access_token_key(jti: str) -> str:
    return redis_key("token", "revoked", jti)


async def revoke_user_tokens(user_id: int) -> None:
    """Refuse every access token and refresh token this user was issued up to now.

    Nothing is kept per token. The user's cutoff time is written, and an access token
    whose ``iat`` is not after it is refused — one issued in the same second included —
    as is a refresh token from a sign-in that is not after it. Not fixed (G1-3): ``iat`` is whole
    seconds, as JWT has it, so a token issued in the same second as the cutoff is refused too; no
    flow of the framework issues one right after revoking, and a project's own flow waits for the
    next second. The cutoff is kept as long
    as the longer-lived of the two can live; after that every token issued before it has
    expired anyway, so losing the Redis data can revive old tokens for at most one lifetime.

    A service without ``web.auth.jwt.secret`` issues and accepts no tokens, and writes the
    cutoff all the same: an Admin that signs no tokens disables an account or changes its
    password, and the service that does sign them must stop honouring them. Services that
    share users share the security Redis, ``core.namespace`` and the jwt lifetimes - this
    service's lifetimes decide how long the cutoff is kept - so a password changed on any
    one of them reaches all of them.
    """
    require_user_id(user_id)
    settings = conf.settings.web.auth.jwt
    from oldman.web.security.store import security_redis_connection

    connection = await security_redis_connection()
    lifetime = max(settings.access_token_ttl, settings.refresh_token_ttl)
    await connection.set(_revoked_before_key(user_id), int(time.time()), ex=lifetime)


async def revoke_access_token(claims: Mapping[str, Any]) -> None:
    """Refuse this one access token from now on, as signing out of one client does.

    Its ``jti`` is kept until the token would have expired anyway. Unreachable Redis
    answers 503: a sign-out that did not happen must not be reported as done.
    """
    remaining = claims["exp"] - int(time.time())
    if remaining <= 0:
        return
    from oldman.web.security.store import security_redis_connection

    try:
        connection = await security_redis_connection()
        await connection.set(_revoked_access_token_key(claims["jti"]), 1, ex=remaining)
    except RedisError as exc:
        raise ServiceUnavailable(gettext("The access token revocation store is unavailable")) from exc


async def access_token_revoked(claims: Mapping[str, Any]) -> bool:
    """Whether this token was revoked, or the user's tokens were cut off at or after it was issued.

    Both are read in one round trip. Unreachable Redis answers 503, as the session
    middleware does: a revocation that cannot be checked must not be read as "not revoked".
    """
    from oldman.web.security.store import security_redis_connection

    try:
        connection = await security_redis_connection()
        cutoff, revoked = await connection.mget(_revoked_before_key(int(claims["sub"])), _revoked_access_token_key(claims["jti"]))
    except RedisError as exc:
        raise ServiceUnavailable(gettext("The access token revocation store is unavailable")) from exc
    return revoked is not None or (cutoff is not None and claims["iat"] <= int(cutoff))


def user_from_access_token(claims: Mapping[str, Any]) -> RequestUser:
    """The user snapshot an access token carries."""
    return RequestUser(
        id=int(claims["sub"]),
        username=claims["username"],
        display_name=claims["display_name"],
        is_staff=claims["is_staff"],
        is_superuser=claims["is_superuser"],
        role_ids=tuple(claims["roles"]),
    )


class JWTAuthentication:
    """A bearer access token in the ``Authorization`` header.

    A token that is missing, malformed, expired or signed with another key leaves the
    request to the next method, and anonymous at the end: whether that is allowed is the
    permission layer's answer, and an API-key bearer secret meant for another check must
    not be turned away here. The client attaches the header on purpose, so the credential
    is not ambient and CSRF protection does not apply.
    """

    name = JWT_METHOD

    def __init__(self) -> None:
        if conf.settings.web.auth.jwt.secret is None:
            raise ValueError("web.auth.authenticators lists 'jwt' but web.auth.jwt.secret is not set")
        from oldman.providers.redis import redis_client
        from oldman.web.security.store import security_redis_alias

        # Checked now so a missing alias stops startup; no connection is opened here.
        redis_client.using(security_redis_alias())

    async def authenticate(self, request: Any) -> Authentication | None:
        token = bearer_credential(request)
        if token is None:
            return None
        claims = read_access_token(token)
        if claims is None or await access_token_revoked(claims):
            return None
        return Authentication(method=self.name, user=user_from_access_token(claims), ambient=False, claims=claims)


__all__ = [
    "JWT_METHOD",
    "AccessToken",
    "JWTAuthentication",
    "access_token_revoked",
    "issue_access_token",
    "read_access_token",
    "revoke_access_token",
    "revoke_user_tokens",
    "user_from_access_token",
]
