"""Oldman request aliases and helpers."""

from __future__ import annotations

from sanic import Request

get_current_request = Request.get_current


def get_arg(args: object, key: str, default: object = None) -> object:
    """Read a single value from request args or a plain mapping."""
    getter = getattr(args, "get", None)
    if getter is None:
        return default
    value = getter(key, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value


def request_accepts_json(request: Request) -> bool:
    """Return whether the request Accept header includes JSON."""
    accept = str((getattr(request, "headers", {}) or {}).get("accept", "")).lower()
    return "application/json" in accept


__all__ = ["Request", "get_arg", "get_current_request", "request_accepts_json"]
