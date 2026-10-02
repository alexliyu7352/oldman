# `oldman.security.rate_limiter`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Framework-independent rate-limiting policies.

Import with `from oldman.security.rate_limiter import <name>`.

## `TokenBucketRateLimiter`

class · defined in `oldman.security.rate_limiter.token_bucket`

```python
class TokenBucketRateLimiter
```

Throttle local async work with a monotonic token bucket.

Constructor:

```python
TokenBucketRateLimiter(rate_limit: int, time_unit: float=60) -> None
```

Members:

- `async def acquire() -> None` — Wait until and then consume one token.

## `TokenBucketRateLimiterRegistry`

class · defined in `oldman.security.rate_limiter.token_bucket`

```python
class TokenBucketRateLimiterRegistry
```

Store named in-process token-bucket limiters.

Constructor:

```python
TokenBucketRateLimiterRegistry() -> None
```

Members:

- `def register(name: str, limiter: TokenBucketRateLimiter) -> None` — Register or replace one named limiter.
- `def register_rate(name: str, rate_limit: int, time_unit: float=60) -> None` — Construct and register one limiter from its numerical rate.
- `def get(name: str) -> TokenBucketRateLimiter` — Return a named limiter or raise when it is absent.
- `def remove(name: str) -> None` — Remove a named limiter when present.
- `def clear() -> None` — Remove every named limiter from this registry.
