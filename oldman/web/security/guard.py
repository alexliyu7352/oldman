"""Require a browser fingerprint on one route.

**What this is, and what it is not.** The AES key lives in `web.security.fingerprint`
and is handed to the browser so it can encrypt its payload. Anyone who opens devtools
can read that key and sign whatever they like. So this raises the cost of scripted
abuse - a scraper now has to run the page's crypto and carry a stable visitor id
through the rate limiter - and it is **not** an authentication boundary. Never decide
who someone is with it; use the session for that.

It is opt-in twice over: `web.security.fingerprint.enabled` turns the subsystem on, and
each route asks for it by name. There is no global middleware.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

import oldman.conf as conf
from oldman.logging import logger
from oldman.utils.decorators import method_adaptor
from oldman.web.exceptions import Forbidden, TooManyRequests
from oldman.web.request import Request, client_ip
from oldman.web.security.fingerprint import get_fingerprint_from_front, log_fake_fingerprint_attempt

#: Header the browser module sends its encrypted `{vid, ts}` payload in.
FINGERPRINT_HEADER = "X-Oldman-Fingerprint"


def _rate_limiter(request: Request) -> Any:
    """Build the limiter once per app, on the session Redis a login site already has."""
    existing = getattr(request.app.ctx, "fingerprint_rate_limiter", None)
    if existing is not None:
        return existing

    from oldman.providers.redis import redis_client
    from oldman.web.security.rate_limiter.fingerprint import FingerprintIPRateLimiter
    from oldman.web.security.store import security_redis_alias

    limiter = FingerprintIPRateLimiter(redis_client.using(security_redis_alias()))
    request.app.ctx.fingerprint_rate_limiter = limiter
    return limiter


def _fingerprint_required(endpoint: str = "default", header: str = FINGERPRINT_HEADER):
    """Build the decorator; `endpoint` selects the rule in `fingerprint.rate_limits`."""

    def decorator(func):
        @wraps(func)
        async def wrapper(view, request: Request, *args: Any, **kwargs: Any):
            config = conf.settings.web.security.fingerprint
            if not config.enabled:
                # 路由要求了指纹，配置却没打开——这是配置错误，静默放行等于假装有防护。
                raise RuntimeError("@fingerprint_required needs settings.web.security.fingerprint.enabled")
            if config.aes_secret_key is None:
                raise RuntimeError("settings.web.security.fingerprint.aes_secret_key is empty; run the service settings sync command")

            address = client_ip(request)
            payload = request.headers.get(header, "")
            if not payload:
                await log_fake_fingerprint_attempt(address, "missing_header")
                raise Forbidden("Fingerprint missing")

            visitor_id, reason = get_fingerprint_from_front(
                payload,
                config.aes_secret_key,
                config.timestamp_max_diff,
            )
            if not visitor_id:
                await log_fake_fingerprint_attempt(address, reason)
                raise Forbidden(f"Fingerprint rejected: {reason}")

            decision = await _rate_limiter(request).check(visitor_id, address, endpoint, config)
            if not decision.allowed:
                logger.warning(f"指纹限流拒绝: {decision.reason}, visitor={visitor_id}, ip={address}")
                window = config.rate_limits.get(endpoint, config.rate_limits["default"]).window
                raise TooManyRequests(
                    f"Rate limited: {decision.reason}",
                    headers={"Retry-After": str(window)},
                )

            request.ctx.visitor_id = visitor_id
            request.ctx.fingerprint_decision = decision
            if view is None:
                return await func(request, *args, **kwargs)
            return await func(view, request, *args, **kwargs)

        return wrapper

    return decorator


fingerprint_required = method_adaptor(_fingerprint_required)

__all__ = ["FINGERPRINT_HEADER", "fingerprint_required"]
