"""Offer the installed Apps' tools to agents over the Model Context Protocol.

An App declares tools in its ``mcp`` module with the process-wide registry::

    from oldman.mcp import mcp

    @mcp.tool()
    async def count_projects(status: str) -> int:
        \"\"\"Count projects in one status.\"\"\"

Only ``mcp-types`` (the protocol's wire models) is used, never the ``mcp`` SDK, and nothing else in
Oldman imports this package, so a service that offers no MCP loads none of it.
"""

from mcp_types import ToolAnnotations

from oldman.mcp._registry import McpRegistry, ToolError

#: Where Apps declare their tools: ``from oldman.mcp import mcp``.
mcp = McpRegistry()

__all__ = ["McpRegistry", "ToolAnnotations", "ToolError", "mcp"]
