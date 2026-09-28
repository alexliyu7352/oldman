"""The one place Redis key names get their namespace.

Every key and channel the framework uses starts with ``core.namespace`` (``core.app_name``
when unset). Services that share sessions, tokens or cache set the same namespace; a service
that must stay apart sets its own, so nothing it writes can collide with anyone else's.
"""

from __future__ import annotations


def redis_namespace() -> str:
    """The namespace this service's Redis keys live under, read from the settings on each call."""
    import oldman.conf as conf

    core = conf.settings.core
    return core.namespace or core.app_name


def redis_key(*parts: object) -> str:
    """A key under this service's namespace: ``redis_key("session", sid)`` is ``<namespace>:session:<sid>``."""
    if not parts:
        raise ValueError("a Redis key needs at least one part below the namespace")
    return ":".join((redis_namespace(), *(str(part) for part in parts)))


__all__ = ["redis_key", "redis_namespace"]
