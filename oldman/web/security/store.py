"""The Redis connection that holds Web security state.

Fingerprint blacklists, rate-limit windows and the sessions they protect all have to
agree on one database. Nothing enforces that by itself: each caller used to name an
alias on its own, and the fingerprint blacklist ended up writing `blacklist:ip:{ip}` on
the DEFAULT connection while the rate limiter's Lua read it on the SESSION one. On a
deployment where those aliases point at different databases — which is the shipped demo
configuration, db 3 and db 5 — the blacklist simply never took effect, and nothing
failed to say so.

So the question "which Redis holds Web security state" gets one owner here, the way
`keys.py` owns "which key does this purpose use". Callers ask; they do not decide.
"""

from __future__ import annotations

from typing import Any

import oldman.conf as conf


def security_redis_alias() -> str:
    """Name the Redis connection that every Web security subsystem must share.

    It follows the session alias because that is the connection a login site already
    configures, and because security state is only meaningful alongside the sessions it
    guards. Read at call time, never captured at import, so a settings reload is seen.
    """
    return conf.settings.web.session.redis_alias


async def security_redis_connection() -> Any:
    """Open the decoded connection holding Web security state."""
    from oldman.providers.redis import redis_client

    return await redis_client.using(security_redis_alias()).async_get_conn()


__all__ = ["security_redis_alias", "security_redis_connection"]
