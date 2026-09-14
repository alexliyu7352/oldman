"""Redis-backed, strongly typed Web session storage."""

import datetime
import time
import uuid
from dataclasses import dataclass
from typing import Any, cast

import msgspec
from sanic import Request
from sanic.cookies.response import SameSite
from sanic.response import BaseHTTPResponse

from oldman.logging import logger
from oldman.providers.redis import redis_client
from oldman.serializers import MsgspecModel

_LOGIN_LUA = """
local user_key = KEYS[1]
local session_key = KEYS[2]
local payload = ARGV[1]
local sid = ARGV[2]
local expiry = tonumber(ARGV[3])
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)

-- Remove expired members before adding the new ordinary login.
redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
redis.call('SET', session_key, payload, 'EX', expiry)
redis.call('ZADD', user_key, now + expiry * 1000, sid)

local latest = redis.call('ZREVRANGE', user_key, 0, 0, 'WITHSCORES')
redis.call('PEXPIREAT', user_key, math.ceil(tonumber(latest[2])))
return 1
"""


_EXCLUSIVE_LOGIN_LUA = """
local user_key = KEYS[1]
local session_key = KEYS[2]
local payload = ARGV[1]
local sid = ARGV[2]
local expiry = tonumber(ARGV[3])
local session_prefix = ARGV[4]
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)

-- An exclusive login revokes every still-indexed session atomically.
redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
local old_sids = redis.call('ZRANGE', user_key, 0, -1)
for _, old_sid in ipairs(old_sids) do
    redis.call('DEL', session_prefix .. old_sid)
end
redis.call('DEL', user_key)

redis.call('SET', session_key, payload, 'EX', expiry)
redis.call('ZADD', user_key, now + expiry * 1000, sid)
redis.call('PEXPIREAT', user_key, now + expiry * 1000)
return 1
"""


_SAVE_AUTHENTICATED_LUA = """
local user_key = KEYS[1]
local session_key = KEYS[2]
local payload = ARGV[1]
local sid = ARGV[2]
local expiry = tonumber(ARGV[3])
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)

-- A stale request must not recreate a SID whose data or index was removed.
local indexed = redis.call('ZSCORE', user_key, sid) ~= false
local session_exists = redis.call('EXISTS', session_key) == 1
if not indexed or not session_exists then
    redis.call('DEL', session_key)
    redis.call('ZREM', user_key, sid)
    local latest = redis.call('ZREVRANGE', user_key, 0, 0, 'WITHSCORES')
    if #latest == 0 then
        redis.call('DEL', user_key)
    else
        redis.call('PEXPIREAT', user_key, math.ceil(tonumber(latest[2])))
    end
    return 0
end

redis.call('SET', session_key, payload, 'EX', expiry)
redis.call('ZADD', user_key, now + expiry * 1000, sid)
local latest = redis.call('ZREVRANGE', user_key, 0, 0, 'WITHSCORES')
redis.call('PEXPIREAT', user_key, math.ceil(tonumber(latest[2])))
return 1
"""


_VALIDATE_EXCLUSIVE_LUA = """
local user_key = KEYS[1]
local session_key = KEYS[2]
local sid = ARGV[1]
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
local session_exists = redis.call('EXISTS', session_key)
if session_exists == 0 then
    redis.call('ZREM', user_key, sid)
end
local indexed = redis.call('ZSCORE', user_key, sid) ~= false
if not indexed and session_exists == 1 then
    redis.call('DEL', session_key)
end

local latest = redis.call('ZREVRANGE', user_key, 0, 0, 'WITHSCORES')
if #latest == 0 then
    redis.call('DEL', user_key)
    return 0
end
redis.call('PEXPIREAT', user_key, math.ceil(tonumber(latest[2])))

if not indexed or redis.call('ZCARD', user_key) ~= 1 then
    return 0
end
return 1
"""


