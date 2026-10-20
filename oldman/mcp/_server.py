"""Answer MCP requests from one catalog, after the transport's own checks.

The request object is the Web request the transport received; tools that ask for it get it, and
permission checks read its ``ctx.user``, as views do. Nothing here depends on how the bytes arrived.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import mcp_types as types
from mcp_types import jsonrpc
from pydantic import ValidationError
from redis.exceptions import RedisError
from sanic.exceptions import SanicException

from oldman.logging import get_logger
from oldman.mcp._protocol import (
    HANDSHAKE_VERSIONS,
    LATEST_HANDSHAKE_VERSION,
    MODERN_VERSIONS,
    Inbound,
    Reply,
    error_reply,
    read_message,
    result_reply,
    validation_summary,
)
from oldman.mcp._registry import McpCatalog, Prompt, Resource, ResourceNotFound, Tool, ToolError
from oldman.web.auth.permissions import has_perm
from oldman.web.request import client_ip
from oldman.web.security.rate_limiter import RateLimiter, window_retry_after

logger = get_logger("default.mcp")


@dataclass(frozen=True, slots=True)
class RateLimit:
    """How often one caller may call tools (spec server/tools: servers MUST rate limit tool invocations)."""

    limiter: RateLimiter
    limit: int
    period: int


class McpServer:
    """One service's MCP answers: its catalog and the identity it reports."""

    __slots__ = ("_capabilities", "_catalog", "_info", "_instructions", "_rate_limit")

    def __init__(self, catalog: McpCatalog, *, name: str, version: str, instructions: str | None = None, rate_limit: RateLimit | None = None) -> None:
        self._catalog = catalog
        self._rate_limit = rate_limit
        self._info = types.Implementation(name=name, version=version)
        self._instructions = instructions
        # spec: servers that support resources or prompts MUST declare them; declared only when there are some.
        self._capabilities = types.ServerCapabilities(
            tools=types.ToolsCapability(),
            resources=types.ResourcesCapability() if catalog.resources else None,
            prompts=types.PromptsCapability() if catalog.prompts else None,
        )

    async def handle(self, request: Any, headers: Iterable[tuple[str, str]], body: bytes, content_type: str | None) -> Reply:
        """Answer one POSTed message."""
        inbound = read_message(headers, body, content_type)
        if isinstance(inbound, Reply):
            return inbound
        method = inbound.method
        if method == "server/discover":
            # serverInfo travels in the result's _meta (spec server/discover: servers SHOULD include it).
            discovered = types.DiscoverResult.model_validate(
                {
                    "supportedVersions": list(MODERN_VERSIONS),
                    "capabilities": self._capabilities,
                    "instructions": self._instructions,
                    "_meta": {types.SERVER_INFO_META_KEY: self._info.model_dump(by_alias=True, mode="json", exclude_none=True)},
                }
            )
            return result_reply(inbound, discovered)
        if method == "initialize":
            offered = inbound.request.params.protocol_version
            return result_reply(
                inbound,
                types.InitializeResult(
                    protocol_version=offered if offered in HANDSHAKE_VERSIONS else LATEST_HANDSHAKE_VERSION,
                    capabilities=self._capabilities,
                    server_info=self._info,
                    instructions=self._instructions,
                ),
            )
        if method == "ping":
            return result_reply(inbound, types.EmptyResult())
        if method == "tools/list":
            return await self._list_tools(request, inbound)
        if method == "tools/call":
            return await self._call_tool(request, inbound)
        if method in ("resources/list", "resources/templates/list") and self._catalog.resources:
            return await self._list_resources(request, inbound)
        if method == "resources/read" and self._catalog.resources:
            return await self._read_resource(request, inbound)
        if method == "prompts/list" and self._catalog.prompts:
            return await self._list_prompts(request, inbound)
        if method == "prompts/get" and self._catalog.prompts:
            return await self._get_prompt(request, inbound)
        # Parsed for this revision but not offered here: completion, logging, subscriptions, and what
        # the capabilities above do not declare.
        return error_reply(inbound.era, inbound.id, jsonrpc.METHOD_NOT_FOUND, f"Method not found: {method}")

    async def _list_tools(self, request: Any, inbound: Inbound) -> Reply:
        try:
            visible = [tool.wire for tool in self._catalog.tools.values() if await _visible(tool, request)]
        except SanicException as exc:  # the permission store is unreachable
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, str(exc))
        # Listed per caller, so caching may only be per caller: the model's defaults are
        # cacheScope "private" and ttlMs 0.
        return result_reply(inbound, types.ListToolsResult(tools=visible))

    async def _call_tool(self, request: Any, inbound: Inbound) -> Reply:
        params = inbound.request.params
        tool = self._catalog.tools.get(params.name)
        try:
            usable = tool is not None and await _visible(tool, request)
        except SanicException as exc:
            return result_reply(inbound, _tool_error(f"{exc} Try again later."))
        if tool is None or not usable:
            # A tool this caller cannot see is answered as unknown, so that calling does not reveal it.
            return error_reply(inbound.era, inbound.id, jsonrpc.INVALID_PARAMS, f"Unknown tool: {params.name}")
        refused = await self._over_limit(request)
        if refused is not None:
            return result_reply(inbound, _tool_error(refused))
        try:
            arguments = tool.arguments.model_validate(params.arguments or {})
        except ValidationError as exc:
            # A tool execution error, not a protocol one, so that the model can correct its arguments.
            return result_reply(inbound, _tool_error(f"Invalid arguments: {validation_summary(exc)}"))
        values = {name: getattr(arguments, name) for name in type(arguments).model_fields}
        try:
            value = await (tool.function(request, **values) if tool.takes_request else tool.function(**values))
            result = tool.result(value)
        except ToolError as exc:
            return result_reply(inbound, _tool_error(str(exc)))
        except SanicException as exc:
            # What a view would answer with: a denied permission, a missing record, a store that is down.
            return result_reply(inbound, _tool_error(str(exc)))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"MCP tool {tool.name!r} failed")
            return result_reply(inbound, _tool_error("The tool failed"))
        return result_reply(inbound, result)

    async def _list_resources(self, request: Any, inbound: Inbound) -> Reply:
        try:
            if inbound.method == "resources/templates/list":
                templates = [
                    resource.wire
                    for resource in self._catalog.resources
                    if isinstance(resource.wire, types.ResourceTemplate) and await _visible(resource, request)
                ]
                return result_reply(inbound, types.ListResourceTemplatesResult(resource_templates=templates))
            fixed = [
                resource.wire
                for resource in self._catalog.resources
                if isinstance(resource.wire, types.Resource) and await _visible(resource, request)
            ]
        except SanicException as exc:
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, str(exc))
        return result_reply(inbound, types.ListResourcesResult(resources=fixed))

    async def _read_resource(self, request: Any, inbound: Inbound) -> Reply:
        uri = inbound.request.params.uri
        not_found = error_reply(inbound.era, inbound.id, jsonrpc.INVALID_PARAMS, "Resource not found", data={"uri": uri})
        try:
            found = await self._find_resource(request, uri)
        except SanicException as exc:
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, str(exc))
        if found is None:
            return not_found
        resource, values = found
        try:
            value = await (resource.function(request, **values) if resource.takes_request else resource.function(**values))
            contents = resource.contents(uri, value)
        except ResourceNotFound:
            return not_found
        except SanicException as exc:
            if exc.status_code in (403, 404):
                # A record the function does not find, or does not let this caller read: the same answer, so
                # that reading does not tell the two apart.
                return not_found
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, str(exc))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"MCP resource {uri!r} failed")
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, "Internal error")
        return result_reply(inbound, types.ReadResourceResult(contents=contents))

    async def _find_resource(self, request: Any, uri: str) -> tuple[Resource, dict[str, Any]] | None:
        """The first visible resource that matches the URI; fixed ones were sorted before templates."""
        for resource in self._catalog.resources:
            values = resource.match(uri)
            if values is not None and await _visible(resource, request):
                return resource, values
        return None

    async def _list_prompts(self, request: Any, inbound: Inbound) -> Reply:
        try:
            visible = [prompt.wire for prompt in self._catalog.prompts.values() if await _visible(prompt, request)]
        except SanicException as exc:
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, str(exc))
        return result_reply(inbound, types.ListPromptsResult(prompts=visible))

    async def _get_prompt(self, request: Any, inbound: Inbound) -> Reply:
        params = inbound.request.params
        prompt = self._catalog.prompts.get(params.name)
        try:
            usable = prompt is not None and await _visible(prompt, request)
        except SanicException as exc:
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, str(exc))
        if prompt is None or not usable:
            # spec server/prompts: an invalid prompt name is -32602; one this caller cannot see is answered the same way.
            return error_reply(inbound.era, inbound.id, jsonrpc.INVALID_PARAMS, f"Unknown prompt: {params.name}")
        try:
            arguments = prompt.arguments.model_validate(params.arguments or {})
        except ValidationError as exc:
            # spec server/prompts: missing required arguments are -32602 too.
            return error_reply(inbound.era, inbound.id, jsonrpc.INVALID_PARAMS, f"Invalid arguments: {validation_summary(exc)}")
        values = {name: getattr(arguments, name) for name in type(arguments).model_fields}
        try:
            value = await (prompt.function(request, **values) if prompt.takes_request else prompt.function(**values))
            result = prompt.result(value)
        except SanicException as exc:
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, str(exc))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"MCP prompt {prompt.name!r} failed")
            return error_reply(inbound.era, inbound.id, jsonrpc.INTERNAL_ERROR, "Internal error")
        return result_reply(inbound, result)

    async def _over_limit(self, request: Any) -> str | None:
        """Why this call is refused by the rate limit, or None. A store that cannot count refuses too."""
        if self._rate_limit is None:
            return None
        limit = self._rate_limit
        try:
            limited = await limit.limiter.is_rate_limited(_caller_key(request), "tools/call", limit.limit, limit.period)
        except RedisError:
            # Not counted is not allowed: the limit would silently stop working while Redis is down.
            logger.exception("MCP rate limit store is unavailable")
            return "The rate limit store is unavailable. Try again later."
        if limited:
            # A tool error rather than an HTTP 429, so that the model reads how long to wait.
            return f"Rate limit exceeded: at most {limit.limit} tool calls per {limit.period} seconds. Try again in {window_retry_after(limit.period)} seconds."
        return None


def _caller_key(request: Any) -> str:
    """Whom a call counts against: the signed-in user, the API key, or the address of an anonymous caller."""
    auth = getattr(request.ctx, "auth", None)
    user = getattr(request.ctx, "user", None)
    if user is not None and user.is_authenticated:
        return f"user:{user.id}"
    if auth is not None and auth.caller is not None:
        return f"caller:{auth.caller}"
    return f"ip:{client_ip(request)}"


async def _visible(item: Tool | Resource | Prompt, request: Any) -> bool:
    """Whether this caller may see and use it: one with a permission is for the users who hold it."""
    return item.permission is None or await has_perm(request, item.permission)


def _tool_error(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=message)], is_error=True)
