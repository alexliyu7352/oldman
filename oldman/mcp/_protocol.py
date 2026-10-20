"""The MCP wire rules Oldman's server follows, separate from the HTTP server that carries them.

One endpoint serves two protocol eras (spec 2026-07-28, basic/versioning, "dual-era"):

- 2026-07-28 is stateless. Every request carries its protocol version and the client's capabilities in
  ``params._meta``, and Streamable HTTP mirrors ``method`` and the tool, prompt or resource name into
  headers the server must check against the body (basic/transports/streamable-http, "Server Validation").
- 2024-11-05 to 2025-11-25 open with an ``initialize`` handshake. Oldman keeps no session, which those
  revisions allow (2025-11-25 transports, "Session Management": a server MAY assign a session ID).

Where the spec leaves the order of the checks open, it follows SDK 2.3.0 (``mcp/shared/inbound.py``,
``mcp/server/_streamable_http_modern.py``, ``mcp/server/streamable_http.py``). Where the two differ the
spec wins: the SDK picks the era from the version header alone, the spec from the body's ``_meta``.
The HTTP checks that come before the body (Origin, method, authentication, Accept, size) belong to the
transport. Nothing here imports the ``mcp`` SDK; the wire models are ``mcp-types``.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import mcp_types as types
from mcp_types import jsonrpc
from mcp_types import methods as wire
from pydantic import ValidationError

#: The revisions this server implements: its own list, not ``mcp_types.version``'s, so that a newer
#: mcp-types which knows a later revision does not make the server claim to speak it.
HANDSHAKE_VERSIONS: tuple[str, ...] = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MODERN_VERSIONS: tuple[str, ...] = ("2026-07-28",)
LATEST_HANDSHAKE_VERSION = HANDSHAKE_VERSIONS[-1]
#: The revision of a handshake-era request without ``MCP-Protocol-Version``: clients before
#: 2025-06-18 sent none, and 2025-11-25 transports says to assume 2025-03-26.
VERSION_WITHOUT_HEADER = "2025-03-26"

PROTOCOL_VERSION_HEADER = "mcp-protocol-version"
METHOD_HEADER = "mcp-method"
NAME_HEADER = "mcp-name"
_ROUTING_HEADERS = (PROTOCOL_VERSION_HEADER, METHOD_HEADER, NAME_HEADER)
#: The methods whose name (or URI) a 2026-07-28 client mirrors into ``Mcp-Name``.
_NAME_BEARING = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}

#: 2026-07-28 answers a JSON-RPC error with an HTTP status as well: 400 for a header mismatch or an
#: unsupported version, 404 for an unknown method (streamable-http, "Protocol Version Header"). Other
#: codes are sent with 200, as the SDK does.
_MODERN_ERROR_STATUS = {
    jsonrpc.PARSE_ERROR: 400,
    jsonrpc.INVALID_REQUEST: 400,
    jsonrpc.INVALID_PARAMS: 400,
    jsonrpc.HEADER_MISMATCH: 400,
    jsonrpc.MISSING_REQUIRED_CLIENT_CAPABILITY: 400,
    jsonrpc.UNSUPPORTED_PROTOCOL_VERSION: 400,
    jsonrpc.METHOD_NOT_FOUND: 404,
}
_SENTINEL_PREFIX = "=?base64?"
_SENTINEL_SUFFIX = "?="
#: What RFC 9110 allows in a header value: visible ASCII, space and tab.
_HEADER_SAFE = frozenset(chr(code) for code in range(0x20, 0x7F)) | {"\t"}
_INVALID_HEADER = object()


class Era(StrEnum):
    """Which family of revisions a request belongs to."""

    MODERN = "modern"
    HANDSHAKE = "handshake"


@dataclass(frozen=True, slots=True)
class Reply:
    """What the transport sends back: an HTTP status and a JSON body, or no body at all."""

    status: int
    body: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Inbound:
    """A request that passed the wire checks, parsed for the revision it is in."""

    era: Era
    version: str
    id: str | int
    method: str
    request: types.Request[Any, Any]


class _Headers:
    """Request headers by lowercase name, keeping every value so that a repeated header shows."""

    __slots__ = ("_values",)

    def __init__(self, pairs: Iterable[tuple[str, str]]) -> None:
        values: dict[str, list[str]] = {}
        for name, value in pairs:
            values.setdefault(name.lower(), []).append(value)
        self._values = values

    def get(self, name: str) -> str | None:
        found = self._values.get(name)
        return found[0] if found else None

    def repeated(self, name: str) -> bool:
        return len(self._values.get(name, ())) > 1


def error_reply(
    era: Era,
    message_id: str | int | None,
    code: int,
    message: str,
    *,
    data: Any = None,
    status: int | None = None,
) -> Reply:
    """A JSON-RPC error; its HTTP status follows the era unless the caller names one."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    if status is None:
        status = _MODERN_ERROR_STATUS.get(code, 200) if era is Era.MODERN else 200
    return Reply(status, {"jsonrpc": jsonrpc.JSONRPC_VERSION, "id": message_id, "error": error})