_VALIDATE_SESSION_LUA = """
local user_key = KEYS[1]
local session_key = KEYS[2]
local sid = ARGV[1]
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)

-- Validation is read-only apart from removing expired or orphaned index data.
-- It must not refresh the session TTL or the member's expiry score.
redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
local session_exists = redis.call('EXISTS', session_key) == 1
local indexed = redis.call('ZSCORE', user_key, sid) ~= false

if indexed and not session_exists then
    redis.call('ZREM', user_key, sid)
    if redis.call('ZCARD', user_key) == 0 then
        redis.call('DEL', user_key)
    end
    return 0
end

-- An existing value may belong to another user. Never delete it merely
-- because the caller supplied the wrong user index.
if not indexed or not session_exists then
    return 0
end
return 1
"""


_LOGOUT_LUA = """
local session_key = KEYS[1]
local user_key = KEYS[2]
local sid = ARGV[1]
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)

-- Remove only the caller's SID; another concurrent login remains valid.
redis.call('DEL', session_key)
redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
redis.call('ZREM', user_key, sid)

local latest = redis.call('ZREVRANGE', user_key, 0, 0, 'WITHSCORES')
if #latest == 0 then
    redis.call('DEL', user_key)
else
    redis.call('PEXPIREAT', user_key, math.ceil(tonumber(latest[2])))
end
return 1
"""


_FORCE_LOGOUT_LUA = """
local user_key = KEYS[1]
local session_prefix = ARGV[1]
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
local sids = redis.call('ZRANGE', user_key, 0, -1)
for _, sid in ipairs(sids) do
    redis.call('DEL', session_prefix .. sid)
end
redis.call('DEL', user_key)
return sids
"""


_ACTIVE_SESSIONS_LUA = """
local user_key = KEYS[1]
local session_prefix = ARGV[1]
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
local indexed = redis.call('ZRANGE', user_key, 0, -1)
local active = {}
for _, sid in ipairs(indexed) do
    if redis.call('EXISTS', session_prefix .. sid) == 1 then
        table.insert(active, sid)
    else
        redis.call('ZREM', user_key, sid)
    end
end

local latest = redis.call('ZREVRANGE', user_key, 0, 0, 'WITHSCORES')
if #latest == 0 then
    redis.call('DEL', user_key)
else
    redis.call('PEXPIREAT', user_key, math.ceil(tonumber(latest[2])))
end
return active
"""


class SessionData(MsgspecModel, kw_only=True):
    """Base identity and authorization snapshot for application sessions."""

    expiry: int | None = None
    user_id: int | None = None
    username: str = ""
    display_name: str = ""
    login_ip: str = ""
    login_time: int = 0
    is_active: bool = False
    is_staff: bool = False
    is_superuser: bool = False

    def is_authenticated(self) -> bool:
        """Return whether this model represents an authenticated user."""
        return self.is_active and self.user_id is not None

    @property
    def is_anonymous(self) -> bool:
        """Return whether this model has no authenticated identity."""
        return not self.is_authenticated()


@dataclass(slots=True)
class _RequestSessionState:
    """Keep transport metadata separate from application session fields."""

    sid: str
    initial_snapshot: bytes
    original_user_id: int | None
    persisted: bool
    skip_save: bool = False
    delete_cookie: bool = False


