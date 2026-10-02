# `oldman.web.authentication`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Request authentication: who is calling, and how they proved it.

Import with `from oldman.web.authentication import <name>`.

## `access_token_revoked`

function · defined in `oldman.web.authentication.jwt`

```python
async def access_token_revoked(claims: Mapping[str, Any]) -> bool
```

Whether this token was revoked, or the user's tokens were cut off at or after it was issued.

## `AccessToken`

class · defined in `oldman.web.authentication.jwt`

```python
class AccessToken
```

A signed access token and what a client needs to know about it.

Members:

- `token: str`
- `expires_in: int`
- `claims: Mapping[str, Any]`

## `ANONYMOUS_USER`

value · defined in `oldman.web.authentication.base`

```python
ANONYMOUS_USER = AnonymousUser()
```

The one anonymous user; compare with ``is`` or read ``is_authenticated``.

## `AnonymousUser`

class · defined in `oldman.web.authentication.base`

```python
class AnonymousUser
```

No one. Every permission answers no, whatever else the request carries.

Members:

- `id: None = None`
- `role_ids: tuple[int, ...] = ()`

## `API_KEY_HEADER`

value · defined in `oldman.web.authentication.api_key`

```python
API_KEY_HEADER = 'X-API-Key'
```

## `API_KEY_METHOD`

value · defined in `oldman.web.authentication.api_key`

```python
API_KEY_METHOD = 'api_key'
```

## `APIKeyAuthentication`

class · defined in `oldman.web.authentication.api_key`

```python
class APIKeyAuthentication
```

A key from ``web.auth.api_keys`` in the ``X-API-Key`` header.

Constructor:

```python
APIKeyAuthentication() -> None
```

Members:

- `async def authenticate(request: Any) -> Authentication | None`

## `Authentication`

class · defined in `oldman.web.authentication.base`

```python
class Authentication
```

How the request proved who, or what, it is.

Members:

- `method: str`
- `user: RequestUser | AnonymousUser = ANONYMOUS_USER`
- `caller: str | None = None`
- `ambient: bool = True`
- `claims: Mapping[str, Any] | None = None`

## `Authenticator`

class · defined in `oldman.web.authentication.base`

```python
class Authenticator(Protocol)
```

One way of recognizing a request's credential.

Members:

- `name: str`
- `async def authenticate(request: Any) -> Authentication | None`

## `BUILTIN_AUTHENTICATORS`

value · defined in `oldman.web.authentication.pipeline`

```python
BUILTIN_AUTHENTICATORS: dict[str, Callable[[], Authenticator]] = {'session': SessionAuthentication, 'jwt': JWTAuthentication, 'api_key': APIKeyAuthentication, 'http…
```

Methods a service names by a bare word in ``web.auth.authenticators``; anything else there is an import path to a project's own class.

## `exempt_from_csrf`

function · defined in `oldman.web.authentication.base`

```python
def exempt_from_csrf(request: Any) -> bool
```

Whether this request authenticated with a credential a forged request cannot carry.

## `forget_session_authentication`

function · defined in `oldman.web.authentication.session`

```python
def forget_session_authentication(request: Any) -> None
```

After this request's own session ended, it no longer authenticates by it.

## `http_basic_challenge`

function · defined in `oldman.web.authentication.http_basic`

```python
def http_basic_challenge() -> str
```

The ``WWW-Authenticate`` value that asks a client for Basic credentials of the configured realm.

## `HTTP_BASIC_METHOD`

value · defined in `oldman.web.authentication.http_basic`

```python
HTTP_BASIC_METHOD = 'http_basic'
```

## `HTTPBasicAuthentication`

class · defined in `oldman.web.authentication.http_basic`

```python
class HTTPBasicAuthentication
```

A username and password from ``web.auth.http_basic.accounts`` in ``Authorization: Basic``.

Constructor:

```python
HTTPBasicAuthentication() -> None
```

Members:

- `async def authenticate(request: Any) -> Authentication | None`

## `install_authentication`

function · defined in `oldman.web.authentication.pipeline`

```python
def install_authentication(app: Any, authenticators: Sequence[Authenticator]) -> None
```

Record ``request.ctx.user`` and ``request.ctx.auth`` before any handler runs.

## `IP_ALLOWLIST_METHOD`

value · defined in `oldman.web.authentication.ip_allowlist`

```python
IP_ALLOWLIST_METHOD = 'ip_allowlist'
```

## `IPAllowlistAuthentication`

class · defined in `oldman.web.authentication.ip_allowlist`

```python
class IPAllowlistAuthentication
```

A request whose addresses fall in one entry of ``web.auth.ip_allowlist``.

Constructor:

```python
IPAllowlistAuthentication() -> None
```

Members:

- `async def authenticate(request: Any) -> Authentication | None`