def result_reply(inbound: Inbound, result: types.Result) -> Reply:
    """A JSON-RPC result, serialized for the request's revision.

    The version-free ``mcp_types`` model carries the 2026-07-28 fields (``resultType``, ``ttlMs``,
    ``cacheScope``) with their defaults; ``serialize_server_result`` keeps them for 2026-07-28 and drops
    them for the handshake revisions.
    """
    return Reply(200, {"jsonrpc": jsonrpc.JSONRPC_VERSION, "id": inbound.id, "result": serialize_result(inbound.method, inbound.version, result)})


def serialize_result(method: str, version: str, result: types.Result) -> dict[str, Any]:
    """One result as ``version`` sends it; raises ValidationError when that revision cannot carry it."""
    return wire.serialize_server_result(method, version, result.model_dump(by_alias=True, mode="json", exclude_none=True))


def read_message(header_pairs: Iterable[tuple[str, str]], body: bytes, content_type: str | None) -> Inbound | Reply:
    """Check one POSTed message and parse it, or say how to answer it without dispatching."""
    headers = _Headers(header_pairs)
    try:
        message = json.loads(body)
    except (ValueError, RecursionError):
        # Not only malformed JSON: an oversized integer literal raises a bare ValueError and deep
        # nesting a RecursionError, as the SDK notes.
        return error_reply(Era.MODERN, None, jsonrpc.PARSE_ERROR, "Parse error", status=400)
    if _era(headers, message) is Era.MODERN:
        return _read_modern(headers, message)
    return _read_handshake(headers, message, content_type)


def _era(headers: _Headers, message: Any) -> Era:
    """A version header that is not a handshake revision, or a body with modern ``_meta``, is 2026-07-28.

    versioning: "A request carrying modern per-request `_meta` is served statelessly according to this
    revision. An `initialize` request selects legacy semantics." An unknown header value goes to the
    modern checks too, which answer it with a structured rejection (the SDK routes it the same way).
    """
    version = headers.get(PROTOCOL_VERSION_HEADER)
    if version is not None and version not in HANDSHAKE_VERSIONS:
        return Era.MODERN
    meta = _meta(message)
    if isinstance(meta, dict) and types.PROTOCOL_VERSION_META_KEY in meta:
        return Era.MODERN
    return Era.HANDSHAKE


def _read_modern(headers: _Headers, message: Any) -> Inbound | Reply:
    if _is_notification(message):
        # 2026-07-28 defines no client notifications over HTTP (a client cancels by closing the response
        # stream), but clients in the field still post them; they are accepted and dropped, as the SDK
        # does. A version this server does not serve is told so, as a request is.
        version = headers.get(PROTOCOL_VERSION_HEADER)
        if version is not None and version not in MODERN_VERSIONS:
            return _unsupported(None, version)
        return Reply(202)
    if not _is_request(message):
        # A batch, a posted response (streamable-http: "The client MUST NOT send JSON-RPC responses"),
        # or a malformed envelope.
        return error_reply(Era.MODERN, None, jsonrpc.INVALID_REQUEST, "Invalid request: the body must be one JSON-RPC request or notification")
    message_id, method = message["id"], message["method"]
    for name in _ROUTING_HEADERS:
        if headers.repeated(name):
            return error_reply(Era.MODERN, message_id, jsonrpc.HEADER_MISMATCH, f"The {name} header appears more than once")
    meta = _meta(message)
    if not isinstance(meta, dict):
        return error_reply(
            Era.MODERN,
            message_id,
            jsonrpc.INVALID_PARAMS,
            f"params._meta must be an object carrying {types.PROTOCOL_VERSION_META_KEY!r} and {types.CLIENT_CAPABILITIES_META_KEY!r}",
        )
    missing = [key for key in (types.PROTOCOL_VERSION_META_KEY, types.CLIENT_CAPABILITIES_META_KEY) if key not in meta]
    if missing:
        return error_reply(Era.MODERN, message_id, jsonrpc.INVALID_PARAMS, f"params._meta is missing {', '.join(map(repr, missing))}")
    version = meta[types.PROTOCOL_VERSION_META_KEY]
    # Before the version check, so that a client which disagrees with itself is told that, rather than
    # that the version in its body is unsupported (the SDK's order).
    mismatch = _header_mismatch(headers, method, message["params"], version)
    if mismatch is not None:
        return error_reply(Era.MODERN, message_id, jsonrpc.HEADER_MISMATCH, mismatch)
    if not isinstance(version, str):
        return error_reply(Era.MODERN, message_id, jsonrpc.INVALID_PARAMS, "The protocol version in params._meta must be a string")
    if version not in MODERN_VERSIONS:
        return _unsupported(message_id, version)
    return _parse(Era.MODERN, version, message_id, method, message["params"])


