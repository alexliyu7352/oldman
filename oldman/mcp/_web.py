"""Put a service's MCP endpoint on its Web application: ``install_mcp(app)``.

The endpoint is one route of the Web service, so a request goes through everything else the service
does first — the authentication pipeline, middleware, logging, ``client_ip`` from the proxy settings.
This module adds the HTTP rules that come before the body (spec 2026-07-28 streamable-http and
2025-11-25 transports: Origin, who may call, Accept, size) and hands the body to the protocol layer.
"""

from __future__ import annotations

import tomllib
from typing import Any

from sanic.response import HTTPResponse
from sanic.response import json as json_response

import oldman.conf as conf
from oldman.conf.constants import PROJECT_ROOT
from oldman.logging import get_logger
from oldman.mcp._server import McpServer, RateLimit
from oldman.web.authentication.api_key import API_KEY_METHOD
from oldman.web.authentication.base import Authentication
from oldman.web.authentication.jwt import JWT_METHOD
from oldman.web.security.csrf import csrf_exempt

logger = get_logger("default.mcp")

#: The route names install_mcp adds; a service installs one endpoint.
ENDPOINT_ROUTE = "mcp_endpoint"
_OTHER_METHODS_ROUTE = "mcp_endpoint_other_methods"


def install_mcp(app: Any) -> McpServer:
    """Offer the installed Apps' MCP tools at ``web.mcp.path`` on this Web service.

    Call it in the service's ``init()`` after ``super().init()``, like ``install_admin(app)``. It loads each
    installed App's ``mcp`` module, builds the catalog and checks the settings now, so a mistake stops
    startup rather than the first request.
    """
    from oldman.mcp import mcp

    settings = conf.settings
    config = settings.web.mcp
    _check_callers(settings)
    app_registry = getattr(app.ctx, "app_registry", None)
    if app_registry is None:
        raise RuntimeError("install_mcp needs the service's App registry on app.ctx; call it after WebApplication.init()")
    app_registry.load_mcp()
    catalog = mcp.catalog(app_registry.packages)
    rate_limit = None
    if config.rate_limit.enabled:
        from oldman.providers.redis import redis_key
        from oldman.web.security.rate_limiter import redis_rate_limiter

        # Built now, so that a missing Redis alias stops startup; no connection is opened here.
        limiter = redis_rate_limiter(config.rate_limit.redis_alias, namespace=redis_key("ratelimit", "mcp"))
        rate_limit = RateLimit(limiter, limit=config.rate_limit.limit, period=config.rate_limit.period)
    server = McpServer(
        catalog,
        name=config.name or settings.core.site_name or settings.core.app_name,
        version=_project_version(),
        instructions=config.instructions,
        rate_limit=rate_limit,
    )
    max_body = config.max_request_body_size
    allowed_origins = frozenset(config.allowed_origins)
    callers = frozenset(config.callers)
    allow_anonymous = config.allow_anonymous

    @csrf_exempt
    async def endpoint(request: Any) -> HTTPResponse:
        # The route is CSRF-exempt because nothing a browser attaches by itself gets past the caller
        # check below: ambient credentials are refused whatever allow_anonymous says.
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            # spec: "If the Origin header is present and invalid, servers MUST respond with HTTP 403".
            return _refusal(403, "forbidden", "This Origin may not call the MCP endpoint")
        refusal = _caller_refusal(getattr(request.ctx, "auth", None), callers=callers, allow_anonymous=allow_anonymous)
        if refusal is not None:
            return refusal
        if not _accepts_json(request.headers.get("accept")):
            return HTTPResponse(status=406)
        body = await _read_body(request, max_body)
        if body is None:
            return json_response({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Request body too large"}}, status=413)
        reply = await server.handle(request, request.headers.items(), body, request.headers.get("content-type"))
        # No Mcp-Session-Id is ever sent: the server keeps no session in either era.
        if reply.body is None:
            return HTTPResponse(status=reply.status)
        return json_response(reply.body, status=reply.status)

    async def other_methods(request: Any) -> HTTPResponse:
        # Neither era's GET stream nor session DELETE is offered (2025-11-25 and 2026-07-28 both allow 405).
        return HTTPResponse(status=405, headers={"Allow": "POST"})

    app.add_route(endpoint, config.path, methods=["POST"], name=ENDPOINT_ROUTE, stream=True)
    app.add_route(other_methods, config.path, methods=["GET", "DELETE"], name=_OTHER_METHODS_ROUTE)
    logger.info(f"MCP endpoint at {config.path} offers {len(catalog.tools)} tool(s)")
    return server


def _check_callers(settings: Any) -> None:
    """Refuse settings under which nobody, or not what was named, could call the endpoint."""
    config = settings.web.mcp
    authenticators = list(settings.web.auth.authenticators or ())
    if config.callers:
        if API_KEY_METHOD not in authenticators:
            raise ValueError("web.mcp.callers names API keys, but web.auth.authenticators does not list 'api_key'")
        unknown = sorted(set(config.callers) - set(settings.web.auth.api_keys))
        if unknown:
            raise ValueError(f"web.mcp.callers names keys that web.auth.api_keys does not define: {', '.join(unknown)}")
    if not config.allow_anonymous and JWT_METHOD not in authenticators and not config.callers:
        raise ValueError(
            "Nobody could call the MCP endpoint: list 'jwt' in web.auth.authenticators, name API keys in web.mcp.callers, "
            "or set web.mcp.allow_anonymous"
        )


def _caller_refusal(auth: Authentication | None, *, callers: frozenset[str], allow_anonymous: bool) -> HTTPResponse | None:
    """Who may call: non-ambient credentials only, API keys only when named, anonymous only when allowed.

    A credential the browser attaches by itself — a session cookie, cached HTTP Basic, the client's
    network — is refused even when anonymous calls are allowed: a forged cross-site request (or a DNS
    rebinding page) would otherwise reach the tools as the signed-in user.
    """
    if auth is None:
        if allow_anonymous:
            return None
        return _refusal(401, "invalid_token", "Authentication required", challenge=True)
    if auth.ambient:
        return _refusal(403, "forbidden", "The MCP endpoint takes a bearer token or an API key, not a browser credential")
    if auth.method == API_KEY_METHOD:
        return None if auth.caller in callers else _refusal(403, "forbidden", "This API key may not use the MCP endpoint")
    if auth.user.is_authenticated:
        return None  # a JWT, or a project's own token that names a user
    return _refusal(403, "forbidden", "This caller may not use the MCP endpoint")


def _refusal(status: int, error: str, description: str, *, challenge: bool = False) -> HTTPResponse:
    headers = {"WWW-Authenticate": f'Bearer error="{error}", error_description="{description}"'} if challenge else None
    return json_response({"error": error, "error_description": description}, status=status, headers=headers)


def _accepts_json(accept: str | None) -> bool:
    """Accept lists application/json, application/* or */* (RFC 9110 wildcards, as the SDK reads them)."""
    media_types = {part.split(";", 1)[0].strip().lower() for part in (accept or "").split(",")}
    return bool(media_types & {"application/json", "application/*", "*/*"})


async def _read_body(request: Any, limit: int) -> bytes | None:
    """The whole body, or None once it exceeds ``limit``; stops reading at that point."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    size = 0
    while (chunk := await request.stream.read()) is not None:
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _project_version() -> str:
    """``serverInfo.version`` is the project's own version, from its pyproject.toml; Oldman's would mislead."""
    try:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
            version = tomllib.load(file).get("project", {}).get("version")
    except (OSError, tomllib.TOMLDecodeError):
        return "unknown"
    return version if isinstance(version, str) and version else "unknown"
