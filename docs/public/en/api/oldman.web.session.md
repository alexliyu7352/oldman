# `oldman.web.session`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Public Web session extension and typed request accessor.

Import with `from oldman.web.session import <name>`.

## `DefaultSessionInterface`

class · defined in `oldman.web.session.base`

```python
class DefaultSessionInterface
```

Store one strongly typed session model in a named Redis connection.

Constructor:

```python
DefaultSessionInterface(expiry: int=2592000, prefix: str | None=None, user_prefix: str | None=None, cookie_name: str='session_id', domain: str | None=None, httponly: bool=True, secure: bool=False, samesite: SameSite | None='Lax', session_name: str='session', redis_alias: str='SESSION', session_model: type[SessionData]=SessionData) -> None
```

Members:

- `async def open(request: Request) -> SessionData` — Load a typed session and attach it to the current request context.
- `async def save(request: Request, response: BaseHTTPResponse) -> None` — Persist a changed request model and update its browser cookie.
- `async def login(session_data: SessionData) -> str` — Create an ordinary login without revoking the user's other sessions.
- `async def exclusive_login(session_data: SessionData) -> str` — Create a login while atomically revoking all other user sessions.
- `async def validate_exclusive_session(session_id: str, user_id: int) -> bool` — Return whether the SID is the user's only active indexed session.
- `async def validate_session(session_id: str, user_id: int) -> bool` — Return whether an ordinary SID is still active for the supplied user.
- `async def logout(session_id: str | None) -> None` — Resolve one SID's stored identity and delete it idempotently.
- `async def force_logout_user(user_id: int) -> tuple[str, ...]` — Delete all active sessions for one user and return their SIDs.
- `async def get_active_session_ids(user_id: int) -> tuple[str, ...]` — Return every non-expired SID whose Redis session value still exists.
- `async def is_user_online(user_id: int) -> bool` — Return whether the user has at least one active Redis session.
- `def update_session_id_to_cookie(response: BaseHTTPResponse, new_sid: str, session_data: SessionData) -> None` — Write a login SID to the response using the configured cookie policy.
- `def get_session_id(request: Request) -> str` — Return the SID captured by middleware instead of rereading the cookie.
- `def opened_session_id(request: Request) -> str | None` — The SID the middleware captured, or None when it did not open this request's session.
- `def write_policy_cookie(response: BaseHTTPResponse, name: str, value: str, *, max_age: int) -> None` — Write another cookie the way the session cookie travels: its Domain, Secure and SameSite, HttpOnly.
- `property prefix: str` — The session key prefix: the one given, or ``<namespace>:session:``.
- `property user_prefix: str` — The user-to-sessions index prefix: the one given, or ``<namespace>:user_session:``.

## `get_session_data`

function · defined in `oldman.web.session`

```python
def get_session_data(request: Request, model: type[TSessionData]) -> TSessionData
```

Return the request session with a statically precise application type.

## `Session`

class · defined in `oldman.web.session`

```python
class Session
```

Install typed Redis sessions and expose session-management operations.

Constructor:

```python
Session(app: Sanic | None=None, interface: DefaultSessionInterface | type[DefaultSessionInterface] | None=None) -> None
```

Members:

- `def init_app(app: Sanic, interface: DefaultSessionInterface | type[DefaultSessionInterface] | None=None, *, session_model: type[SessionData]=SessionData) -> None` — Install middleware and build the default interface from process settings.
- `async def login(session_data: SessionData) -> str` — Create an ordinary login that may coexist with other user sessions.
- `async def exclusive_login(session_data: SessionData) -> str` — Create an exclusive login and revoke the user's other sessions.
- `async def validate_exclusive_session(session_id: str, user_id: int) -> bool` — Return whether the SID is the user's only active session.
- `async def validate_session(session_id: str, user_id: int) -> bool` — Return whether an ordinary SID is still active for one user.
- `async def logout(session_id: str | None) -> None` — Resolve and idempotently delete one stored session.
- `async def force_logout_user(user_id: int) -> tuple[str, ...]` — Delete and return all active session IDs for one user.
- `async def get_active_session_ids(user_id: int) -> tuple[str, ...]` — Return all active session IDs for one user.
- `async def is_user_online(user_id: int) -> bool` — Return whether one user has any active sessions.
- `def update_session_id_to_cookie(response: BaseHTTPResponse, new_sid: str, session_data: SessionData) -> None` — Write a newly created login SID to a response cookie.
- `def get_session_id(request: Request) -> str` — Return the request SID captured by Session middleware.
- `def opened_session_id(request: Request) -> str | None` — The request SID, or None when this middleware did not open the request's session (a hand-built request).
- `def send_cookie(request: Request, name: str, value: str, *, max_age: int) -> None` — Have the response carry this cookie, written the way the session cookie is, once the session is saved.
- `staticmethod def get_session_manager(request: Request) -> Session` — Return the Session extension installed on the request application.
- `staticmethod async def logout_session(request: Request) -> None` — Log out the current request and schedule its cookie for deletion.

## `session`

value · defined in `oldman.web.session`

```python
session = Session()
```

## `SessionData`

class · defined in `oldman.web.session.base`

```python
class SessionData(MsgspecModel, kw_only=True)
```

Base identity and authorization snapshot for application sessions.

Members:

- `expiry: int | None = None`
- `user_id: int | None = None`
- `username: str = ''`
- `display_name: str = ''`
- `login_ip: str = ''`
- `login_time: int = 0`
- `is_active: bool = False`
- `is_staff: bool = False`
- `is_superuser: bool = False`
- `role_ids: tuple[int, ...] = ()`
- `def is_authenticated() -> bool` — Return whether this model represents an authenticated user.
- `property is_anonymous: bool` — Return whether this model has no authenticated identity.
