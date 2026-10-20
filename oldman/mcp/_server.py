"""Answer MCP requests from one catalog, after the transport's own checks.

The request object is the Web request the transport received; tools that ask for it get it, and
permission checks read its ``ctx.user``, as views do. Nothing here depends on how the bytes arrived.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

import mcp_types as types
from mcp_types import jsonrpc
from pydantic import ValidationError
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
from oldman.mcp._registry import McpCatalog, Tool, ToolError
from oldman.web.auth.permissions import has_perm

logger = get_logger("default.mcp")


class McpServer:
    """One service's MCP answers: its catalog and the identity it reports."""

    __slots__ = ("_capabilities", "_catalog", "_info", "_instructions")

    def __init__(self, catalog: McpCatalog, *, name: str, version: str, instructions: str | None = None) -> None:
        self._catalog = catalog
        self._info = types.Implementation(name=name, version=version)
        self._instructions = instructions
        self._capabilities = types.ServerCapabilities(tools=types.ToolsCapability())

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


async def _visible(tool: Tool, request: Any) -> bool:
    """Whether this caller may see and call the tool: one with a permission is for users who hold it."""
    return tool.permission is None or await has_perm(request, tool.permission)


def _tool_error(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=message)], is_error=True)
