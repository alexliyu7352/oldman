"""Oldman request aliases and helpers."""

from __future__ import annotations

from typing import Any

from sanic import Request

get_current_request = Request.get_current


def first_arg_value(value: object, default: object = None) -> object:
    """Reduce a Sanic multi-value parameter to its first value.

    An empty sequence means the parameter was not supplied, so it yields the default
    rather than None - the two spellings of this helper used to disagree on that.
    """
    if isinstance(value, (list, tuple)):
        return value[0] if value else default
    return value


def get_arg(args: object, key: str, default: object = None) -> object:
    """Read a single value from request args or a plain mapping."""
    getter = getattr(args, "get", None)
    if getter is None:
        return default
    return first_arg_value(getter(key, default), default)


def iter_args(args: object) -> list[tuple[str, object]]:
    """Walk request args as single-valued pairs."""
    items = getattr(args, "items", None)
    if items is None:
        return []
    return [(key, first_arg_value(value)) for key, value in items()]


def client_ip(request: Any) -> str:
    """The address a request came from: Sanic's `client_ip` honours the configured proxy headers, `ip` is the socket peer."""
    return str(getattr(request, "client_ip", None) or getattr(request, "ip", None) or "")


def request_accepts_json(request: Request) -> bool:
    """Return whether the request Accept header includes JSON."""
    accept = str((getattr(request, "headers", {}) or {}).get("accept", "")).lower()
    return "application/json" in accept


__all__ = [
    "Request",
    "client_ip",
    "first_arg_value",
    "get_arg",
    "get_current_request",
    "iter_args",
    "request_accepts_json",
]
