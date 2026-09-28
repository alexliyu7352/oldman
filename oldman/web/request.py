"""Oldman request aliases and helpers."""

from __future__ import annotations

import base64
import binascii
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


def bearer_credential(request: Any) -> str | None:
    """The token of an ``Authorization: Bearer`` header, or None.

    The scheme is matched case-insensitively, as RFC 7235 requires. Sanic's
    ``request.token`` is not used: it also takes a ``Token`` scheme, and hands back the
    whole header when no scheme matches.
    """
    headers = getattr(request, "headers", None) or {}
    scheme, _, credential = str(headers.get("authorization") or "").strip().partition(" ")
    credential = credential.strip()
    if scheme.lower() != "bearer" or not credential:
        return None
    return credential


def basic_credentials(request: Any) -> tuple[str, str] | None:
    """The username and password of an ``Authorization: Basic`` header, or None.

    The scheme is matched case-insensitively. The value must be valid base64 of UTF-8 text
    (RFC 7617); it is split at the first colon, so a password may contain one. Anything
    malformed is None rather than an error: an unreadable credential recognizes no one.
    """
    headers = getattr(request, "headers", None) or {}
    scheme, _, encoded = str(headers.get("authorization") or "").strip().partition(" ")
    if scheme.lower() != "basic" or not encoded.strip():
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


def request_sends_json(request: Any) -> bool:
    """Whether the request body is JSON, by its Content-Type: ``application/json`` or a ``+json`` type.

    Sanic's ``request.json`` parses the body the moment it is read, so ask this first.
    """
    content_type = str((getattr(request, "headers", None) or {}).get("content-type", "")).partition(";")[0].strip().lower()
    return content_type == "application/json" or content_type.endswith("+json")


def request_accepts_json(request: Request) -> bool:
    """Return whether the request Accept header includes JSON."""
    accept = str((getattr(request, "headers", {}) or {}).get("accept", "")).lower()
    return "application/json" in accept


__all__ = [
    "Request",
    "basic_credentials",
    "bearer_credential",
    "client_ip",
    "first_arg_value",
    "get_arg",
    "get_current_request",
    "iter_args",
    "request_accepts_json",
    "request_sends_json",
]