def _read_handshake(headers: _Headers, message: Any, content_type: str | None) -> Inbound | Reply:
    if not _is_json(content_type):
        return error_reply(Era.HANDSHAKE, None, jsonrpc.INVALID_REQUEST, "Unsupported Media Type: Content-Type must be application/json", status=415)
    if _is_notification(message) or _is_response(message):
        # 2025-11-25 transports: "If the input is a JSON-RPC response or notification … the server MUST
        # return HTTP status code 202 Accepted". Without a session there is nothing to apply them to.
        return Reply(202)
    if not _is_request(message):
        return error_reply(Era.HANDSHAKE, None, jsonrpc.INVALID_REQUEST, "Invalid request: the body must be one JSON-RPC message", status=400)
    message_id, method = message["id"], message["method"]
    if method == "initialize":
        # Every handshake revision validates against one schema (2025-11-25's); the version the
        # client asks for is negotiated from the request itself.
        version = LATEST_HANDSHAKE_VERSION
    else:
        version = headers.get(PROTOCOL_VERSION_HEADER) or VERSION_WITHOUT_HEADER
    return _parse(Era.HANDSHAKE, version, message_id, method, message.get("params"))


def _parse(era: Era, version: str, message_id: str | int, method: str, params: Any) -> Inbound | Reply:
    if (method, version) not in wire.CLIENT_REQUESTS:
        return error_reply(era, message_id, jsonrpc.METHOD_NOT_FOUND, f"Method not found: {method}")
    try:
        request = wire.parse_client_request(method, version, params)
    except ValidationError as exc:
        return error_reply(era, message_id, jsonrpc.INVALID_PARAMS, f"Invalid params: {validation_summary(exc)}")
    return Inbound(era, version, message_id, method, request)


def _header_mismatch(headers: _Headers, method: str, params: dict[str, Any], version: Any) -> str | None:
    """Why the mirrored headers disagree with the body, or None. A missing header is a mismatch too."""
    header_version = headers.get(PROTOCOL_VERSION_HEADER)
    if header_version != version:
        return "The MCP-Protocol-Version header does not match the protocol version in params._meta"
    header_method = headers.get(METHOD_HEADER)
    if header_method is None:
        return "The Mcp-Method header is missing"
    if header_method != method:
        return "The Mcp-Method header does not match the request's method"
    key = _NAME_BEARING.get(method)
    if key is not None:
        body_value = params.get(key)
        header_name = headers.get(NAME_HEADER)
        if body_value is not None and header_name is None:
            return "The Mcp-Name header is missing"
        if body_value is not None and _decode_header_value(header_name) != body_value:
            return f"The Mcp-Name header does not match the request's {key!r}"
    return None


def _decode_header_value(value: str | None) -> object:
    """A header value as the client meant it: Base64 sentinels decoded; an unsafe value never matches."""
    if value is None:
        return None
    if value.startswith(_SENTINEL_PREFIX) and value.endswith(_SENTINEL_SUFFIX) and len(value) >= len(_SENTINEL_PREFIX) + len(_SENTINEL_SUFFIX):
        payload = value[len(_SENTINEL_PREFIX) : len(value) - len(_SENTINEL_SUFFIX)]
        try:
            return base64.b64decode(payload, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return _INVALID_HEADER
    if not set(value) <= _HEADER_SAFE:
        return _INVALID_HEADER
    return value


def _unsupported(message_id: str | int | None, requested: str) -> Reply:
    return error_reply(
        Era.MODERN,
        message_id,
        jsonrpc.UNSUPPORTED_PROTOCOL_VERSION,
        "Unsupported protocol version",
        data={"supported": list(MODERN_VERSIONS), "requested": requested},
    )


def validation_summary(exc: ValidationError) -> str:
    """One line naming each invalid field, short enough for a model to act on."""
    return "; ".join(f"{'.'.join(str(part) for part in error['loc']) or 'value'}: {error['msg']}" for error in exc.errors())


def _meta(message: Any) -> Any:
    params = message.get("params") if isinstance(message, dict) else None
    return params.get("_meta") if isinstance(params, dict) else None


def _is_notification(message: Any) -> bool:
    return (
        isinstance(message, dict)
        and message.get("jsonrpc") == jsonrpc.JSONRPC_VERSION
        and isinstance(message.get("method"), str)
        and "id" not in message
    )


def _is_response(message: Any) -> bool:
    return isinstance(message, dict) and "id" in message and "method" not in message and ("result" in message or "error" in message)


def _is_request(message: Any) -> bool:
    if not isinstance(message, dict) or message.get("jsonrpc") != jsonrpc.JSONRPC_VERSION or not isinstance(message.get("method"), str):
        return False
    message_id = message.get("id")
    if isinstance(message_id, bool) or not isinstance(message_id, str | int):
        return False
    return "params" not in message or isinstance(message["params"], dict)


def _is_json(content_type: str | None) -> bool:
    return content_type is not None and content_type.split(";", 1)[0].strip().lower() == "application/json"