class DefaultSessionInterface:
    """Store one strongly typed session model in a named Redis connection."""

    _state_prefix = "_oldman_session_state_"

    def __init__(
        self,
        expiry: int = 2592000,
        prefix: str = "session:",
        user_prefix: str = "user_session:",
        cookie_name: str = "session_id",
        domain: str | None = None,
        httponly: bool = True,
        secure: bool = False,
        samesite: SameSite | None = "Lax",
        session_name: str = "session",
        redis_alias: str = "SESSION",
        session_model: type[SessionData] = SessionData,
    ) -> None:
        """Validate local configuration without opening a Redis connection."""
        if type(expiry) is not int:
            raise TypeError("Session default expiry must be an integer")
        if expiry <= 0:
            raise ValueError("Session expiry must be greater than zero")
        if not isinstance(session_model, type) or not issubclass(session_model, SessionData):
            raise TypeError("session_model must be a SessionData subclass")

        self.expiry = expiry
        self.prefix = prefix
        self.user_prefix = user_prefix
        self.cookie_name = cookie_name
        self.domain = domain
        self.httponly = httponly
        self.secure = secure
        self.samesite: SameSite | None = samesite
        self.session_name = session_name
        self.redis_alias = redis_alias
        self.session_model = session_model
        self._data_decoder = msgspec.msgpack.Decoder(type=self.session_model)

        # Application defaults are a local model contract and fail before the
        # extension is installed; no Redis server is contacted here.
        anonymous = self._new_anonymous()
        validated, _snapshot = self._validate_and_encode(anonymous)
        if self._session_user_id(validated) is not None:
            raise TypeError("session_model defaults must create an anonymous session")

    async def open(self, request: Request) -> SessionData:
        """Load a typed session and attach it to the current request context."""
        cookie_sid = request.cookies.get(self.cookie_name)
        sid = str(cookie_sid) if cookie_sid else uuid.uuid4().hex
        loaded = await self._read_session(sid) if cookie_sid else None

        if loaded is None:
            # Missing and invalid external SIDs are never reused.
            if cookie_sid:
                sid = uuid.uuid4().hex
            data = self._new_anonymous()
            snapshot = data.to_msgpack()
            persisted = False
        else:
            data, snapshot = loaded
            persisted = True

        original_user_id = self._session_user_id(data)
        setattr(request.ctx, self.session_name, data)
        setattr(
            request.ctx,
            self._state_name,
            _RequestSessionState(
                sid=sid,
                initial_snapshot=snapshot,
                original_user_id=original_user_id,
                persisted=persisted,
            ),
        )
        return data

    async def save(self, request: Request, response: BaseHTTPResponse) -> None:
        """Persist a changed request model and update its browser cookie."""
        state = self._request_state(request, required=False)
        if state is None:
            return
        if state.skip_save:
            if state.delete_cookie:
                self._delete_cookie(response)
            return

        data = self._request_data(request)
        snapshot = data.to_msgpack()
        if snapshot == state.initial_snapshot:
            return
        validated = self._decode_snapshot(snapshot)
        current_user_id = self._session_user_id(validated)
        resolved_expiry = self._resolve_expiry(validated.expiry)

        # Authentication identity changes must use login/logout so SID rotation
        # and the user index remain atomic.
        if state.original_user_id is None and current_user_id is not None:
            raise RuntimeError("Authenticated sessions must be created with login() or exclusive_login()")
        if state.original_user_id is not None and current_user_id != state.original_user_id:
            raise RuntimeError("Authenticated identity changes must use logout() followed by login()")

        if current_user_id is None:
            connection = await self._get_redis()
            if state.persisted:
                updated = await connection.set(
                    self._get_session_key(state.sid),
                    snapshot,
                    ex=resolved_expiry,
                    xx=True,
                )
                if not updated:
                    # An expired or explicitly deleted anonymous SID must not
                    # be recreated by a request that opened it earlier.
                    state.skip_save = True
                    return
            else:
                await connection.set(self._get_session_key(state.sid), snapshot, ex=resolved_expiry)
                state.persisted = True
        else:
            saved = await self._save_authenticated(state.sid, current_user_id, snapshot, resolved_expiry)
            if not saved:
                # Another request revoked this SID. The stale response must not
                # delete a newer login cookie that may already be in the browser.
                state.skip_save = True
                return

        self._set_cookie(response, state.sid, resolved_expiry)
        state.initial_snapshot = snapshot

    async def login(self, session_data: SessionData) -> str:
        """Create an ordinary login without revoking the user's other sessions."""
        user_id, resolved_expiry, payload = self._prepare_login(session_data)
        new_sid = uuid.uuid4().hex
        await self._execute_script(
            _LOGIN_LUA,
            keys=[self._get_user_key(user_id), self._get_session_key(new_sid)],
            args=[payload, new_sid, resolved_expiry],
        )
        return new_sid

    async def exclusive_login(self, session_data: SessionData) -> str:
        """Create a login while atomically revoking all other user sessions."""
        user_id, resolved_expiry, payload = self._prepare_login(session_data)
        new_sid = uuid.uuid4().hex
        await self._execute_script(
            _EXCLUSIVE_LOGIN_LUA,
            keys=[self._get_user_key(user_id), self._get_session_key(new_sid)],
            args=[payload, new_sid, resolved_expiry, self.prefix],
        )
        return new_sid

    async def validate_exclusive_session(self, session_id: str, user_id: int) -> bool:
        """Return whether the SID is the user's only active indexed session."""
        if not session_id:
            return False
        result = await self._execute_script(
            _VALIDATE_EXCLUSIVE_LUA,
            keys=[self._get_user_key(user_id), self._get_session_key(session_id)],
            args=[session_id],
        )
        return bool(result)

    async def validate_session(self, session_id: str, user_id: int) -> bool:
        """Return whether an ordinary SID is still active for the supplied user."""
        if not session_id:
            return False
        result = await self._execute_script(
            _VALIDATE_SESSION_LUA,
            keys=[self._get_user_key(user_id), self._get_session_key(session_id)],
            args=[session_id],
        )
        return bool(result)

    async def logout(self, session_id: str | None) -> None:
        """Resolve one SID's stored identity and delete it idempotently."""
        if not session_id:
            return
        loaded = await self._read_session(session_id)
        if loaded is None:
            return
        data, _snapshot = loaded
        await self._logout_known_session(session_id, self._session_user_id(data))

    async def force_logout_user(self, user_id: int) -> tuple[str, ...]:
        """Delete all active sessions for one user and return their SIDs."""
        result = await self._execute_script(
            _FORCE_LOGOUT_LUA,
            keys=[self._get_user_key(user_id)],
            args=[self.prefix],
        )
        return self._decode_session_ids(result)

    async def get_active_session_ids(self, user_id: int) -> tuple[str, ...]:
        """Return every non-expired SID whose Redis session value still exists."""
        result = await self._execute_script(
            _ACTIVE_SESSIONS_LUA,
            keys=[self._get_user_key(user_id)],
            args=[self.prefix],
        )
        return self._decode_session_ids(result)

    async def is_user_online(self, user_id: int) -> bool:
        """Return whether the user has at least one active Redis session."""
        return bool(await self.get_active_session_ids(user_id))

    def update_session_id_to_cookie(
        self,
        response: BaseHTTPResponse,
        new_sid: str,
        session_data: SessionData,
    ) -> None:
        """Write a login SID to the response using the configured cookie policy."""
        _user_id, resolved_expiry, _snapshot = self._prepare_login(session_data)
        self._write_cookie(response, new_sid, resolved_expiry)

    def get_session_id(self, request: Request) -> str:
        """Return the SID captured by middleware instead of rereading the cookie."""
        state = self._request_state(request, required=True)
        assert state is not None
        return state.sid

    async def _logout_request(self, request: Request) -> None:
        """Delete the current request SID and mark its response cookie for removal."""
        state = self._request_state(request, required=False)
        if state is None or state.skip_save:
            return
        # The identity captured at open time is authoritative even if handler
        # code has accidentally mutated or replaced the public model.
        await self._logout_known_session(state.sid, state.original_user_id)
        state.skip_save = True
        state.delete_cookie = True
        setattr(request.ctx, self.session_name, self._new_anonymous())

    async def _read_session(self, sid: str) -> tuple[SessionData, bytes] | None:
        """Read and decode one Redis value, deleting invalid data fail-closed."""
        connection = await self._get_redis()
        key = self._get_session_key(sid)
        payload = await connection.get(key)
        if payload is None:
            return None
        try:
            data = self._decode_snapshot(payload)
            # A canonical baseline avoids rewriting untouched sessions merely
            # because a model gained a field with a default value.
            return data, data.to_msgpack()
        except (msgspec.DecodeError, TypeError, ValueError) as exc:
            # Corrupt session data is invalidated instead of recovered. A user
            # whose value raced with this deletion can authenticate again.
            await connection.delete(key)
            logger.warning("Rejected invalid Redis session payload (%s)", type(exc).__name__)
            return None

    async def _save_authenticated(self, sid: str, user_id: int, payload: bytes, expiry: int) -> bool:
        """Update a still-indexed authenticated SID without resurrecting stale requests."""
        result = await self._execute_script(
            _SAVE_AUTHENTICATED_LUA,
            keys=[self._get_user_key(user_id), self._get_session_key(sid)],
            args=[payload, sid, expiry],
        )
        return bool(result)

    async def _logout_known_session(self, session_id: str, user_id: int | None) -> None:
        """Delete a request-owned SID using its already validated identity."""
        if user_id is None:
            connection = await self._get_redis()
            await connection.delete(self._get_session_key(session_id))
            return
        await self._execute_script(
            _LOGOUT_LUA,
            keys=[self._get_session_key(session_id), self._get_user_key(user_id)],
            args=[session_id],
        )

    async def _get_redis(self) -> Any:
        """Return the registry-owned binary connection for the configured alias."""
        return await redis_client.using(self.redis_alias).async_get_bin_conn()

    async def _execute_script(
        self,
        source: str,
        *,
        keys: list[str],
        args: list[object],
    ) -> object:
        """Bind one Lua source to the current registry connection and execute it."""
        connection = await self._get_redis()
        script = connection.register_script(source)
        return await script(keys=keys, args=args)

    def _decode_snapshot(self, payload: bytes) -> SessionData:
        """Decode and semantically validate one concrete application model."""
        data = self._data_decoder.decode(payload)
        self._validate_session_data(data)
        self._session_user_id(data)
        self._resolve_expiry(data.expiry)
        return data

    def _validate_and_encode(self, data: SessionData) -> tuple[SessionData, bytes]:
        """Encode a caller model and validate its runtime field values before I/O."""
        self._validate_session_data(data)
        snapshot = data.to_msgpack()
        return self._decode_snapshot(snapshot), snapshot

    def _new_anonymous(self) -> SessionData:
        """Construct and validate the configured model's anonymous defaults."""
        data = self.session_model()
        self._validate_session_data(data)
        return data

    def _prepare_login(self, data: SessionData) -> tuple[int, int, bytes]:
        """Validate and encode one complete authenticated model before Redis I/O."""
        validated, snapshot = self._validate_and_encode(data)
        user_id = self._session_user_id(validated)
        if user_id is None:
            raise ValueError("login session data requires user_id and is_active=True")
        return user_id, self._resolve_expiry(validated.expiry), snapshot

    def _validate_session_data(self, data: object) -> None:
        """Require the exact configured model so persisted fields cannot be discarded."""
        if type(data) is not self.session_model:
            raise TypeError(f"Session data must be exactly {self.session_model.__qualname__}")

    @staticmethod
    def _session_user_id(data: SessionData) -> int | None:
        """Validate common identity claims and return the authenticated user ID."""
        if type(data.username) is not str:
            raise TypeError("Session username must be a string")
        if type(data.is_active) is not bool:
            raise TypeError("Session is_active must be a boolean")
        if type(data.is_staff) is not bool:
            raise TypeError("Session is_staff must be a boolean")
        if type(data.is_superuser) is not bool:
            raise TypeError("Session is_superuser must be a boolean")
        if data.user_id is not None and type(data.user_id) is not int:
            raise TypeError("Session user_id must be an int or None")
        if data.is_active:
            if data.user_id is None:
                raise ValueError("An active session requires a user_id")
            return data.user_id
        if data.user_id is not None:
            raise ValueError("An anonymous session cannot contain a user_id")
        # Callers may check role flags directly, so anonymous models must never
        # carry authorization claims even when their user_id is absent.
        if data.is_staff or data.is_superuser:
            raise ValueError("An anonymous session cannot contain privileges")
        return None

    def _request_data(self, request: Request) -> SessionData:
        """Return the request model and reject replacement with a different type."""
        data = getattr(request.ctx, self.session_name, None)
        self._validate_session_data(data)
        return cast(SessionData, data)

    def _request_state(self, request: Request, *, required: bool) -> _RequestSessionState | None:
        """Return private transport state stored beside the public request model."""
        state = getattr(request.ctx, self._state_name, None)
        if state is None and required:
            raise RuntimeError("Session middleware has not initialized this request")
        if state is not None and not isinstance(state, _RequestSessionState):
            raise TypeError("Invalid private request session state")
        return state

    @property
    def _state_name(self) -> str:
        """Return the private request-context attribute for this session name."""
        return f"{self._state_prefix}{self.session_name}"

    def _set_cookie(self, response: BaseHTTPResponse, sid: str, expiry: int) -> None:
        """Refresh one persisted SID without replacing a cookie set by the handler."""
        if response.cookies.has_cookie(self.cookie_name, domain=self.domain):
            return
        self._write_cookie(response, sid, expiry)

    def _write_cookie(self, response: BaseHTTPResponse, sid: str, expiry: int) -> None:
        """Write one validated SID and duration using the configured policy."""
        response.add_cookie(
            self.cookie_name,
            sid,
            httponly=self.httponly,
            expires=self._calculate_expires(expiry),
            max_age=expiry,
            domain=self.domain,
            samesite=self.samesite,
            secure=self.secure,
        )

    def _delete_cookie(self, response: BaseHTTPResponse) -> None:
        """Delete the browser cookie using the same domain as writes."""
        response.delete_cookie(self.cookie_name, domain=self.domain)

    def _get_user_key(self, user_id: int) -> str:
        """Build the Redis key for a user's active-session index."""
        return self.user_prefix + str(self._require_user_id(user_id))

    @staticmethod
    def _require_user_id(user_id: object) -> int:
        """Reject non-integer identities before crossing the Redis boundary."""
        if type(user_id) is not int:
            raise TypeError("user_id must be an int")
        return cast(int, user_id)

    def _get_session_key(self, session_id: str) -> str:
        """Build the Redis key for one persisted session value."""
        return self.prefix + session_id

    def _resolve_expiry(self, expiry: int | None) -> int:
        """Resolve the interface default and reject invalid custom durations."""
        if expiry is None:
            return self.expiry
        if type(expiry) is not int:
            raise TypeError("Session expiry must be an integer or None")
        if expiry <= 0:
            raise ValueError("Session expiry must be greater than zero")
        return expiry

    @staticmethod
    def _decode_session_ids(result: object) -> tuple[str, ...]:
        """Decode binary Redis script results into the public string SID type."""
        if not isinstance(result, (list, tuple)):
            raise TypeError("Redis session index returned an invalid result")
        decoded: list[str] = []
        for value in result:
            if isinstance(value, bytes):
                decoded.append(value.decode("utf-8"))
            elif isinstance(value, str):
                decoded.append(value)
            else:
                raise TypeError("Redis session index returned a non-string SID")
        return tuple(decoded)

    @staticmethod
    def _calculate_expires(expiry: int) -> datetime.datetime:
        """Convert a relative expiry duration to Sanic's cookie datetime."""
        return datetime.datetime.fromtimestamp(time.time() + expiry)
