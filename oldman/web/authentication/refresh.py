"""Refresh tokens: how a client gets a new access token without signing in again.

A refresh token is an opaque random string; Redis keeps only its SHA-256, so a copy of the
store holds nothing a client could present. Every sign-in starts a family, and every use
of a refresh token replaces it with the next one of the same family: the old one stops
working, the new one lives ``web.auth.jwt.refresh_token_ttl`` seconds from then. A client
that refreshes within that time stays signed in.

A refresh token that was already replaced and is presented again means two parties hold
the family — the client and whoever copied its token — and nobody can tell which is which,
so the whole family ends and both sign in again. The access tokens it already handed out
are not recalled; they expire within ``web.auth.jwt.access_token_ttl``.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

from redis.exceptions import RedisError
from sanic.exceptions import ServiceUnavailable

from oldman.i18n import gettext
from oldman.logging import get_logger
from oldman.providers.redis import redis_key
from oldman.security import require_user_id
from oldman.web.authentication.jwt import _jwt_settings, _revoked_before_key

logger = get_logger("default.web.authentication.refresh")

# 32 random bytes: as strong as the HS256 key that signs the access tokens.
_TOKEN_BYTES = 32

# KEYS: family, new token, the user's cutoff. ARGV: presented hash, new hash, lifetime, new token record.
# Returns 1 when rotated, 0 when the family is gone or was cut off, -1 when a replaced token came back.
_ROTATE_LUA = """
local current = redis.call('HGET', KEYS[1], 'current')
if not current then
    return 0
end
if current ~= ARGV[1] then
    redis.call('DEL', KEYS[1])
    return -1
end
local cutoff = redis.call('GET', KEYS[3])
if cutoff and tonumber(redis.call('HGET', KEYS[1], 'login_at')) <= tonumber(cutoff) then
    redis.call('DEL', KEYS[1])
    return 0
end
redis.call('HSET', KEYS[1], 'current', ARGV[2])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('SET', KEYS[2], ARGV[4], 'EX', ARGV[3])
return 1
"""


@dataclass(frozen=True, slots=True)
class RefreshToken:
    """A refresh token and how long it may be used."""

    token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class RotatedRefreshToken:
    """The user a refresh token was issued to, and the token that replaces it."""

    user_id: int
    refresh_token: RefreshToken


def _digest(token: str) -> str:
    # surrogatepass: a lone surrogate a caller passes still hashes, to a digest no issued token has.
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


def _token_key(digest: str) -> str:
    return redis_key("token", "refresh", digest)


def _family_key(family: str) -> str:
    return redis_key("token", "refresh_family", family)


@contextmanager
def _store_available():
    """Unreachable Redis answers 503: a refresh token that cannot be checked is not a valid one."""
    try:
        yield
    except RedisError as exc:
        raise ServiceUnavailable(gettext("The refresh token store is unavailable")) from exc


async def _connection():
    from oldman.web.security.store import security_redis_connection

    return await security_redis_connection()


async def _family_of(token: object) -> tuple[str, int] | None:
    """The family and user a refresh token record names, or None for an unknown token."""
    if not isinstance(token, str) or not token:
        return None
    record = await (await _connection()).get(_token_key(_digest(token)))
    if record is None:
        return None
    if isinstance(record, bytes):
        # An alias configured with decode_responses: false answers in bytes.
        record = record.decode()
    family, _, user_id = record.partition(":")
    return family, int(user_id)


async def refresh_token_user(token: object) -> int | None:
    """The user a refresh token was issued to, or None when it is unknown; the token stays unused.

    Check the user before ``rotate_refresh_token`` uses the token up: a lookup that fails
    after the rotation leaves the client holding a replaced token, whose next use ends the
    whole sign-in as if it had been stolen.
    """
    with _store_available():
        found = await _family_of(token)
    return None if found is None else found[1]


async def issue_refresh_token(user_id: int) -> RefreshToken:
    """Start a new family for a user who has just signed in, and return its first token."""
    require_user_id(user_id)
    lifetime = _jwt_settings().refresh_token_ttl
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    digest = _digest(token)
    family = uuid.uuid4().hex
    with _store_available():
        connection = await _connection()
        async with connection.pipeline(transaction=True) as pipeline:
            pipeline.hset(_family_key(family), mapping={"user_id": user_id, "login_at": int(time.time()), "current": digest})
            pipeline.expire(_family_key(family), lifetime)
            pipeline.set(_token_key(digest), f"{family}:{user_id}", ex=lifetime)
            await pipeline.execute()
    return RefreshToken(token, lifetime)


async def rotate_refresh_token(token: object) -> RotatedRefreshToken | None:
    """Replace a refresh token with the next one of its family, or None when it is not valid.

    Not valid: unknown, expired, from a family that was revoked or whose user's tokens
    were cut off after the sign-in, or already replaced — which also ends its family. The
    check and the replacement are one atomic step, so two requests racing with the same
    token cannot both succeed: the second one counts as reuse.
    """
    lifetime = _jwt_settings().refresh_token_ttl
    with _store_available():
        found = await _family_of(token)
        if found is None:
            return None
        family, user_id = found
        replacement = secrets.token_urlsafe(_TOKEN_BYTES)
        replacement_digest = _digest(replacement)
        script = (await _connection()).register_script(_ROTATE_LUA)
        outcome = await script(
            keys=[_family_key(family), _token_key(replacement_digest), _revoked_before_key(user_id)],
            args=[_digest(str(token)), replacement_digest, lifetime, f"{family}:{user_id}"],
        )
    if outcome == -1:
        logger.warning("A replaced refresh token of user %s was presented again; its sign-in was ended", user_id)
    if outcome != 1:
        return None
    return RotatedRefreshToken(user_id, RefreshToken(replacement, lifetime))


async def revoke_refresh_token(token: object) -> None:
    """End the family a refresh token belongs to, as signing out of one client does.

    An unknown or expired token is not an error: there is nothing left to end.
    """
    with _store_available():
        found = await _family_of(token)
        if found is not None:
            await (await _connection()).delete(_family_key(found[0]))


__all__ = [
    "RefreshToken",
    "RotatedRefreshToken",
    "issue_refresh_token",
    "refresh_token_user",
    "revoke_refresh_token",
    "rotate_refresh_token",
]
