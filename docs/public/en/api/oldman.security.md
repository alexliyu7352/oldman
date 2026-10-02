# `oldman.security`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Framework-independent security primitives.

Import with `from oldman.security import <name>`.

## `ExpiredTokenError`

class · defined in `oldman.security.jwt`

```python
class ExpiredTokenError(InvalidTokenError)
```

Raised when a token has expired.

## `InvalidTokenError`

class · defined in `oldman.security.jwt`

```python
class InvalidTokenError(JWTError)
```

Raised when a token is malformed or its signature is invalid.

## `jwt_decode`

function · defined in `oldman.security.jwt`

```python
def jwt_decode(token: str, secret_key: str | bytes, *, algorithms: Sequence[str] | None=None, verify_exp: bool=True, leeway: int | float | timedelta=0, audience: str | None=None, issuer: str | None=None) -> dict[str, Any]
```

Decode and verify a JSON Web Token signed by :func:`jwt_encode`.

## `jwt_encode`

function · defined in `oldman.security.jwt`

```python
def jwt_encode(payload: Mapping[str, Any], secret_key: str | bytes, *, algorithm: str='HS256', headers: Mapping[str, Any] | None=None, expires_delta: timedelta | None=None) -> str
```

Encode a JSON Web Token signed with an HMAC SHA algorithm.

## `JWTError`

class · defined in `oldman.security.jwt`

```python
class JWTError(ValueError)
```

Base error for JWT encode/decode failures.

## `require_user_id`

function · defined in `oldman.security.identity`

```python
def require_user_id(user_id: object) -> int
```

Return ``user_id`` when it is exactly an ``int``; raise TypeError otherwise.