## `issue_access_token`

function · defined in `oldman.web.authentication.jwt`

```python
def issue_access_token(user: Any, *, role_ids: Iterable[int]=()) -> AccessToken
```

Sign an access token for a user who has just proved who they are.

## `issue_refresh_token`

function · defined in `oldman.web.authentication.refresh`

```python
async def issue_refresh_token(user_id: int) -> RefreshToken
```

Start a new family for a user who has just signed in, and return its first token.

## `JWT_METHOD`

value · defined in `oldman.web.authentication.jwt`

```python
JWT_METHOD = 'jwt'
```

## `JWTAuthentication`

class · defined in `oldman.web.authentication.jwt`

```python
class JWTAuthentication
```

A bearer access token in the ``Authorization`` header.

Constructor:

```python
JWTAuthentication() -> None
```

Members:

- `async def authenticate(request: Any) -> Authentication | None`

## `read_access_token`

function · defined in `oldman.web.authentication.jwt`

```python
def read_access_token(token: str) -> Mapping[str, Any] | None
```

The claims of a valid access token, or None for anything else.

## `record_authentication`

function · defined in `oldman.web.authentication.base`

```python
def record_authentication(request: Any, authentication: Authentication | None) -> None
```

Set ``request.ctx.user`` and ``request.ctx.auth`` from one authentication, or anonymous.

## `refresh_token_user`

function · defined in `oldman.web.authentication.refresh`

```python
async def refresh_token_user(token: object) -> int | None
```

The user a refresh token was issued to, or None when it is unknown; the token stays unused.

## `RefreshToken`

class · defined in `oldman.web.authentication.refresh`

```python
class RefreshToken
```

A refresh token and how long it may be used.

Members:

- `token: str`
- `expires_in: int`

## `request_user`

function · defined in `oldman.web.authentication.base`

```python
def request_user(request: Any) -> RequestUser | AnonymousUser
```

The user the authentication pipeline recorded for this request.

## `RequestUser`

class · defined in `oldman.web.authentication.base`

```python
class RequestUser
```

A signed-in user as the request knows them: a snapshot, not a database row.

Members:

- `id: int`
- `username: str`
- `display_name: str = ''`
- `is_staff: bool = False`
- `is_superuser: bool = False`
- `role_ids: tuple[int, ...] = ()`
- `property is_authenticated: bool`
- `property is_anonymous: bool`
- `property is_active: bool`

## `resolve_authenticators`

function · defined in `oldman.web.authentication.pipeline`

```python
def resolve_authenticators(names: Sequence[str] | None, *, session_enabled: bool) -> tuple[Authenticator, ...]
```

Build the methods a service tries, in the order they are listed.

## `revoke_access_token`

function · defined in `oldman.web.authentication.jwt`

```python
async def revoke_access_token(claims: Mapping[str, Any]) -> None
```

Refuse this one access token from now on, as signing out of one client does.

## `revoke_refresh_token`

function · defined in `oldman.web.authentication.refresh`

```python
async def revoke_refresh_token(token: object) -> None
```

End the family a refresh token belongs to, as signing out of one client does.

## `revoke_user_tokens`

function · defined in `oldman.web.authentication.jwt`

```python
async def revoke_user_tokens(user_id: int) -> None
```

Refuse every access token and refresh token this user was issued up to now.

## `rotate_refresh_token`

function · defined in `oldman.web.authentication.refresh`

```python
async def rotate_refresh_token(token: object) -> RotatedRefreshToken | None
```

Replace a refresh token with the next one of its family, or None when it is not valid.

## `RotatedRefreshToken`

class · defined in `oldman.web.authentication.refresh`

```python
class RotatedRefreshToken
```

The user a refresh token was issued to, and the token that replaces it.

Members:

- `user_id: int`
- `refresh_token: RefreshToken`

## `session_authentication`

function · defined in `oldman.web.authentication.session`

```python
def session_authentication(session: Any) -> Authentication | None
```

What a signed-in browser session proves, or None when it signs no one in.

## `SESSION_METHOD`

value · defined in `oldman.web.authentication.session`

```python
SESSION_METHOD = 'session'
```

## `SessionAuthentication`

class · defined in `oldman.web.authentication.session`

```python
class SessionAuthentication
```

The signed-in browser session, if the request has one.

Members:

- `async def authenticate(request: Any) -> Authentication | None`

## `user_from_access_token`

function · defined in `oldman.web.authentication.jwt`

```python
def user_from_access_token(claims: Mapping[str, Any]) -> RequestUser
```

The user snapshot an access token carries.

## `user_from_session`

function · defined in `oldman.web.authentication.base`

```python
def user_from_session(session: Any) -> RequestUser | AnonymousUser
```

The user a browser session signs in, or anonymous.
