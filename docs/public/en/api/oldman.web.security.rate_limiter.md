# `oldman.web.security.rate_limiter`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

HTTP path and browser-fingerprint rate-limiting policies.

Import with `from oldman.web.security.rate_limiter import <name>`.

## `FingerprintIPRateLimiter`

class · defined in `oldman.web.security.rate_limiter.fingerprint`

```python
class FingerprintIPRateLimiter
```

Enforce combined fingerprint/IP limits and relationship anomalies.

Constructor:

```python
FingerprintIPRateLimiter(client: RedisConnectionClient, *, fail_open: bool=True) -> None
```

Members:

- `async def check(fingerprint: str, ip: str, endpoint: str, config: FingerprintSecurityConfig) -> FingerprintRateLimitDecision` — Evaluate one request against fingerprint and IP security limits.

## `FingerprintRateLimitDecision`

class · defined in `oldman.web.security.rate_limiter.fingerprint`

```python
class FingerprintRateLimitDecision
```

Describe the security decision returned by the Redis Lua policy.

Members:

- `allowed: bool`
- `reason: str`
- `fingerprint_count: int`
- `ip_count: int`
- `anomalies: list[str]`

## `RateLimiter`

class · defined in `oldman.web.security.rate_limiter.base`

```python
class RateLimiter(Protocol)
```

What a flow needs from a limiter; `RedisFixedWindowRateLimiter` satisfies it.

Members:

- `async def is_rate_limited(subject: int | str, path: str, limit: int, period: int) -> bool` — Count this event and return whether the subject is now over the limit.

## `redis_rate_limiter`

function · defined in `oldman.web.security.rate_limiter.fixed_window`

```python
def redis_rate_limiter(alias: str | None=None, namespace: str | None=None) -> RedisFixedWindowRateLimiter
```

The default limiter: a Redis fixed window on the session connection (the one a login site must have).

## `RedisFixedWindowRateLimiter`

class · defined in `oldman.web.security.rate_limiter.fixed_window`

```python
class RedisFixedWindowRateLimiter
```

Apply one Redis-backed fixed request window per subject and path.

Constructor:

```python
RedisFixedWindowRateLimiter(client: RedisConnectionClient, namespace: str='ratelimit') -> None
```

Members:

- `async def is_rate_limited(subject: int | str, path: str, limit: int, period: int) -> bool` — Increment the current window and return whether limit was exceeded.
- `async def count(subject: int | str, path: str, period: int) -> int` — Return what the current window already holds, without counting this read.
- `async def record(subject: int | str, path: str, period: int) -> int` — Count one event in the current window and return the window's new total.

## `window_retry_after`

function · defined in `oldman.web.security.rate_limiter.fixed_window`

```python
def window_retry_after(period: int) -> int
```

Seconds until the current fixed window rolls over and its count starts again.

## `WindowCounter`

class · defined in `oldman.web.security.rate_limiter.base`

```python
class WindowCounter(Protocol)
```

A window a caller can read before deciding whether to charge anything to it.

Members:

- `async def count(subject: int | str, path: str, period: int) -> int` — Return what the current window already holds, without counting this read.
- `async def record(subject: int | str, path: str, period: int) -> int` — Count one event in the current window and return its new total.
